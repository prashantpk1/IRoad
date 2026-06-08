"""Shared operational field options — single source for Booking, Shipment, and linked forms."""

from __future__ import annotations

import json

from django.utils import timezone

from tenant_workspace.models import (
    SalesInvoiceReport,
    SalesInvoiceReportBooking,
    TenantBooking,
    TenantShipment,
)

OPERATION_ORDER_TYPE_OPTIONS = ('Credit', 'COD')
OPERATION_SALES_REPORT_STATUS_OPTIONS = ('Pending', 'Submitted', 'Invoiced')
OPERATION_PHYSICAL_LOCATION_OPTIONS = (
    'Not Collected',
    'With Driver',
    'In Company',
    'Submitted to Receiver',
    'Submitted to Client',
)
OPERATION_PHYSICAL_LOCATION_SET = frozenset(OPERATION_PHYSICAL_LOCATION_OPTIONS)


def normalize_operation_physical_location(value, default=''):
    """Canonical physical custody location for shipment documents and handover."""
    stripped = (value or '').strip()
    if stripped in OPERATION_PHYSICAL_LOCATION_SET:
        return stripped
    normalized = stripped.lower().replace('_', ' ').replace('-', ' ')
    normalized = ' '.join(normalized.split())
    legacy_map = {
        'not collected': 'Not Collected',
        'with driver': 'With Driver',
        'in company': 'In Company',
        'with admin': 'In Company',
        'office': 'In Company',
        'submitted to receiver': 'Submitted to Receiver',
        'with receiver': 'Submitted to Receiver',
        'receiver': 'Submitted to Receiver',
        'submitted to client': 'Submitted to Client',
        'with client': 'Submitted to Client',
        'client': 'Submitted to Client',
        'out of company': 'Submitted to Client',
    }
    return legacy_map.get(normalized, stripped if stripped else default)


def operation_pod_type_options():
    return tuple(choice[0] for choice in TenantShipment.PodType.choices)


def operation_pod_status_options():
    return tuple(choice[0] for choice in TenantShipment.PodStatus.choices)


def normalize_operation_pod_type(value, default=''):
    """Canonical POD type (Digital / Soft / Hard) for all operational forms."""
    normalized = (value or '').strip().lower().replace('_', ' ').replace('-', ' ')
    normalized = ' '.join(normalized.split())
    if normalized in {'soft', 'soft copy', 'photo'}:
        return TenantShipment.PodType.SOFT
    if normalized in {'hard', 'hard copy', 'signature'}:
        return TenantShipment.PodType.HARD
    if normalized in {'digital', 'digital evidence', 'digital copy'}:
        return TenantShipment.PodType.DIGITAL
    valid_values = {choice[0] for choice in TenantShipment.PodType.choices}
    return value if value in valid_values else default


def normalize_operation_pod_status(value, default=None):
    """Canonical POD status for all operational forms."""
    if default is None:
        default = TenantShipment.PodStatus.PENDING
    if not value:
        return default
    stripped = (value or '').strip()
    valid_values = {choice[0] for choice in TenantShipment.PodStatus.choices}
    if stripped in valid_values:
        return stripped
    normalized = stripped.lower().replace('_', ' ').replace('-', ' ')
    normalized = ' '.join(normalized.split())
    legacy_map = {
        'pending': TenantShipment.PodStatus.PENDING,
        'received': TenantShipment.PodStatus.HARD_COPY_RECEIVED,
        'hard copy received': TenantShipment.PodStatus.HARD_COPY_RECEIVED,
        'verified': TenantShipment.PodStatus.COMPLIANT,
        'compliant': TenantShipment.PodStatus.COMPLIANT,
        'not compliant': TenantShipment.PodStatus.NOT_COMPLIANT,
    }
    return legacy_map.get(normalized, default)


def operation_sales_report_status_label(report_status):
    """Map Sales Invoice Report status to booking/shipment Sales Report Status."""
    status = (report_status or '').strip()
    if status == SalesInvoiceReport.Status.CONVERTED:
        return 'Invoiced'
    if status == SalesInvoiceReport.Status.VERIFIED:
        return 'Submitted'
    if status == SalesInvoiceReport.Status.DRAFT:
        return 'Pending'
    return ''


