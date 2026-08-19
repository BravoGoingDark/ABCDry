from django.db import migrations, models


class Migration(migrations.Migration):
    """Add Region columns to the database.

    Django's state already knows about these fields from migration 0008
    (SeparateDatabaseAndState), so no state_operations are needed here.
    """

    dependencies = [
        ('dashboard', '0008_agriculturalmetrics_latitude_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS area_km2 numeric(12, 2) NULL;",
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS country varchar(100) NULL;",
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS description text NULL;",
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS elevation_m integer NULL;",
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS latitude numeric(10, 6) NULL;",
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS longitude numeric(10, 6) NULL;",
                "ALTER TABLE regions ADD COLUMN IF NOT EXISTS radius_km numeric(8, 2) DEFAULT 100.0 NOT NULL;",
            ],
            reverse_sql=[
                "ALTER TABLE regions DROP COLUMN IF EXISTS radius_km;",
                "ALTER TABLE regions DROP COLUMN IF EXISTS longitude;",
                "ALTER TABLE regions DROP COLUMN IF EXISTS latitude;",
                "ALTER TABLE regions DROP COLUMN IF EXISTS elevation_m;",
                "ALTER TABLE regions DROP COLUMN IF EXISTS description;",
                "ALTER TABLE regions DROP COLUMN IF EXISTS country;",
                "ALTER TABLE regions DROP COLUMN IF EXISTS area_km2;",
            ],
        ),
    ]
