"""
mobile_api/hard_pod/views/hard_pod_documents_view.py

GET Shipment Document checklist for Hard POD confirmation.

``GET /api/v1/mobile/driver/jobs/shipments/<shipment_id>/hard-pod/documents/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.hard_pod.services.delivery_note_pages import (
    build_hard_pod_confirmation_context,
)
from mobile_api.job_detail.services.job_detail_driver_resolver import tenant_schema_for_request
from mobile_api.job_detail.services.shipment_job_resolver import resolve_shipment_job
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.pod_capture.services.pod_section_metadata import (
    HARD_POD_ACTION_CODE,
    build_hard_copy_confirmation_block,
)
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.hard_pod')


class HardPodDocumentsAPIView(MobileAPIView):
    """Return delivery-note documents and page checklist for Hard POD confirmation."""

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.hard_pod'
    throttle_classes = [MobileUserThrottle]

    def get(self, request, shipment_id: str):
        tenant_schema = tenant_schema_for_request(request)
        jwt_payload = get_mobile_jwt_payload(request)
        _tenant_user, driver, err_msg, err_code = resolve_mobile_driver_session(
            request,
            jwt_payload,
        )
        if driver is None:
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        if not tenant_schema:
            return self.error(
                message=_('mobile.auth.tenant_required'),
                code='tenant_required',
                message_key='mobile.auth.tenant_required',
                http_code=400,
            )

        resolved = resolve_shipment_job(
            driver,
            shipment_id,
            tenant_schema=tenant_schema,
        )
        if not resolved.ownership_validated or resolved.shipment is None:
            code = str(resolved.error_code or 'job_not_found')
            message = str(resolved.error_message or _('mobile.jobs.not_found'))
            http_code = 403 if code == 'forbidden' else 404
            if code == 'tenant_required':
                http_code = 400
            elif code in {'driver_inactive'}:
                http_code = 401
            return self.error(
                message=message,
                code=code,
                message_key='mobile.jobs.not_found' if http_code == 404 else None,
                http_code=http_code,
            )

        shipment = resolved.shipment
        hard_block = build_hard_copy_confirmation_block(
            shipment,
            driver=driver,
            tenant_schema=tenant_schema,
        )
        confirmation = build_hard_pod_confirmation_context(
            shipment,
            tenant_schema=tenant_schema,
        )

        data = {
            'shipment_id': str(getattr(shipment, 'pk', None) or shipment_id),
            'required': bool(hard_block.get('required')),
            'pending': bool(hard_block.get('pending')),
            'action_code': (hard_block.get('action_code') or HARD_POD_ACTION_CODE).strip(),
            'submit_endpoint': hard_block.get('submit_endpoint') or '/api/v1/mobile/driver/hard-pod/submit/',
            'execute_action_code': (
                hard_block.get('execute_action_code') or HARD_POD_ACTION_CODE
            ).strip(),
            'documents': list(confirmation.get('documents') or []),
            'pages': list(confirmation.get('pages') or []),
        }
        logger.info(
            'hard_pod_documents tenant=%s shipment=%s pages=%s',
            tenant_schema,
            data['shipment_id'],
            len(data['pages']),
        )
        return self.success(
            message=str(_('mobile.hard_pod.documents_success')),
            data=data,
            message_key='mobile.hard_pod.documents_success',
            http_code=200,
        )
