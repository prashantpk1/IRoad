# CP-PCS-P1: Postgres workspace schema metadata + immutable order line snapshots

from django.db import migrations, models
from django.db.models import Q


def backfill_order_line_snapshots(apps, schema_editor):
    OrderPlanLine = apps.get_model('superadmin', 'OrderPlanLine')
    OrderAddonLine = apps.get_model('superadmin', 'OrderAddonLine')
    SubscriptionPlan = apps.get_model('superadmin', 'SubscriptionPlan')

    for pl in OrderPlanLine.objects.filter(
        plan_name_en_snapshot='',
    ).iterator(chunk_size=500):
        if not pl.plan_id:
            continue
        try:
            p = SubscriptionPlan.objects.get(pk=pl.plan_id)
        except SubscriptionPlan.DoesNotExist:
            continue
        OrderPlanLine.objects.filter(pk=pl.pk).update(
            plan_name_en_snapshot=p.plan_name_en,
            plan_name_ar_snapshot=getattr(p, 'plan_name_ar', '') or '',
        )

    add_on_field = OrderAddonLine._meta.get_field('add_on_type')
    choice_map = dict(add_on_field.choices)
    for al in OrderAddonLine.objects.filter(
        add_on_type_label_snapshot='',
    ).iterator(chunk_size=500):
        OrderAddonLine.objects.filter(pk=al.pk).update(
            add_on_type_label_snapshot=choice_map.get(
                al.add_on_type,
                al.add_on_type,
            ),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0015_audit_log_append_only_trigger'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantprofile',
            name='workspace_schema',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='PostgreSQL schema name for isolated tenant workspace (CP 4.3.2).',
                max_length=63,
            ),
        ),
        migrations.AddConstraint(
            model_name='tenantprofile',
            constraint=models.UniqueConstraint(
                fields=('workspace_schema',),
                condition=~Q(workspace_schema=''),
                name='uniq_tenant_workspace_schema_when_set',
            ),
        ),
        migrations.AddField(
            model_name='orderplanline',
            name='plan_name_en_snapshot',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Plan display name at order time (invoice immutability, §5.3).',
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='orderplanline',
            name='plan_name_ar_snapshot',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='orderaddonline',
            name='add_on_type_label_snapshot',
            field=models.CharField(
                blank=True,
                default='',
                help_text='English label for add-on type at order time (§5.3).',
                max_length=200,
            ),
        ),
        migrations.RunPython(
            backfill_order_line_snapshots,
            migrations.RunPython.noop,
        ),
    ]
