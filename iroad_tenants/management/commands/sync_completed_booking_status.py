"""Backfill stored booking_status=Completed when portal derivation is Completed."""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from iroad_tenants.booking_status import (
    BOOKING_HEADER_COMPLETED,
    DB_STATUS_COMPLETED,
    DB_STATUS_CONFIRMED,
    derive_booking_header_status,
    sync_booking_status_after_item_change,
)
from iroad_tenants.models import TenantRegistry
from tenant_workspace.models import TenantBooking


class Command(BaseCommand):
    help = (
        'Set booking_status to Completed in DB for bookings whose derived '
        'header status is Completed (fixes mobile dashboard stale Confirmed rows).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            dest='schema_name',
            default='',
            help='Tenant workspace schema name (default: first registry schema).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report candidates without saving.',
        )

    def handle(self, *args, **options):
        schema_name = (options.get('schema_name') or '').strip()
        dry_run = bool(options.get('dry_run'))
        if not schema_name:
            registry = TenantRegistry.objects.exclude(schema_name='').first()
            if registry is None:
                self.stderr.write('No tenant registry found.')
                return
            schema_name = registry.schema_name
            self.stdout.write(f'Using schema: {schema_name}')

        updated = 0
        scanned = 0
        with schema_context(schema_name):
            qs = TenantBooking.objects.filter(booking_status=DB_STATUS_CONFIRMED)
            for booking in qs.iterator():
                scanned += 1
                if derive_booking_header_status(booking) != BOOKING_HEADER_COMPLETED:
                    continue
                if dry_run:
                    self.stdout.write(f'Would complete: {booking.booking_no}')
                    updated += 1
                    continue
                if sync_booking_status_after_item_change(booking):
                    self.stdout.write(f'Completed: {booking.booking_no}')
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Scanned {scanned} Confirmed booking(s); '
                f'{"would update" if dry_run else "updated"} {updated}.'
            )
        )
