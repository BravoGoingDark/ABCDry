#!/bin/bash
set -e

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running migrations..."
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Creating admin user if not exists..."
python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ.get('ADMIN_USERNAME', 'admin')
password = os.environ.get('ADMIN_PASSWORD', 'admin')
email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f'Admin user \"{username}\" created.')
else:
    u = User.objects.get(username=username)
    u.set_password(password)
    u.save()
    print(f'Admin user \"{username}\" password updated.')
"

echo "Build complete!"
