"""Backfill Google Maps links on action logs that already have GPS coordinates."""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from iroad_tenants.fleet_gps_tracking import build_google_maps_link
from iroad_tenants.models import TenantRegistry
from tenant_workspace.models import TenantOperationActionLog


class Command(BaseCommand):
    help = 'Backfill map_link on operation action logs from stored latitude/longitude.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            dest='schema_name',
            default='',
            help='Tenant workspace schema name (required).',
        )

    def handle(self, *args, **options):
        schema_name = (options.get('schema_name') or '').strip()
        if not schema_name:
            registry = TenantRegistry.objects.exclude(schema_name='').first()
            if registry is None:
                self.stderr.write('No tenant registry found.')
                return
            schema_name = registry.schema_name
            self.stdout.write(f'Using schema: {schema_name}')

        updated = 0
        with schema_context(schema_name):
            qs = TenantOperationActionLog.objects.exclude(latitude='').exclude(longitude='')
            for log in qs.iterator():
                new_link = build_google_maps_link(log.latitude, log.longitude, log.map_link)
                if new_link and new_link != (log.map_link or ''):
                    log.map_link = new_link
                    log.save(update_fields=['map_link'])
                    updated += 1

        self.stdout.write(self.style.SUCCESS(f'Updated {updated} action log map links.'))
