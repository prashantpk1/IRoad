from django.core.management.base import BaseCommand
from django.db import connection, transaction
import datetime
import uuid


class Command(BaseCommand):
    help = (
        'Seed a fresh Credit job (Booking + Shipment) for a driver. '
        'Run: python manage.py seed_driver_job '
        '--schema=t_bb773f861f3048748c0a7f0ffbee0df6 '
        '--driver=DR-0002'
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
            '--dry-run',
            action='store_true',
            help='Print what would be created without saving',
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
            driver = DriverMaster.objects.get(driver_code=driver_code)
        except DriverMaster.DoesNotExist:
            self.stderr.write(f'Driver with code {driver_code} not found.')
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

        # --- Resolve addresses (named if possible) — same as seed_driver_job_cod ---
        loading_address = (
            TenantAddressMaster.objects.filter(
                display_name__icontains='warehouse',
            ).first()
            or TenantAddressMaster.objects.first()
        )
        delivery_address = (
            TenantAddressMaster.objects.filter(
                display_name__icontains='customer',
            ).first()
            or TenantAddressMaster.objects.exclude(pk=loading_address.pk).first()
            or TenantAddressMaster.objects.last()
        )
        if not loading_address or not delivery_address:
            self.stderr.write('No addresses found.')
            return

        # --- Resolve route (optional) ---
        route = None
        try:
            from tenant_workspace.models import TenantRouteMaster

            route = TenantRouteMaster.objects.first()
            if not route:
                self.stderr.write(
                    'No route found. Seed will continue without route.',
                )
        except ImportError:
            route = None

        # --- Generate unique numbers ---
        today = datetime.date.today()
        unique_suffix = uuid.uuid4().hex[:8].upper()
        booking_no = f'BK-SEED-{unique_suffix}'
        shipment_no = f'SH-SEED-{unique_suffix}'
        booking_item_ref = f'SEED-ITEM-{unique_suffix}'

        route_display = ''
        if route is not None:
            route_display = (
                getattr(route, 'route_display', None)
                or getattr(route, 'route_label', None)
                or ''
            )[:120]

        self.stdout.write(f'Schema:          {schema}')
        self.stdout.write(
            f'Driver:          {driver.english_name} ({driver.driver_code})',
        )
        self.stdout.write(f'Truck:           {truck.plate_number}')
        self.stdout.write(f'Client:          {client.name_english}')
        self.stdout.write(f'Booking No:      {booking_no}')
        self.stdout.write(f'Shipment No:     {shipment_no}')
        self.stdout.write(f'Date:            {today}')
        self.stdout.write('Order Type:      Credit')
        self.stdout.write(
            f'Pickup:          {loading_address.display_name} '
            f'({loading_address.address_code})',
        )
        self.stdout.write(
            f'Drop:            {delivery_address.display_name} '
            f'({delivery_address.address_code})',
        )
        if route is not None:
            self.stdout.write(
                f'Route:           {route_display or route.route_code}',
            )
        else:
            self.stdout.write('Route:           (none)')

        if dry_run:
            self.stdout.write('DRY RUN — nothing saved.')
            return

        booking_kwargs = {
            'booking_no': booking_no,
            'client_account': client,
            'booking_status': 'Confirmed',
            'trip_type': 'One-Way',
            'order_type': 'Credit',
            'sourcing_mode': 'Internal',
            'loading_address': loading_address,
            'delivery_address': delivery_address,
            'assigned_driver': driver,
            'assigned_truck': truck,
            'booking_date': today,
            'created_by_label': 'seed_driver_job',
        }
        if route is not None:
            booking_kwargs['route'] = route

        shipment_kwargs = {
            'shipment_no': shipment_no,
            'booking': None,
            'client_account': client,
            'booking_item_ref': booking_item_ref,
            'booking_item_type': 'Outbound',
            'sourcing_mode': 'In-Source',
            'trip_type': 'One-Way',
            'order_type': 'Credit',
            'shipment_status': 'Created',
            'pod_type': 'Soft',
            'shipment_date': today,
            'driver': driver,
            'truck': truck,
            'loading_address': loading_address,
            'delivery_address': delivery_address,
            'route_display': route_display,
            'created_by_label': 'seed_driver_job',
        }

        with transaction.atomic():
            booking = TenantBooking.objects.create(**booking_kwargs)
            self.stdout.write(
                f'Booking created: {booking.booking_no} ({booking.booking_id})',
            )

            shipment_kwargs['booking'] = booking
            shipment = TenantShipment.objects.create(**shipment_kwargs)
            self.stdout.write(
                f'Shipment created: {shipment.shipment_no} ({shipment.shipment_id})',
            )

        self.stdout.write('')
        self.stdout.write('=== CREDIT JOB READY FOR DRIVER ===')
        self.stdout.write(
            f'Driver {driver.english_name} can now log in '
            f'and see job {shipment_no} on the dashboard.',
        )
        self.stdout.write('ORDER TYPE: Credit')
        self.stdout.write(
            'CREDIT FLOW: A1 A2 A3 A4 A5 A6 POD-Capture A7 A8 A10 (skip A9)',
        )
        self.stdout.write(f'Shipment ID: {shipment.shipment_id}')
        self.stdout.write(f'Booking ID:  {booking.booking_id}')
        self.stdout.write(
            'NOTE: Driver must fire A4 (Confirm Loaded) to create Movement '
            'record. A5 will not work until A4 succeeds.',
        )
        self.stdout.write(
            'Run A1 through A10 in Postman to test the full Credit flow on '
            'this fresh job.',
        )
