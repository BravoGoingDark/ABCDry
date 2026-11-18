import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0032_farm_irrigation_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='FarmActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('irrigation', 'Irrigation'), ('fertilizer', 'Fertilizer'), ('treatment', 'Treatment'), ('scouting', 'Field check'), ('sowing', 'Sowing'), ('harvest', 'Harvest'), ('other', 'Other')], max_length=12)),
                ('status', models.CharField(choices=[('done', 'Done'), ('skipped', 'Not done')], default='done', max_length=8)),
                ('date', models.DateField()),
                ('amount_mm', models.DecimalField(blank=True, decimal_places=1, help_text='Irrigation: water applied (gross mm = L/m2)', max_digits=6, null=True)),
                ('task_key', models.CharField(blank=True, default='', help_text='Reminder this answers (services.farm_tasks)', max_length=80)),
                ('note', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('farm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='dashboard.farm')),
            ],
            options={
                'db_table': 'farm_activities',
                'ordering': ['-date', '-created_at'],
                'indexes': [models.Index(fields=['farm', 'kind', 'date'], name='farm_act_farm_kind_date')],
            },
        ),
    ]
