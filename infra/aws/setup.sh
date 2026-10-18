#!/bin/bash
# One-time host setup on Ubuntu 24.04: swap, Docker, then the Compose stack.
# Usage: sudo bash infra/aws/setup.sh <public-hostname> <comma-separated web origins>
set -euo pipefail
HOST="$1"
ORIGINS="$2"
cd "$(dirname "$0")/../.."

if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if ! command -v docker >/dev/null; then
  apt-get update -y
  apt-get install -y docker.io docker-compose-v2
  # Cap container logs so a long-running host does not fill its disk.
  mkdir -p /etc/docker
  echo '{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}' > /etc/docker/daemon.json
  systemctl enable --now docker
  systemctl restart docker
fi

ENV_FILE=infra/aws/.env
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  {
    echo "TENANT_RW_PASSWORD=$(openssl rand -hex 24)"
    echo "TENANT_RO_PASSWORD=$(openssl rand -hex 24)"
  } > "$ENV_FILE"
fi
sed -i '/^API_HOST=/d;/^CORS_ORIGINS=/d' "$ENV_FILE"
echo "API_HOST=$HOST" >> "$ENV_FILE"
echo "CORS_ORIGINS=$ORIGINS" >> "$ENV_FILE"

docker compose -f infra/aws/docker-compose.yml --env-file "$ENV_FILE" up -d --build
docker compose -f infra/aws/docker-compose.yml --env-file "$ENV_FILE" ps
