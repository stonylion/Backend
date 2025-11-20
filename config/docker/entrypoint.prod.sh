#!/bin/sh

echo "Installing MeloTTS and OpenVoice ..."
pip install -e /app/MeloTTS
pip install -e /app/OpenVoice

cd /app/Dstonylion

echo "Applying database migrations"
python manage.py migrate --noinput

echo "Collecting static files"
python manage.py collectstatic --noinput

echo "Starting server..."
exec "$@"
