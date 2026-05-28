from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = 'Find and repair Loaded shipments missing Movement records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            required=True,
            help='Tenant schema name',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without fixing',
        )

    def handle(self, *args, **options):
        schema = options['schema']
        dry_run = options['dry_run']

        connection.set_schema(schema)

        from iroad_tenants.operation_runtime.movement_ops import (
            birth_movement_for_shipment,
        )
        from tenant_workspace.models import (
            TenantShipment,
            TenantTruckMovementLog,
        )

        loaded_shipments = TenantShipment.objects.filter(
            shipment_status=TenantShipment.ShipmentStatus.LOADED
        )

        fixed = 0
        for shipment in loaded_shipments:
            has_movement = (
                TenantTruckMovementLog.objects.filter(shipment=shipment)
                .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
                .exists()
            )

            if not has_movement:
                self.stdout.write(
                    f'Orphan found: {shipment.shipment_no} ({shipment.shipment_id})'
                )
                if not dry_run:
                    with transaction.atomic():
                        birth_movement_for_shipment(
                            shipment,
                            movement_date=shipment.shipment_date or datetime.date.today(),
                            created_by_label='repair_command',
                        )
                    self.stdout.write('  Fixed: Movement created')
                    fixed += 1
                else:
                    self.stdout.write('  Would fix (dry-run)')

        self.stdout.write(f'Done. Fixed {fixed} orphan shipments.')
