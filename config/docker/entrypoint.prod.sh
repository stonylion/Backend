#!/bin/sh
set -e

cd /app/Dstonylion

echo "Applying database migrations"
python manage.py migrate

echo "Collecting static files"
python manage.py collectstatic --no-input

exec "$@"
