"""
Foundation tests for delay / issue reporting (prep-only).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch
from mobile_api.tests.transaction_test_case import TransactionTestCase

from mobile_api.issues.exceptions import IssueReportingError
from mobile_api.issues.models.operational_issue import (
    OperationalIssue,
    OperationalIssueEscalationEvent,
    OperationalIssueEvidence,
    OperationalIssueTimelineEntry,
)
from mobile_api.issues.services.issue_reconciliation_service import (
    IssueReconciliationService,
)
from mobile_api.issues.services.issue_reporting_service import (
    IssueReportingService,
    _IssueJobScope,
)


def _driver(driver_pk: str):
    return SimpleNamespace(pk=driver_pk, driver_id=driver_pk)


class _DummyShipmentResolver:
    def __init__(self, *, shipment_id: str, owned: bool = True, exists: bool = True):
        self._shipment_id = shipment_id
        self._owned = owned
        self._exists = exists

    def resolve(self, driver, shipment_id):
        if not self._exists:
            raise IssueReportingError(
                'Not found',
                code='job_not_found',
                http_status=404,
            )
        if not self._owned:
            raise IssueReportingError(
                'Forbidden',
                code='forbidden',
                http_status=403,
            )
        return SimpleNamespace(
            pk=shipment_id,
            shipment_id=shipment_id,
            booking=SimpleNamespace(pk='bk-1'),
        )


class IssueReportingFoundationTests(TransactionTestCase):
    reset_sequences = True

    def _service(self, *, shipment_id: str, owned: bool = True) -> IssueReportingService:
        svc = IssueReportingService()
        resolver = _DummyShipmentResolver(shipment_id=shipment_id, owned=owned)

        def _resolve_job_scope(**kwargs):
            shipment_ref = (kwargs.get('shipment_ref') or '').strip()
            movement_ref = (kwargs.get('movement_ref') or '').strip()
            ref = movement_ref or shipment_ref
            shipment = resolver.resolve(kwargs['driver'], ref)
            scope_id = str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', ''))
            return _IssueJobScope(
                job_type='shipment',
                scope_id=scope_id,
                shipment=shipment,
                movement=None,
            )

        svc._resolve_job_scope = _resolve_job_scope  # noqa: SLF001
        return svc

    def _payload(self, *, client_issue_id: str, shipment_id: str, issue_type: str = 'delay'):
        tenant = 'tenant_issues'
        driver_id = str(uuid.uuid4())
        return (
            tenant,
            driver_id,
            {
                'client_issue_id': client_issue_id,
                'shipment_id': shipment_id,
                'issue_type': issue_type,
                'severity': 'high',
                'notes': 'Traffic delay on highway',
                'latitude': '25.1',
                'longitude': '55.2',
                'media': [
                    {
                        'media_type': 'photo',
                        'file_ref': (
                            f'mobile_driver_uploads/{tenant}/{driver_id}/{shipment_id}'
                            f'/issues/delay.jpg'
                        ),
                        'file_name': 'delay.jpg',
                    }
                ],
            },
        )

    def test_movement_issue_via_shipment_id_fallback(self):
        movement_id = str(uuid.uuid4())
        client_issue_id = f'issue-mov-{uuid.uuid4()}'
        tenant, driver_id, payload = self._payload(
            client_issue_id=client_issue_id,
            shipment_id=movement_id,
            issue_type='delay',
        )
        movement = SimpleNamespace(
            pk=movement_id,
            movement_id=movement_id,
            truck=SimpleNamespace(pk='truck-1'),
        )

        svc = IssueReportingService()

        def _resolve_job_scope(**kwargs):
            return _IssueJobScope(
                job_type='movement',
                scope_id=movement_id,
                shipment=None,
                movement=movement,
            )

        svc._resolve_job_scope = _resolve_job_scope  # noqa: SLF001

        with patch(
            'mobile_api.issues.services.issue_reporting_service.append_incident_report_action_log',
        ) as mock_append_log:
            result = svc.report_issue(
                driver=_driver(driver_id),
                tenant_schema=tenant,
                payload=payload,
            )
            mock_append_log.assert_called_once()
            self.assertIsNone(mock_append_log.call_args.kwargs.get('shipment'))
            self.assertEqual(
                mock_append_log.call_args.kwargs.get('movement'),
                movement,
            )

        self.assertEqual(result['issue']['job_type'], 'movement')
        self.assertEqual(result['issue']['movement_id'], movement_id)

    def test_issue_creation_and_escalation_flow(self):
        shipment_id = str(uuid.uuid4())
        client_issue_id = f'issue-{uuid.uuid4()}'
        tenant, driver_id, payload = self._payload(
            client_issue_id=client_issue_id,
            shipment_id=shipment_id,
            issue_type='accident',
        )

        with patch(
            'mobile_api.issues.services.issue_reporting_service.append_incident_report_action_log',
        ) as mock_append_log:
            result = self._service(shipment_id=shipment_id).report_issue(
                driver=_driver(driver_id),
                tenant_schema=tenant,
                payload=payload,
            )
            mock_append_log.assert_called_once()

        self.assertIn('issue', result)
        self.assertIn('escalation', result)
        self.assertIn('timeline_preview', result)
        self.assertIn('workflow_impact', result)
        self.assertFalse(result['workflow_impact']['workflow_mutation_performed'])
        self.assertTrue(result['issue']['blocking_recommended'])
        self.assertEqual(result['escalation']['escalation_state'], 'escalated')

        issue = OperationalIssue.objects.get(client_issue_id=client_issue_id)
        self.assertEqual(issue.issue_type, 'accident')
        self.assertGreaterEqual(issue.escalation_events.count(), 1)
        self.assertGreaterEqual(issue.timeline_entries.count(), 1)
        self.assertGreaterEqual(issue.evidence_rows.count(), 1)

    def test_issue_replay_returns_same_issue(self):
        shipment_id = str(uuid.uuid4())
        client_issue_id = f'issue-{uuid.uuid4()}'
        tenant, driver_id, payload = self._payload(
            client_issue_id=client_issue_id,
            shipment_id=shipment_id,
        )
        svc = self._service(shipment_id=shipment_id)

        first = svc.report_issue(
            driver=_driver(driver_id),
            tenant_schema=tenant,
            payload=payload,
        )
        second = svc.report_issue(
            driver=_driver(driver_id),
            tenant_schema=tenant,
            payload=payload,
        )

        self.assertFalse(first['issue']['replayed'])
        self.assertTrue(second['issue']['replayed'])
        self.assertEqual(first['issue']['issue_id'], second['issue']['issue_id'])
        self.assertEqual(OperationalIssue.objects.filter(client_issue_id=client_issue_id).count(), 1)

    def test_issue_replay_integrity_mismatch_rejected(self):
        shipment_id = str(uuid.uuid4())
        client_issue_id = f'issue-{uuid.uuid4()}'
        tenant, driver_id, payload = self._payload(
            client_issue_id=client_issue_id,
            shipment_id=shipment_id,
        )
        svc = self._service(shipment_id=shipment_id)

        svc.report_issue(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)

        tampered = dict(payload)
        tampered['notes'] = 'tampered notes'
        with self.assertRaises(IssueReportingError) as exc:
            svc.report_issue(
                driver=_driver(driver_id),
                tenant_schema=tenant,
                payload=tampered,
            )
        self.assertEqual(exc.exception.http_status, 409)
        self.assertEqual(exc.exception.code, 'issue_replay_integrity_mismatch')

    def test_wrong_shipment_replay_rejected(self):
        shipment_id = str(uuid.uuid4())
        client_issue_id = f'issue-{uuid.uuid4()}'
        tenant, driver_id, payload = self._payload(
            client_issue_id=client_issue_id,
            shipment_id=shipment_id,
        )
        svc = self._service(shipment_id=shipment_id)
        svc.report_issue(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)

        payload['shipment_id'] = str(uuid.uuid4())
        with self.assertRaises(IssueReportingError) as exc:
            svc.report_issue(driver=_driver(driver_id), tenant_schema=tenant, payload=payload)
        self.assertEqual(exc.exception.code, 'issue_replay_shipment_mismatch')

    def test_wrong_driver_forbidden(self):
        shipment_id = str(uuid.uuid4())
        tenant, driver_id, payload = self._payload(
            client_issue_id=f'issue-{uuid.uuid4()}',
            shipment_id=shipment_id,
        )
        with self.assertRaises(IssueReportingError) as exc:
            self._service(shipment_id=shipment_id, owned=False).report_issue(
                driver=_driver(driver_id),
                tenant_schema=tenant,
                payload=payload,
            )
        self.assertEqual(exc.exception.code, 'forbidden')

    def test_media_staging_immutable(self):
        shipment_id = str(uuid.uuid4())
        tenant, driver_id, payload = self._payload(
            client_issue_id=f'issue-{uuid.uuid4()}',
            shipment_id=shipment_id,
        )
        self._service(shipment_id=shipment_id).report_issue(
            driver=_driver(driver_id),
            tenant_schema=tenant,
            payload=payload,
        )
        row = OperationalIssueEvidence.objects.first()
        self.assertIsNotNone(row)
        row.file_ref = 'tampered'
        with self.assertRaises(ValueError):
            row.save()

    def test_unresolved_issues_counted(self):
        shipment_id = str(uuid.uuid4())
        tenant = 'tenant_issues'
        driver_id = str(uuid.uuid4())

        OperationalIssue.objects.create(
            tenant_schema=tenant,
            shipment_id=shipment_id,
            driver_id=driver_id,
            client_issue_id=f'old-{uuid.uuid4()}',
            issue_type='delay',
            severity='low',
            escalation_state=OperationalIssue.EscalationState.OPEN,
            blocking_recommended=False,
        )

        recon = IssueReconciliationService()
        count = recon.count_unresolved_for_shipment(
            tenant_schema=tenant,
            shipment_id=shipment_id,
        )
        self.assertEqual(count, 1)

        OperationalIssue.objects.filter(shipment_id=shipment_id).update(
            escalation_state=OperationalIssue.EscalationState.RESOLVED,
        )
        self.assertEqual(
            recon.count_unresolved_for_shipment(
                tenant_schema=tenant,
                shipment_id=shipment_id,
            ),
            0,
        )

    def test_escalation_append_only(self):
        shipment_id = str(uuid.uuid4())
        tenant, driver_id, payload = self._payload(
            client_issue_id=f'issue-{uuid.uuid4()}',
            shipment_id=shipment_id,
        )
        self._service(shipment_id=shipment_id).report_issue(
            driver=_driver(driver_id),
            tenant_schema=tenant,
            payload=payload,
        )
        event = OperationalIssueEscalationEvent.objects.first()
        self.assertIsNotNone(event)
        event.notes = 'mutated'
        with self.assertRaises(ValueError):
            event.save()

    def test_reconciliation_blocking_recommended_for_route_blocked(self):
        recon = IssueReconciliationService()
        self.assertTrue(
            recon.compute_blocking_recommended(
                issue_type='route_blocked',
                severity='low',
            )
        )
        self.assertFalse(
            recon.compute_blocking_recommended(
                issue_type='other',
                severity='low',
            )
        )

    def test_timeline_entry_created_on_report(self):
        shipment_id = str(uuid.uuid4())
        tenant, driver_id, payload = self._payload(
            client_issue_id=f'issue-{uuid.uuid4()}',
            shipment_id=shipment_id,
            issue_type='customer_unavailable',
        )
        result = self._service(shipment_id=shipment_id).report_issue(
            driver=_driver(driver_id),
            tenant_schema=tenant,
            payload=payload,
        )
        preview = result['timeline_preview'].get('timeline_preview') or []
        self.assertGreaterEqual(len(preview), 1)
        self.assertEqual(preview[0].get('event_category'), 'issue')
