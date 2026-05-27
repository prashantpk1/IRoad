"""
Expire draft/ready POD capture bundles past TTL. Promoted bundles and audit rows are kept.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from mobile_api.pod_capture.repositories.durable_bundle_repository import (
    DurableBundleRepository,
)


class Command(BaseCommand):
    help = 'Mark expired POD capture bundles (draft/ready) as expired; never deletes promoted rows.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--tenant-schema',
            dest='tenant_schema',
            default='',
            help='Optional tenant schema filter',
        )

    def handle(self, *args, **options) -> None:
        tenant = (options.get('tenant_schema') or '').strip() or None
        repo = DurableBundleRepository()
        count = repo.expire_stale_bundles(tenant_schema=tenant, now=timezone.now())
        self.stdout.write(
            self.style.SUCCESS(f'Expired {count} POD capture bundle(s) at {timezone.now().isoformat()}')
        )
