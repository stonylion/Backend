#!/bin/bash

# Docker 설치 여부 확인, 없다면 설치
if ! type docker > /dev/null
then
  echo "[INFO] Docker not installed. Installing..."
  sudo apt-get update
  sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -

  sudo add-apt-repository \
    "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable"

  sudo apt update
  apt-cache policy docker-ce
  sudo apt install -y docker-ce
fi

# Docker Compose 설치 여부 확인, 없다면 설치
if ! docker compose version > /dev/null 2>&1; then
  echo "[INFO] Docker Compose not installed. Installing..."
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -SL \
    https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

echo "[INFO] Docker Compose Installed:"
docker compose version

# Docker Compose로 서버 빌드 및 실행 (docker-compose.prod.yml 사용)
echo "start docker-compose up: ubuntu"
cd /home/ubuntu/srv/ubuntu
sudo docker-compose -f docker-compose.prod.yml up --build -d