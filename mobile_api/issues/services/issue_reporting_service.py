"""
mobile_api/issues/services/issue_reporting_service.py

Orchestrate delay/issue reporting (prep-only operational exceptions).
"""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_ITEMS
from mobile_api.job_detail.guards.entity_lookup import (
    lookup_movement_by_reference,
    lookup_shipment_by_reference,
)
from mobile_api.job_detail.guards.ownership import (
    driver_owns_movement,
    driver_owns_shipment_leg,
    driver_pk,
    movement_is_driver_accessible,
    movement_is_empty_move_job,
    shipment_is_driver_accessible,
)
from mobile_api.job_detail.services.movement_job_resolver import resolve_empty_move_job
from mobile_api.issues.dto.issue_response_builder import IssueResponseBuilder
from mobile_api.issues.exceptions import IssueReportingError
from mobile_api.issues.models.operational_issue import OperationalIssue
from mobile_api.issues.services.issue_escalation_service import IssueEscalationService
from mobile_api.issues.services.issue_reconciliation_service import (
    IssueReconciliationService,
)
from mobile_api.issues.services.issue_action_log_bridge import (
    append_incident_report_action_log,
)
from mobile_api.issues.staging.issue_bundle_service import IssueBundleService


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _coord_str(value: Any) -> str:
    if value is None or value == '':
        return ''
    return str(value).strip()[:32]


@dataclass(frozen=True)
class _IssueJobScope:
    job_type: str
    scope_id: str
    shipment: Any | None = None
    movement: Any | None = None


