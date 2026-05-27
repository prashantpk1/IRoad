"""
DB-backed foundation tests for payment collection staging.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.test import TransactionTestCase

from mobile_api.payment_collection.exceptions import PaymentCollectionError
from mobile_api.payment_collection.models import (
    PaymentCollectionBundle,
    PaymentCollectionEvidence,
)
from mobile_api.payment_collection.services.payment_collection_service import (
    PaymentCollectionService,
)
from mobile_api.payment_collection.services.payment_reconciliation_service import (
    PaymentReconciliationService,
)
from mobile_api.payment_collection.services.payment_idempotency_service import (
    PaymentIdempotencyService,
)


class _DummyValidation:
    def __init__(self, *, expected_amount: Decimal, is_cod: bool = True, duplicate: bool = False):
        self._expected_amount = expected_amount
        self._is_cod = is_cod
        self._duplicate = duplicate

    def resolve_shipment(self, *, driver, tenant_schema, shipment_id):
        # Shipment stub: only fields referenced by validation are present.
        return SimpleNamespace(
            pk=shipment_id,
            shipment_id=shipment_id,
            order_type='COD' if self._is_cod else 'SA',
            cod_amount=self._expected_amount,
            collection_status='Pending',
        )

    def validate_cod_eligibility(self, *, shipment):
        if not self._is_cod:
            raise PaymentCollectionError(
                'Not a COD shipment.',
                code='not_cod_shipment',
                http_status=400,
                message_key='mobile.payment_collection.not_cod',
            )

    def validate_amount_ceiling(self, *, shipment, amount):
        expected = Decimal(str(getattr(shipment, 'cod_amount')))
        submitted = Decimal(str(amount))
        if submitted <= 0:
            raise PaymentCollectionError(
                'Invalid amount.',
                code='invalid_amount',
            )
        if submitted > expected:
            raise PaymentCollectionError(
                'Amount ceiling exceeded.',
                code='amount_ceiling_exceeded',
            )
        return {
            'expected_amount': expected,
            'collected_amount': submitted,
            'variance_detected': submitted != expected,
        }

    def validate_duplicate_payment(self, *, shipment, driver):
        return bool(self._duplicate)

    def validate_proof_media_paths(self, *, media_items, tenant_schema, driver_pk, shipment_pk):
        # For unit tests, skip path checks.
        return None


def _driver(driver_pk: str):
    return SimpleNamespace(pk=driver_pk, driver_id=driver_pk)


class PaymentCollectionFoundationTests(TransactionTestCase):
    reset_sequences = True

    def test_cod_payment_stages_bundle(self):
        tenant = 'tenant_payment'
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        client_payment_id = f'pay-{uuid.uuid4()}'

        service = PaymentCollectionService(
            validation=_DummyValidation(expected_amount=Decimal('100.00')),
            idempotency=PaymentIdempotencyService(),
            reconciliation=PaymentReconciliationService(),
        )

        payload = {
            'client_payment_id': client_payment_id,
            'shipment_id': shipment_id,
            'amount': '90.00',
            'notes': 'partial test',
            'payment_mode': 'COD',
            'proof_media': [
                {
                    'media_type': 'photo',
                    'file_ref': f'mobile_driver_uploads/{tenant}/{driver_id}/{shipment_id}/payment_collection/proof.jpg',
                    'file_name': 'proof.jpg',
                    'mime_type': 'image/jpeg',
                    'checksum': '',
                    'captured_at': None,
                    'sort_order': 1,
                }
            ],
        }

        result = service.stage_payment(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)
        self.assertIn('payment_bundle', result)
        self.assertIn('reconciliation', result)
        self.assertTrue(result['payment_bundle']['bundle_id'])
        self.assertTrue(result['reconciliation']['variance_detected'])
        self.assertEqual(PaymentCollectionBundle.objects.filter(tenant_schema=tenant).count(), 1)
        self.assertEqual(PaymentCollectionEvidence.objects.filter(bundle__tenant_schema=tenant).count(), 1)

    def test_non_cod_shipment_rejected(self):
        tenant = 'tenant_payment'
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        client_payment_id = f'pay-{uuid.uuid4()}'

        service = PaymentCollectionService(
            validation=_DummyValidation(expected_amount=Decimal('100.00'), is_cod=False),
        )

        payload = {
            'client_payment_id': client_payment_id,
            'shipment_id': shipment_id,
            'amount': '50.00',
            'notes': '',
            'payment_mode': 'COD',
            'proof_media': [],
        }

        with self.assertRaises(PaymentCollectionError) as exc:
            service.stage_payment(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)
        self.assertEqual(exc.exception.code, 'not_cod_shipment')

    def test_duplicate_payment_rejected_for_new_key(self):
        tenant = 'tenant_payment'
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        client_payment_id = f'pay-{uuid.uuid4()}'

        service = PaymentCollectionService(
            validation=_DummyValidation(expected_amount=Decimal('100.00'), duplicate=True),
        )

        payload = {
            'client_payment_id': client_payment_id,
            'shipment_id': shipment_id,
            'amount': '100.00',
            'notes': '',
            'payment_mode': 'COD',
            'proof_media': [],
        }

        with self.assertRaises(PaymentCollectionError) as exc:
            service.stage_payment(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)
        self.assertEqual(exc.exception.code, 'duplicate_payment')

    def test_replay_payment_returns_existing_bundle(self):
        tenant = 'tenant_payment'
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        client_payment_id = f'pay-{uuid.uuid4()}'

        service = PaymentCollectionService(
            validation=_DummyValidation(expected_amount=Decimal('100.00')),
        )

        payload = {
            'client_payment_id': client_payment_id,
            'shipment_id': shipment_id,
            'amount': '100.00',
            'notes': 'first',
            'payment_mode': 'COD',
            'proof_media': [],
        }

        first = service.stage_payment(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)
        second = service.stage_payment(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)

        self.assertFalse(first['payment_bundle']['replayed'])
        self.assertTrue(second['payment_bundle']['replayed'])
        self.assertEqual(
            PaymentCollectionBundle.objects.filter(client_payment_id=client_payment_id).count(),
            1,
        )

    def test_replay_payment_integrity_mismatch_rejected(self):
        tenant = 'tenant_payment'
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        client_payment_id = f'pay-{uuid.uuid4()}'

        service = PaymentCollectionService(
            validation=_DummyValidation(expected_amount=Decimal('100.00')),
        )

        base_payload = {
            'client_payment_id': client_payment_id,
            'shipment_id': shipment_id,
            'amount': '100.00',
            'notes': 'first',
            'payment_mode': 'COD',
            'proof_media': [
                {
                    'media_type': 'photo',
                    'file_ref': f'mobile_driver_uploads/{tenant}/{driver_id}/{shipment_id}/payment_collection/proof.jpg',
                    'file_name': 'proof.jpg',
                    'mime_type': 'image/jpeg',
                    'checksum': '',
                    'captured_at': None,
                    'sort_order': 1,
                }
            ],
        }

        service.stage_payment(
            driver=_driver(driver_id),
            tenant_schema=tenant,
            payload=base_payload,
        )

        tampered_payload = dict(base_payload)
        tampered_payload['amount'] = '90.00'  # same client key, different body
        tampered_payload['notes'] = 'tampered'

        from mobile_api.payment_collection.exceptions import PaymentCollectionError

        with self.assertRaises(PaymentCollectionError) as exc:
            service.stage_payment(
                driver=_driver(driver_id),
                tenant_schema=tenant,
                payload=tampered_payload,
            )
        self.assertEqual(exc.exception.http_status, 409)
        self.assertEqual(exc.exception.code, 'payment_replay_integrity_mismatch')

    def test_evidence_is_immutable(self):
        tenant = 'tenant_payment'
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        client_payment_id = f'pay-{uuid.uuid4()}'

        service = PaymentCollectionService(
            validation=_DummyValidation(expected_amount=Decimal('100.00')),
        )

        payload = {
            'client_payment_id': client_payment_id,
            'shipment_id': shipment_id,
            'amount': '100.00',
            'notes': '',
            'payment_mode': 'COD',
            'proof_media': [
                {
                    'media_type': 'photo',
                    'file_ref': f'mobile_driver_uploads/{tenant}/{driver_id}/{shipment_id}/payment_collection/proof.jpg',
                    'file_name': 'proof.jpg',
                    'mime_type': 'image/jpeg',
                    'checksum': '',
                    'captured_at': None,
                    'sort_order': 1,
                }
            ],
        }

        result = service.stage_payment(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)
        bundle_id = result['payment_bundle']['bundle_id']
        evidence = PaymentCollectionEvidence.objects.get(bundle__id=bundle_id)
        with self.assertRaises(ValueError):
            evidence.file_name = 'changed.jpg'
            evidence.save()

