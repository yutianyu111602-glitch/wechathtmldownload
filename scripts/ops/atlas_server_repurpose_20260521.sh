#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="/root/atlas-repurpose-backups/${stamp}"

mkdir -p "${backup_root}"

backup_if_exists() {
  local path="$1"
  if [ -e "${path}" ]; then
    mkdir -p "${backup_root}$(dirname "${path}")"
    cp -a "${path}" "${backup_root}${path}"
  fi
}

if [ "${mode}" = "new-atlas-origin" ]; then
  echo "[atlas] preparing retired Claude VPS as Atlas origin candidate"

  backup_if_exists /etc/hostname
  backup_if_exists /etc/hosts
  backup_if_exists /etc/systemd/system/xray.service
  backup_if_exists /etc/systemd/system/xray.service.d
  backup_if_exists /usr/local/etc/xray
  backup_if_exists /etc/systemd/system/sub-server.service
  backup_if_exists /etc/systemd/system/wg-quick@warp.service
  backup_if_exists /etc/wireguard
  backup_if_exists /var/www/sub

  systemctl stop xray.service 2>/dev/null || true
  systemctl disable xray.service 2>/dev/null || true
  systemctl stop sub-server.service 2>/dev/null || true
  systemctl disable sub-server.service 2>/dev/null || true
  systemctl stop wg-quick@warp.service 2>/dev/null || true
  systemctl disable wg-quick@warp.service 2>/dev/null || true
  systemctl stop warp-svc.service 2>/dev/null || true
  systemctl disable warp-svc.service 2>/dev/null || true

  hostnamectl set-hostname sg-atlas-origin

  if command -v ufw >/dev/null 2>&1; then
    ufw --force delete allow 8443/tcp 2>/dev/null || true
    ufw --force delete allow 18443/tcp 2>/dev/null || true
    ufw deny 8443/tcp 2>/dev/null || true
    ufw deny 18443/tcp 2>/dev/null || true
  fi

  systemctl daemon-reload
  echo "[atlas] backup=${backup_root}"
  echo "[atlas] active services:"
  systemctl is-active ssh xray sub-server warp-svc wg-quick@warp 2>/dev/null || true
  echo "[atlas] listening ports:"
  ss -tulpn | grep -E ':(22|80|443|8443|18443|40000)\b' || true
  echo "[atlas] ufw:"
  ufw status verbose 2>/dev/null || true
  exit 0
fi

if [ "${mode}" = "old-huaidj-public-down" ]; then
  echo "[atlas] taking old huaidj public site/API offline while preserving finagent-beta"

  nginx_conf="/etc/nginx/sites-enabled/huaidj.club"
  backup_if_exists "${nginx_conf}"

  python3 - <<'PY'
from pathlib import Path

path = Path("/etc/nginx/sites-enabled/huaidj.club")
text = path.read_text()

replacements = {
"""    location = /healthz {
        proxy_pass http://127.0.0.1:3001/api/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
""":
"""    location = /healthz {
        add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
        return 410 "huaidj public site retired\\n";
    }
""",
"""    location /api/submissions {
        limit_req zone=api_submit burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
""":
"""    location /api/submissions {
        add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
        return 410 '{"error":"huaidj_public_site_retired"}';
    }
""",
"""    location /api/knowledge-base {
        limit_req zone=api_lookup burst=10 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
    }
""":
"""    location /api/knowledge-base {
        add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
        return 410 '{"error":"huaidj_public_site_retired"}';
    }
""",
"""    location /api {
        limit_req zone=api_general burst=20 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
""":
"""    location /api {
        add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
        return 410 '{"error":"huaidj_public_site_retired"}';
    }
""",
"""    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
""":
"""    location / {
        add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
        add_header Cache-Control "private, no-store" always;
        return 410 "huaidj public site retired. Atlas is moving behind protected access.\\n";
    }
""",
}

missing = []
for old, new in replacements.items():
    if old not in text:
        missing.append(old.splitlines()[0].strip())
    text = text.replace(old, new)

if missing:
    raise SystemExit("expected blocks not found: " + ", ".join(missing))

path.write_text(text)
PY

  nginx -t
  systemctl reload nginx

  echo "[atlas] backup=${backup_root}"
  echo "[atlas] verification:"
  curl -k -s -o /dev/null -w 'root=%{http_code}\n' https://127.0.0.1/ -H 'Host: huaidj.club'
  curl -k -s -o /dev/null -w 'api=%{http_code}\n' https://127.0.0.1/api/health -H 'Host: huaidj.club'
  curl -k -s -o /dev/null -w 'finagent=%{http_code}\n' https://127.0.0.1/finagent-beta/health/liveliness -H 'Host: huaidj.club'
  exit 0
fi

echo "usage: $0 new-atlas-origin|old-huaidj-public-down" >&2
exit 2
