from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0008_agriculturalmetrics_latitude_and_more'),
    ]

    operations = [
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
    ]
