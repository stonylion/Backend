#!/bin/sh

cd /app/Dstonylion

python manage.py migrate --noinput

exec daphne -b 0.0.0.0 -p 8001 stonylion.asgi:application
