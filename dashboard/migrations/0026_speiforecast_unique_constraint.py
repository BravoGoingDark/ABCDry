from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0025_dedupe_speiforecasts'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='speiforecast',
            constraint=models.UniqueConstraint(
                fields=('region', 'feature_month', 'target_month_t1'),
                name='uniq_speiforecast_region_feature_target_t1',
            ),
        ),
    ]