class IssueReportingService:
    """Create operational exceptions with staged evidence (no workflow mutation)."""

    def __init__(
        self,
        *,
        bundle_service: IssueBundleService | None = None,
        escalation: IssueEscalationService | None = None,
        reconciliation: IssueReconciliationService | None = None,
        response_builder: IssueResponseBuilder | None = None,
    ) -> None:
        self._bundle = bundle_service or IssueBundleService()
        self._escalation = escalation or IssueEscalationService()
        self._reconciliation = reconciliation or IssueReconciliationService()
        self._response = response_builder or IssueResponseBuilder()

    def report_issue(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        client_issue_id = (payload.get('client_issue_id') or '').strip()
        shipment_ref = (payload.get('shipment_id') or '').strip()
        movement_ref = (payload.get('movement_id') or '').strip()
        driver_id = str(driver_pk(driver) or '').strip()
        issue_type = (payload.get('issue_type') or '').strip()
        severity = (payload.get('severity') or '').strip()
        notes = str(payload.get('notes') or '').strip()
        media_items = list(payload.get('media') or [])

        if not client_issue_id:
            raise IssueReportingError(
                str(_('mobile.issues.client_issue_id_required')),
                code='client_issue_id_required',
                http_status=400,
                message_key='mobile.issues.client_issue_id_required',
            )

        self._validate_issue_type(issue_type)
        self._validate_severity(severity)

        if len(media_items) > EXECUTION_MEDIA_MAX_ITEMS:
            raise IssueReportingError(
                str(_('mobile.jobs.execute.media_limit_exceeded')),
                code='media_limit_exceeded',
                http_status=400,
                message_key='mobile.jobs.execute.media_limit_exceeded',
            )

        existing = self._bundle.try_get_by_client_issue(
            tenant_schema=schema,
            driver_id=driver_id,
            client_issue_id=client_issue_id,
        )
        if existing is not None:
            try:
                file_refs = [
                    str(m.get('file_ref') or '').replace('\\', '/').lstrip('/')
                    for m in media_items
                ]
                expected_checksum = _sha256_hex(
                    '|'.join(
                        [
                            schema,
                            driver_id,
                            str(getattr(existing, 'shipment_id', '') or ''),
                            client_issue_id,
                            issue_type,
                            severity,
                            notes,
                            ','.join(sorted(r for r in file_refs if r)),
                        ]
                    )
                )
                self._bundle.assert_replay_scope(
                    existing=existing,
                    tenant_schema=schema,
                    driver_id=driver_id,
                    shipment_id=str(getattr(existing, 'shipment_id', '') or ''),
                    integrity_checksum=expected_checksum,
                )
            except ValueError as exc:
                code = str(exc)
                if 'shipment' in code:
                    raise IssueReportingError(
                        'Issue replay shipment scope mismatch.',
                        code='issue_replay_shipment_mismatch',
                        http_status=409,
                        message_key='mobile.issues.replay_shipment_mismatch',
                    ) from exc
                if 'driver' in code:
                    raise IssueReportingError(
                        'Issue replay driver scope mismatch.',
                        code='issue_replay_driver_mismatch',
                        http_status=409,
                        message_key='mobile.issues.replay_driver_mismatch',
                    ) from exc
                if 'integrity' in code:
                    raise IssueReportingError(
                        'Issue replay integrity mismatch.',
                        code='issue_replay_integrity_mismatch',
                        http_status=409,
                        message_key='mobile.issues.replay_integrity_mismatch',
                    ) from exc
                raise IssueReportingError(
                    'Issue replay scope mismatch.',
                    code='issue_replay_scope_mismatch',
                    http_status=409,
                    message_key='mobile.issues.replay_scope_mismatch',
                ) from exc

            evidence_rows = list(existing.evidence_rows.order_by('line_no'))
            replay_scope = _IssueJobScope(
                job_type='movement' if movement_ref else 'shipment',
                scope_id=str(getattr(existing, 'shipment_id', '') or ''),
            )
            return self._build_full_response(
                issue=existing,
                evidence_rows=evidence_rows,
                replayed=True,
                job_scope=replay_scope,
            )

        with schema_context(schema):
            job_scope = self._resolve_job_scope(
                driver=driver,
                shipment_ref=shipment_ref,
                movement_ref=movement_ref,
                tenant_schema=schema,
            )
            scope_id = job_scope.scope_id

            media_items = self._rehome_inline_issue_uploads(
                media_items=media_items,
                tenant_schema=schema,
                driver_pk=driver_id,
                shipment_pk=scope_id,
            )

            self._validate_media_paths(
                media_items=media_items,
                tenant_schema=schema,
                driver_pk=driver_id,
                shipment_pk=scope_id,
            )

            blocking_recommended = self._reconciliation.compute_blocking_recommended(
                issue_type=issue_type,
                severity=severity,
            )

            file_refs = [
                str(m.get('file_ref') or '').replace('\\', '/').lstrip('/')
                for m in media_items
            ]
            integrity_checksum = _sha256_hex(
                '|'.join(
                    [
                        schema,
                        driver_id,
                        scope_id,
                        client_issue_id,
                        issue_type,
                        severity,
                        notes,
                        ','.join(sorted(r for r in file_refs if r)),
                    ]
                )
            )

            initial_state = OperationalIssue.EscalationState.OPEN
            auto_escalate = blocking_recommended and severity in {
                OperationalIssue.Severity.HIGH,
                OperationalIssue.Severity.CRITICAL,
            }

            create_kwargs = dict(
                tenant_schema=schema,
                driver_id=driver_id,
                shipment_id=scope_id,
                client_issue_id=client_issue_id,
                issue_type=issue_type,
                severity=severity,
                notes=notes,
                escalation_state=initial_state,
                blocking_recommended=blocking_recommended,
                latitude=_coord_str(payload.get('latitude')),
                longitude=_coord_str(payload.get('longitude')),
                integrity_checksum=integrity_checksum,
                evidence_items=media_items,
            )

            try:
                issue, evidence_rows, created = self._bundle.create_race_safe(
                    create_kwargs=create_kwargs,
                )
            except ValueError as exc:
                # Most commonly: integrity checksum mismatch on unique collision.
                if 'integrity' in str(exc):
                    raise IssueReportingError(
                        'Issue replay integrity mismatch.',
                        code='issue_replay_integrity_mismatch',
                        http_status=409,
                        message_key='mobile.issues.replay_integrity_mismatch',
                    ) from exc
                raise

            if created:
                self._escalation.record_initial_report(
                    issue,
                    notes=notes,
                    auto_escalate=auto_escalate,
                )
                issue.refresh_from_db()
                append_incident_report_action_log(
                    shipment=job_scope.shipment,
                    movement=job_scope.movement,
                    driver=driver,
                    payload=payload,
                    client_issue_id=client_issue_id,
                    tenant_schema=schema,
                )

            return self._build_full_response(
                issue=issue,
                evidence_rows=evidence_rows,
                replayed=not created,
                job_scope=job_scope,
            )

    def _build_full_response(
        self,
        *,
        issue: OperationalIssue,
        evidence_rows: list[Any],
        replayed: bool,
        job_scope: _IssueJobScope | None = None,
    ) -> dict[str, Any]:
        unresolved = self._reconciliation.count_unresolved_for_shipment(
            tenant_schema=issue.tenant_schema,
            shipment_id=issue.shipment_id,
        )
        workflow_impact = self._reconciliation.workflow_impact(
            issue=issue,
            unresolved_count=unresolved,
        )
        escalation_payload = self._escalation.build_escalation_payload(issue)
        timeline_preview = self._escalation.build_timeline_preview(issue)
        return self._response.build_response(
            issue=issue,
            evidence_rows=evidence_rows,
            escalation=escalation_payload,
            timeline_preview=timeline_preview,
            workflow_impact=workflow_impact,
            replayed=replayed,
            job_type=(job_scope.job_type if job_scope else 'shipment'),
            movement_id=(
                job_scope.scope_id if job_scope and job_scope.job_type == 'movement' else ''
            ),
        )

    def _resolve_job_scope(
        self,
        *,
        driver: Any,
        shipment_ref: str,
        movement_ref: str,
        tenant_schema: str,
    ) -> _IssueJobScope:
        movement_ref = (movement_ref or '').strip()
        shipment_ref = (shipment_ref or '').strip()

        if movement_ref:
            return self._resolve_movement_scope(
                driver,
                movement_ref,
                tenant_schema=tenant_schema,
            )

        if shipment_ref:
            shipment = lookup_shipment_by_reference(shipment_ref)
            if shipment is not None:
                return self._resolve_shipment_scope(driver, shipment)

            movement = lookup_movement_by_reference(shipment_ref)
            if movement is not None:
                return self._resolve_movement_scope(
                    driver,
                    shipment_ref,
                    tenant_schema=tenant_schema,
                    movement=movement,
                )

        raise IssueReportingError(
            str(_('mobile.jobs.not_found')),
            code='job_not_found',
            http_status=404,
            message_key='mobile.jobs.not_found',
        )

    def _resolve_shipment_scope(self, driver: Any, shipment: Any) -> _IssueJobScope:
        if not shipment_is_driver_accessible(shipment):
            raise IssueReportingError(
                str(_('mobile.jobs.inactive')),
                code='job_inactive',
                http_status=404,
                message_key='mobile.jobs.inactive',
            )
        booking = getattr(shipment, 'booking', None)
        if not driver_owns_shipment_leg(driver, booking, shipment):
            raise IssueReportingError(
                str(_('mobile.auth.forbidden')),
                code='forbidden',
                http_status=403,
                message_key='mobile.auth.forbidden',
            )
        scope_id = str(
            getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', '') or ''
        ).strip()
        return _IssueJobScope(
            job_type='shipment',
            scope_id=scope_id,
            shipment=shipment,
            movement=None,
        )

    def _resolve_movement_scope(
        self,
        driver: Any,
        movement_ref: str,
        *,
        tenant_schema: str,
        movement: Any | None = None,
    ) -> _IssueJobScope:
        if movement is None:
            ctx = resolve_empty_move_job(
                driver,
                movement_ref,
                tenant_schema=tenant_schema,
            )
            if not ctx.ok:
                code = (ctx.error_code or 'job_not_found').strip()
                if code == 'forbidden':
                    raise IssueReportingError(
                        str(_('mobile.auth.forbidden')),
                        code='forbidden',
                        http_status=403,
                        message_key='mobile.auth.forbidden',
                    )
                if code == 'job_inactive':
                    raise IssueReportingError(
                        str(_('mobile.jobs.inactive')),
                        code='job_inactive',
                        http_status=404,
                        message_key='mobile.jobs.inactive',
                    )
                raise IssueReportingError(
                    str(_('mobile.jobs.not_found')),
                    code='job_not_found',
                    http_status=404,
                    message_key='mobile.jobs.not_found',
                )
            movement = ctx.entity_row

        if not movement_is_empty_move_job(movement):
            raise IssueReportingError(
                str(_('mobile.jobs.not_found')),
                code='job_not_found',
                http_status=404,
                message_key='mobile.jobs.not_found',
            )
        if not movement_is_driver_accessible(movement):
            raise IssueReportingError(
                str(_('mobile.jobs.inactive')),
                code='job_inactive',
                http_status=404,
                message_key='mobile.jobs.inactive',
            )
        if not driver_owns_movement(driver, movement):
            raise IssueReportingError(
                str(_('mobile.auth.forbidden')),
                code='forbidden',
                http_status=403,
                message_key='mobile.auth.forbidden',
            )
        scope_id = str(
            getattr(movement, 'pk', '')
            or getattr(movement, 'movement_id', '')
            or movement_ref
        ).strip()
        return _IssueJobScope(
            job_type='movement',
            scope_id=scope_id,
            shipment=None,
            movement=movement,
        )

    def _resolve_shipment(self, *, driver: Any, shipment_id: str) -> Any:
        reference = (shipment_id or '').strip()
        if not reference:
            raise IssueReportingError(
                str(_('mobile.validation.failed')),
                code='invalid_shipment_reference',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        shipment = lookup_shipment_by_reference(reference)
        if shipment is None:
            raise IssueReportingError(
                str(_('mobile.jobs.not_found')),
                code='job_not_found',
                http_status=404,
                message_key='mobile.jobs.not_found',
            )
        return self._resolve_shipment_scope(driver, shipment).shipment

    @staticmethod
    def _validate_issue_type(issue_type: str) -> None:
        valid = {c.value for c in OperationalIssue.IssueType}
        if issue_type not in valid:
            raise IssueReportingError(
                f'Invalid issue_type: {issue_type!r}',
                code='invalid_issue_type',
                http_status=400,
                message_key='mobile.issues.invalid_issue_type',
            )

    @staticmethod
    def _validate_severity(severity: str) -> None:
        valid = {c.value for c in OperationalIssue.Severity}
        if severity not in valid:
            raise IssueReportingError(
                f'Invalid severity: {severity!r}',
                code='invalid_severity',
                http_status=400,
                message_key='mobile.issues.invalid_severity',
            )

    @staticmethod
    def issue_media_upload_prefix(
        *,
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> str:
        tenant = (tenant_schema or '').strip()
        driver = (driver_pk or '').strip()
        shipment = (shipment_pk or '').strip()
        return f'mobile_driver_uploads/{tenant}/{driver}/{shipment}/issues/'

    def _rehome_inline_issue_uploads(
        self,
        *,
        media_items: list[dict[str, Any]],
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> list[dict[str, Any]]:
        """
        Move multipart-uploaded files into the issue scoped prefix.

        `process_media_files` stores uploads under `mobile/issue_evidence/...`.
        This endpoint enforces the issue-specific secure scope, so we relocate
        those files before validating file_ref paths.
        """
        if not media_items:
            return media_items

        prefix = self.issue_media_upload_prefix(
            tenant_schema=tenant_schema,
            driver_pk=driver_pk,
            shipment_pk=shipment_pk,
        )
        migrated: list[dict[str, Any]] = []

        for item in media_items:
            row = dict(item or {})
            file_ref = str(row.get('file_ref') or '').strip()
            if not file_ref:
                migrated.append(row)
                continue

            normalized = file_ref.replace('\\', '/').lstrip('/')
            if normalized.startswith(prefix):
                migrated.append(row)
                continue

            if not normalized.startswith('mobile/issue_evidence/'):
                migrated.append(row)
                continue

            original_name = str(row.get('file_name') or '').strip()
            base_name = (
                os.path.basename(original_name)
                or os.path.basename(normalized)
                or f'{uuid.uuid4().hex}.bin'
            )
            target_ref = f'{prefix}{uuid.uuid4().hex}-{base_name}'

            try:
                if default_storage.exists(normalized):
                    with default_storage.open(normalized, 'rb') as src:
                        saved_ref = default_storage.save(
                            target_ref,
                            ContentFile(src.read()),
                        )
                    try:
                        default_storage.delete(normalized)
                    except Exception:
                        pass
                    row['file_ref'] = str(saved_ref).replace('\\', '/').lstrip('/')
            except Exception:
                # Keep original path; scope validation will reject invalid leftovers.
                pass

            migrated.append(row)

        return migrated

    def _validate_media_paths(
        self,
        *,
        media_items: list[dict[str, Any]],
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> None:
        prefix = self.issue_media_upload_prefix(
            tenant_schema=tenant_schema,
            driver_pk=driver_pk,
            shipment_pk=shipment_pk,
        )
        for item in media_items:
            file_ref = (item.get('file_ref') or '').strip()
            if not file_ref:
                continue
            normalized = file_ref.replace('\\', '/').lstrip('/')
            if '..' in normalized.split('/'):
                raise IssueReportingError(
                    'Invalid media path.',
                    code='invalid_media_path',
                    http_status=400,
                    message_key='mobile.issues.invalid_media_path',
                )
            if not normalized.startswith(prefix):
                raise IssueReportingError(
                    'Media path outside issue upload scope.',
                    code='orphan_upload',
                    http_status=403,
                    message_key='mobile.issues.orphan_upload',
                )
