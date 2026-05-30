# Database Setup Guide

This guide explains how to set up PostgreSQL + PostGIS for the Agricultural Metrics Dashboard.

## Table of Contents
1. [Overview](#overview)
2. [PostgreSQL Installation](#postgresql-installation)
3. [PostGIS Installation](#postgis-installation)
4. [Database Configuration](#database-configuration)
5. [Running Migrations](#running-migrations)
6. [Testing the Setup](#testing-the-setup)

## Overview

The application supports both SQLite (default) and PostgreSQL with PostGIS:

- **SQLite**: Suitable for development and testing. All data stored in a single file.
- **PostgreSQL + PostGIS**: Recommended for production. Provides geospatial capabilities, better performance, and scalability.

### Why PostgreSQL + PostGIS?

- **Geospatial Data**: Store and query geographic coordinates, boundaries, and spatial relationships
- **Time-Series Data**: Optimized handling of climate and weather data over time
- **Scalability**: Handle large datasets efficiently
- **Concurrent Access**: Support multiple users simultaneously
- **Advanced Queries**: Spatial queries for agricultural analysis

## PostgreSQL Installation

### Windows

1. Download PostgreSQL installer from: https://www.postgresql.org/download/windows/
2. Run the installer and follow the installation wizard
3. Remember the superuser (postgres) password during installation
4. PostgreSQL will be installed as a Windows service
5. Access pgAdmin (GUI) from the Start menu

### macOS

```bash
# Using Homebrew
brew install postgresql@15

# Start PostgreSQL
brew services start postgresql@15
```

### Linux (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib

# Start PostgreSQL service
sudo systemctl start postgresql
```

## PostGIS Installation

PostGIS is a PostgreSQL extension that adds geospatial capabilities.

### Windows

1. Download PostGIS installer from: https://postgis.net/windows/downloads/
2. Run the installer
3. Select your PostgreSQL installation
4. Choose components (enable all for full functionality)
5. Complete the installation

### macOS

```bash
brew install postgis
```

### Linux (Ubuntu/Debian)

```bash
sudo apt-get install postgis postgresql-15-postgis-3
```

## Database Configuration

### 1. Create Database

```bash
# Connect to PostgreSQL as superuser
psql -U postgres

# Create database
CREATE DATABASE agri_dashboard;

# Enable PostGIS extension
\c agri_dashboard
CREATE EXTENSION PostGIS;

# Verify installation
SELECT PostGIS_version();
```

### 2. Create Database User

```bash
# In PostgreSQL prompt
CREATE USER agri_user WITH PASSWORD 'secure_password_here';

# Grant privileges
ALTER ROLE agri_user SET client_encoding TO 'utf8';
ALTER ROLE agri_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE agri_user SET default_transaction_deferrable TO on;
ALTER ROLE agri_user SET default_transaction_read_only TO off;
ALTER ROLE agri_user SET timezone TO 'UTC';

# Grant all privileges
GRANT ALL PRIVILEGES ON DATABASE agri_dashboard TO agri_user;
```

### 3. Configure Django Settings

Create or update your `.env` file:

```env
# Database Configuration
DB_ENGINE=django.contrib.gis.db.backends.postgis
DB_NAME=agri_dashboard
DB_USER=agri_user
DB_PASSWORD=secure_password_here
DB_HOST=localhost
DB_PORT=5432
```

Update `agri_dashboard/settings.py`:

```python
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.contrib.gis.db.backends.postgis'),
        'NAME': os.getenv('DB_NAME', 'agri_dashboard'),
        'USER': os.getenv('DB_USER', 'agri_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}
```

### 4. Install Required Python Packages

```bash
pip install -r requirements.txt

# Additional GIS packages for enhanced functionality
pip install Django>=4.2
pip install psycopg2-binary>=2.9.0
pip install Shapely>=2.0.0
```

## Running Migrations

Once PostgreSQL and PostGIS are set up:

```bash
# Create migrations for new models
python manage.py makemigrations

# Apply migrations to database
python manage.py migrate

# Create superuser for admin panel
python manage.py createsuperuser
```

## Geospatial Models

The application includes spatial field examples:

```python
from django.contrib.gis.db import models

class FieldBoundary(models.Model):
    name = models.CharField(max_length=200)
    geometry = models.PolygonField(srid=4326)  # WGS84
    area_hectares = models.DecimalField(max_digits=8, decimal_places=2)
    
    objects = models.GeoManager()
    
    class Meta:
        indexes = [models.Index(fields=['geometry'])]
```

## Testing the Setup

### Test PostgreSQL Connection

```bash
# From command line
psql -U agri_user -d agri_dashboard -h localhost

# You should see the PostgreSQL prompt
agri_dashboard=#
```

### Test Django Connection

```python
python manage.py dbshell

# Or run a simple query:
from dashboard.models import Region
Region.objects.all()  # Should return no errors
```

### Run Django Tests

```bash
python manage.py test dashboard
```

## Backup and Restore

### Backup Database

```bash
# Full backup
pg_dump -U agri_user -d agri_dashboard > backup.sql

# Compressed backup
pg_dump -U agri_user -d agri_dashboard | gzip > backup.sql.gz
```

### Restore Database

```bash
# From backup file
psql -U agri_user -d agri_dashboard < backup.sql

# From compressed backup
gunzip < backup.sql.gz | psql -U agri_user -d agri_dashboard
```

## Performance Optimization

### 1. Create Indexes

```python
# In your model
class Meta:
    indexes = [
        models.Index(fields=['region', 'measurement_date']),
        models.Index(fields=['drought_severity_class']),
    ]
```

### 2. Enable Query Logging

```python
# In settings.py for debugging
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
```

## Troubleshooting

### Connection Error: "could not connect to server"

1. Verify PostgreSQL is running:
   ```bash
   psql -U postgres  # Should connect
   ```

2. Check database credentials in `.env` file

3. Ensure firewall allows PostgreSQL port (default 5432)

### PostGIS Extension Not Found

```sql
CREATE EXTENSION PostGIS;
```

### Migration Errors

```bash
# Reset migrations (development only!)
python manage.py migrate dashboard zero
python manage.py makemigrations
python manage.py migrate
```

## Additional Resources

- PostgreSQL Documentation: https://www.postgresql.org/docs/
- PostGIS Documentation: https://postgis.net/documentation/
- GeoDjango Documentation: https://docs.djangoproject.com/en/4.2/ref/contrib/gis/

## Support

For issues or questions, please refer to:
1. Django GIS Documentation
2. PostgreSQL Forums
3. Project Issue Tracker
