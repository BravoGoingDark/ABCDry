import os
from django.apps import AppConfig
from django.db.models.signals import post_migrate


def create_default_superuser(sender, **kwargs):
    from django.contrib.auth.models import User
    if User.objects.filter(is_superuser=True).exists():
        return
    username = os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
    email = os.getenv('DJANGO_SUPERUSER_EMAIL', 'admin@abcdry.com')
    password = os.getenv('DJANGO_SUPERUSER_PASSWORD', 'admin123')
    User.objects.create_superuser(username=username, email=email, password=password)


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'

    def ready(self):
        post_migrate.connect(create_default_superuser, sender=self)
