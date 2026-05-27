"""
mobile_api/pod_capture/services/pod_capture_validation_service.py

Enterprise POD compliance validation — derives rules from Action Master + POD policy.

Reuses :class:`~mobile_api.execution.evidence.evidence_validation_service.EvidenceValidationService`
for GPS / notes / media count enforcement (no duplicated rule engine).
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_DOCUMENTS
from mobile_api.execution.evidence.evidence_validation_service import EvidenceValidationService
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput
from mobile_api.pod_capture.dto.validation_error import build_validation_error
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.policy.canonical_pod_action_registry import is_pod_upload_action
from mobile_api.pod_capture.policy.pod_capture_policy import (
    POD_CAPTURE_TYPES,
    build_pod_capture_requirements,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    resolve_default_pod_action,
)
from mobile_api.pod_capture.services.pod_evidence_adapter import (
    map_execute_error,
    media_items_to_action_log_rows,
    to_execute_action_context,
)


class PodCaptureValidationService:
    """
    Validate POD capture requests against workflow evidence requirements.

    Validation order::

        resolve target Action Master row
        → build_pod_capture_requirements (metadata + POD type overlay)
        → EvidenceValidationService (GPS, notes, media counts)
        → duplicate media / integrity checks
    """

    def __init__(
        self,
        *,
        evidence_validator: EvidenceValidationService | None = None,
    ) -> None:
        self._evidence = evidence_validator or EvidenceValidationService()

    def validate_capture_request(self, context: PodCaptureContext) -> None:
        if context.idempotent_replay:
            return

        self._validate_capture_metadata(context)
        self.resolve_target_action(context)
        self.validate_pod_compliance(context)

    def resolve_target_action(self, context: PodCaptureContext) -> None:
        """Load ``TenantOperationAction`` for ``target_action_code`` (tenant schema)."""
        code = (context.target_action_code or '').strip()
        if not code:
            raise self._validation_error(
                'target_action_code_required',
                str(_('mobile.pod_capture.target_action_code_required')),
            )

        schema = (context.tenant_schema or '').strip()
        with schema_context(schema):
            from tenant_workspace.models import TenantOperationAction

            action = (
                TenantOperationAction.objects.filter(action_code__iexact=code)
                .exclude(status=TenantOperationAction.Status.INACTIVE)
                .first()
            )

        if action is None:
            raise self._validation_error(
                'target_action_not_found',
                str(_('mobile.pod_capture.target_action_not_found')),
                http_status=404,
            )

        context.operation_action = action
        self._assert_pod_capture_action(action)

    @staticmethod
    def _assert_pod_capture_action(action) -> None:
        if not (
            is_pod_upload_action(action)
            or getattr(action, 'auto_pod_post', False)
            or getattr(action, 'hard_copy_collection', False)
        ):
            raise PodCaptureValidationService._validation_error(
                'target_action_not_pod_capture',
                str(_('mobile.pod_capture.target_action_not_pod_capture')),
            )

    def validate_pod_compliance(self, context: PodCaptureContext) -> None:
        """Run execution-grade evidence validation with POD policy overlay."""
        requirements = build_pod_capture_requirements(
            context.operation_action,
            pod_capture_type=context.pod_capture_type,
            shipment=context.shipment,
        )
        context.compliance_requirements = requirements

        exec_ctx = to_execute_action_context(context)
        try:
            self._evidence._validate_gps(exec_ctx.payload, requirements)  # noqa: SLF001
            self._evidence._validate_notes(exec_ctx.payload, requirements)  # noqa: SLF001
            self._validate_media_with_requirements(exec_ctx, requirements)
        except Exception as exc:
            if isinstance(exc, PodCaptureError):
                raise
            from mobile_api.execution.exceptions import ExecuteActionError

            if isinstance(exc, ExecuteActionError):
                raise map_execute_error(exc) from exc
            raise

        self._validate_document_minimum(context.media_items, requirements)
        self._assert_no_duplicate_media(context.media_items)
        self._assert_media_integrity(context.media_items)

    @staticmethod
    def _validate_document_minimum(
        items: list[PODCaptureMediaItemInput],
        requirements: dict,
    ) -> None:
        doc_min = int(requirements.get('document_min_count') or 0)
        if doc_min <= 0:
            return
        document_count = sum(
            1 for item in items if (item.media_type or '').strip().casefold() == 'document'
        )
        if document_count < doc_min:
            raise PodCaptureValidationService._validation_error(
                'document_required',
                str(_('mobile.pod_capture.document_required')),
            )
        if document_count > EXECUTION_MEDIA_MAX_DOCUMENTS:
            raise PodCaptureValidationService._validation_error(
                'document_limit_exceeded',
                str(_('mobile.pod_capture.document_limit_exceeded')),
            )

    def _validate_media_with_requirements(
        self,
        exec_ctx,
        requirements: dict,
    ) -> None:
        """Delegate count/MIME-type rules to execution validator with explicit requirements."""
        original_action = exec_ctx.operation_action
        try:
            exec_ctx.operation_action = original_action
            self._evidence._validate_media(exec_ctx, requirements)  # noqa: SLF001
        finally:
            exec_ctx.operation_action = original_action

    def _validate_capture_metadata(self, context: PodCaptureContext) -> None:
        client_capture_id = (context.client_capture_id or '').strip()
        if not client_capture_id:
            raise self._validation_error(
                'client_capture_id_required',
                str(_('mobile.pod_capture.client_capture_id_required')),
            )
        if len(client_capture_id) > 128:
            raise self._validation_error(
                'client_capture_id_too_long',
                str(_('mobile.pod_capture.client_capture_id_too_long')),
            )

        content_hash = (context.content_hash or '').strip()
        if not content_hash:
            raise self._validation_error(
                'content_hash_required',
                str(_('mobile.pod_capture.content_hash_required')),
            )

        pod_type = (context.pod_capture_type or '').strip().casefold()
        if pod_type and pod_type not in POD_CAPTURE_TYPES:
            raise self._validation_error(
                'invalid_pod_capture_type',
                str(_('mobile.pod_capture.invalid_pod_capture_type')),
            )

        lat = (context.latitude or '').strip()
        lon = (context.longitude or '').strip()
        if bool(lat) ^ bool(lon):
            raise self._validation_error(
                'gps_incomplete',
                str(_('mobile.pod_capture.gps_incomplete')),
            )

    @staticmethod
    def _assert_no_duplicate_media(items: list[PODCaptureMediaItemInput]) -> None:
        seen_refs: set[str] = set()
        seen_checksums: set[str] = set()
        for item in items:
            ref = (item.file_ref or '').strip().replace('\\', '/').lstrip('/').casefold()
            if ref:
                if ref in seen_refs:
                    raise PodCaptureValidationService._validation_error(
                        'duplicate_media',
                        str(_('mobile.pod_capture.duplicate_media')),
                    )
                seen_refs.add(ref)
            checksum = (item.checksum or '').strip().casefold()
            if checksum:
                if checksum in seen_checksums:
                    raise PodCaptureValidationService._validation_error(
                        'duplicate_media',
                        str(_('mobile.pod_capture.duplicate_media')),
                    )
                seen_checksums.add(checksum)

    @staticmethod
    def _assert_media_integrity(items: list[PODCaptureMediaItemInput]) -> None:
        for item in items:
            if not item.file_ref and not item.upload:
                raise PodCaptureValidationService._validation_error(
                    'media_file_required',
                    str(_('mobile.pod_capture.media_file_required')),
                )

    @staticmethod
    def _validation_error(
        error_code: str,
        message: str,
        *,
        http_status: int = 400,
    ) -> PodCaptureError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=False,
        )
        return PodCaptureError(
            message,
            code=error_code,
            http_status=http_status,
            message_key=f'mobile.pod_capture.{error_code}',
            refresh_required=False,
            validation_error=body,
        )
