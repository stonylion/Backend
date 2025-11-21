#!/bin/bash

cd /home/ubuntu/srv/ubuntu

echo "[INFO] Starting docker compose"
sudo docker compose -f docker-compose.prod.yml up --build -d
