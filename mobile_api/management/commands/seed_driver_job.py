from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone
import datetime
import uuid


class Command(BaseCommand):
    help = (
        'Seed a fresh job (Booking + Shipment) for a driver. '
        'Run: python manage.py seed_driver_job '
        '--schema=t_bb773f861f3048748c0a7f0ffbee0df6 '
        '--driver=DR-0002'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            default='t_bb773f861f3048748c0a7f0ffbee0df6',
            help='Tenant schema name'
        )
        parser.add_argument(
            '--driver',
            type=str,
            default='DR-0002',
            help='Driver code (e.g. DR-0002)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be created without saving'
        )

    def handle(self, *args, **options):
        schema = options['schema']
        driver_code = options['driver']
        dry_run = options['dry_run']

        connection.set_schema(schema)

        from tenant_workspace.models import (
            TenantClientAccount,
            DriverMaster,
            TruckMaster,
            TenantBooking,
            TenantShipment,
            TenantAddressMaster,
        )

        # --- Resolve driver ---
        try:
            driver = DriverMaster.objects.get(
                driver_code=driver_code
            )
        except DriverMaster.DoesNotExist:
            self.stderr.write(
                f'Driver with code {driver_code} not found.'
            )
            return

        # --- Resolve truck (first available) ---
        truck = TruckMaster.objects.first()
        if not truck:
            self.stderr.write('No truck found in database.')
            return

        # --- Resolve client account (first available) ---
        client = TenantClientAccount.objects.first()
        if not client:
            self.stderr.write('No client account found.')
            return

        # --- Resolve addresses (first available) ---
        loading_address = TenantAddressMaster.objects.first()
        delivery_address = TenantAddressMaster.objects.last()
        if not loading_address or not delivery_address:
            self.stderr.write('No addresses found.')
            return

        # --- Generate unique numbers ---
        today = datetime.date.today()
        unique_suffix = uuid.uuid4().hex[:8].upper()
        booking_no = f'BK-SEED-{unique_suffix}'
        shipment_no = f'SH-SEED-{unique_suffix}'

        self.stdout.write(f'Schema:          {schema}')
        self.stdout.write(
            f'Driver:          {driver.english_name} '
            f'({driver.driver_code})'
        )
        self.stdout.write(
            f'Truck:           {truck.plate_number}'
        )
        self.stdout.write(
            f'Client:          {client.name_english}'
        )
        self.stdout.write(f'Booking No:      {booking_no}')
        self.stdout.write(f'Shipment No:     {shipment_no}')
        self.stdout.write(f'Date:            {today}')

        if dry_run:
            self.stdout.write(
                'DRY RUN — nothing saved.'
            )
            return

        with transaction.atomic():
            # --- Create Booking ---
            booking = TenantBooking.objects.create(
                booking_no=booking_no,
                client_account=client,
                booking_status='Confirmed',
                trip_type='One-Way',
                order_type='Credit',
                sourcing_mode='Internal',
                loading_address=loading_address,
                delivery_address=delivery_address,
                assigned_driver=driver,
                assigned_truck=truck,
                booking_date=today,
                created_by_label='seed_driver_job',
            )
            self.stdout.write(
                f'Booking created: {booking.booking_no} '
                f'({booking.booking_id})'
            )

            # --- Create Shipment ---
            shipment = TenantShipment.objects.create(
                shipment_no=shipment_no,
                booking=booking,
                client_account=client,
                booking_item_ref=f'SEED-ITEM-{unique_suffix}',
                booking_item_type='Outbound',
                sourcing_mode='In-Source',
                trip_type='One-Way',
                order_type='Credit',
                shipment_status='Created',
                pod_type='Soft',
                shipment_date=today,
                driver=driver,
                truck=truck,
                loading_address=loading_address,
                delivery_address=delivery_address,
                created_by_label='seed_driver_job',
            )
            self.stdout.write(
                f'Shipment created: {shipment.shipment_no} '
                f'({shipment.shipment_id})'
            )

        self.stdout.write('')
        self.stdout.write('=== JOB READY FOR DRIVER ===')
        self.stdout.write(
            f'Driver {driver.english_name} can now log in '
            f'and see job {shipment_no} on the dashboard.'
        )
        self.stdout.write(
            f'Shipment ID: {shipment.shipment_id}'
        )
        self.stdout.write(
            f'Booking ID:  {booking.booking_id}'
        )
        self.stdout.write(
            'Run A1 through A10 in Postman to test the '
            'full flow on this fresh job.'
        )
