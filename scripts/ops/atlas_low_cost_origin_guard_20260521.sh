#!/usr/bin/env bash
set -euo pipefail

mode="${1:-install}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="/root/atlas-origin-guard-backups/${stamp}"
atlas_dir="/etc/atlas-origin"
tls_dir="${atlas_dir}/tls"
site_conf="/etc/nginx/sites-available/atlas-origin-guard.conf"
site_link="/etc/nginx/sites-enabled/atlas-origin-guard.conf"

backup_if_exists() {
  local path="$1"
  if [ -e "${path}" ]; then
    mkdir -p "${backup_root}$(dirname "${path}")"
    cp -a "${path}" "${backup_root}${path}"
  fi
}

need_root() {
  if [ "$(id -u)" != "0" ]; then
    echo "must run as root" >&2
    exit 1
  fi
}

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y nginx ufw fail2ban curl ca-certificates openssl
}

write_cloudflare_realip() {
  mkdir -p "${atlas_dir}"
  curl -fsSL https://www.cloudflare.com/ips-v4 -o "${atlas_dir}/cloudflare-ips-v4.txt.tmp"
  curl -fsSL https://www.cloudflare.com/ips-v6 -o "${atlas_dir}/cloudflare-ips-v6.txt.tmp"
  mv "${atlas_dir}/cloudflare-ips-v4.txt.tmp" "${atlas_dir}/cloudflare-ips-v4.txt"
  mv "${atlas_dir}/cloudflare-ips-v6.txt.tmp" "${atlas_dir}/cloudflare-ips-v6.txt"

  backup_if_exists /etc/nginx/conf.d/atlas-cloudflare-realip.conf
  {
    echo "# managed by atlas_low_cost_origin_guard_20260521.sh"
    echo "real_ip_header CF-Connecting-IP;"
    echo "real_ip_recursive on;"
    while IFS= read -r cidr; do
      [ -n "${cidr}" ] && echo "set_real_ip_from ${cidr};"
    done < "${atlas_dir}/cloudflare-ips-v4.txt"
    while IFS= read -r cidr; do
      [ -n "${cidr}" ] && echo "set_real_ip_from ${cidr};"
    done < "${atlas_dir}/cloudflare-ips-v6.txt"
  } > /etc/nginx/conf.d/atlas-cloudflare-realip.conf
}

write_nginx_common() {
  backup_if_exists /etc/nginx/conf.d/atlas-origin-common.conf
  cat > /etc/nginx/conf.d/atlas-origin-common.conf <<'NGINX'
# managed by atlas_low_cost_origin_guard_20260521.sh
server_tokens off;

log_format atlas_guard '$remote_addr - $remote_user [$time_local] "$request" '
                       '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                       'cf_ray="$http_cf_ray" cf_ip="$http_cf_connecting_ip" '
                       'host="$host" request_time="$request_time"';

limit_req_zone $binary_remote_addr zone=atlas_page:10m rate=6r/s;
limit_req_zone $binary_remote_addr zone=atlas_api:10m rate=2r/s;
limit_conn_zone $binary_remote_addr zone=atlas_conn:10m;
NGINX
}

write_self_signed_tls() {
  mkdir -p "${tls_dir}"
  if [ ! -s "${tls_dir}/selfsigned.crt" ] || [ ! -s "${tls_dir}/selfsigned.key" ]; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
      -subj "/CN=atlas.huaidj.club" \
      -addext "subjectAltName=DNS:atlas.huaidj.club,DNS:huaidj.club,IP:149.28.150.224" \
      -keyout "${tls_dir}/selfsigned.key" \
      -out "${tls_dir}/selfsigned.crt"
    chmod 600 "${tls_dir}/selfsigned.key"
    chmod 644 "${tls_dir}/selfsigned.crt"
  fi
}

write_nginx_site() {
  backup_if_exists "${site_conf}"
  backup_if_exists "${site_link}"
  cat > "${site_conf}" <<'NGINX'
# managed by atlas_low_cost_origin_guard_20260521.sh
#
# This is an origin guard, not the final Atlas app deployment.
# It intentionally fails closed for /atlas and /api/v1/stage7 until
# Cloudflare + Turnstile + server-side Atlas session gates are installed.

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

    location ~* ^/(atlas\.sqlite|atlas\.db|atlas\.json|.*\.(sqlite|db|sql|dump|bak|old|log))$ {
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

    location /api/v1/stage7/ {
        limit_req zone=atlas_api burst=5 nodelay;
        limit_req_status 429;
        default_type application/json;
        return 503 '{"error":"atlas_origin_locked","reason":"cloudflare_turnstile_session_gate_not_installed"}';
    }

    location /atlas {
        limit_req zone=atlas_page burst=20 nodelay;
        limit_req_status 429;
        default_type text/plain;
        return 503 "Atlas origin guard is armed. Public Atlas UI is locked until Cloudflare + Turnstile + bounded graph API gates are configured.\n";
    }

    location / {
        return 403;
    }
}
NGINX

  ln -sfn "${site_conf}" "${site_link}"
  rm -f /etc/nginx/sites-enabled/default
}

