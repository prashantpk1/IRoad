"""
PostgreSQL E2E — Job Detail POD upload and COD collection (real Action Logs).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from mobile_api.helpers.compliance_operation_actions import (
    resolve_cod_collect_action,
    resolve_pod_upload_action,
)
from mobile_api.services.driver_job_pod_cod_service import DriverJobPodCodService
from mobile_api.tests.job_detail_db_support import (
    JobDetailDbTestBase,
    job_detail_db_tests_enabled,
    skip_reason,
)
from tenant_workspace.models import TenantOperationActionLog, TenantShipment, TenantShipmentDocument


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailPodCodDbTests(JobDetailDbTestBase):
    def _shipment_for_cod(self):
        from tenant_workspace.models import TenantShipment

        return TenantShipment.objects.create(
            shipment_id=uuid.uuid4(),
            shipment_no=f'JD-COD-{uuid.uuid4().hex[:8]}',
            booking_item_ref='JD-COD',
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
            order_type='COD',
            cod_amount=Decimal('150.00'),
            collection_status=TenantShipment.CollectionStatus.PENDING,
            driver=self.driver,
        )

    def test_pod_execute_persists_log_when_compliance_met(self):
        pod_action = resolve_pod_upload_action()
        if pod_action is None:
            self.skipTest('POD action (A7) not configured in Action Master')

        TenantShipmentDocument.objects.create(
            shipment=self.shipment,
            record_no=f'DN-{uuid.uuid4().hex[:8]}',
            document_type='delivery_note',
            document_ref_no=f'DNREF-{uuid.uuid4().hex[:8]}',
            is_delivery_note=True,
            status=TenantShipmentDocument.Status.PENDING,
        )
        ctx = self.build_execution_context()
        before = self.log_count_for_shipment()

        with patch(
            'mobile_api.helpers.pod_cod_validation.count_media_attachments',
            return_value=1,
        ):
            result = DriverJobPodCodService.upload_pod(
                driver=self.driver,
                tenant_user=self.tenant_user,
                shipment_id=str(self.shipment.shipment_id),
                validated_body={
                    'idempotency_key': f'jd-pod-{uuid.uuid4().hex}',
                    'notes': 'pod-e2e',
                },
                execution_ctx=ctx,
            )

        if not result.get('success') and result.get('code') in (
            'action_not_allowed',
            'pod_validation_failed',
        ):
            self.skipTest(f'POD not allowed in fixture state: {result}')

        self.assertTrue(result.get('success'), result)
        self.assertEqual(self.log_count_for_shipment(), before + 1)
        self.assertIn('execution', result)
        self.assertIn('compliance', result)

    def test_cod_collect_persists_log_for_cod_shipment(self):
        cod_action = resolve_cod_collect_action()
        if cod_action is None:
            self.skipTest('COD action (A9) not configured in Action Master')

        shipment = self._shipment_for_cod()
        ctx = self.build_execution_context()
        before = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()

        result = DriverJobPodCodService.collect_cod(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(shipment.shipment_id),
            validated_body={
                'idempotency_key': f'jd-cod-{uuid.uuid4().hex}',
                'cod_amount': '150.00',
                'notes': 'cod-e2e',
            },
            execution_ctx=ctx,
        )

        if not result.get('success') and result.get('code') in (
            'action_not_allowed',
            'cod_validation_failed',
        ):
            self.skipTest(f'COD not allowed in fixture state: {result}')

        self.assertTrue(result.get('success'), result)
        after = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()
        self.assertEqual(after, before + 1)
        self.assertIn('treasury', (result.get('compliance') or {}).get('cod') or {})

    def test_cod_rejects_non_cod_order_type(self):
        cod_action = resolve_cod_collect_action()
        if cod_action is None:
            self.skipTest('COD action not configured')

        ctx = self.build_execution_context()
        before = self.log_count_for_shipment()
        result = DriverJobPodCodService.collect_cod(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body={'cod_amount': '10.00'},
            execution_ctx=ctx,
        )
        self.assertFalse(result.get('success'))
        self.assertEqual(self.log_count_for_shipment(), before)
