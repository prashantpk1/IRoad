"""CSV export views for tenant portal list pages (honours current search/filters/sort)."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.db.models import Count, F, Q
from django.shortcuts import redirect
from django.views import View

from iroad_tenants.list_table_utils import (
    build_csv_http_response,
    build_eal_list_queryset,
    get_list_search_q,
)
from tenant_workspace.models import (
    DriverAttachment,
    DriverMaster,
    TenantAddressMaster,
    TenantBooking,
    TenantCargoCategory,
    TenantCargoMaster,
    TenantClientAccount,
    TenantClientContact,
    TenantClientContract,
    TenantDocumentHandover,
    TenantLocationMaster,
    TenantPriceList,
    TenantRouteMaster,
    TenantServiceItemMaster,
    TenantShipment,
    TenantShipmentDocument,
    TenantShipmentSurcharge,
    TenantTruckMovementLog,
    TruckAttachment,
    TruckMaster,
    TruckTypeMaster,
)


def _fmt_date(value):
    if not value:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    return str(value)


def _fmt_datetime(value):
    if not value:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _yes_no(flag):
    return 'Yes' if flag else 'No'


def _csv_cell(value):
    if value is None:
        return ''
    return value


class TenantWorkspaceExportView(View):
    """Base CSV export: activates tenant schema and applies list filters from GET."""

    filename = 'export.csv'
    headers: list[str] = []

    def check_access(self, request, context):
        return None

    def get_queryset(self, request):
        raise NotImplementedError

    def iter_rows(self, request, records):
        raise NotImplementedError

    def get(self, request):
        from iroad_tenants.views import (
            _activate_tenant_workspace_schema,
            _tenant_context_from_session,
            clear_tenant_portal_cookie,
            restore_public_schema,
        )

        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        denied = self.check_access(request, context)
        if denied is not None:
            return denied
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            records = list(self.get_queryset(request))
            return build_csv_http_response(
                self.filename,
                self.headers,
                self.iter_rows(request, records),
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                'Tenant list export failed (%s)',
                self.filename,
            )
            raise
        finally:
            restore_public_schema(request)


def _address_master_base_qs(request):
    qs = TenantAddressMaster.objects.select_related('client_account', 'country')
    status_raw = (request.GET.get('status') or '').strip().lower()
    if 'status' not in request.GET:
        qs = qs.filter(status=TenantAddressMaster.Status.ACTIVE)
    elif not status_raw or status_raw == 'active':
        qs = qs.filter(status=TenantAddressMaster.Status.ACTIVE)
    elif status_raw == 'inactive':
        qs = qs.filter(status=TenantAddressMaster.Status.INACTIVE)

    cid = (request.GET.get('client') or '').strip()
    if cid:
        try:
            qs = qs.filter(client_account_id=uuid.UUID(cid))
        except ValueError:
            client_row = TenantClientAccount.objects.filter(account_no__iexact=cid).first()
            if client_row:
                qs = qs.filter(client_account_id=client_row.account_id)

    column_field_map = {
        1: 'address_code',
        2: 'client_account__account_no',
        3: 'display_name',
        4: 'address_category',
        5: 'city',
        6: 'contact_name',
        7: 'phone_no',
    }
    sort_col_field_map = dict(column_field_map)
    search_fields = [
        'display_name',
        'address_code',
        'city',
        'client_account__display_name',
        'client_account__account_no',
        'contact_name',
        'phone_no',
    ]
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=search_fields,
        column_field_map=column_field_map,
        sort_col_field_map=sort_col_field_map,
        default_order=('address_code',),
    )


class TenantAddressMasterExportView(TenantWorkspaceExportView):
    filename = 'address_master_export.csv'
    headers = [
        'Address Code',
        'Client Account',
        'Display Name',
        'Address Category',
        'City',
        'Country',
        'Contact Name',
        'Phone No.',
        'Status',
    ]

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_address_master_access

        return _tenant_address_master_access(request, context)

    def get_queryset(self, request):
        return _address_master_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.address_code,
                row.client_account.account_no if row.client_account_id else '',
                row.display_name,
                row.address_category,
                row.city or '',
                row.country_id or '',
                row.contact_name or '',
                row.phone_no or '',
                row.status,
            ]


def _client_contacts_base_qs(request):
    chip = (request.GET.get('chip') or 'all').strip().lower()
    qs = TenantClientContact.objects.select_related('client_account')
    if chip == 'primary':
        qs = qs.filter(is_primary=True)
    elif chip == 'secondary':
        qs = qs.filter(is_primary=False)

    def _contact_primary_column_filter(queryset, val):
        v = val.strip().lower()
        if 'primary' in v and 'secondary' not in v:
            return queryset.filter(is_primary=True)
        if 'secondary' in v:
            return queryset.filter(is_primary=False)
        return queryset

    column_field_map = {
        1: 'client_account__account_no',
        2: 'name',
        3: 'email',
        4: 'mobile_number',
        5: 'telephone_number',
        6: 'extension',
        7: 'position',
        8: 'is_primary',
    }
    sort_col_field_map = dict(column_field_map)
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=[
            'client_account__account_no',
            'client_account__display_name',
            'name',
            'email',
            'mobile_number',
            'position',
        ],
        column_field_map=column_field_map,
        sort_col_field_map=sort_col_field_map,
        default_order=('-created_at',),
        column_filter_hooks={8: _contact_primary_column_filter},
    )


class TenantClientContactsExportView(TenantWorkspaceExportView):
    filename = 'client_contacts_export.csv'
    headers = [
        'Client Account',
        'Name',
        'Email',
        'Mobile',
        'Telephone',
        'Extension',
        'Position',
        'Primary',
    ]

    def get_queryset(self, request):
        return _client_contacts_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.client_account.account_no if row.client_account_id else '',
                row.name,
                row.email or '',
                row.mobile_number or '',
                row.telephone_number or '',
                row.extension or '',
                row.position or '',
                _yes_no(row.is_primary),
            ]


class TenantClientContractExportView(TenantWorkspaceExportView):
    filename = 'client_contracts_export.csv'
    headers = [
        'Contract No.',
        'Client Account',
        'Start Date',
        'End Date',
        'Notes',
        'Has Attachment',
        'Status',
    ]

    def get_queryset(self, request):
        column_field_map = {
            1: 'contract_no',
            2: 'client_account__account_no',
            3: 'start_date',
            4: 'end_date',
            5: 'notes',
            6: 'contract_attachment',
            7: 'status',
        }
        return build_eal_list_queryset(
            request,
            TenantClientContract.objects.select_related('client_account'),
            search_fields=[
                'contract_no',
                'client_account__account_no',
                'client_account__display_name',
                'notes',
            ],
            column_field_map=column_field_map,
            sort_col_field_map={
                1: 'contract_no',
                2: 'client_account__account_no',
                3: 'start_date',
                4: 'end_date',
                5: 'notes',
                7: 'status',
            },
            default_order=('-created_at',),
            column_filter_types={3: 'date', 4: 'date', 6: 'file'},
        )

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.contract_no,
                row.client_account.account_no if row.client_account_id else '',
                _fmt_date(row.start_date),
                _fmt_date(row.end_date),
                row.notes or '',
                _yes_no(bool(row.contract_attachment)),
                row.status,
            ]


def _cargo_master_base_qs(request):
    qs = TenantCargoMaster.objects.select_related('client_account', 'cargo_category')
    status_raw = (request.GET.get('status') or '').strip().lower()
    if 'status' not in request.GET:
        qs = qs.filter(status=TenantCargoMaster.Status.ACTIVE)
    elif not status_raw or status_raw == 'active':
        qs = qs.filter(status=TenantCargoMaster.Status.ACTIVE)
    elif status_raw == 'inactive':
        qs = qs.filter(status=TenantCargoMaster.Status.INACTIVE)

    cid = (request.GET.get('client') or '').strip()
    if cid:
        try:
            qs = qs.filter(client_account_id=uuid.UUID(cid))
        except ValueError:
            qs = qs.filter(client_account__account_no__iexact=cid)

    column_field_map = {
        0: 'cargo_code',
        1: 'client_account__display_name',
        2: 'cargo_category__name_english',
        3: 'display_name',
        4: 'english_label',
        5: 'arabic_label',
        6: 'client_sku_external_ref',
        7: 'status',
    }
    search_fields = [
        'display_name',
        'cargo_code',
        'client_sku_external_ref',
        'client_account__display_name',
        'client_account__account_no',
        'cargo_category__name_english',
        'cargo_category__category_code',
        'english_label',
        'arabic_label',
    ]
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=search_fields,
        column_field_map=column_field_map,
        sort_col_field_map=column_field_map,
        default_order=('cargo_code',),
    )


class TenantCargoMasterExportView(TenantWorkspaceExportView):
    filename = 'cargo_master_export.csv'
    headers = [
        'Cargo Code',
        'Client',
        'Category',
        'Display Name',
        'English Label',
        'Arabic Label',
        'Client SKU / Ref',
        'Status',
    ]

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_cargo_master_access_guard

        return _tenant_cargo_master_access_guard(request, context)

    def get_queryset(self, request):
        return _cargo_master_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.cargo_code,
                row.client_account.display_name if row.client_account_id else '',
                row.cargo_category.name_english if row.cargo_category_id else '',
                row.display_name,
                row.english_label or '',
                row.arabic_label or '',
                row.client_sku_external_ref or '',
                row.status,
            ]


class TenantCargoCategoryExportView(TenantWorkspaceExportView):
    filename = 'cargo_categories_export.csv'
    headers = ['Category Code', 'English Name', 'Arabic Name', 'Status']

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_cargo_master_access_guard

        return _tenant_cargo_master_access_guard(request, context)

    def get_queryset(self, request):
        scope = (request.GET.get('scope') or 'all').strip().lower()
        qs = TenantCargoCategory.objects.all()
        if scope == 'active':
            qs = qs.filter(status=TenantCargoCategory.Status.ACTIVE)
        elif scope == 'inactive':
            qs = qs.filter(status=TenantCargoCategory.Status.INACTIVE)
        return build_eal_list_queryset(
            request,
            qs,
            search_fields=['name_english', 'name_arabic', 'category_code'],
            default_order=('-created_at',),
        )

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.category_code,
                row.name_english,
                row.name_arabic,
                row.status,
            ]


def _location_master_base_qs(request):
    qs = TenantLocationMaster.objects.select_related('country')
    status_filter = (request.GET.get('status') or 'all').strip().lower()
    if status_filter == 'active':
        qs = qs.filter(status=TenantLocationMaster.Status.ACTIVE)
    elif status_filter == 'inactive':
        qs = qs.filter(status=TenantLocationMaster.Status.INACTIVE)

    serviceable_filter = (request.GET.get('serviceable') or 'all').strip().lower()
    if serviceable_filter == 'yes':
        qs = qs.filter(is_serviceable=True)
    elif serviceable_filter == 'no':
        qs = qs.filter(is_serviceable=False)

    column_field_map = {
        1: 'location_code',
        2: 'country__name_en',
        3: 'province',
        4: 'location_name_english',
        5: 'location_name_arabic',
        6: 'display_label',
        7: 'location_type',
        8: 'status',
        9: 'is_serviceable',
    }
    search_fields = [
        'location_code',
        'display_label',
        'location_name_english',
        'location_name_arabic',
        'province',
        'country__name_en',
    ]
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=search_fields,
        column_field_map=column_field_map,
        sort_col_field_map=column_field_map,
        default_order=('-created_at',),
        column_filter_types={9: 'boolean'},
    )


class TenantLocationMasterExportView(TenantWorkspaceExportView):
    filename = 'location_master_export.csv'
    headers = [
        'Location Code',
        'Country',
        'Province',
        'English Name',
        'Arabic Name',
        'Display Label',
        'Type',
        'Status',
        'Serviceable',
    ]

    def get_queryset(self, request):
        return _location_master_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.location_code,
                row.country.name_en if row.country_id else '',
                row.province or '',
                row.location_name_english,
                row.location_name_arabic,
                row.display_label,
                row.location_type,
                row.status,
                _yes_no(row.is_serviceable),
            ]


def _route_master_base_qs(request):
    qs = TenantRouteMaster.objects.select_related('origin_point', 'destination_point')
    route_scope = (request.GET.get('scope') or 'all').strip().lower()
    if route_scope == 'domestic':
        qs = qs.filter(route_type=TenantRouteMaster.RouteType.DOMESTIC)
    elif route_scope == 'international':
        qs = qs.filter(route_type=TenantRouteMaster.RouteType.INTERNATIONAL)

    column_field_map = {
        1: 'route_code',
        2: 'route_label',
        3: 'route_type',
        4: 'origin_point__display_label',
        5: 'destination_point__display_label',
        6: 'status',
        7: 'distance_km',
        8: 'estimated_duration_h',
    }
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=[
            'route_code',
            'route_label',
            'origin_point__display_label',
            'destination_point__display_label',
        ],
        column_field_map=column_field_map,
        sort_col_field_map=column_field_map,
        default_order=('-created_at',),
        column_filter_types={7: 'number', 8: 'number'},
    )


class TenantRouteMasterExportView(TenantWorkspaceExportView):
    filename = 'route_master_export.csv'
    headers = [
        'Route Code',
        'Route Label',
        'Route Type',
        'Origin',
        'Destination',
        'Status',
        'Distance (km)',
        'Est. Duration (h)',
    ]

    def check_access(self, request, context):
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to export routes.', extra_tags='tenant')
            from iroad_tenants.views import _tenant_redirect

            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        return None

    def get_queryset(self, request):
        return _route_master_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.route_code,
                row.route_label,
                row.route_type,
                row.origin_point.display_label if row.origin_point_id else '',
                row.destination_point.display_label if row.destination_point_id else '',
                row.status,
                row.distance_km,
                row.estimated_duration_h,
            ]


class TenantServiceItemMasterExportView(TenantWorkspaceExportView):
    filename = 'service_items_export.csv'
    headers = [
        'Service Item Code',
        'English Label',
        'Arabic Label',
        'Service Type',
        'Status',
    ]

    def get_queryset(self, request):
        column_field_map = {
            1: 'service_code',
            2: 'english_name',
            3: 'arabic_name',
            4: 'service_type',
            5: 'status',
        }
        return build_eal_list_queryset(
            request,
            TenantServiceItemMaster.objects.all(),
            search_fields=[
                'service_code',
                'english_name',
                'arabic_name',
                'service_type',
                'category_name',
            ],
            column_field_map=column_field_map,
            sort_col_field_map=column_field_map,
            default_order=('-created_at',),
        )

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.service_code,
                row.english_name,
                row.arabic_name,
                row.service_type,
                row.status,
            ]


def _price_list_base_qs(request):
    qs = (
        TenantPriceList.objects.select_related('client_account')
        .annotate(
            _trip_line_count=Count('trip_lines', distinct=True),
            _service_line_count=Count('service_lines', distinct=True),
        )
        .annotate(_line_count=F('_trip_line_count') + F('_service_line_count'))
    )
    status_raw = (request.GET.get('status') or 'all').strip().lower()
    if status_raw == 'draft':
        qs = qs.filter(status=TenantPriceList.Status.DRAFT)
    elif status_raw == 'active':
        qs = qs.filter(status=TenantPriceList.Status.ACTIVE)
    elif status_raw == 'inactive':
        qs = qs.filter(status=TenantPriceList.Status.INACTIVE)

    client_param = (request.GET.get('client') or '').strip()
    if client_param:
        try:
            qs = qs.filter(client_account_id=uuid.UUID(client_param))
        except (ValueError, TypeError):
            pass

    def _price_list_client_column_filter(queryset, val):
        return queryset.filter(
            Q(client_account__account_no__icontains=val)
            | Q(client_account__display_name__icontains=val)
        )

    column_field_map = {
        1: 'price_list_code',
        2: 'price_list_name',
        3: 'client_account__account_no',
        4: '_line_count',
        5: 'effective_from',
        6: 'effective_to',
        7: 'status',
    }
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=[
            'price_list_code',
            'price_list_name',
            'client_account__account_no',
            'client_account__display_name',
            'base_currency',
        ],
        column_field_map=column_field_map,
        sort_col_field_map={
            1: 'price_list_code',
            2: 'price_list_name',
            3: 'client_account__account_no',
            4: '_line_count',
            5: 'effective_from',
            6: 'effective_to',
            7: 'status',
        },
        default_order=('-created_at',),
        column_filter_types={4: 'number', 5: 'date', 6: 'date'},
        column_filter_hooks={3: _price_list_client_column_filter},
    )


class TenantPriceListMasterExportView(TenantWorkspaceExportView):
    filename = 'price_lists_export.csv'
    headers = [
        'Price List Code',
        'Price List Name',
        'Client Account',
        'Line Count',
        'Effective From',
        'Effective To',
        'Status',
    ]

    def get_queryset(self, request):
        return _price_list_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.price_list_code,
                row.price_list_name,
                row.client_account.account_no if row.client_account_id else '',
                getattr(row, '_line_count', 0),
                _fmt_date(row.effective_from),
                _fmt_date(row.effective_to),
                row.status,
            ]


def _truck_master_base_qs(request):
    tm = TruckMaster
    qs = tm.objects.select_related('truck_type', 'default_driver_id')
    status_raw = (request.GET.get('status') or '').strip().lower()
    if 'status' in request.GET and status_raw and status_raw != 'all':
        if status_raw == 'inactive':
            qs = qs.filter(status=tm.Status.INACTIVE)
        elif status_raw == 'active':
            qs = qs.filter(status=tm.Status.ACTIVE)

    sourcing_raw = (request.GET.get('sourcing_mode') or 'all').strip().lower()
    if sourcing_raw == 'in_source':
        qs = qs.filter(sourcing_mode=tm.SourcingMode.IN_SOURCE)
    elif sourcing_raw == 'out_source':
        qs = qs.filter(sourcing_mode=tm.SourcingMode.OUT_SOURCE)

    tt_param = (request.GET.get('truck_type') or '').strip()
    if tt_param:
        try:
            qs = qs.filter(truck_type_id=uuid.UUID(tt_param))
        except ValueError:
            pass

    column_field_map = {
        1: 'truck_code',
        2: 'owner_name',
        3: 'default_driver_id',
        4: 'sourcing_mode',
        5: 'truck_type__english_label',
        6: 'plate_number',
        7: 'status',
    }
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=[
            'truck_code',
            'plate_number',
            'owner_name',
            'truck_type__english_label',
            'default_driver_id',
        ],
        column_field_map=column_field_map,
        sort_col_field_map=column_field_map,
        default_order=('truck_code',),
    )


class TruckMasterExportView(TenantWorkspaceExportView):
    filename = 'truck_master_export.csv'
    headers = [
        'Truck Code',
        'Owner',
        'Default Driver',
        'Sourcing Mode',
        'Truck Type',
        'Plate Number',
        'Status',
    ]

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_truck_master_access

        return _tenant_truck_master_access(request, context)

    def get_queryset(self, request):
        return _truck_master_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.truck_code,
                row.owner_name or '',
                (
                    row.default_driver_id.driver_code
                    if row.default_driver_id_id
                    else ''
                ),
                row.sourcing_mode,
                row.truck_type.english_label if row.truck_type_id else '',
                row.plate_number,
                row.status,
            ]


def _truck_type_base_qs(request):
    tt = TruckTypeMaster
    qs = tt.objects.all()
    status_raw = (request.GET.get('status') or '').strip().lower()
    if 'status' in request.GET and status_raw and status_raw != 'all':
        if status_raw == 'inactive':
            qs = qs.filter(status=tt.Status.INACTIVE)
        elif status_raw in ('', 'active'):
            qs = qs.filter(status=tt.Status.ACTIVE)

    sort_key_raw = (request.GET.get('sort') or 'truck_type_code').strip().lower()
    sort_dir_raw = (request.GET.get('dir') or 'asc').strip().lower()
    sort_map = {
        'truck_type_code': 'truck_type_code',
        'english_label': 'english_label',
        'arabic_label': 'arabic_label',
        'status': 'status',
    }
    sort_key = sort_map.get(sort_key_raw, 'truck_type_code')
    sort_dir = 'desc' if sort_dir_raw == 'desc' else 'asc'
    order_expr = f'-{sort_key}' if sort_dir == 'desc' else sort_key
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=['truck_type_code', 'english_label', 'arabic_label'],
    ).order_by(order_expr)


class TruckTypeMasterExportView(TenantWorkspaceExportView):
    filename = 'truck_types_export.csv'
    headers = ['Truck Type Code', 'English Label', 'Arabic Label', 'Status']

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_truck_master_access

        return _tenant_truck_master_access(request, context)

    def get_queryset(self, request):
        return _truck_type_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.truck_type_code,
                row.english_label,
                row.arabic_label,
                row.status,
            ]


def _driver_master_base_qs(request):
    dm = DriverMaster
    qs = dm.objects.select_related('nationality_country')
    status_raw = (request.GET.get('status') or '').strip().lower()
    if 'status' in request.GET and status_raw and status_raw != 'all':
        if status_raw == 'inactive':
            qs = qs.filter(driver_status=dm.Status.INACTIVE)
        elif status_raw in ('', 'active'):
            qs = qs.filter(driver_status=dm.Status.ACTIVE)

    source_raw = (request.GET.get('driver_source') or 'all').strip().lower()
    if source_raw == 'in_source':
        qs = qs.filter(driver_source=dm.DriverSource.IN_SOURCE)
    elif source_raw == 'out_source':
        qs = qs.filter(driver_source=dm.DriverSource.OUT_SOURCE)

    sort_key_raw = (request.GET.get('sort') or 'driver_code').strip().lower()
    sort_dir_raw = (request.GET.get('dir') or 'asc').strip().lower()
    sort_map = {
        'driver_code': 'driver_code',
        'driver_name': 'english_name',
        'english_name': 'english_name',
        'arabic_name': 'arabic_name',
        'mobile_number': 'mobile_number',
        'driver_status': 'driver_status',
        'nationality': 'nationality_country__name_en',
        'dl_number': 'dl_number',
        'dl_expiry_date': 'dl_expiry_date',
    }
    sort_key = sort_map.get(sort_key_raw, 'driver_code')
    sort_dir = 'desc' if sort_dir_raw == 'desc' else 'asc'
    order_expr = f'-{sort_key}' if sort_dir == 'desc' else sort_key
    return build_eal_list_queryset(
        request,
        qs,
        search_fields=[
            'driver_code',
            'arabic_name',
            'english_name',
            'mobile_number',
            'dl_number',
            'nationality_country__name_en',
        ],
    ).order_by(order_expr, '-created_at')


class DriverMasterExportView(TenantWorkspaceExportView):
    filename = 'drivers_export.csv'
    headers = [
        'Driver Code',
        'English Name',
        'Arabic Name',
        'Mobile',
        'Nationality',
        'DL Number',
        'DL Expiry',
        'Driver Source',
        'Status',
    ]

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_driver_master_access

        return _tenant_driver_master_access(request, context)

    def get_queryset(self, request):
        return _driver_master_base_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.driver_code,
                row.english_name or '',
                row.arabic_name or '',
                row.mobile_number or '',
                row.nationality_country.name_en if row.nationality_country_id else '',
                row.dl_number or '',
                _fmt_date(row.dl_expiry_date),
                row.driver_source,
                row.driver_status,
            ]


def _truck_attachments_filtered(request):
    sq = get_list_search_q(request)
    qs = TruckAttachment.objects.filter(is_deleted=False).select_related(
        'truck',
        'truck__truck_type',
    )
    if sq:
        qs = qs.filter(
            Q(attachment_no__icontains=sq)
            | Q(doc_ref_number__icontains=sq)
            | Q(arabic_label__icontains=sq)
            | Q(english_label__icontains=sq)
            | Q(file_notes__icontains=sq)
            | Q(truck__truck_code__icontains=sq)
            | Q(truck__plate_number__icontains=sq)
            | Q(truck__truck_type__english_label__icontains=sq)
            | Q(attachment_file__icontains=sq),
        )
    sort_field = (request.GET.get('sort') or 'attachment_no').strip()
    sort_dir = (request.GET.get('dir') or 'desc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'
    prefix = '-' if sort_dir == 'desc' else ''
    allowed = {
        'attachment_no',
        'attachment_date',
        'ref_number',
        'arabic_label',
        'english_label',
        'status',
    }
    if sort_field not in allowed:
        sort_field = 'attachment_no'
    if sort_field == 'ref_number':
        sort_field = 'doc_ref_number'
    return qs.order_by(f'{prefix}{sort_field}')


class TruckAttachmentAllExportView(TenantWorkspaceExportView):
    filename = 'truck_attachments_export.csv'
    headers = [
        'Attachment No',
        'Date',
        'Truck Code',
        'Ref Number',
        'Arabic Label',
        'English Label',
        'Status',
    ]

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_truck_master_access

        return _tenant_truck_master_access(request, context)

    def get_queryset(self, request):
        return _truck_attachments_filtered(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.attachment_no,
                _fmt_date(row.attachment_date),
                row.truck.truck_code if row.truck_id else '',
                row.doc_ref_number or '',
                row.arabic_label or '',
                row.english_label or '',
                row.status,
            ]


def _driver_attachments_filtered(request):
    sq = get_list_search_q(request)
    qs = DriverAttachment.objects.select_related('driver')
    if sq:
        qs = qs.filter(
            Q(attachment_no__icontains=sq)
            | Q(doc_ref_number__icontains=sq)
            | Q(arabic_label__icontains=sq)
            | Q(english_label__icontains=sq)
            | Q(file_notes__icontains=sq)
            | Q(driver__driver_code__icontains=sq)
            | Q(driver__english_name__icontains=sq)
            | Q(driver__arabic_name__icontains=sq)
            | Q(attachment_file__icontains=sq),
        )
    sort_field = (request.GET.get('sort') or 'attachment_no').strip()
    sort_dir = (request.GET.get('dir') or 'desc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'
    prefix = '-' if sort_dir == 'desc' else ''
    if sort_field == 'ref_number':
        sort_field = 'doc_ref_number'
    elif sort_field == 'driver':
        sort_field = 'driver__driver_code'
    return qs.order_by(f'{prefix}{sort_field or "attachment_no"}')


class DriverAttachmentAllExportView(TenantWorkspaceExportView):
    filename = 'driver_attachments_export.csv'
    headers = [
        'Attachment No',
        'Date',
        'Driver Code',
        'Ref Number',
        'Arabic Label',
        'English Label',
        'Status',
    ]

    def check_access(self, request, context):
        from iroad_tenants.views import _tenant_driver_master_access

        return _tenant_driver_master_access(request, context)

    def get_queryset(self, request):
        return _driver_attachments_filtered(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.attachment_no,
                _fmt_date(row.attachment_date),
                row.driver.driver_code if row.driver_id else '',
                row.doc_ref_number or '',
                row.arabic_label or '',
                row.english_label or '',
                row.status,
            ]


def _booking_filtered_qs(request):
    search_q = get_list_search_q(request, 'search')
    qs = TenantBooking.objects.select_related(
        'client_account',
        'route',
        'assigned_truck',
        'assigned_driver',
    ).order_by('-created_at')
    if search_q:
        qs = qs.filter(
            Q(booking_no__icontains=search_q)
            | Q(client_account__display_name__icontains=search_q)
            | Q(route_display__icontains=search_q)
            | Q(trip_type__icontains=search_q)
            | Q(assigned_truck__truck_code__icontains=search_q)
            | Q(route__route_label__icontains=search_q)
            | Q(route__origin_point__display_label__icontains=search_q)
            | Q(route__destination_point__display_label__icontains=search_q)
        )
    return qs


class TenantOperationBookingExportView(TenantWorkspaceExportView):
    filename = 'bookings_export.csv'
    headers = [
        'Booking No',
        'Booking Date',
        'Client',
        'Route',
        'Trip Type',
        'Truck',
        'Status',
    ]

    def check_access(self, request, context):
        if not context.get('is_tenant_admin') and not context.get('can_view_booking'):
            messages.error(request, 'You do not have permission to export bookings.', extra_tags='tenant')
            from iroad_tenants.views import _tenant_redirect

            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        return None

    def get_queryset(self, request):
        return _booking_filtered_qs(request)

    def iter_rows(self, request, records):
        from iroad_tenants.views import _tenant_booking_derived_header_status

        for row in records:
            yield [
                row.booking_no,
                _fmt_date(row.booking_date),
                row.client_account.display_name if row.client_account_id else '',
                row.route_display or '',
                row.trip_type or '',
                row.assigned_truck.truck_code if row.assigned_truck_id else '',
                _tenant_booking_derived_header_status(row),
            ]


def _shipment_filtered_qs(request):
    search_q = get_list_search_q(request, 'search')
    qs = TenantShipment.objects.select_related(
        'truck',
        'driver',
        'booking',
        'client_account',
    ).order_by('-created_at')
    if search_q:
        qs = qs.filter(
            Q(shipment_no__icontains=search_q)
            | Q(booking__booking_no__icontains=search_q)
            | Q(client_account__display_name__icontains=search_q)
            | Q(truck__truck_code__icontains=search_q)
            | Q(driver__driver_code__icontains=search_q)
            | Q(shipment_status__icontains=search_q)
        )
    return qs


class TenantOperationShipmentExportView(TenantWorkspaceExportView):
    filename = 'shipments_export.csv'
    headers = [
        'Shipment No',
        'Date',
        'Status',
        'Client',
        'Booking No',
        'Truck',
        'Driver',
    ]

    def get_queryset(self, request):
        return _shipment_filtered_qs(request)

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.shipment_no,
                _fmt_date(row.shipment_date),
                row.shipment_status,
                row.client_account.display_name if row.client_account_id else '',
                row.booking.booking_no if row.booking_id else '',
                row.truck.truck_code if row.truck_id else '',
                row.driver.driver_code if row.driver_id else '',
            ]


class TenantOperationTruckMovementLogExportView(TenantWorkspaceExportView):
    filename = 'truck_movement_logs_export.csv'
    headers = [
        'Movement No',
        'Truck',
        'Driver',
        'Booking No',
        'Shipment No',
        'From',
        'To',
        'Status',
    ]

    def get_queryset(self, request):
        search_q = get_list_search_q(request)
        qs = TenantTruckMovementLog.objects.select_related(
            'booking',
            'shipment',
            'truck',
            'driver',
            'from_location_point',
            'to_location_point',
        ).order_by('-created_at')
        if search_q:
            qs = qs.filter(
                Q(movement_no__icontains=search_q)
                | Q(truck__truck_code__icontains=search_q)
                | Q(driver__driver_code__icontains=search_q)
                | Q(booking__booking_no__icontains=search_q)
                | Q(shipment__shipment_no__icontains=search_q)
                | Q(from_location_point__display_label__icontains=search_q)
                | Q(to_location_point__display_label__icontains=search_q)
                | Q(status__icontains=search_q)
            )
        return qs

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.movement_no,
                row.truck.truck_code if row.truck_id else '',
                row.driver.driver_code if row.driver_id else '',
                row.booking.booking_no if row.booking_id else '',
                row.shipment.shipment_no if row.shipment_id else '',
                row.from_location_point.display_label if row.from_location_point_id else '',
                row.to_location_point.display_label if row.to_location_point_id else '',
                row.status,
            ]


class TenantOperationDocumentHandoverExportView(TenantWorkspaceExportView):
    filename = 'document_handovers_export.csv'
    headers = [
        'Handover No',
        'Booking No',
        'Shipment No',
        'Received User',
        'Status',
        'Created At',
    ]

    def get_queryset(self, request):
        search_q = get_list_search_q(request)
        qs = TenantDocumentHandover.objects.select_related(
            'booking',
            'shipment',
        ).order_by('-created_at')
        if search_q:
            qs = qs.filter(
                Q(handover_no__icontains=search_q)
                | Q(booking__booking_no__icontains=search_q)
                | Q(shipment__shipment_no__icontains=search_q)
                | Q(received_user__icontains=search_q)
                | Q(status__icontains=search_q)
            )
        return qs

    def iter_rows(self, request, records):
        for row in records:
            yield [
                row.handover_no,
                row.booking.booking_no if row.booking_id else '',
                row.shipment.shipment_no if row.shipment_id else '',
                row.received_user or '',
                row.status,
                _fmt_datetime(row.created_at),
            ]


class TenantOperationSurchargeSalesExportView(TenantWorkspaceExportView):
    filename = 'surcharge_transactions_export.csv'
    headers = [
        'Transaction No',
        'Shipment No',
        'Booking No',
        'Client',
        'Item',
        'Amount',
        'Status',
    ]

    def get_queryset(self, request):
        search_q = get_list_search_q(request)
        qs = TenantShipmentSurcharge.objects.select_related(
            'shipment',
            'booking',
            'client_account',
            'service_item',
        ).order_by('-created_at')
        if search_q:
            qs = qs.filter(
                Q(transaction_no__icontains=search_q)
                | Q(item_label__icontains=search_q)
                | Q(shipment__shipment_no__icontains=search_q)
                | Q(shipment__booking__booking_no__icontains=search_q)
                | Q(client_account__account_no__icontains=search_q)
                | Q(client_account__display_name__icontains=search_q)
            )
        return qs

    def iter_rows(self, request, records):
        for row in records:
            service_label = row.item_label or ''
            if row.service_item_id:
                service_label = (
                    f'{row.service_item.service_code} - {row.service_item.english_name}'
                )
            yield [
                row.transaction_no,
                row.shipment.shipment_no if row.shipment_id else '',
                row.booking.booking_no if row.booking_id else '',
                row.client_account.display_name if row.client_account_id else '',
                service_label,
                _csv_cell(row.subtotal),
                row.status,
            ]


class TenantOperationShipmentPodExportView(TenantWorkspaceExportView):
    filename = 'shipment_pod_export.csv'
    headers = [
        'Record No',
        'Record Date',
        'Booking No',
        'Booking Item',
        'Shipment No',
        'Doc Ref',
        'Doc Date',
        'Pages',
        'POD Type',
        'POD Status',
    ]

    def get_queryset(self, request):
        from iroad_tenants.views import SHIPMENT_POD_REF_PREFIX

        search_q = get_list_search_q(request)
        pod_prefix = f'{SHIPMENT_POD_REF_PREFIX}-'
        qs = TenantShipmentDocument.objects.select_related(
            'shipment',
            'booking',
            'shipment__booking',
        ).filter(record_no__startswith=pod_prefix).order_by('-created_at')
        if search_q:
            qs = qs.filter(
                Q(record_no__icontains=search_q)
                | Q(booking__booking_no__icontains=search_q)
                | Q(shipment__booking_item_ref__icontains=search_q)
                | Q(shipment__shipment_no__icontains=search_q)
                | Q(document_ref_no__icontains=search_q)
            )
        return qs

    def iter_rows(self, request, records):
        for doc in records:
            shipment = doc.shipment
            yield [
                doc.record_no,
                _fmt_date(doc.record_date),
                doc.booking.booking_no if doc.booking_id else '',
                shipment.booking_item_ref if shipment else '',
                shipment.shipment_no if shipment else '',
                doc.document_ref_no or '',
                _fmt_date(doc.document_date),
                doc.page_count or 0,
                shipment.pod_type if shipment else '',
                shipment.pod_status if shipment else '',
            ]


class TenantOperationShipmentDocumentsExportView(TenantWorkspaceExportView):
    filename = 'shipment_documents_export.csv'
    headers = [
        'Record No',
        'Record Date',
        'Booking No',
        'Shipment No',
        'Document Type',
        'Doc Ref',
        'Doc Date',
        'Pages',
        'Status',
        'Physical Location',
    ]

    def get_queryset(self, request):
        search_q = get_list_search_q(request)
        qs = TenantShipmentDocument.objects.select_related(
            'booking',
            'shipment',
        ).order_by('-created_at')
        if search_q:
            qs = qs.filter(
                Q(record_no__icontains=search_q)
                | Q(booking__booking_no__icontains=search_q)
                | Q(shipment__shipment_no__icontains=search_q)
                | Q(document_ref_no__icontains=search_q)
                | Q(document_type__icontains=search_q)
                | Q(status__icontains=search_q)
            )
        return qs

    def iter_rows(self, request, records):
        for doc in records:
            yield [
                doc.record_no,
                _fmt_date(doc.record_date),
                doc.booking.booking_no if doc.booking_id else '',
                doc.shipment.shipment_no if doc.shipment_id else '',
                doc.document_type,
                doc.document_ref_no or '',
                _fmt_date(doc.document_date),
                doc.page_count or 0,
                doc.status,
                doc.physical_location or '',
            ]
