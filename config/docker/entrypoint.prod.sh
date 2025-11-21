#!/bin/sh
set -e

echo "[ENTRYPOINT] Installing MeloTTS and OpenVoice ..."
pip install -e /app/MeloTTS
pip install -e /app/OpenVoice

echo "[ENTRYPOINT] Applying database migrations..."
python manage.py migrate --noinput

echo "[ENTRYPOINT] Collecting static files..."
python manage.py collectstatic --noinput

echo "[ENTRYPOINT] Ready. Executing command: $@"
exec "$@"
