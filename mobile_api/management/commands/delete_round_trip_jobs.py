"""
Delete all round-trip bookings and related execution data in a tenant schema.

Usage:
  python manage.py delete_round_trip_jobs --dry-run
  python manage.py delete_round_trip_jobs --schema=t_bb773f861f3048748c0a7f0ffbee0df6 --confirm
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Q


class Command(BaseCommand):
    help = (
        'Delete all Round trip_type bookings and their shipments, '
        'movements, action logs, documents, and mobile staging rows.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            default='t_bb773f861f3048748c0a7f0ffbee0df6',
            help='Tenant schema name',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Count only; do not delete',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Required to perform deletes (ignored when --dry-run)',
        )

    def handle(self, *args, **options):
        schema = (options['schema'] or '').strip()
        dry_run = bool(options['dry_run'])
        confirm = bool(options['confirm'])

        if not schema:
            self.stderr.write('Schema is required.')
            return

        if not dry_run and not confirm:
            self.stderr.write(
                'Refusing to delete without --confirm. '
                'Use --dry-run to preview counts first.',
            )
            return

        connection.set_schema(schema)

        from tenant_workspace.models import TenantBooking, TenantShipment

        bookings = list(
            TenantBooking.objects.filter(trip_type__iexact='Round').order_by('booking_no'),
        )
        if not bookings:
            self.stdout.write(f'No round-trip bookings in schema {schema}.')
            return

        self.stdout.write(f'Schema: {schema}')
        self.stdout.write(f'Round-trip bookings found: {len(bookings)}')
        for booking in bookings:
            shipment_count = TenantShipment.objects.filter(booking_id=booking.pk).count()
            self.stdout.write(
                f'  - {booking.booking_no} ({booking.booking_id}) '
                f'[{shipment_count} shipment(s)]',
            )

        if dry_run:
            stats = self._purge_bookings(
                bookings,
                schema=schema,
                dry_run=True,
            )
            self.stdout.write('')
            self.stdout.write('DRY RUN — rows that would be deleted:')
            for key in sorted(stats.keys()):
                self.stdout.write(f'  {key}: {stats[key]}')
            return

        with transaction.atomic():
            stats = self._purge_bookings(
                bookings,
                schema=schema,
                dry_run=False,
            )

        self.stdout.write('')
        self.stdout.write('Deleted:')
        for key in sorted(stats.keys()):
            self.stdout.write(f'  {key}: {stats[key]}')
        self.stdout.write(self.style.SUCCESS('Round-trip purge complete.'))

    def _purge_bookings(
        self,
        bookings: list,
        *,
        schema: str,
        dry_run: bool,
    ) -> dict[str, int]:
        stats: dict[str, int] = defaultdict(int)

        for booking in bookings:
            self._purge_one_booking(
                booking,
                schema=schema,
                dry_run=dry_run,
                stats=stats,
            )

        return stats

    def _purge_one_booking(
        self,
        booking,
        *,
        schema: str,
        dry_run: bool,
        stats: dict[str, int],
    ) -> None:
        from tenant_workspace.models import (
            DriverTreasuryTransaction,
            TenantDocumentHandover,
            TenantOperationActionLog,
            TenantShipment,
            TenantShipmentDocument,
            TenantShipmentPodPage,
            TenantShipmentDocumentPage,
            TenantTruckMovementLog,
        )

        booking_pk = booking.pk
        shipments = list(TenantShipment.objects.filter(booking_id=booking_pk))
        shipment_pks = [s.pk for s in shipments]
        shipment_id_strs = [str(s.shipment_id) for s in shipments]

        self._delete_mobile_staging(
            schema,
            shipment_id_strs,
            dry_run=dry_run,
            stats=stats,
        )

        movement_pks = list(
            TenantTruckMovementLog.objects.filter(
                Q(shipment_id__in=shipment_pks) | Q(booking_id=booking_pk),
            ).values_list('pk', flat=True),
        )

        treasury_qs = DriverTreasuryTransaction.objects.filter(
            Q(shipment_id__in=shipment_pks) | Q(operation_action_log__booking_id=booking_pk),
        )
        self._delete_qs(treasury_qs, 'driver_treasury_transactions', dry_run, stats)

        log_qs = TenantOperationActionLog.objects.filter(
            Q(shipment_id__in=shipment_pks)
            | Q(booking_id=booking_pk)
            | Q(truck_movement_id__in=movement_pks),
        )
        self._delete_qs(log_qs, 'operation_action_logs', dry_run, stats)

        movement_qs = TenantTruckMovementLog.objects.filter(pk__in=movement_pks)
        self._delete_qs(movement_qs, 'truck_movement_logs', dry_run, stats)

        handover_qs = TenantDocumentHandover.objects.filter(
            Q(shipment_id__in=shipment_pks) | Q(booking_id=booking_pk),
        )
        self._delete_qs(handover_qs, 'document_handovers', dry_run, stats)

        doc_qs = TenantShipmentDocument.objects.filter(
            Q(shipment_id__in=shipment_pks) | Q(booking_id=booking_pk),
        )
        doc_pks = list(doc_qs.values_list('pk', flat=True))
        if doc_pks:
            pod_page_qs = TenantShipmentPodPage.objects.filter(document_id__in=doc_pks)
            if not dry_run:
                pod_page_qs.update(source_page_id=None)
            self._delete_qs(pod_page_qs, 'shipment_pod_pages', dry_run, stats)

            page_qs = TenantShipmentDocumentPage.objects.filter(document_id__in=doc_pks)
            self._delete_qs(page_qs, 'shipment_document_pages', dry_run, stats)

            self._delete_qs(doc_qs, 'shipment_documents', dry_run, stats)

        shipment_qs = TenantShipment.objects.filter(pk__in=shipment_pks)
        self._delete_qs(shipment_qs, 'shipments', dry_run, stats)

        from tenant_workspace.models import TenantBooking

        booking_qs = TenantBooking.objects.filter(pk=booking_pk)
        self._delete_qs(booking_qs, 'bookings', dry_run, stats)

    def _delete_mobile_staging(
        self,
        schema: str,
        shipment_id_strs: list[str],
        *,
        dry_run: bool,
        stats: dict[str, int],
    ) -> None:
        if not shipment_id_strs:
            return

        try:
            from mobile_api.hard_pod.models import (
                HardPODCustodySubmission,
                HardPODCustodySubmissionEvent,
                HardPODCustodySubmissionMedia,
            )
            from mobile_api.issues.models.operational_issue import (
                OperationalIssue,
                OperationalIssueEscalationEvent,
                OperationalIssueEvidence,
                OperationalIssueTimelineEntry,
            )
            from mobile_api.payment_collection.models import (
                PaymentCollectionAudit,
                PaymentCollectionBundle,
                PaymentCollectionEvidence,
            )
            from mobile_api.pod_capture.models import (
                PODCaptureBundle,
                PODCaptureMedia,
                PODCapturePromotionAudit,
            )
        except ImportError:
            return

        scope = Q(tenant_schema=schema) & Q(shipment_id__in=shipment_id_strs)

        issue_qs = OperationalIssue.objects.filter(scope)
        issue_pks = list(issue_qs.values_list('pk', flat=True))
        if issue_pks:
            self._delete_qs(
                OperationalIssueTimelineEntry.objects.filter(issue_id__in=issue_pks),
                'operational_issue_timeline',
                dry_run,
                stats,
            )
            self._delete_qs(
                OperationalIssueEscalationEvent.objects.filter(issue_id__in=issue_pks),
                'operational_issue_escalation',
                dry_run,
                stats,
            )
            self._delete_qs(
                OperationalIssueEvidence.objects.filter(issue_id__in=issue_pks),
                'operational_issue_evidence',
                dry_run,
                stats,
            )
            self._delete_qs(issue_qs, 'operational_issues', dry_run, stats)

        bundle_qs = PODCaptureBundle.objects.filter(scope)
        bundle_pks = list(bundle_qs.values_list('pk', flat=True))
        if bundle_pks:
            self._delete_qs(
                PODCapturePromotionAudit.objects.filter(bundle_id__in=bundle_pks),
                'pod_capture_promotion_audit',
                dry_run,
                stats,
            )
            self._delete_qs(
                PODCaptureMedia.objects.filter(bundle_id__in=bundle_pks),
                'pod_capture_media',
                dry_run,
                stats,
            )
            self._delete_qs(bundle_qs, 'pod_capture_bundles', dry_run, stats)

        pay_bundle_qs = PaymentCollectionBundle.objects.filter(scope)
        pay_pks = list(pay_bundle_qs.values_list('pk', flat=True))
        if pay_pks:
            self._delete_qs(
                PaymentCollectionAudit.objects.filter(bundle_id__in=pay_pks),
                'payment_collection_audit',
                dry_run,
                stats,
            )
            self._delete_qs(
                PaymentCollectionEvidence.objects.filter(bundle_id__in=pay_pks),
                'payment_collection_evidence',
                dry_run,
                stats,
            )
            self._delete_qs(pay_bundle_qs, 'payment_collection_bundles', dry_run, stats)

        hard_qs = HardPODCustodySubmission.objects.filter(scope)
        hard_pks = list(hard_qs.values_list('pk', flat=True))
        if hard_pks:
            self._delete_qs(
                HardPODCustodySubmissionEvent.objects.filter(submission_id__in=hard_pks),
                'hard_pod_events',
                dry_run,
                stats,
            )
            self._delete_qs(
                HardPODCustodySubmissionMedia.objects.filter(submission_id__in=hard_pks),
                'hard_pod_media',
                dry_run,
                stats,
            )
            self._delete_qs(hard_qs, 'hard_pod_submissions', dry_run, stats)

    @staticmethod
    def _delete_qs(qs, label: str, dry_run: bool, stats: dict[str, int]) -> None:
        count = qs.count()
        if count == 0:
            return
        if dry_run:
            stats[label] += count
            return
        deleted, _detail = qs.delete()
        stats[label] += int(deleted)
