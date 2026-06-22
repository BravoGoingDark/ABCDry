#!/usr/bin/env bash
set -euo pipefail

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Loading local data fixture..."
python manage.py load_render_fixture fixture.json

echo "Verifying data..."
python manage.py verify_data

echo "Build complete!"
