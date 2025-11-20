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
if ! type docker-compose > /dev/null
then
  echo "docker-compose does not exist"
  echo "Start installing docker-compose"
  sudo curl -SL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
fi

# Docker Compose로 서버 빌드 및 실행 (docker-compose.prod.yml 사용)
echo "start docker-compose up: ubuntu"
cd /home/ubuntu/srv/ubuntu
sudo docker-compose -f docker-compose.prod.yml up --build -d