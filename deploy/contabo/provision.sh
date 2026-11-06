#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: provision.sh RELEASE_ARCHIVE DOMAIN [OWNER_EMAIL]" >&2
  exit 2
fi

ARCHIVE=$1
DOMAIN=$2
OWNER_EMAIL=${3:-}

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script as root on the Contabo server." >&2
  exit 1
fi
if [[ ! -r "$ARCHIVE" ]]; then
  echo "Release archive is not readable: $ARCHIVE" >&2
  exit 1
fi
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Invalid domain name." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y bubblewrap certbot nginx python3-venv

if [[ ! -e /etc/apparmor.d/bwrap ]]; then
  install -o root -g root -m 0644 "$(dirname "$0")/bwrap.apparmor" /etc/apparmor.d/bwrap
  apparmor_parser -r /etc/apparmor.d/bwrap
elif ! grep -q 'userns,' /etc/apparmor.d/bwrap; then
  echo "An existing /etc/apparmor.d/bwrap profile does not grant user namespaces; review it before continuing." >&2
  exit 1
fi

if ! id opspilot >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/opspilot --shell /usr/sbin/nologin opspilot
fi
install -d -o root -g opspilot -m 0750 /opt/opspilot
tar --no-same-owner -xzf "$ARCHIVE" -C /opt/opspilot
python3 -m venv /opt/opspilot/.venv
chown -R root:opspilot /opt/opspilot
chmod -R u=rwX,g=rX,o= /opt/opspilot

install -d -o opspilot -g opspilot -m 0750 /var/lib/opspilot
install -d -o root -g opspilot -m 0750 /etc/opspilot
install -d -o root -g root -m 0700 /var/backups/opspilot
if [[ ! -e /etc/opspilot/opspilot.env ]]; then
  cat > /etc/opspilot/opspilot.env <<EOF
TASKVAULT_HOST=127.0.0.1
TASKVAULT_PORT=8120
TASKVAULT_DB_PATH=/var/lib/opspilot/opspilot.sqlite3
TASKVAULT_CORS_ORIGINS=https://${DOMAIN}
TASKVAULT_SANDBOX_MODE=bubblewrap
EOF
fi
chown root:opspilot /etc/opspilot/opspilot.env
chmod 0640 /etc/opspilot/opspilot.env

if ! grep -q '^TASKVAULT_AUTH_PASSWORD_HASH=' /etc/opspilot/opspilot.env; then
  PASSWORD=$(openssl rand -hex 24)
  PASSWORD_HASH=$(printf '%s\n' "$PASSWORD" | python3 "$(dirname "$0")/hash_password.py" --stdin)
  printf '\nTASKVAULT_AUTH_REQUIRED=1\nTASKVAULT_AUTH_PASSWORD_HASH=%s\n' "$PASSWORD_HASH" >> /etc/opspilot/opspilot.env
  printf 'Username: operator\nPassword: %s\n' "$PASSWORD" > /root/opspilot-initial-login.txt
  chmod 0600 /root/opspilot-initial-login.txt
elif ! grep -q '^TASKVAULT_AUTH_REQUIRED=1$' /etc/opspilot/opspilot.env; then
  printf '\nTASKVAULT_AUTH_REQUIRED=1\n' >> /etc/opspilot/opspilot.env
fi

install -o root -g root -m 0644 "$(dirname "$0")/opspilot.service" /etc/systemd/system/opspilot.service
install -o root -g root -m 0644 "$(dirname "$0")/opspilot-backup.service" /etc/systemd/system/opspilot-backup.service
install -o root -g root -m 0644 "$(dirname "$0")/opspilot-backup.timer" /etc/systemd/system/opspilot-backup.timer
install -o root -g root -m 0750 "$(dirname "$0")/backup.sh" /usr/local/sbin/opspilot-backup
install -o root -g root -m 0644 "$(dirname "$0")/opspilot-rate-limit.conf" /etc/nginx/conf.d/opspilot-rate-limit.conf
if [[ -s "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  sed "s/__DOMAIN__/${DOMAIN}/g" "$(dirname "$0")/nginx-https.conf" > /etc/nginx/sites-available/opspilot
else
  sed "s/__DOMAIN__/${DOMAIN}/g" "$(dirname "$0")/nginx-http.conf" > /etc/nginx/sites-available/opspilot
fi
ln -sfn /etc/nginx/sites-available/opspilot /etc/nginx/sites-enabled/opspilot

rm -f /etc/nginx/opspilot.htpasswd

systemctl daemon-reload
systemctl enable --now opspilot.service
systemctl enable --now opspilot-backup.timer
systemctl restart opspilot.service
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8120/api/health >/dev/null; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    journalctl -u opspilot.service -n 80 --no-pager
    exit 1
  fi
  sleep 1
done

/usr/local/sbin/opspilot-backup

nginx -t
systemctl reload nginx

if [[ "${SKIP_TLS:-0}" == "1" ]]; then
  echo "OpsPilot is running on loopback and remains unavailable at the public hostname until that DNS record points to this server and HTTPS is provisioned."
  exit 0
fi

if [[ ! -s "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  CERTBOT_ARGS=(certonly --webroot -w /var/www/html -d "$DOMAIN" --non-interactive --agree-tos --preferred-challenges http)
  if [[ -n "$OWNER_EMAIL" ]]; then
    CERTBOT_ARGS+=(--email "$OWNER_EMAIL")
  else
    CERTBOT_ARGS+=(--register-unsafely-without-email)
  fi
  certbot "${CERTBOT_ARGS[@]}"
fi

sed "s/__DOMAIN__/${DOMAIN}/g" "$(dirname "$0")/nginx-https.conf" > /etc/nginx/sites-available/opspilot
nginx -t
systemctl reload nginx

INITIAL_LOGIN=$(cat /root/opspilot-initial-login.txt 2>/dev/null || true)
if [[ -n "$INITIAL_LOGIN" ]]; then
  printf 'Initial OpsPilot login\n%s\n' "$INITIAL_LOGIN"
  rm -f /root/opspilot-initial-login.txt
else
  printf 'Existing OpsPilot sign-in was preserved.\n'
fi

printf 'Health: '
curl --fail --silent --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/health" || true
printf '\n'
