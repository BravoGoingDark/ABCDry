from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0031_drought_grid'),
    ]

    operations = [
        migrations.AddField(
            model_name='farm',
            name='irrigation_method',
            field=models.CharField(blank=True, choices=[('drip', 'Drip'), ('sprinkler', 'Sprinkler'), ('surface', 'Surface / furrow')], default='', max_length=12),
        ),
        migrations.AddField(
            model_name='farm',
            name='irrigation_flow_m3h',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='Water delivered to the whole farm (m3 per hour)', max_digits=7, null=True),
        ),
        migrations.AddField(
            model_name='farm',
            name='last_irrigation_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
