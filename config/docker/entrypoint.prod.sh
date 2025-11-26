#!/bin/sh

echo "[ENTRYPOINT] Running Django setup..."

cd /app/Dstonylion

echo "[ENTRYPOINT] Fake apply existing AI migration (0005)"
python manage.py migrate AI 0005_extendchat_extendmessage --fake || true

echo "[ENTRYPOINT] Applying migrations"
python manage.py migrate --noinput || exit 1

echo "[ENTRYPOINT] Collecting static files"
python manage.py collectstatic --noinput || exit 1

exec "$@"
