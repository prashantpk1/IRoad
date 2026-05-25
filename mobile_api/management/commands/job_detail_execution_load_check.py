"""
Job Detail load / EXPLAIN smoke for staging validation.

Usage::

    python manage.py job_detail_execution_load_check --schema tenant_x --shipment-id <uuid>
"""
from __future__ import annotations

import time
import uuid

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run timeline/detail query timing and optional EXPLAIN on a tenant schema.'

    def add_arguments(self, parser):
        parser.add_argument('--schema', required=True)
        parser.add_argument('--shipment-id', default='')
        parser.add_argument('--driver-id', default='')
        parser.add_argument('--explain', action='store_true')

    def handle(self, *args, **options):
        from django.db import connection
        from django_tenants.utils import schema_context

        from mobile_api.helpers.job_detail_perf import load_scoped_action_logs
        from iroad_tenants.services.timeline_service import TimelineService

        schema = options['schema']
        shipment_id = (options.get('shipment_id') or '').strip()
        driver_id = (options.get('driver_id') or '').strip()

        with schema_context(schema):
            from tenant_workspace.models import DriverMaster, TenantShipment

            shipment = None
            driver = None
            if shipment_id:
                try:
                    shipment = TenantShipment.objects.get(pk=uuid.UUID(shipment_id))
                except (TenantShipment.DoesNotExist, ValueError):
                    self.stderr.write('Shipment not found')
                    raise SystemExit(1)
            if driver_id:
                try:
                    driver = DriverMaster.objects.get(pk=uuid.UUID(driver_id))
                except (DriverMaster.DoesNotExist, ValueError):
                    driver = None
            if shipment is None:
                shipment = TenantShipment.objects.filter(driver__isnull=False).first()
            if shipment is None:
                self.stderr.write('No shipment in schema')
                raise SystemExit(1)
            if driver is None:
                driver = shipment.driver

            if options.get('explain'):
                with connection.cursor() as cursor:
                    cursor.execute(
                        'EXPLAIN (ANALYZE, BUFFERS) '
                        'SELECT log_id FROM tenant_operation_action_logs '
                        'WHERE shipment_id = %s AND driver_id = %s '
                        'ORDER BY log_date DESC, created_at DESC, log_id DESC LIMIT 21',
                        [shipment.pk, driver.pk],
                    )
                    for row in cursor.fetchall():
                        self.stdout.write(row[0])

            t0 = time.perf_counter()
            load_scoped_action_logs(
                shipment=shipment,
                driver_id=driver.pk,
                limit=120,
            )
            detail_ms = (time.perf_counter() - t0) * 1000

            t1 = time.perf_counter()
            qs = TimelineService.scoped_action_log_queryset(
                shipment=shipment,
                driver_id=driver.pk,
            )
            list(qs[:21])
            timeline_ms = (time.perf_counter() - t1) * 1000

            self.stdout.write(f'schema={schema} shipment={shipment.shipment_no}')
            self.stdout.write(f'detail_log_batch_ms={detail_ms:.1f}')
            self.stdout.write(f'timeline_page_ms={timeline_ms:.1f}')
            if detail_ms > 800:
                self.stdout.write(self.style.WARNING('detail_log_batch exceeds 800ms target'))
            if timeline_ms > 1000:
                self.stdout.write(self.style.WARNING('timeline_page exceeds 1000ms target'))
