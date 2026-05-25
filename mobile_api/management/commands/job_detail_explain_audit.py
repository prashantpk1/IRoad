"""
EXPLAIN (FORMAT JSON) audit for Job Detail timeline query shapes on a tenant schema.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        'Run EXPLAIN on driver-scoped shipment/movement timeline querysets '
        'for one tenant schema (validates cursor index use).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--schema', required=True, help='Tenant schema name')
        parser.add_argument(
            '--driver-id',
            help='Driver UUID (optional; uses first driver if omitted)',
        )
        parser.add_argument(
            '--shipment-id',
            help='Shipment UUID for shipment timeline EXPLAIN',
        )
        parser.add_argument(
            '--movement-id',
            help='Movement UUID for movement timeline EXPLAIN',
        )
        parser.add_argument(
            '--page-size',
            type=int,
            default=25,
            help='LIMIT for EXPLAIN query (default 25)',
        )

    def handle(self, *args, **options):
        from django_tenants.utils import schema_context

        from iroad_tenants.services.timeline_service import TimelineService
        from mobile_api.helpers.timeline_cursor import apply_timeline_cursor_filter
        from tenant_workspace.models import DriverMaster, TenantShipment, TenantTruckMovementLog

        schema = options['schema']
        page_size = max(1, min(int(options['page_size']), 100))

        with schema_context(schema):
            driver_id = options.get('driver_id')
            if driver_id:
                driver = DriverMaster.objects.filter(pk=driver_id).first()
            else:
                driver = DriverMaster.objects.order_by('pk').first()
            if driver is None:
                self.stderr.write(self.style.ERROR('No driver found in schema'))
                raise SystemExit(1)

            shipment = None
            movement = None
            if options.get('shipment_id'):
                shipment = TenantShipment.objects.filter(
                    pk=options['shipment_id'],
                ).first()
            else:
                shipment = (
                    TenantShipment.objects.filter(driver_id=driver.pk)
                    .order_by('-updated_at')
                    .first()
                )
            if options.get('movement_id'):
                movement = TenantTruckMovementLog.objects.filter(
                    pk=options['movement_id'],
                ).first()
            else:
                movement = (
                    TenantTruckMovementLog.objects.filter(driver_id=driver.pk)
                    .order_by('-updated_at')
                    .first()
                )

            plans = []
            if shipment is not None:
                from iroad_tenants.services.timeline_query import (
                    scoped_shipment_action_log_queryset,
                    shipment_direct_projection,
                    shipment_via_movement_projection,
                )
                from iroad_tenants.services.timeline_query import base_action_log_queryset

                base = base_action_log_queryset(driver_id=driver.pk)
                direct = shipment_direct_projection(base, shipment.pk)
                via_movement = shipment_via_movement_projection(base, shipment.pk)
                qs = scoped_shipment_action_log_queryset(
                    shipment=shipment,
                    driver_id=driver.pk,
                    select_related=False,
                )
                plans.append(
                    self._explain(
                        direct[:page_size],
                        label=f'shipment_timeline_direct shipment={shipment.pk}',
                    )
                )
                plans.append(
                    self._explain(
                        via_movement[:page_size],
                        label=f'shipment_timeline_via_movement shipment={shipment.pk}',
                    )
                )
                plans.append(
                    self._explain(
                        qs[:page_size],
                        label=f'shipment_timeline_union shipment={shipment.pk}',
                    )
                )
            if movement is not None:
                qs = TimelineService.scoped_action_log_queryset(
                    movement=movement,
                    driver_id=driver.pk,
                )
                plans.append(
                    self._explain(
                        qs[:page_size],
                        label=f'movement_timeline movement={movement.pk}',
                    )
                )

            if not plans:
                self.stderr.write(self.style.ERROR('No shipment/movement to EXPLAIN'))
                raise SystemExit(1)

            self.stdout.write(json.dumps(plans, indent=2))
            combined = json.dumps(plans).lower()
            if 'seq scan' in combined and 'tenant_operation_action_logs' in combined:
                self.stderr.write(
                    self.style.WARNING(
                        'Possible sequential scan on tenant_operation_action_logs — '
                        'confirm timeline indexes are present (0093/0095).'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        'No obvious seq scan on tenant_operation_action_logs.'
                    )
                )

    def _explain(self, qs, *, label: str) -> dict:
        sql, params = qs.query.sql_with_params()
        explain_sql = 'EXPLAIN (FORMAT JSON) ' + sql
        with connection.cursor() as cursor:
            cursor.execute(explain_sql, params)
            row = cursor.fetchone()
        plan = row[0] if row else []
        return {'label': label, 'plan': plan}
