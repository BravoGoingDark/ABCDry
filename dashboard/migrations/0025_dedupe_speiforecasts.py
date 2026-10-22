from django.db import migrations


def dedupe_speiforecasts(apps, schema_editor):
    """Collapse duplicate SpeiForecast rows, keeping the earliest-issued one.

    The first forecast for a (region, feature month) pair is the one users
    actually saw and the one SpeiVerification must score, so it is the one
    kept. Later re-issues are discarded here; a separate run archive is the
    right home for them, not this table.

    Kept in its own migration: deleting rows and then ALTERing the same table
    inside one transaction trips Postgres' "pending trigger events" check.
    """
    SpeiForecast = apps.get_model('dashboard', 'SpeiForecast')
    kept = set()
    for row in SpeiForecast.objects.order_by('generated_at', 'id').values(
            'id', 'region_id', 'feature_month', 'target_month_t1'):
        key = (row['region_id'], row['feature_month'], row['target_month_t1'])
        if key in kept:
            SpeiForecast.objects.filter(id=row['id']).delete()
        else:
            kept.add(key)


def noop_reverse(apps, schema_editor):
    """Deduplication is irreversible; deleted rows are not recreated."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0024_speiverification_and_more'),
    ]

    operations = [
        migrations.RunPython(dedupe_speiforecasts, noop_reverse),
    ]
