#!/bin/sh
set -e

echo "[ENTRYPOINT] Waiting for UniDic to be installed..."
while [ ! -f /usr/local/lib/python3.10/site-packages/unidic/dicdir/mecabrc ]; do
    echo "  → UniDic not ready. Waiting..."
    sleep 2
done
echo "[ENTRYPOINT] UniDic found!"

echo "[ENTRYPOINT] Installing MeloTTS and OpenVoice..."
pip install -e /app/MeloTTS
pip install -e /app/OpenVoice

echo "[ENTRYPOINT] Applying migrations..."
python manage.py migrate --noinput

echo "[ENTRYPOINT] Collecting static..."
python manage.py collectstatic --noinput

echo "[ENTRYPOINT] Starting server..."
exec "$@"
