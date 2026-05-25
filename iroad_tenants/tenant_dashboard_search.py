"""Tenant portal dashboard search — global navbar vs hub-specific scopes."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django_tenants.utils import schema_context

from superadmin.models import SupportTicket
from tenant_workspace.models import (
    DriverMaster,
    SalesInvoiceReport,
    TenantAddressMaster,
    TenantBooking,
    TenantClientAccount,
    TenantOperationActionLog,
    TenantShipment,
    TenantShipmentDocument,
    TenantTruckMovementLog,
    TruckMaster,
)

SEARCH_LIMIT = 10
SHIPMENT_POD_REF_PREFIX = 'POD'

# Which result sections each search scope may return (strict — no mixing).
SCOPE_SECTION_KEYS: dict[str, tuple[str, ...]] = {
    'navbar': ('shipments', 'clients', 'addresses'),
    'overview': ('invoices', 'tickets', 'logs'),
    'operations': ('bookings', 'shipments', 'movements', 'pods'),
    'fleet_truck': ('trucks',),
    'fleet_driver': ('drivers',),
}

SECTION_LABELS: dict[str, str] = {
    'shipments': 'Shipments',
    'clients': 'Clients',
    'addresses': 'Addresses',
    'bookings': 'Bookings',
    'movements': 'Movements',
    'pods': 'POD',
    'invoices': 'Invoices',
    'tickets': 'Support tickets',
    'logs': 'Resource logs',
    'trucks': 'Trucks',
    'drivers': 'Drivers',
}

SECTION_TONES: dict[str, str] = {
    'shipments': 'green',
    'clients': 'purple',
    'addresses': 'orange',
    'bookings': 'blue',
    'movements': 'orange',
    'pods': 'green',
    'invoices': 'purple',
    'tickets': 'orange',
    'logs': 'blue',
    'trucks': 'blue',
    'drivers': 'green',
}

SECTION_TABLE_COLUMNS: dict[str, list[dict[str, str]]] = {
    'shipments': [
        {'key': 'ref', 'label': 'Shipment No'},
        {'key': 'name', 'label': 'Linked booking'},
        {'key': 'status', 'label': 'Status', 'badge': '1'},
    ],
    'clients': [
        {'key': 'ref', 'label': 'Account No'},
        {'key': 'name', 'label': 'Client name'},
    ],
    'addresses': [
        {'key': 'ref', 'label': 'Address code'},
        {'key': 'name', 'label': 'Display name'},
        {'key': 'detail', 'label': 'Client / City'},
    ],
    'bookings': [
        {'key': 'ref', 'label': 'Booking No'},
        {'key': 'name', 'label': 'Client'},
        {'key': 'status', 'label': 'Status', 'badge': '1'},
    ],
    'movements': [
        {'key': 'ref', 'label': 'Movement No'},
        {'key': 'name', 'label': 'Linked booking / shipment'},
        {'key': 'status', 'label': 'Status', 'badge': '1'},
    ],
    'pods': [
        {'key': 'ref', 'label': 'POD record'},
        {'key': 'name', 'label': 'Shipment / Booking'},
    ],
    'invoices': [
        {'key': 'ref', 'label': 'Report No'},
        {'key': 'name', 'label': 'Client'},
        {'key': 'status', 'label': 'Status', 'badge': '1'},
    ],
    'tickets': [
        {'key': 'ref', 'label': 'Ticket No'},
        {'key': 'name', 'label': 'Subject'},
        {'key': 'status', 'label': 'Status', 'badge': '1'},
    ],
    'logs': [
        {'key': 'ref', 'label': 'Log No'},
        {'key': 'name', 'label': 'Action / description'},
        {'key': 'detail', 'label': 'Source'},
    ],
    'trucks': [
        {'key': 'ref', 'label': 'Truck code'},
        {'key': 'name', 'label': 'Plate / type'},
    ],
    'drivers': [
        {'key': 'ref', 'label': 'Driver code'},
        {'key': 'name', 'label': 'Name'},
    ],
}

SECTION_ICONS: dict[str, str] = {
    'shipments': 'bi-truck',
    'clients': 'bi-people',
    'addresses': 'bi-geo-alt',
    'bookings': 'bi-calendar-check',
    'movements': 'bi-signpost-split',
    'pods': 'bi-cloud-upload',
    'invoices': 'bi-receipt',
    'tickets': 'bi-ticket-detailed',
    'logs': 'bi-journal-text',
    'trucks': 'bi-truck-front',
    'drivers': 'bi-person-badge',
}


def build_dashboard_search_routes() -> dict[str, str]:
    return {
        'api': reverse('iroad_tenants:tenant_dashboard_search'),
        'results': reverse('iroad_tenants:tenant_dashboard_search_results'),
        'dashboard': reverse('iroad_tenants:tenant_dashboard'),
        'login_events': reverse('iroad_tenants:tenant_login_session_events'),
        'bookings': reverse('iroad_tenants:tenant_operation_booking_list'),
        'clients': reverse('iroad_tenants:tenant_client_account'),
        'addresses': reverse('iroad_tenants:tenant_address_master'),
        'trucks': reverse('iroad_tenants:truck_master'),
        'drivers': reverse('iroad_tenants:driver_master'),
        'shipments': reverse('iroad_tenants:tenant_operation_shipment_list'),
        'invoices': reverse('iroad_tenants:sales_invoice_report_list'),
        'movements': reverse('iroad_tenants:tenant_operation_truck_movement_log_list'),
        'pods': reverse('iroad_tenants:tenant_operation_shipment_pod_list'),
        'support': reverse('iroad_tenants:tenant_support_ticket_list'),
    }


def get_search_scope_meta(scope: str) -> dict[str, str]:
    """UI copy for the results page header and search input."""
    key = (scope or 'navbar').strip().lower()
    catalog = {
        'navbar': {
            'title': 'Global search results',
            'subtitle': 'Shipments, clients, and addresses',
            'placeholder': 'Search shipments, clients, addresses...',
            'empty_hint': 'Try a shipment number, client name, account number, or address code.',
        },
        'overview': {
            'title': 'Overview search results',
            'subtitle': 'Invoices, support tickets, and resource logs',
            'placeholder': 'Search invoices, support tickets, or resource logs...',
            'empty_hint': 'Try an invoice report number, ticket ID, or action log number.',
        },
        'operations': {
            'title': 'Operations search results',
            'subtitle': 'Bookings, shipments, movements, and POD',
            'placeholder': 'Search bookings, shipments, movements, or POD...',
            'empty_hint': 'Try a booking number, shipment number, movement number, or POD record.',
        },
        'fleet_truck': {
            'title': 'Truck search results',
            'subtitle': 'Trucks only',
            'placeholder': 'Truck search (plate, VIN, brand)...',
            'empty_hint': 'Try a truck code, plate number, or VIN.',
        },
        'fleet_driver': {
            'title': 'Driver search results',
            'subtitle': 'Drivers only',
            'placeholder': 'Driver search (name, IQAMA, license)...',
            'empty_hint': 'Try a driver code, name, or ID number.',
        },
    }
    return catalog.get(key, catalog['navbar'])


def _empty_results() -> dict[str, list[dict[str, str]]]:
    keys = set()
    for section_keys in SCOPE_SECTION_KEYS.values():
        keys.update(section_keys)
    return {key: [] for key in keys}


def build_search_results_url(query: str, scope: str = '') -> str:
    q = (query or '').strip()
    params: dict[str, str] = {'q': q}
    if scope:
        params['scope'] = scope
    return f"{reverse('iroad_tenants:tenant_dashboard_search_results')}?{urlencode(params)}"


def _row(
    label: str,
    url: str,
    meta: str = '',
    result_type: str = '',
    *,
    ref: str = '',
    name: str = '',
    detail: str = '',
    status: str = '',
) -> dict[str, str]:
    return {
        'label': label,
        'url': url,
        'meta': meta,
        'type': result_type,
        'ref': ref or label,
        'name': name,
        'detail': detail,
        'status': status,
    }


def _split_meta_status(meta: str) -> tuple[str, str]:
    """Split 'Client · Draft' into detail + status."""
    text = (meta or '').strip()
    if ' · ' in text:
        parts = [p.strip() for p in text.split(' · ') if p.strip()]
        if len(parts) >= 2:
            return ' · '.join(parts[:-1]), parts[-1]
    return text, ''


def _append_q(base_url: str, param: str, value: str) -> str:
    sep = '&' if '?' in base_url else '?'
    return f'{base_url}{sep}{urlencode({param: value})}'


def _enabled_sections(scope: str) -> set[str]:
    key = (scope or 'navbar').strip().lower()
    return set(SCOPE_SECTION_KEYS.get(key, SCOPE_SECTION_KEYS['navbar']))


def _search_shipments(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    shipment_filter = (
        Q(shipment_no__icontains=q)
        | Q(booking__booking_no__icontains=q)
        | Q(client_account__display_name__icontains=q)
        | Q(booking_item_ref__icontains=q)
    )
    for shipment in (
        TenantShipment.objects.filter(shipment_filter)
        .select_related('booking', 'client_account')
        .order_by('-created_at')[:limit]
    ):
        meta = shipment.shipment_status or ''
        if shipment.booking_id:
            meta = f'{meta} · BK {shipment.booking.booking_no}'.strip(' · ')
        status = shipment.shipment_status or ''
        linked = f'BK {shipment.booking.booking_no}' if shipment.booking_id else ''
        rows.append(
            _row(
                f'Shipment {shipment.shipment_no}',
                reverse(
                    'iroad_tenants:tenant_operation_shipment_detail',
                    kwargs={'shipment_id': shipment.shipment_id},
                ),
                meta,
                'shipment',
                ref=shipment.shipment_no,
                name=linked,
                status=status,
            )
        )
    return rows


def _search_clients(q: str, limit: int, routes: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    client_filter = (
        Q(account_no__icontains=q)
        | Q(display_name__icontains=q)
        | Q(name_english__icontains=q)
        | Q(name_arabic__icontains=q)
    )
    for client in TenantClientAccount.objects.filter(client_filter).order_by('account_no')[:limit]:
        rows.append(
            _row(
                client.display_name or client.account_no,
                _append_q(routes['clients'], 'q', q),
                client.account_no,
                'client',
                ref=client.account_no,
                name=client.display_name or client.name_english,
            )
        )
    return rows


def _search_addresses(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    addr_filter = (
        Q(address_code__icontains=q)
        | Q(display_name__icontains=q)
        | Q(city__icontains=q)
        | Q(client_account__display_name__icontains=q)
    )
    for addr in (
        TenantAddressMaster.objects.filter(addr_filter)
        .select_related('client_account')
        .order_by('address_code')[:limit]
    ):
        client_label = addr.client_account.display_name if addr.client_account_id else ''
        rows.append(
            _row(
                f'{addr.address_code} — {addr.display_name}',
                reverse(
                    'iroad_tenants:tenant_address_master_detail',
                    kwargs={'address_ref': addr.address_code},
                ),
                f'{client_label} · {addr.city}'.strip(' · '),
                'address',
                ref=addr.address_code,
                name=addr.display_name,
                detail=f'{client_label} · {addr.city}'.strip(' · '),
            )
        )
    return rows


def _search_bookings(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    booking_filter = (
        Q(booking_no__icontains=q)
        | Q(client_account__display_name__icontains=q)
        | Q(client_account__account_no__icontains=q)
    )
    for booking in (
        TenantBooking.objects.filter(booking_filter)
        .select_related('client_account')
        .order_by('-created_at')[:limit]
    ):
        client_name = booking.client_account.display_name if booking.client_account_id else ''
        rows.append(
            _row(
                f'Booking {booking.booking_no}',
                reverse(
                    'iroad_tenants:tenant_operation_booking_detail',
                    kwargs={'booking_id': booking.booking_id},
                ),
                client_name,
                'booking',
                ref=booking.booking_no,
                name=client_name,
                status=booking.booking_status,
            )
        )
    return rows


def _search_movements(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    movement_filter = (
        Q(movement_no__icontains=q)
        | Q(notes__icontains=q)
        | Q(booking__booking_no__icontains=q)
        | Q(shipment__shipment_no__icontains=q)
    )
    for movement in (
        TenantTruckMovementLog.objects.filter(movement_filter)
        .select_related('booking', 'shipment')
        .order_by('-movement_date')[:limit]
    ):
        meta = movement.status or ''
        if movement.booking_id:
            meta = f'{meta} · BK {movement.booking.booking_no}'.strip(' · ')
        linked = ''
        if movement.booking_id:
            linked = f'BK {movement.booking.booking_no}'
        elif movement.shipment_id:
            linked = movement.shipment.shipment_no
        rows.append(
            _row(
                f'Movement {movement.movement_no}',
                reverse(
                    'iroad_tenants:tenant_operation_truck_movement_log_detail',
                    kwargs={'movement_id': movement.movement_id},
                ),
                meta,
                'movement',
                ref=movement.movement_no,
                name=linked,
                status=movement.status,
            )
        )
    return rows


def _search_pods(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pod_prefix = f'{SHIPMENT_POD_REF_PREFIX}-'
    pod_filter = (
        Q(record_no__icontains=q)
        | Q(booking__booking_no__icontains=q)
        | Q(shipment__shipment_no__icontains=q)
        | Q(shipment__booking_item_ref__icontains=q)
        | Q(document_ref_no__icontains=q)
    )
    for document in (
        TenantShipmentDocument.objects.filter(record_no__startswith=pod_prefix)
        .filter(pod_filter)
        .select_related('shipment', 'booking')
        .order_by('-created_at')[:limit]
    ):
        ship_no = document.shipment.shipment_no if document.shipment_id else ''
        meta = ship_no or (document.booking.booking_no if document.booking_id else '')
        pod_url = '{}?{}'.format(
            reverse('iroad_tenants:tenant_operation_shipment_pod_detail'),
            urlencode({'record_no': document.record_no}),
        )
        rows.append(
            _row(
                f'POD {document.record_no}',
                pod_url,
                meta,
                'pod',
                ref=document.record_no,
                name=meta,
            )
        )
    return rows


def _search_invoices(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    invoice_filter = Q(report_no__icontains=q) | Q(client__display_name__icontains=q)
    for invoice in (
        SalesInvoiceReport.objects.filter(invoice_filter)
        .select_related('client')
        .order_by('-report_date')[:limit]
    ):
        rows.append(
            _row(
                f'Invoice report {invoice.report_no}',
                reverse(
                    'iroad_tenants:sales_invoice_report_detail',
                    kwargs={'report_id': invoice.report_id},
                ),
                f'{invoice.client.display_name} · {invoice.status}',
                'invoice',
                ref=invoice.report_no,
                name=invoice.client.display_name,
                status=invoice.status,
            )
        )
    return rows


def _search_logs(q: str, limit: int, routes: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    log_filter = (
        Q(log_no__icontains=q)
        | Q(source_ref__icontains=q)
        | Q(created_by_label__icontains=q)
        | Q(booking__booking_no__icontains=q)
        | Q(shipment__shipment_no__icontains=q)
    )
    for action_log in (
        TenantOperationActionLog.objects.filter(log_filter)
        .select_related('booking', 'shipment', 'operation_action')
        .order_by('-log_date')[:limit]
    ):
        action_name = ''
        if action_log.operation_action_id:
            action_name = action_log.operation_action.english_label or ''
        meta = action_name or action_log.source or ''
        rows.append(
            _row(
                f'Action log {action_log.log_no}',
                reverse(
                    'iroad_tenants:tenant_operation_action_log_detail',
                    kwargs={'log_id': action_log.log_id},
                ),
                meta,
                'log',
                ref=action_log.log_no,
                name=meta,
                detail=action_log.source or '',
            )
        )

    lower = q.lower()
    if any(token in lower for token in ('login', 'session', 'audit', 'access')):
        rows.append(
            _row(
                'Browse login & session events',
                _append_q(routes['login_events'], 'q', q),
                'Audit & security',
                'login_events',
                ref='—',
                name='Login & session events',
                detail='Audit & security',
            )
        )
    return rows[: limit + 1]


def _search_trucks(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    truck_filter = (
        Q(truck_code__icontains=q)
        | Q(plate_number__icontains=q)
        | Q(chassis_number_vin__icontains=q)
        | Q(owner_name__icontains=q)
        | Q(truck_type__english_label__icontains=q)
    )
    for truck in (
        TruckMaster.objects.filter(truck_filter)
        .select_related('truck_type')
        .order_by('truck_code')[:limit]
    ):
        meta = truck.plate_number or ''
        if truck.truck_type_id:
            meta = f'{meta} · {truck.truck_type.english_label}'.strip(' · ')
        rows.append(
            _row(
                f'Truck {truck.truck_code}',
                reverse(
                    'iroad_tenants:truck_master_detail',
                    kwargs={'truck_id': truck.truck_id},
                ),
                meta,
                'truck',
                ref=truck.truck_code,
                name=meta,
            )
        )
    return rows


def _search_drivers(q: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    driver_filter = (
        Q(driver_code__icontains=q)
        | Q(english_name__icontains=q)
        | Q(arabic_name__icontains=q)
        | Q(id_number__icontains=q)
        | Q(mobile_number__icontains=q)
    )
    for driver in DriverMaster.objects.filter(driver_filter).order_by('driver_code')[:limit]:
        rows.append(
            _row(
                driver.english_name or driver.driver_code,
                reverse(
                    'iroad_tenants:driver_master_detail',
                    kwargs={'driver_id': driver.driver_id},
                ),
                driver.driver_code,
                'driver',
                ref=driver.driver_code,
                name=driver.english_name or driver.arabic_name,
            )
        )
    return rows


def _search_tickets(q: str, limit: int, tenant_id) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not tenant_id:
        return rows
    ticket_filter = Q(ticket_no__icontains=q) | Q(subject__icontains=q)
    for ticket in (
        SupportTicket.objects.filter(tenant_id=tenant_id)
        .filter(ticket_filter)
        .order_by('-created_at')[:limit]
    ):
        rows.append(
            _row(
                f'{ticket.ticket_no} — {ticket.subject}',
                reverse(
                    'iroad_tenants:tenant_support_ticket_detail',
                    kwargs={'ticket_id': ticket.ticket_id},
                ),
                ticket.status or '',
                'ticket',
                ref=ticket.ticket_no,
                name=ticket.subject,
                status=ticket.status or '',
            )
        )
    return rows


def run_dashboard_search(
    schema_name: str,
    query: str,
    *,
    tenant_id=None,
    scope: str = 'navbar',
    limit: int = SEARCH_LIMIT,
) -> dict[str, list[dict[str, str]]]:
    """Run search for exactly one scope — categories never mixed."""
    q = (query or '').strip()
    results = _empty_results()
    if not q or not schema_name:
        return results

    enabled = _enabled_sections(scope)
    routes = build_dashboard_search_routes()

    with schema_context(schema_name):
        if 'shipments' in enabled:
            results['shipments'] = _search_shipments(q, limit)
        if 'clients' in enabled:
            results['clients'] = _search_clients(q, limit, routes)
        if 'addresses' in enabled:
            results['addresses'] = _search_addresses(q, limit)
        if 'bookings' in enabled:
            results['bookings'] = _search_bookings(q, limit)
        if 'movements' in enabled:
            results['movements'] = _search_movements(q, limit)
        if 'pods' in enabled:
            results['pods'] = _search_pods(q, limit)
        if 'invoices' in enabled:
            results['invoices'] = _search_invoices(q, limit)
        if 'logs' in enabled:
            results['logs'] = _search_logs(q, limit, routes)
        if 'trucks' in enabled:
            results['trucks'] = _search_trucks(q, limit)
        if 'drivers' in enabled:
            results['drivers'] = _search_drivers(q, limit)

    if 'tickets' in enabled:
        results['tickets'] = _search_tickets(q, limit, tenant_id)

    return results


def count_dashboard_search_results(results: dict[str, list]) -> int:
    return sum(len(rows) for rows in results.values())


def summarize_dashboard_search(results: dict[str, list], scope: str = 'navbar') -> list[dict[str, Any]]:
    summary = []
    for key in SCOPE_SECTION_KEYS.get((scope or 'navbar').lower(), ()):
        count = len(results.get(key) or [])
        if count:
            summary.append({
                'key': key,
                'title': SECTION_LABELS.get(key, key.title()),
                'count': count,
                'tone': SECTION_TONES.get(key, 'blue'),
            })
    return summary


def build_result_sections(
    results: dict[str, list],
    scope: str,
) -> list[dict[str, Any]]:
    """Ordered sections with table columns for the results template."""
    sections = []
    for key in SCOPE_SECTION_KEYS.get((scope or 'navbar').lower(), ()):
        raw_rows = results.get(key) or []
        if not raw_rows:
            continue
        table_rows = []
        for idx, row in enumerate(raw_rows, start=1):
            table_rows.append({**row, 'sn': idx})
        sections.append({
            'key': key,
            'title': SECTION_LABELS.get(key, key.title()),
            'icon': SECTION_ICONS.get(key, 'bi-search'),
            'tone': SECTION_TONES.get(key, 'blue'),
            'columns': SECTION_TABLE_COLUMNS.get(key, []),
            'rows': table_rows,
            'count': len(table_rows),
        })
    return sections


def run_global_search(schema_name: str, query: str, *, limit: int = 12) -> list[dict[str, str]]:
    grouped = run_dashboard_search(schema_name, query, scope='navbar', limit=limit)
    flat: list[dict[str, str]] = []
    for key in SCOPE_SECTION_KEYS['navbar']:
        flat.extend(grouped.get(key) or [])
    return flat[:limit]


def pick_global_search_redirect(
    schema_name: str,
    query: str,
    routes: dict[str, str] | None = None,
    scope: str = 'navbar',
) -> str | None:
    q = (query or '').strip()
    if not q:
        return None
    return build_search_results_url(q, scope=scope or 'navbar')
