"""
mobile_api/pod_capture/views/pod_capture_view.py

POST shipment POD evidence capture (staging only).

``POST /api/v1/mobile/driver/jobs/shipments/<shipment_id>/pod/capture/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.job_detail.services.job_detail_driver_resolver import tenant_schema_for_request
from mobile_api.job_detail.services.shipment_job_resolver import resolve_shipment_job
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.serializers.pod_capture_serializer import (
    PodCaptureRequestSerializer,
)
from mobile_api.pod_capture.services.pod_capture_orchestrator import PodCaptureOrchestrator
from mobile_api.pod_capture.services.pod_capture_screen_routing import (
    build_pod_capture_get_routing,
)
from mobile_api.pod_capture.services.pod_section_metadata import build_pod_section_metadata
from mobile_api.pod_capture.services.shipment_log_evidence import resolve_shipment_log_evidence
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.utils.file_upload_handler import merge_multipart_media_with_json_hints
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.pod_capture')


class PodCaptureAPIView(MobileAPIView):
    """
    Stage POD evidence for a shipment — does not execute workflow actions.

    Security: JWT, driver role, ``mobile.driver.pod_capture``, tenant schema,
    shipment ownership inside orchestrator.
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.pod_capture'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._orchestrator = PodCaptureOrchestrator()

    def get(self, request, shipment_id: str, *args, **kwargs):
        """
        Return POD capture sync metadata for one shipment.

        GET /api/v1/mobile/driver/jobs/shipments/{shipment_id}/pod/capture/
        """
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
        updated = getattr(shipment, 'updated_at', None)
        hash_value = updated.isoformat() if hasattr(updated, 'isoformat') else ''
        log_evidence = resolve_shipment_log_evidence(
            shipment,
            driver=driver,
            tenant_schema=tenant_schema,
        )
        pod_section = build_pod_section_metadata(
            shipment,
            driver=driver,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
        requested_step = str(
            request.query_params.get('step')
            or request.query_params.get('capture_step')
            or ''
        ).strip()
        routing = build_pod_capture_get_routing(
            pod_section,
            requested_step=requested_step,
        )
        digital = dict(pod_section.get('digital_evidence') or {})
        hard_block = dict(pod_section.get('hard_copy_confirmation') or {})
        from mobile_api.pod_capture.services.pod_section_metadata import (
            DIGITAL_EVIDENCE_SCREEN_TITLE,
            HARD_COPY_SCREEN_TITLE,
            UI_MODE_DIGITAL_EVIDENCE,
            UI_MODE_HARD_POD_CONFIRMATION,
            build_hard_copy_confirmation_ui,
        )

        capture_mode = (routing.get('capture_mode') or '').strip().casefold()
        is_hard_copy_step = capture_mode == 'hard_copy_confirmation'
        screen_contract = ''
        if is_hard_copy_step:
            pages = list(hard_block.get('pages') or [])
            confirmation_ui = dict(hard_block.get('confirmation_ui') or {})
            if not confirmation_ui and pages:
                confirmation_ui = build_hard_copy_confirmation_ui(pages)
            screen_title = HARD_COPY_SCREEN_TITLE
            ui_mode = UI_MODE_HARD_POD_CONFIRMATION
            capture_ui = {}
            screen_contract = 'confirmation_ui'
        else:
            confirmation_ui = {}
            screen_title = (
                pod_section.get('screen_title')
                or digital.get('screen_title')
                or DIGITAL_EVIDENCE_SCREEN_TITLE
            )
            ui_mode = UI_MODE_DIGITAL_EVIDENCE
            capture_ui = pod_section.get('capture_ui') or digital.get('capture_ui') or {}
        data = {
            'shipment_id': str(getattr(shipment, 'pk', None) or shipment_id),
            'content_hash': hash_value,
            'workflow_version': hash_value,
            'entity_versions': {
                'shipment': hash_value,
            },
            'generated_at': hash_value,
            'pod_section': pod_section,
            'screen_title': screen_title,
            'ui_mode': ui_mode,
            'capture_ui': capture_ui,
            'confirmation_ui': confirmation_ui,
            'screen_contract': screen_contract,
            **routing,
        }
        return self.success(
            message=_('mobile.pod_capture.success'),
            data=data,
            message_key='mobile.pod_capture.success',
            http_code=200,
        )

    def post(self, request, shipment_id: str):
        serializer_data = {key: request.data.get(key) for key in request.data.keys()}
        processed_media = merge_multipart_media_with_json_hints(
            request,
            prefix='media',
            subfolder='pod_evidence',
        )
        if processed_media:
            serializer_data['media'] = processed_media

        serializer = PodCaptureRequestSerializer(data=serializer_data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

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

        try:
            data = self._orchestrator.capture_pod_evidence(
                driver=driver,
                tenant_schema=tenant_schema,
                shipment_id=shipment_id,
                payload=serializer.validated_data,
                request=request,
                user_id=str(jwt_payload.get('user_id') or ''),
                job_type='shipment',
            )
        except PodCaptureError as exc:
            logger.warning(
                'pod_capture denied shipment_id=%s code=%s',
                shipment_id,
                exc.code,
            )
            if exc.validation_error:
                return self.error(
                    message=str(exc),
                    data=exc.to_validation_dict(),
                    code=exc.code,
                    message_key=exc.message_key,
                    http_code=exc.http_status,
                )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        http_code = 200 if data.get('capture_bundle', {}).get('replayed') else 201
        return self.success(
            message=_('mobile.pod_capture.success'),
            data=data,
            message_key='mobile.pod_capture.success',
            http_code=http_code,
        )
