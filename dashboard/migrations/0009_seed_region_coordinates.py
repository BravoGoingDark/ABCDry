from django.db import migrations


def seed_region_coordinates(apps, schema_editor):
    Region = apps.get_model('dashboard', 'Region')
    coords = {
        'Tunisia': {'lat': 34.0, 'lng': 9.0, 'radius': 300, 'country': 'Tunisia'},
        'Morocco': {'lat': 31.79, 'lng': -7.08, 'radius': 300, 'country': 'Morocco'},
        'Algeria': {'lat': 36.75, 'lng': 3.06, 'radius': 300, 'country': 'Algeria'},
        'Ichkeul': {'lat': 37.16, 'lng': 9.66, 'radius': 50, 'country': 'Tunisia'},
        'Kairouan': {'lat': 35.68, 'lng': 10.10, 'radius': 50, 'country': 'Tunisia'},
        'Meknes': {'lat': 33.89, 'lng': -5.55, 'radius': 50, 'country': 'Morocco'},
        'Skhira': {'lat': 34.30, 'lng': 10.07, 'radius': 50, 'country': 'Tunisia'},
    }
    for name, data in coords.items():
        Region.objects.update_or_create(
            name=name,
            defaults={
                'latitude': data['lat'],
                'longitude': data['lng'],
                'radius_km': data['radius'],
                'country': data['country'],
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0010_region_add_missing_fields'),
    ]

    operations = [
        migrations.RunPython(seed_region_coordinates, migrations.RunPython.noop),
    ]