def operation_sales_report_options_for_booking(booking):
    """Sales reports linked to a booking (direct FK or SIR booking lines)."""
    if booking is None:
        return []
    reports = {}
    if getattr(booking, 'sales_invoice_report_id', None):
        report = getattr(booking, 'sales_invoice_report', None)
        if report is None:
            report = SalesInvoiceReport.objects.filter(pk=booking.sales_invoice_report_id).first()
        if report is not None:
            reports[str(report.report_id)] = {
                'report_id': str(report.report_id),
                'report_no': report.report_no,
                'status': operation_sales_report_status_label(report.status),
            }
    for line in SalesInvoiceReportBooking.objects.filter(booking_id=booking.booking_id).select_related('report'):
        report = line.report
        if report is None:
            continue
        reports[str(report.report_id)] = {
            'report_id': str(report.report_id),
            'report_no': report.report_no,
            'status': operation_sales_report_status_label(report.status),
        }
    return sorted(reports.values(), key=lambda row: row['report_no'])


def operation_sales_report_lookup_by_booking_ids(booking_ids):
    """Lookup map: booking_id -> list of linked sales report options."""
    lookup = {str(booking_id): [] for booking_id in booking_ids}
    if not booking_ids:
        return lookup

    for line in (
        SalesInvoiceReportBooking.objects.filter(booking_id__in=booking_ids)
        .select_related('report')
        .order_by('report__report_no')
    ):
        report = line.report
        if report is None:
            continue
        bucket = lookup.setdefault(str(line.booking_id), [])
        option = {
            'report_id': str(report.report_id),
            'report_no': report.report_no,
            'status': operation_sales_report_status_label(report.status),
        }
        if option not in bucket:
            bucket.append(option)

    for booking in TenantBooking.objects.filter(
        booking_id__in=booking_ids,
        sales_invoice_report__isnull=False,
    ).select_related('sales_invoice_report'):
        report = booking.sales_invoice_report
        if report is None:
            continue
        bucket = lookup.setdefault(str(booking.booking_id), [])
        option = {
            'report_id': str(report.report_id),
            'report_no': report.report_no,
            'status': operation_sales_report_status_label(report.status),
        }
        if option not in bucket:
            bucket.append(option)

    for bucket in lookup.values():
        bucket.sort(key=lambda row: row['report_no'])
    return lookup


def operation_sales_report_linkage(booking):
    """Resolved Sales Report no + derived status for display controls."""
    empty = {
        'sales_report_no': '',
        'sales_report_status': '',
        'sales_report_id': None,
    }
    if booking is None:
        return empty

    report = None
    if getattr(booking, 'sales_invoice_report_id', None):
        report = getattr(booking, 'sales_invoice_report', None)
        if report is None:
            report = SalesInvoiceReport.objects.filter(pk=booking.sales_invoice_report_id).first()

    if report is None:
        status_rank = {
            SalesInvoiceReport.Status.CONVERTED: 0,
            SalesInvoiceReport.Status.VERIFIED: 1,
            SalesInvoiceReport.Status.DRAFT: 2,
        }
        lines = list(
            SalesInvoiceReportBooking.objects.filter(booking_id=booking.booking_id).select_related('report')
        )
        if lines:
            best_line = min(
                lines,
                key=lambda row: (
                    status_rank.get(getattr(row.report, 'status', ''), 99),
                    -(getattr(row.report, 'updated_at', timezone.now()).timestamp()),
                ),
            )
            report = best_line.report

    if report is None:
        stored_status = (getattr(booking, 'sales_report_status', '') or '').strip()
        if stored_status:
            empty['sales_report_status'] = stored_status
        return empty

    status_label = operation_sales_report_status_label(report.status)
    stored_status = (getattr(booking, 'sales_report_status', '') or '').strip()
    return {
        'sales_report_no': report.report_no,
        'sales_report_status': status_label or stored_status,
        'sales_report_id': str(report.report_id),
    }


def operation_field_options_context(*, booking=None):
    """Template context keys shared by Booking and Shipment forms."""
    pod_type_options = operation_pod_type_options()
    pod_status_options = operation_pod_status_options()
    sales_report = operation_sales_report_linkage(booking)
    return {
        'operation_order_type_options': OPERATION_ORDER_TYPE_OPTIONS,
        'operation_pod_type_options': pod_type_options,
        'operation_pod_status_options': pod_status_options,
        'operation_sales_report_status_options': OPERATION_SALES_REPORT_STATUS_OPTIONS,
        'operation_sales_report_options': operation_sales_report_options_for_booking(booking),
        'operation_sales_report': sales_report,
        'booking_order_type_options': OPERATION_ORDER_TYPE_OPTIONS,
        'booking_pod_type_options': pod_type_options,
        'booking_pod_status_options': pod_status_options,
        'booking_sales_report_options': operation_sales_report_options_for_booking(booking),
        'booking_sales_report': sales_report,
    }


def operation_sales_report_lookup_json(booking_ids):
    return json.dumps(operation_sales_report_lookup_by_booking_ids(booking_ids))
