#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="/root/atlas-app-runtime-backups/${stamp}"
app_root="/opt/atlas-weekly-api"
data_root="/var/lib/atlas"
env_dir="/etc/atlas"
env_file="${env_dir}/atlas.env"
service_file="/etc/systemd/system/atlas-weekly-api.service"
nginx_site="/etc/nginx/sites-available/atlas-origin-guard.conf"

need_root() {
  if [ "$(id -u)" != "0" ]; then
    echo "must run as root" >&2
    exit 1
  fi
}

backup_if_exists() {
  local path="$1"
  if [ -e "${path}" ]; then
    mkdir -p "${backup_root}$(dirname "${path}")"
    cp -a "${path}" "${backup_root}${path}"
  fi
}

node_major() {
  if ! command -v node >/dev/null 2>&1; then
    echo 0
    return
  fi
  node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0
}

install_node_runtime() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg build-essential python3 make g++ rsync openssl
  if [ "$(node_major)" -lt 20 ]; then
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg.tmp
    mv /etc/apt/keyrings/nodesource.gpg.tmp /etc/apt/keyrings/nodesource.gpg
    chmod 644 /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list
    apt-get update
    apt-get install -y nodejs
  fi
  node -v
  npm -v
}

ensure_user_and_dirs() {
  if ! id atlas >/dev/null 2>&1; then
    useradd --system --home "${app_root}" --shell /usr/sbin/nologin atlas
  fi
  mkdir -p "${app_root}" "${data_root}" "${env_dir}"
  chown root:root "${app_root}"
  chmod 755 "${app_root}"
  chown root:atlas "${data_root}"
  chmod 750 "${data_root}"
  touch "${env_file}"
  chown root:root "${env_file}"
  chmod 600 "${env_file}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if [ -f "${env_file}" ]; then
    grep -v -E "^${key}=" "${env_file}" > "${tmp}" || true
  fi
  printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
  install -m 600 -o root -g root "${tmp}" "${env_file}"
  rm -f "${tmp}"
}

ensure_secret_value() {
  local key="$1"
  if grep -q -E "^${key}=.+" "${env_file}" 2>/dev/null; then
    return
  fi
  set_env_value "${key}" "$(openssl rand -base64 48 | tr -d '\n')"
}

write_env_defaults() {
  set_env_value NODE_ENV production
  set_env_value HOST 127.0.0.1
  set_env_value PORT 8787
  set_env_value STAGE7_ATLAS_SQLITE_DB "${data_root}/atlas.sqlite"
  set_env_value ATLAS_REQUIRE_SESSION 1
  set_env_value ATLAS_SQLITE_READONLY 1
  set_env_value ATLAS_COOKIE_SECURE 1
  set_env_value ATLAS_EXPOSE_INTERNAL_DB_PATH 0
  set_env_value DEEPSEEK_ENRICH_ENABLED false
  set_env_value WEEKLY_ACTIVITY_API_DIR "${app_root}/services/weekly_activity_cloudrun/data/current_release"
  ensure_secret_value ATLAS_SESSION_SECRET
}

write_systemd_service() {
  backup_if_exists "${service_file}"
  cat > "${service_file}" <<SERVICE
[Unit]
Description=Atlas graph weekly API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=atlas
Group=atlas
WorkingDirectory=${app_root}
EnvironmentFile=${env_file}
ExecStart=/usr/bin/node ${app_root}/services/weekly_activity_cloudrun/src/server.mjs
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=${app_root} ${data_root}
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
SERVICE
  systemctl daemon-reload
}

install_node_dependencies() {
  if [ ! -f "${app_root}/package-lock.json" ]; then
    echo "missing ${app_root}/package-lock.json; upload app files first" >&2
    exit 2
  fi
  cd "${app_root}"
  npm ci --omit=dev
  chown -R root:root "${app_root}"
  find "${app_root}" -type d -exec chmod 755 {} +
  find "${app_root}" -type f -exec chmod 644 {} +
}