write_fail2ban() {
  backup_if_exists /etc/fail2ban/filter.d/nginx-atlas-honey.conf
  backup_if_exists /etc/fail2ban/jail.d/nginx-atlas-honey.local

  cat > /etc/fail2ban/filter.d/nginx-atlas-honey.conf <<'EOF'
[Definition]
failregex = ^<HOST> - .* "(GET|POST|HEAD|PUT|DELETE|OPTIONS) /(atlas\.sqlite|atlas\.db|atlas\.json|.*\.(sqlite|db|sql|dump|bak|old|log)|api/v1/stage7/(export|full-graph|full|dump|bulk|raw|all|sqlite)|\.env|\.git|\.svn|wp-login\.php|xmlrpc\.php|cgi-bin/).*" (403|444) .*
ignoreregex =
EOF

  cat > /etc/fail2ban/jail.d/nginx-atlas-honey.local <<'EOF'
[nginx-atlas-honey]
enabled = true
port = http,https
filter = nginx-atlas-honey
logpath = /var/log/nginx/atlas_honey.log
maxretry = 1
findtime = 86400
bantime = 86400
EOF

  touch /var/log/nginx/atlas_honey.log
}

write_origin_readme() {
  cat > "${atlas_dir}/README.md" <<'EOF'
# Atlas Origin Guard

Managed by `scripts/ops/atlas_low_cost_origin_guard_20260521.sh`.

Current purpose:

- keep direct Atlas origin closed except Cloudflare edge access to 80/443
- expose only `/healthz`
- return fail-closed responses for `/atlas` and `/api/v1/stage7/*`
- block and fail2ban obvious bulk/export/probe paths

Do not place Atlas SQLite, graph dumps, raw JSON exports, or secrets on a public path.
EOF
}

configure_ufw_cloudflare_only() {
  if ! command -v ufw >/dev/null 2>&1; then
    return
  fi

  ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw deny 8443/tcp >/dev/null 2>&1 || true
  ufw deny 18443/tcp >/dev/null 2>&1 || true

  while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    ufw allow proto tcp from "${cidr}" to any port 80 comment "atlas-cloudflare-http" >/dev/null 2>&1 || true
    ufw allow proto tcp from "${cidr}" to any port 443 comment "atlas-cloudflare-https" >/dev/null 2>&1 || true
  done < "${atlas_dir}/cloudflare-ips-v4.txt"

  while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    ufw allow proto tcp from "${cidr}" to any port 80 comment "atlas-cloudflare-http6" >/dev/null 2>&1 || true
    ufw allow proto tcp from "${cidr}" to any port 443 comment "atlas-cloudflare-https6" >/dev/null 2>&1 || true
  done < "${atlas_dir}/cloudflare-ips-v6.txt"

  ufw --force enable >/dev/null 2>&1 || true
}

verify() {
  echo "[atlas-origin] nginx config:"
  nginx -t
  echo "[atlas-origin] services:"
  systemctl is-active nginx fail2ban ssh || true
  echo "[atlas-origin] listen:"
  ss -ltnp | grep -E ':(22|80|443|8443|18443)\b' || true
  echo "[atlas-origin] local health:"
  curl -skI --max-time 5 https://127.0.0.1/healthz -H 'Host: atlas.huaidj.club' | head -n 1
  echo "[atlas-origin] local atlas lock:"
  curl -skI --max-time 5 https://127.0.0.1/atlas -H 'Host: atlas.huaidj.club' | head -n 1
  echo "[atlas-origin] honey endpoint:"
  curl -skI --max-time 5 https://127.0.0.1/atlas.sqlite -H 'Host: atlas.huaidj.club' | head -n 1
  echo "[atlas-origin] ufw summary:"
  ufw status numbered 2>/dev/null | sed -n '1,80p' || true
}

install() {
  need_root
  mkdir -p "${backup_root}" "${atlas_dir}" "${tls_dir}"
  backup_if_exists /etc/nginx
  backup_if_exists /etc/fail2ban
  backup_if_exists /etc/ufw

  install_packages
  write_cloudflare_realip
  write_nginx_common
  write_self_signed_tls
  write_nginx_site
  write_fail2ban
  write_origin_readme
  configure_ufw_cloudflare_only

  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
  systemctl enable --now fail2ban
  systemctl restart fail2ban

  echo "[atlas-origin] backup=${backup_root}"
  verify
}

case "${mode}" in
  install)
    install
    ;;
  verify)
    need_root
    verify
    ;;
  refresh-cloudflare-ips)
    need_root
    mkdir -p "${backup_root}" "${atlas_dir}"
    write_cloudflare_realip
    configure_ufw_cloudflare_only
    nginx -t
    systemctl reload nginx
    verify
    ;;
  *)
    echo "usage: $0 install|verify|refresh-cloudflare-ips" >&2
    exit 2
    ;;
esac
