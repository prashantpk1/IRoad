from django.core.management.base import BaseCommand

from superadmin.models import TenantProfile
from iroad_tenants.services import ensure_tenant_schema_registry


class Command(BaseCommand):
    help = (
        'Sync django-tenants registry + migrations for every subscriber '
        '(CP 4.3.2).'
    )

    def handle(self, *args, **options):
        qs = TenantProfile.objects.all().order_by('company_name')
        for tenant in qs.iterator():
            ensure_tenant_schema_registry(tenant)
            self.stdout.write(
                self.style.SUCCESS(
                    f'OK {tenant.tenant_id} -> {tenant.workspace_schema}',
                ),
            )
