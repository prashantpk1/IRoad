"""
mobile_api/payment_collection/services/payment_validation_service.py

Validate shipment ownership, COD eligibility, amount ceiling, and duplicates.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import mimetypes
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django_tenants.utils import schema_context
from django.utils.translation import gettext_lazy as _

from iroad_tenants.driver_treasury_ops import (
    cod_client_collection_exists,
    ensure_active_driver_treasury,
)
from tenant_workspace.models import TenantShipment

from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference
from mobile_api.job_detail.guards.ownership import (
    driver_owns_shipment_leg,
    shipment_is_driver_accessible,
)
from mobile_api.payment_collection.exceptions import PaymentCollectionError


class PaymentValidationService:
    """Read-only validation layer for payment collection staging."""

    def resolve_shipment(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        shipment_id: str,
    ) -> Any:
        reference = (shipment_id or '').strip()
        if not reference:
            raise PaymentCollectionError(
                str(_('mobile.validation.failed')),
                code='invalid_shipment_reference',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        with schema_context((tenant_schema or '').strip()):
            shipment = lookup_shipment_by_reference(reference)
            if shipment is None:
                raise PaymentCollectionError(
                    str(_('mobile.jobs.not_found')),
                    code='job_not_found',
                    http_status=404,
                    message_key='mobile.jobs.not_found',
                )
            if not shipment_is_driver_accessible(shipment):
                raise PaymentCollectionError(
                    str(_('mobile.jobs.inactive')),
                    code='job_inactive',
                    http_status=404,
                    message_key='mobile.jobs.inactive',
                )
            booking = getattr(shipment, 'booking', None)
            if not driver_owns_shipment_leg(driver, booking, shipment):
                raise PaymentCollectionError(
                    str(_('mobile.auth.forbidden')),
                    code='forbidden',
                    http_status=403,
                    message_key='mobile.auth.forbidden',
                )

            return shipment

    @staticmethod
    def _is_cod_shipment(shipment: Any | None) -> bool:
        return (getattr(shipment, 'order_type', None) or '').strip().upper() == 'COD'

    @staticmethod
    def payment_proof_upload_prefix(
        *,
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> str:
        tenant = (tenant_schema or '').strip()
        driver = (driver_pk or '').strip()
        shipment = (shipment_pk or '').strip()
        return f'mobile_driver_uploads/{tenant}/{driver}/{shipment}/payment_collection/'

    def validate_proof_media_paths(
        self,
        *,
        media_items: list[dict[str, Any]],
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> None:
        # Path + extension policy only (no DB writes). Storage existence is handled
        # later by Execute Action media pipeline when proofs are consumed.
        prefix = self.payment_proof_upload_prefix(
            tenant_schema=tenant_schema,
            driver_pk=driver_pk,
            shipment_pk=shipment_pk,
        )

        from mobile_api.execution.evidence.execution_media_security import (
            _EXTENSION_BY_MEDIA,
            _MIME_BY_MEDIA,
        )

        for item in media_items:
            media_type = (item.get('media_type') or '').strip().casefold()
            file_ref = (item.get('file_ref') or '').strip()
            if not file_ref:
                continue
            normalized = file_ref.replace('\\', '/').lstrip('/')
            if not normalized.startswith(prefix):
                raise PaymentCollectionError(
                    str(_('mobile.hard_pod.orphan_upload')),
                    code='orphan_upload',
                    http_status=403,
                    message_key='mobile.hard_pod.orphan_upload',
                )
            ext = PurePosixPath(normalized).suffix.lower()
            allowed_ext = _EXTENSION_BY_MEDIA.get(media_type) or set()
            if allowed_ext and ext and ext not in allowed_ext:
                raise PaymentCollectionError(
                    str(_('mobile.jobs.execute.media_extension_not_allowed')),
                    code='media_extension_not_allowed',
                    http_status=400,
                    message_key='mobile.jobs.execute.media_extension_not_allowed',
                )
            guessed_mime = mimetypes.guess_type(normalized)[0] or ''
            allowed_mimes = _MIME_BY_MEDIA.get(media_type) or set()
            if allowed_mimes and guessed_mime and guessed_mime not in allowed_mimes:
                raise PaymentCollectionError(
                    str(_('mobile.jobs.execute.media_mime_not_allowed')),
                    code='media_mime_not_allowed',
                    http_status=400,
                    message_key='mobile.jobs.execute.media_mime_not_allowed',
                )

    def validate_cod_eligibility(self, *, shipment: Any) -> None:
        if shipment is None:
            raise PaymentCollectionError(
                str(_('mobile.validation.failed')),
                code='shipment_missing',
            )
        if not self._is_cod_shipment(shipment):
            raise PaymentCollectionError(
                str(_('mobile.payment_collection.not_cod')),
                code='not_cod_shipment',
                http_status=400,
                message_key='mobile.hard_pod.not_hard_pod_shipment',
            )

    @staticmethod
    def detect_variance(*, collected_amount: Decimal, cod_amount: Decimal) -> dict[str, Any] | None:
        collected = Decimal(str(collected_amount))
        expected = Decimal(str(cod_amount))
        if collected == expected:
            return None

        variance_amount = collected - expected
        variance_type = 'short' if variance_amount < 0 else 'over'
        return {
            'has_variance': True,
            'variance_type': variance_type,
            'variance_amount': abs(variance_amount),
            'expected': expected,
            'collected': collected,
        }

    def validate_amount_ceiling(
        self,
        *,
        shipment: Any,
        amount: Decimal,
    ) -> dict[str, Decimal | bool]:
        expected = Decimal(str(getattr(shipment, 'cod_amount', None) or Decimal('0')))
        submitted = Decimal(str(amount))

        if submitted <= 0:
            raise PaymentCollectionError(
                str(_('mobile.payment_collection.amount_must_be_positive')),
                code='invalid_amount',
                http_status=400,
                message_key='mobile.validation.failed',
            )
        if submitted < expected:
            raise PaymentCollectionError(
                str(_('mobile.payment_collection.amount_below_minimum')),
                code='amount_below_minimum',
                http_status=400,
                message_key='mobile.payment_collection.amount_below_minimum',
            )
        variance = self.detect_variance(collected_amount=submitted, cod_amount=expected)
        return {
            'expected_amount': expected,
            'collected_amount': submitted,
            'variance_detected': bool(variance),
            'variance': variance,
        }

    def validate_duplicate_payment(
        self,
        *,
        shipment: Any,
        driver: Any,
        tenant_schema: str,
    ) -> bool:
        """
        True when the driver has already collected COD payment
        (Action 9 treasury side effects).
        """
        if shipment is None:
            return False

        if getattr(shipment, 'shipment_status', None) == TenantShipment.ShipmentStatus.CANCELLED:
            return True

        if getattr(shipment, 'collection_status', None) == TenantShipment.CollectionStatus.CANCELLED:
            return True

        if getattr(shipment, 'collection_status', None) == TenantShipment.CollectionStatus.COLLECTED:
            return True

        schema = (tenant_schema or '').strip()
        if not schema:
            return False

        with schema_context(schema):
            treasury = ensure_active_driver_treasury(driver, auto_create=False)
            if treasury is None:
                return False
            return cod_client_collection_exists(
                shipment=shipment,
                driver_treasury=treasury,
            )

