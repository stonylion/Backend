#!/bin/bash

# ====== Install Docker if missing ======
if ! type docker > /dev/null; then
  echo "[INFO] Docker not installed. Installing..."
  sudo apt-get update
  sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
  sudo add-apt-repository \
    "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable"
  sudo apt update
  sudo apt install -y docker-ce
fi

# ====== Install Docker Compose ======
if ! docker compose version > /dev/null 2>&1; then
  echo "[INFO] Installing Docker Compose..."
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -SL \
    https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

echo "[INFO] Docker Compose Installed:"
docker compose version

# ====== Deploy containers ======
cd /home/ubuntu/srv/ubuntu
sudo docker compose -f docker-compose.prod.yml up --build -d

echo "[INFO] Waiting for containers to be ready..."
sleep 5

# ====== Detect container names ======
WEB=$(docker ps --format "{{.Names}}" | grep web)
ASGI=$(docker ps --format "{{.Names}}" | grep asgi)

# ====== UniDic installer ======
install_unidic() {
  NAME=$1
  echo "[INFO] Installing UniDic inside $NAME ..."

  # Wait for container to be alive
  until docker exec $NAME echo "Container ready"; do
      echo "[WAIT] $NAME still starting..."
      sleep 2
  done

  docker exec $NAME pip install --no-cache-dir unidic || true
  docker exec $NAME python3 -m unidic download

  docker exec $NAME bash -c "rm -rf /usr/local/lib/python3.10/site-packages/unidic/dicdir \
    && ln -s /root/.local/share/unidic /usr/local/lib/python3.10/site-packages/unidic/dicdir"

  echo "[OK] UniDic installed in $NAME"
}

install_unidic $WEB
install_unidic $ASGI
