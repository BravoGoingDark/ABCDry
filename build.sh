#!/usr/bin/env bash
set -euo pipefail

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Seeding demo metrics (if missing or incomplete)..."
python manage.py verify_data || python manage.py setup_render_data --force

echo "Verifying data..."
python manage.py verify_data

echo "Build complete!"
