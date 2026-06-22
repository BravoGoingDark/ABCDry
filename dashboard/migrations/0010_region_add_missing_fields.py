from django.db import migrations, models


class Migration(migrations.Migration):

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
            state_operations=[
                migrations.AddField(
                    model_name='region',
                    name='area_km2',
                    field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
                ),
                migrations.AddField(
                    model_name='region',
                    name='country',
                    field=models.CharField(blank=True, max_length=100, null=True),
                ),
                migrations.AddField(
                    model_name='region',
                    name='description',
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='region',
                    name='elevation_m',
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='region',
                    name='latitude',
                    field=models.DecimalField(blank=True, decimal_places=6, max_digits=10, null=True),
                ),
                migrations.AddField(
                    model_name='region',
                    name='longitude',
                    field=models.DecimalField(blank=True, decimal_places=6, max_digits=10, null=True),
                ),
                migrations.AddField(
                    model_name='region',
                    name='radius_km',
                    field=models.DecimalField(decimal_places=2, default=100.0, max_digits=8),
                ),
            ],
        ),
    ]
