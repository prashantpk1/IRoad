"""
mobile_api/hard_pod/guards/hard_pod_security_guard.py

Ownership, Hard POD shipment validation, and media path policy for submit.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.hard_pod.exceptions import HardPodError
from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference
from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    driver_owns_shipment_leg,
    shipment_is_driver_accessible,
)
from mobile_api.helpers.backload_booking_redirect import coerce_driver_active_shipment_leg
from tenant_workspace.models import TenantShipment


HARD_POD_UPLOAD_PREFIX = 'mobile_driver_uploads/{tenant}/{driver}/{shipment}/hard_pod/'


def build_hard_pod_upload_prefix(
    *,
    tenant_schema: str,
    driver_pk: str,
    shipment_pk: str,
) -> str:
    return HARD_POD_UPLOAD_PREFIX.format(
        tenant=(tenant_schema or '').strip(),
        driver=(driver_pk or '').strip(),
        shipment=(shipment_pk or '').strip(),
    )


class HardPodSecurityGuard:
    """Validate driver scope and Hard POD shipment eligibility (read-only checks)."""

    def resolve_and_assert_shipment(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        shipment_id: str,
    ) -> Any:
        driver_err = assert_driver_active(driver)
        if driver_err:
            raise HardPodError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=401,
                message_key='mobile.auth.unauthorized',
            )

        schema = (tenant_schema or '').strip()
        reference = (shipment_id or '').strip()
        if not schema:
            raise HardPodError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )
        if not reference:
            raise HardPodError(
                str(_('mobile.validation.failed')),
                code='invalid_shipment_reference',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        with schema_context(schema):
            shipment = lookup_shipment_by_reference(reference)
            if shipment is None:
                raise HardPodError(
                    str(_('mobile.jobs.not_found')),
                    code='job_not_found',
                    http_status=404,
                    message_key='mobile.jobs.not_found',
                )
            if not shipment_is_driver_accessible(shipment):
                raise HardPodError(
                    str(_('mobile.jobs.inactive')),
                    code='job_inactive',
                    http_status=404,
                    message_key='mobile.jobs.inactive',
                )
            booking = getattr(shipment, 'booking', None)
            if not driver_owns_shipment_leg(driver, booking, shipment):
                raise HardPodError(
                    str(_('mobile.auth.forbidden')),
                    code='forbidden',
                    http_status=403,
                    message_key='mobile.auth.forbidden',
                )
            shipment = coerce_driver_active_shipment_leg(driver, shipment) or shipment
            booking = getattr(shipment, 'booking', None) or booking
            pod_type = (getattr(shipment, 'pod_type', None) or '').strip()
            if pod_type != TenantShipment.PodType.HARD:
                raise HardPodError(
                    str(_('mobile.hard_pod.not_hard_pod_shipment')),
                    code='not_hard_pod_shipment',
                    http_status=400,
                    message_key='mobile.hard_pod.not_hard_pod_shipment',
                )
            return shipment

    def assert_media_paths(
        self,
        media_items: list[dict[str, Any]],
        *,
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> None:
        prefix = build_hard_pod_upload_prefix(
            tenant_schema=tenant_schema,
            driver_pk=driver_pk,
            shipment_pk=shipment_pk,
        )
        for row in media_items:
            file_ref = (row.get('file_ref') or '').replace('\\', '/').lstrip('/')
            if not file_ref:
                continue
            if not file_ref.startswith(prefix):
                raise HardPodError(
                    str(_('mobile.hard_pod.orphan_upload')),
                    code='orphan_upload',
                    http_status=403,
                    message_key='mobile.hard_pod.orphan_upload',
                )
