#!/bin/sh

echo "[ENTRYPOINT] Running Django setup..."

cd /app/Dstonylion

# echo "[ENTRYPOINT] Applying migrations"
python manage.py migrate --noinput || exit 1

echo "[ENTRYPOINT] Collecting static files"
python manage.py collectstatic --noinput || exit 1

exec "$@"
