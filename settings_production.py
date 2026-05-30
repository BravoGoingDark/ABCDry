# ============================================================================
# Django Settings for TimescaleDB + PostgreSQL + PostGIS
# File: agri_dashboard/settings_production.py (use instead of settings.py)
# ============================================================================
# This configuration replaces default SQLite with PostgreSQL + TimescaleDB
# ============================================================================

import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# ============================================================================
# DATABASE CONFIGURATION - TimescaleDB
# ============================================================================
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',  # PostGIS-enabled backend
        'NAME': config('DB_NAME', default='agri_db'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        
        # Connection pooling with PgBouncer
        'CONN_MAX_AGE': 0,  # Disable Django's persistent connections (use PgBouncer instead)
        
        # Optimize connection parameters
        'OPTIONS': {
            'connect_timeout': 10,
            'options': '-c default_transaction_isolation=read_committed -c statement_timeout=30000',
            'sslmode': 'prefer',  # Use SSL if available
        },
        
        # Atomic transactions by default
        'ATOMIC_REQUESTS': False,  # Set True only if needed (impacts performance)
        
        # Connection pool size (used if using django-db-geventpool)
        'CONN_HEALTH_CHECKS': True,  # Check connection health before using
        'DISABLE_SERVER_SIDE_CURSORS': False,
    }
}

# ============================================================================
# CACHING CONFIGURATION (Redis for performance)
# ============================================================================
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True,
            },
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            'IGNORE_EXCEPTIONS': True,  # Cache failures don't break the app
        }
    }
}

# ============================================================================
# INSTALLED APPS
# ============================================================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',  # Required for PostGIS
    
    # Third-party apps
    'rest_framework',
    'django_filters',
    'corsheaders',
    'django_extensions',
    'django_celery_beat',  # For scheduled tasks (data imports, aggregations)
    
    # Application
    'dashboard',
]

# ============================================================================
# MIDDLEWARE
# ============================================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'db_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'database.log'),
            'maxBytes': 1024 * 1024 * 10,
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': config('DJANGO_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['db_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# ============================================================================
# CELERY CONFIGURATION (for async tasks)
# ============================================================================
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

# Scheduled tasks
CELERY_BEAT_SCHEDULE = {
    'refresh-materialized-views': {
        'task': 'dashboard.tasks.refresh_materialized_views',
        'schedule': 3600.0,  # Every hour
    },
    'generate-daily-risk-assessments': {
        'task': 'dashboard.tasks.generate_daily_risk_assessments',
        'schedule': 86400.0,  # Daily at midnight
    },
}

# ============================================================================
# REST FRAMEWORK CONFIGURATION
# ============================================================================
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour'
    },
}

# ============================================================================
# GEOSPATIAL CONFIGURATION (PostGIS)
# ============================================================================
USE_SPATIAL_DB = True
GEOS_LIBRARY_PATH = config('GEOS_LIBRARY_PATH', default=None)  # Set if needed
GDAL_LIBRARY_PATH = config('GDAL_LIBRARY_PATH', default=None)  # Set if needed

# ============================================================================
# SECURITY SETTINGS (PRODUCTION)
# ============================================================================
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())
SECRET_KEY = config('SECRET_KEY', default='change-me-in-production')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=True, cast=bool)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': ("'self'", "'unsafe-inline'", "cdn.tailwindcss.com"),
    'style-src': ("'self'", "'unsafe-inline'", "fonts.googleapis.com"),
}

# ============================================================================
# STATIC & MEDIA FILES
# ============================================================================
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ============================================================================
# INTERNATIONALIZATION
# ============================================================================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
LANGUAGES = [
    ('en', 'English'),
    ('fr', 'Français'),
    ('ar', 'العربية'),
]

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'Templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ============================================================================
# DATABASE BACKUP & MONITORING SETTINGS
# ============================================================================
# For pgBackRest backup configuration:
# Set environment variables or use .pgbackrest.conf file
BACKUP_ENABLED = config('BACKUP_ENABLED', default=True, cast=bool)
BACKUP_PATH = config('BACKUP_PATH', default='/backups/pgbackrest')
BACKUP_RETENTION_DAYS = config('BACKUP_RETENTION_DAYS', default=30, cast=int)

# Monitoring (e.g., with pg_stat_statements)
MONITORING_ENABLED = config('MONITORING_ENABLED', default=True, cast=bool)

# ============================================================================
# DASHBOARD SPECIFIC SETTINGS
# ============================================================================
DASHBOARD_REFRESH_INTERVAL = 300  # seconds (5 minutes)
HISTORICAL_DATA_RETENTION_YEARS = 2
AGGREGATION_RUN_TIME = '00:30'  # 12:30 AM UTC
RISK_ASSESSMENT_THRESHOLD = 60  # Risk score threshold for alerts
