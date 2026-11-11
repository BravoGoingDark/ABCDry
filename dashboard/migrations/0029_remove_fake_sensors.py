"""Delete the sensor pins that were never connected to a data source.

The sensors page used to seed seven demo stations (AWS-01, SMP-01, ...) and
plot generated values for every pin. Only sensors fed by a real source (the
SmartFarm probe, external_source='smartfarm') have readings; everything else
showed invented figures, so it is removed. Not reversible: the demo pins and
hand-added test pins carried no data.
"""
from django.db import migrations


def remove_fake_sensors(apps, schema_editor):
    Sensor = apps.get_model('dashboard', 'Sensor')
    Sensor.objects.filter(external_source='').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0028_smartfarm_soil_probe'),
    ]

    operations = [
        migrations.RunPython(remove_fake_sensors, migrations.RunPython.noop),
    ]
