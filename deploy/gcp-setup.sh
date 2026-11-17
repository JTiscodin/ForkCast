#!/usr/bin/env bash
# Run ON the Google Cloud VM (Debian 12) as root. It clones nothing: put the repo at
# /opt/forkcast first, then run (see docs/DEPLOY-GCP.md):
#   sudo git clone https://github.com/JTiscodin/Swiggy-Builder.git /opt/forkcast
#   sudo bash /opt/forkcast/deploy/gcp-setup.sh forkcast-api.duckdns.org
# Safe to run again (after a git pull, or to change the hostname).
set -euo pipefail

HOST="${1:?usage: sudo bash gcp-setup.sh <your-name>.duckdns.org}"
APP=/opt/forkcast
[[ "$HOST" =~ ^[a-z0-9.-]+$ ]] || { echo "not a hostname: $HOST" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "run it with sudo" >&2; exit 1; }
[ -f "$APP/backend/requirements.txt" ] || { echo "repo not found at $APP: clone or copy it there first" >&2; exit 1; }

# 1. Packages (Debian 12 has caddy in its own repos)
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv git caddy

# 2. 2 GB swap: the e2-micro has only 1 GB RAM
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
fi
swapon --show=NAME --noheadings | grep -qx /swapfile || swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 3. Own user with no sudo and no login, so a backend bug cannot take over the VM
id forkcast >/dev/null 2>&1 || useradd --system --home-dir "$APP" --no-create-home --shell /usr/sbin/nologin forkcast
chown -R forkcast:forkcast "$APP"

# 4. Python environment (--no-cache-dir: the user's home is the repo, keep it clean)
[ -x "$APP/backend/.venv/bin/python" ] || sudo -u forkcast python3 -m venv "$APP/backend/.venv"
sudo -u forkcast "$APP/backend/.venv/bin/pip" install --no-cache-dir -q -r "$APP/backend/requirements.txt"

# 5. Secrets file: made once from the template, never overwritten
if [ ! -f "$APP/backend/.env" ]; then
  install -m 600 -o forkcast -g forkcast "$APP/backend/.env.example" "$APP/backend/.env"
  echo ">> Now fill in the values: sudo nano $APP/backend/.env  then: sudo systemctl restart forkcast"
fi

# 6. systemd unit: the repo copy is written for Oracle's ubuntu user, so swap user and path
sed -e "s#/home/ubuntu/Swiggy-Builder#$APP#g" -e 's#^User=ubuntu$#User=forkcast#' \
  "$APP/deploy/forkcast.service" > /etc/systemd/system/forkcast.service
systemctl daemon-reload
systemctl enable forkcast
systemctl restart forkcast

# 7. Caddy: HTTPS for the DuckDNS name (certificate is automatic once 80/443 reach the VM)
sed "s#^forkcast-api\.duckdns\.org {#$HOST {#" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl restart caddy

echo ">> Done. Check: curl https://$HOST/mode   Logs: sudo journalctl -u forkcast -f"