write_nginx_site() {
  backup_if_exists "${nginx_site}"
  cat > "${nginx_site}" <<'NGINX'
# managed by atlas_origin_app_runtime_20260521.sh
upstream atlas_weekly_api {
    server 127.0.0.1:8787;
    keepalive 16;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name atlas.huaidj.club huaidj.club _;

    access_log /var/log/nginx/atlas_origin_access.log atlas_guard;
    error_log /var/log/nginx/atlas_origin_error.log warn;

    if ($host !~* ^(atlas\.huaidj\.club|huaidj\.club)$) {
        return 444;
    }

    location = /healthz {
        add_header Cache-Control "no-store" always;
        add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
        return 200 "atlas-origin-guarded\n";
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2 default_server;
    listen [::]:443 ssl http2 default_server;
    server_name atlas.huaidj.club huaidj.club _;

    ssl_certificate /etc/atlas-origin/tls/selfsigned.crt;
    ssl_certificate_key /etc/atlas-origin/tls/selfsigned.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    access_log /var/log/nginx/atlas_origin_access.log atlas_guard;
    error_log /var/log/nginx/atlas_origin_error.log warn;

    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "same-origin" always;
    add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
    add_header Cache-Control "private, no-store" always;

    if ($host !~* ^(atlas\.huaidj\.club|huaidj\.club)$) {
        return 444;
    }

    limit_conn atlas_conn 20;

    location = /healthz {
        add_header Cache-Control "no-store" always;
        return 200 "atlas-origin-guarded\n";
    }

    location = /robots.txt {
        default_type text/plain;
        return 200 "User-agent: *\nDisallow: /\n";
    }

    location ~* ^/(atlas\.sqlite|atlas\.db|atlas\.json|graph\.json|.*\.(sqlite|db|sql|dump|bak|old|log))$ {
        access_log /var/log/nginx/atlas_honey.log atlas_guard;
        return 403;
    }

    location ~* ^/api/v1/stage7/(export|full-graph|full|dump|bulk|raw|all|sqlite) {
        access_log /var/log/nginx/atlas_honey.log atlas_guard;
        default_type application/json;
        return 403 '{"error":"forbidden_bulk_atlas_endpoint"}';
    }

    location ~* ^/(\.env|\.git|\.svn|wp-login\.php|xmlrpc\.php|cgi-bin/) {
        access_log /var/log/nginx/atlas_honey.log atlas_guard;
        return 403;
    }

    location = /api/v1/atlas/session/status {
        limit_req zone=atlas_api burst=8 nodelay;
        limit_req_status 429;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_pass http://atlas_weekly_api;
    }

    location = /api/v1/atlas/session {
        limit_req zone=atlas_api burst=4 nodelay;
        limit_req_status 429;
        client_max_body_size 16k;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_pass http://atlas_weekly_api;
    }

    location /api/v1/stage7/ {
        limit_req zone=atlas_api burst=5 nodelay;
        limit_req_status 429;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_pass http://atlas_weekly_api;
    }

    location = /atlas {
        return 302 /atlas/graph;
    }

    location /atlas/ {
        limit_req zone=atlas_page burst=20 nodelay;
        limit_req_status 429;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_pass http://atlas_weekly_api;
    }

    location / {
        return 403;
    }
}
NGINX
  nginx -t
  systemctl reload nginx
}

prepare_runtime() {
  need_root
  mkdir -p "${backup_root}"
  install_node_runtime
  ensure_user_and_dirs
  write_env_defaults
  echo "[atlas] runtime prepared; env names:"
  awk -F= 'NF && $1 !~ /^#/ {print $1}' "${env_file}"
}

configure_app() {
  need_root
  mkdir -p "${backup_root}"
  ensure_user_and_dirs
  write_env_defaults
  if [ ! -s "${data_root}/atlas.sqlite" ]; then
    echo "missing ${data_root}/atlas.sqlite; upload database first" >&2
    exit 3
  fi
  chown root:atlas "${data_root}/atlas.sqlite"
  chmod 640 "${data_root}/atlas.sqlite"
  install_node_dependencies
  write_systemd_service
  systemctl enable atlas-weekly-api.service
  systemctl restart atlas-weekly-api.service
  sleep 2
  systemctl --no-pager --full status atlas-weekly-api.service | sed -n '1,18p'
  write_nginx_site
  echo "[atlas] app configured; backup=${backup_root}"
}

smoke() {
  need_root
  systemctl is-active atlas-weekly-api.service
  curl -fsS http://127.0.0.1:8787/healthz >/tmp/atlas-healthz.json
  curl -k -sS -o /tmp/atlas-page.html -w 'page_http=%{http_code}\n' https://127.0.0.1/atlas/graph -H 'Host: atlas.huaidj.club'
  curl -k -sS -o /tmp/atlas-seed.json -w 'seed_http=%{http_code}\n' https://127.0.0.1/api/v1/stage7/graph/seed?q=DADA -H 'Host: atlas.huaidj.club'
  curl -k -sS -o /tmp/atlas-honey.txt -w 'honey_http=%{http_code}\n' https://127.0.0.1/atlas.sqlite -H 'Host: atlas.huaidj.club'
  echo "[atlas] response snippets:"
  python3 - <<'PY'
from pathlib import Path
for p in ["/tmp/atlas-healthz.json", "/tmp/atlas-page.html", "/tmp/atlas-seed.json", "/tmp/atlas-honey.txt"]:
    data = Path(p).read_text(errors="ignore")
    print(p, data[:240].replace("\n", " "))
PY
}

case "${mode}" in
  prepare-runtime) prepare_runtime ;;
  configure-app) configure_app ;;
  smoke) smoke ;;
  *)
    echo "usage: $0 {prepare-runtime|configure-app|smoke}" >&2
    exit 64
    ;;
esac
