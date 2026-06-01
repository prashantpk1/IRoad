from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection, transaction
import datetime
import uuid


class Command(BaseCommand):
    help = (
        'Seed a fresh Round Trip COD job '
        '(Booking + Outbound Shipment + Backload Shipment) '
        'for a driver. '
        'Run: python manage.py seed_driver_job_round_cod '
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
            '--backload-driver',
            type=str,
            default='',
            help=(
                'Driver code for backload leg. '
                'If not set uses same driver as outbound.'
            ),
        )
        parser.add_argument(
            '--cod-amount',
            type=str,
            default='1500.00',
            help='COD amount for outbound leg (default: 1500.00)',
        )
        parser.add_argument(
            '--backload-cod-amount',
            type=str,
            default='1200.00',
            help='COD amount for backload leg (default: 1200.00)',
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
        cod_amount = Decimal(options['cod_amount'])
        backload_cod_amount = Decimal(options['backload_cod_amount'])

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

        # --- Resolve backload driver ---
        backload_driver_code = options.get('backload_driver', '')
        if backload_driver_code:
            try:
                backload_driver = DriverMaster.objects.get(
                    driver_code=backload_driver_code,
                )
            except DriverMaster.DoesNotExist:
                self.stderr.write(
                    f'Backload driver {backload_driver_code} '
                    f'not found. Using same driver.',
                )
                backload_driver = driver
        else:
            backload_driver = driver

        # --- Resolve truck (first available) ---
        truck = TruckMaster.objects.first()
        if not truck:
            self.stderr.write('No truck found in database.')
            return

        backload_truck = TruckMaster.objects.last() or truck
        if backload_truck.pk == truck.pk:
            backload_truck = truck

        # --- Resolve client account (first available) ---
        client = TenantClientAccount.objects.first()
        if not client:
            self.stderr.write('No client account found.')
            return

        # --- Resolve addresses ---
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
            or TenantAddressMaster.objects.exclude(
                pk=loading_address.pk,
            ).first()
            or TenantAddressMaster.objects.last()
        )
        backload_delivery_address = (
            TenantAddressMaster.objects.exclude(
                pk=delivery_address.pk,
            ).exclude(
                pk=loading_address.pk,
            ).first()
            or loading_address
        )
        if not loading_address or not delivery_address:
            self.stderr.write('No addresses found.')
            return

        # --- Generate unique numbers ---
        today = datetime.date.today()
        unique_suffix = uuid.uuid4().hex[:8].upper()
        booking_no = f'BK-RT-COD-{unique_suffix}'
        outbound_shipment_no = f'SH-RT-COD-OUT-{unique_suffix}'
        backload_shipment_no = f'SH-RT-COD-BACK-{unique_suffix}'
        outbound_item_ref = f'RT-OUT-{unique_suffix}'
        backload_item_ref = f'RT-BACK-{unique_suffix}'

        self.stdout.write(f'Schema:               {schema}')
        self.stdout.write(
            f'Driver:               {driver.english_name} ({driver.driver_code})',
        )
        self.stdout.write(f'Truck:                {truck.plate_number}')
        self.stdout.write(f'Client:               {client.name_english}')
        self.stdout.write(f'Booking No:           {booking_no}')
        self.stdout.write(f'Outbound Shipment:    {outbound_shipment_no}')
        self.stdout.write(f'Backload Shipment:    {backload_shipment_no}')
        self.stdout.write(f'Outbound Driver:      {driver.english_name}')
        self.stdout.write(f'Backload Driver:      {backload_driver.english_name}')
        self.stdout.write(f'Trip Type:            Round')
        self.stdout.write(f'Order Type:           COD')
        self.stdout.write(f'Outbound COD Amount:  {cod_amount}')
        self.stdout.write(f'Backload COD Amount:  {backload_cod_amount}')
        self.stdout.write(f'Date:                 {today}')
        self.stdout.write(
            f'Outbound pickup:      {loading_address.display_name} '
            f'({loading_address.address_code})',
        )
        self.stdout.write(
            f'Outbound drop:        {delivery_address.display_name} '
            f'({delivery_address.address_code})',
        )
        self.stdout.write(
            f'Backload drop:        {backload_delivery_address.display_name} '
            f'({backload_delivery_address.address_code})',
        )

        if dry_run:
            self.stdout.write('DRY RUN — nothing saved.')
            return

        with transaction.atomic():
            booking = TenantBooking.objects.create(
                booking_no=booking_no,
                client_account=client,
                booking_status='Confirmed',
                trip_type='Round',
                order_type='COD',
                sourcing_mode='Internal',
                loading_address=loading_address,
                delivery_address=delivery_address,
                assigned_driver=driver,
                assigned_truck=truck,
                booking_line_backload_driver=backload_driver,
                booking_line_backload_truck=backload_truck,
                booking_line_cod_amount=cod_amount,
                booking_line_backload_cod_amount=backload_cod_amount,
                booking_date=today,
                created_by_label='seed_driver_job_round_cod',
            )
            self.stdout.write(
                f'Booking created: {booking.booking_no} ({booking.booking_id})',
            )

            outbound_shipment = TenantShipment.objects.create(
                shipment_no=outbound_shipment_no,
                booking=booking,
                client_account=client,
                booking_item_ref=outbound_item_ref,
                booking_item_type='Outbound',
                sourcing_mode='In-Source',
                trip_type='Round',
                order_type='COD',
                shipment_status='Created',
                pod_type='Soft',
                shipment_date=today,
                driver=driver,
                truck=truck,
                loading_address=loading_address,
                delivery_address=delivery_address,
                cod_amount=cod_amount,
                created_by_label='seed_driver_job_round_cod',
            )
            self.stdout.write(
                f'Outbound shipment created: {outbound_shipment.shipment_no} '
                f'({outbound_shipment.shipment_id})',
            )

            backload_shipment = TenantShipment.objects.create(
                shipment_no=backload_shipment_no,
                booking=booking,
                client_account=client,
                booking_item_ref=backload_item_ref,
                booking_item_type='Backload',
                sourcing_mode='In-Source',
                trip_type='Round',
                order_type='COD',
                shipment_status='Created',
                pod_type='Soft',
                shipment_date=today,
                driver=backload_driver,
                truck=backload_truck,
                loading_address=delivery_address,
                delivery_address=backload_delivery_address,
                cod_amount=backload_cod_amount,
                created_by_label='seed_driver_job_round_cod',
            )
            self.stdout.write(
                f'Backload shipment created: {backload_shipment.shipment_no} '
                f'({backload_shipment.shipment_id})',
            )

        self.stdout.write('')
        self.stdout.write('=== ROUND TRIP COD JOB READY ===')
        self.stdout.write(f'Booking ID:           {booking.booking_id}')
        self.stdout.write(f'Booking No:           {booking.booking_no}')
        self.stdout.write(f'Trip Type:            Round (COD)')
        self.stdout.write(f'Outbound COD Amount:  {cod_amount}')
        self.stdout.write(f'Backload COD Amount:  {backload_cod_amount}')
        self.stdout.write('')
        self.stdout.write('--- OUTBOUND LEG ---')
        self.stdout.write(f'Shipment ID:    {outbound_shipment.shipment_id}')
        self.stdout.write(f'Shipment No:    {outbound_shipment.shipment_no}')
        self.stdout.write(f'Driver:         {driver.english_name}')
        self.stdout.write(f'From:           {loading_address}')
        self.stdout.write(f'To:             {delivery_address}')
        self.stdout.write('')
        self.stdout.write('--- BACKLOAD LEG ---')
        self.stdout.write(f'Shipment ID:    {backload_shipment.shipment_id}')
        self.stdout.write(f'Shipment No:    {backload_shipment.shipment_no}')
        self.stdout.write(f'Driver:         {backload_driver.english_name}')
        self.stdout.write(f'From:           {delivery_address}')
        self.stdout.write(f'To:             {backload_delivery_address}')
        self.stdout.write('')
        self.stdout.write('ROUND TRIP COD FLOW:')
        self.stdout.write(
            'OUTBOUND: A1 A2 A3 A4 A5 A6 '
            'POD-Capture A7 A8 A9(Payment) A10',
        )
        self.stdout.write(
            'BACKLOAD: Dashboard -> A1 A2 A3 A4 A5 A6 '
            'POD-Capture A7 A8 A9(Payment) A10',
        )
        self.stdout.write('')
        self.stdout.write(
            'NOTE: Each leg requires its own A9 payment. '
            f'Outbound = {cod_amount} SAR. '
            f'Backload = {backload_cod_amount} SAR. '
            'Variance allowed on both legs.',
        )
        self.stdout.write(
            'NOTE: Complete Outbound fully (A10) first. '
            'Then Dashboard shows Backload as next active job. '
            'Same driver sees both legs if same_driver mode.',
        )
        self.stdout.write(
            'NOTE: Both shipments are Created status. '
            'Each leg creates its own Movement on A4.',
        )
