#!/usr/bin/env bash
set -euo pipefail

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Build complete!"
