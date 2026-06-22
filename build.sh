#!/usr/bin/env bash
set -euo pipefail

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Seeding demo metrics (skipped if data already exists)..."
python manage.py setup_render_data

echo "Verifying data..."
python manage.py verify_data

echo "Build complete!"
