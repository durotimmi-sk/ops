#!/usr/bin/env bash
# TaskVault (OpsPilot) - Vultr Cloud Compute Automated Provisioning Script
# Vultr Agent Rush Hackathon: Challenge 1 (Blast Radius Zero)
set -euo pipefail

echo "==> [1/6] Updating system packages on Vultr VM..."
apt-get update -y
apt-get upgrade -y
apt-get install -y curl git ufw nginx ca-certificates gnupg

echo "==> [2/6] Installing Docker & Docker Compose Plugin..."
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
fi

echo "==> [3/6] Setting up OpsPilot application..."
APP_DIR="/opt/opspilot"
if [ ! -d "$APP_DIR" ]; then
    git clone https://github.com/durotimmi-sk/ops.git "$APP_DIR"
else
    cd "$APP_DIR"
    git fetch origin
    git reset --hard origin/main
fi

cd "$APP_DIR"

if [ ! -f .env ]; then
    echo "==> Creating .env from template..."
    cat << 'EOF' > .env
TASKVAULT_HOST=0.0.0.0
TASKVAULT_PORT=8000
TASKVAULT_COMPETITION_TRACK=blast_radius_zero
VULTR_INFERENCE_URL=https://api.vultrinference.com/v1/chat/completions
VULTR_INFERENCE_API_KEY=
VULTR_INFERENCE_MODEL=
EOF
    echo "NOTICE: Please edit /opt/opspilot/.env and set your VULTR_INFERENCE_API_KEY."
fi

echo "==> [4/6] Configuring Nginx reverse proxy..."
cp "$APP_DIR/deploy/vultr/nginx.conf" /etc/nginx/sites-available/opspilot
ln -sf /etc/nginx/sites-available/opspilot /etc/nginx/sites-enabled/opspilot
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> [5/6] Starting TaskVault services via Docker Compose..."
docker compose down || true
docker compose up -d --build

echo "==> [6/6] Verifying health check..."
sleep 5
HEALTH=$(curl -s http://127.0.0.1:8000/api/health || echo '{"ok":false}')
echo "Health Response: $HEALTH"

echo "=========================================================="
echo "  OpsPilot is deployed and running on your Vultr VM!"
echo "  Port 80 is forwarded to the TaskVault Control Plane."
echo "  Remember to set VULTR_INFERENCE_API_KEY in /opt/opspilot/.env"
echo "=========================================================="
