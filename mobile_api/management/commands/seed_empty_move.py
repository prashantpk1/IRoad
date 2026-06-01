from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

REASON_LABELS = {
    'reposition': 'Repositioning',
    'maintenance': 'Maintenance',
    'noLoad': 'No Load Available',
}


class Command(BaseCommand):
    help = (
        'Seed a standalone empty truck movement (no booking, no shipment). '
        'Run: python manage.py seed_empty_move '
        '--schema=t_bb773f861f3048748c0a7f0ffbee0df6 '
        '--driver=DR-0002 --reason=reposition'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            default='t_bb773f861f3048748c0a7f0ffbee0df6',
            help='Tenant schema name',
        )
        parser.add_argument(
            '--driver',
            type=str,
            default='DR-0002',
            help='Driver code (e.g. DR-0002)',
        )
        parser.add_argument(
            '--reason',
            type=str,
            choices=['reposition', 'maintenance', 'noLoad'],
            default='reposition',
            help='Empty move reason (reposition, maintenance, noLoad)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be created without saving the movement',
        )

    def handle(self, *args, **options):
        schema = options['schema']
        driver_code = options['driver']
        reason = options['reason']
        dry_run = options['dry_run']

        connection.set_schema(schema)

        from iroad_tenants.operation_runtime.constants import (
            TRUCK_MOVEMENT_LOG_AUTO_FORM_CODE,
            TRUCK_MOVEMENT_LOG_AUTO_FORM_LABEL,
            TRUCK_MOVEMENT_LOG_REF_PREFIX,
        )
        from iroad_tenants.views import _next_auto_number_for_form
        from tenant_workspace.models import (
            DriverMaster,
            TenantLocationMaster,
            TenantTruckMovementLog,
            TruckMaster,
        )

        try:
            driver = DriverMaster.objects.get(driver_code=driver_code)
        except DriverMaster.DoesNotExist:
            self.stderr.write(f'Driver with code {driver_code} not found.')
            return

        truck = TruckMaster.objects.last()
        if not truck:
            self.stderr.write('No truck found in database.')
            return

        from_location = TenantLocationMaster.objects.first()
        to_location = (
            TenantLocationMaster.objects.exclude(pk=from_location.pk).first()
            if from_location
            else None
        )
        if not from_location or not to_location:
            raise CommandError('Need at least 2 locations')

        movement_no, movement_sequence = _next_auto_number_for_form(
            form_code=TRUCK_MOVEMENT_LOG_AUTO_FORM_CODE,
            form_label=TRUCK_MOVEMENT_LOG_AUTO_FORM_LABEL,
            prefix=TRUCK_MOVEMENT_LOG_REF_PREFIX,
        )

        reason_label = REASON_LABELS.get(reason, reason)
        from_label = from_location.display_label
        to_label = to_location.display_label

        self.stdout.write(f'Schema: {schema}')
        self.stdout.write(f'Driver: {driver.driver_code}')
        self.stdout.write(f'Truck: {truck.truck_code}')
        self.stdout.write(f'Reason: {reason_label} ({reason})')
        self.stdout.write(f'From Location: {from_label}')
        self.stdout.write(f'To Location: {to_label}')
        self.stdout.write(f'Movement No: {movement_no}')

        if dry_run:
            self.stdout.write('')
            self.stdout.write('DRY RUN - nothing saved')
            return

        with transaction.atomic():
            movement = TenantTruckMovementLog.objects.create(
                movement_no=movement_no,
                movement_sequence=movement_sequence,
                movement_date=timezone.localdate(),
                movement_source='empty',
                empty_move_reason=reason,
                status=TenantTruckMovementLog.Status.SCHEDULED,
                booking=None,
                shipment=None,
                truck=truck,
                driver=driver,
                from_location_point=from_location,
                to_location_point=to_location,
                distance_km=0,
                created_by_label='seed_empty_move',
            )

        self.stdout.write('')
        self.stdout.write('=== EMPTY MOVE CREATED ===')
        self.stdout.write('')
        self.stdout.write(f'Movement ID: {movement.movement_id}')
        self.stdout.write(f'Movement No: {movement.movement_no}')
        self.stdout.write(f'Status: {movement.status}')
        self.stdout.write(f'Reason: {reason_label} ({movement.empty_move_reason})')
        self.stdout.write('')
        self.stdout.write(f'Driver: {driver.driver_code}')
        self.stdout.write(f'Truck: {truck.truck_code}')
        self.stdout.write('')
        self.stdout.write(f'From Location: {from_label}')
        self.stdout.write(f'To Location: {to_label}')
        self.stdout.write('')
        self.stdout.write('Movement Source: empty')
        self.stdout.write('')
        self.stdout.write('Booking: None')
        self.stdout.write('Shipment: None')
        self.stdout.write('')
        self.stdout.write('Dashboard Eligibility:')
        self.stdout.write('YES')
        self.stdout.write('')
        self.stdout.write('Empty Detection:')
        self.stdout.write("source == 'empty'")
