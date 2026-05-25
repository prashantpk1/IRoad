"""
EXPLAIN (FORMAT JSON) audit for driver job list query shapes on a tenant schema.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Run EXPLAIN on job-list driver scope + list queries for one tenant schema.'

    def add_arguments(self, parser):
        parser.add_argument('--schema', required=True, help='Tenant schema name')
        parser.add_argument('--driver-id', required=True, help='Driver UUID for scope')

    def handle(self, *args, **options):
        schema = options['schema']
        driver_id = options['driver_id']
        from django_tenants.utils import schema_context

        from mobile_api.helpers.job_list_driver_scope import filter_shipments_for_driver
        from mobile_api.helpers.job_list_filters import JobListFilters, apply_job_filters
        from mobile_api.helpers.job_list_ordering import apply_job_ordering
        from tenant_workspace.models import DriverMaster

        with schema_context(schema):
            driver = DriverMaster.objects.filter(pk=driver_id).first()
            if driver is None:
                self.stderr.write(self.style.ERROR('Driver not found'))
                raise SystemExit(1)
            qs = filter_shipments_for_driver(driver)
            qs = apply_job_filters(
                qs,
                entity_type='shipment',
                filters=JobListFilters(tab='active'),
                driver=driver,
            )
            qs = apply_job_ordering(qs, entity_type='shipment', sort='updated_desc')
            sql, params = qs[:20].query.sql_with_params()
            explain_sql = 'EXPLAIN (FORMAT JSON) ' + sql
            with connection.cursor() as cursor:
                cursor.execute(explain_sql, params)
                row = cursor.fetchone()
            plan = row[0] if row else []
            self.stdout.write(json.dumps(plan, indent=2))
            text = json.dumps(plan).lower()
            if 'seq scan' in text and 'tenant_shipments' in text:
                self.stderr.write(self.style.WARNING('Possible sequential scan on tenant_shipments'))
            else:
                self.stdout.write(self.style.SUCCESS('No obvious seq scan on tenant_shipments.'))
