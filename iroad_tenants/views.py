import csv
from decimal import Decimal
from urllib.parse import urlencode

import logging
import io
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, resolve, reverse
from django.views import View
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.db import IntegrityError, ProgrammingError, connection
from django.db.models.deletion import ProtectedError
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django_tenants.utils import schema_context
import os
import uuid
from superadmin.billing_helpers import (
    generate_invoice_pdf_bytes,
    calculate_pro_rata_credit,
    complete_order_payment_as_system,
    get_fx_snapshot,
    get_tax_code_for_tenant,
    refresh_order_projected_fields,
    resolve_upgrade_credit_basis_price,
    sync_or_create_order_payment_transaction,
    validate_downgrade_order,
)
from superadmin.models import TenantProfile, TenantSecuritySettings
from superadmin.models import (
    AccessLog,
    AdminUser,
    AuditLog,
    Country,
    Currency,
    OrderPlanLine,
    PaymentMethod,
    PlanPricingCycle,
    StandardInvoice,
    SubscriptionOrder,
    SubscriptionFAQ,
    SubscriptionPlan,
)
from superadmin.redis_helpers import (
    get_all_active_tenant_sessions,
    get_tenant_session,
    refresh_tenant_session,
    revoke_tenant_session_key,
)
from superadmin.tenant_portal_auth import (
    clear_tenant_portal_cookie,
    get_tenant_portal_cookie_payload,
)
from superadmin.communication_helpers import send_named_notification_email
from tenant_workspace.models import (
    AutoNumberConfiguration,
    AutoNumberSequence,
    OrganizationProfile,
    TenantAddressMaster,
    TenantCargoCategory,
    TenantCargoMaster,
    TenantCargoMasterAttachment,
    TenantLocationMaster,
    TenantRouteMaster,
    TenantClientAccount,
    TenantClientAccountSetting,
    TenantClientAttachment,
    TenantClientContact,
    TenantClientContract,
    TenantClientContractSetting,
    TenantRole,
    TenantRolePermission,
    TenantUser,
)
from iroad_tenants.models import TenantPaymentCard, TenantRegistry
from iroad_tenants.forms_tenant_address import TenantAddressMasterForm
from iroad_tenants.forms_tenant_cargo import TenantCargoCategoryForm, TenantCargoMasterForm
from iroad_tenants.forms_tenant_location import TenantLocationMasterForm
from iroad_tenants.forms_tenant_route import TenantRouteMasterForm

logger = logging.getLogger(__name__)

ADDRESS_MASTER_AUTO_FORM_CODE = 'address-master'
ADDRESS_MASTER_AUTO_FORM_LABEL = 'Address Code'
ADDRESS_MASTER_REF_PREFIX = 'AD'

CARGO_MASTER_AUTO_FORM_CODE = 'cargo-master'
CARGO_MASTER_AUTO_FORM_LABEL = 'Cargo code'
CARGO_MASTER_REF_PREFIX = 'CG'

CARGO_CATEGORY_AUTO_FORM_CODE = 'cargo-category'
CARGO_CATEGORY_AUTO_FORM_LABEL = 'Category code'
CARGO_CATEGORY_REF_PREFIX = 'CAT'

LOCATION_MASTER_AUTO_FORM_CODE = 'location-master'
LOCATION_MASTER_AUTO_FORM_LABEL = 'Location Master'
LOCATION_MASTER_REF_PREFIX = 'LC'

ROUTE_MASTER_AUTO_FORM_CODE = 'route-master'
ROUTE_MASTER_AUTO_FORM_LABEL = 'Route Master'
ROUTE_MASTER_REF_PREFIX = 'RT'

MAX_CARGO_ATTACHMENT_BYTES = 10 * 1024 * 1024

CLIENT_ATTACHMENT_AUTO_FORM_CODE = 'client-attachment'
CLIENT_ATTACHMENT_AUTO_FORM_LABEL = 'Client Attachment'
CLIENT_ATTACHMENT_REF_PREFIX = 'ATT'
MAX_CLIENT_ATTACHMENT_BYTES = 10 * 1024 * 1024
CLIENT_ATTACHMENT_ALLOWED_EXT = frozenset({
    '.pdf',
    '.doc',
    '.docx',
    '.xls',
    '.xlsx',
    '.jpg',
    '.jpeg',
    '.png',
    '.gif',
})

CLIENT_CONTRACT_AUTO_FORM_CODE = 'client-contract'
CLIENT_CONTRACT_AUTO_FORM_LABEL = 'Client Contract'
CLIENT_CONTRACT_REF_PREFIX = 'CNT'
MAX_CLIENT_CONTRACT_BYTES = 10 * 1024 * 1024
CLIENT_CONTRACT_ALLOWED_EXT = frozenset({
    '.pdf',
    '.doc',
    '.docx',
    '.jpg',
    '.jpeg',
    '.png',
    '.gif',
    '.webp',
})


def _validate_client_attachment_upload(upload):
    if not upload:
        return 'Attachment file is required.'
    try:
        size = int(upload.size)
    except (TypeError, ValueError):
        size = 0
    if size > MAX_CLIENT_ATTACHMENT_BYTES:
        return 'File must be 10MB or smaller.'
    name = (getattr(upload, 'name', None) or '').lower()
    ext = os.path.splitext(name)[1]
    if ext not in CLIENT_ATTACHMENT_ALLOWED_EXT:
        return 'Unsupported file type. Use PDF, Office, or image formats.'
    return ''


def _validate_client_contract_upload(upload, *, allow_empty=False):
    if not upload:
        return '' if allow_empty else 'Contract attachment is required.'
    try:
        size = int(upload.size)
    except (TypeError, ValueError):
        size = 0
    if size > MAX_CLIENT_CONTRACT_BYTES:
        return 'File must be 10MB or smaller.'
    name = (getattr(upload, 'name', None) or '').lower()
    ext = os.path.splitext(name)[1]
    if ext not in CLIENT_CONTRACT_ALLOWED_EXT:
        return 'Unsupported file type. Use PDF, DOC, or image formats.'
    return ''


def _contract_status_for_dates(start_date, end_date):
    today = timezone.localdate()
    if end_date and end_date < today:
        return TenantClientContract.Status.EXPIRED
    if start_date and start_date > today:
        return TenantClientContract.Status.UPCOMING
    return TenantClientContract.Status.ACTIVE


def _redirect_client_contract_list(request):
    url = reverse('iroad_tenants:tenant_client_contract_list')
    tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
    if tid:
        url = f'{url}?{urlencode({"tid": tid})}'
    return redirect(url)


def _get_singleton_client_contract_settings():
    """Single settings row for the active tenant schema (per-tenant DB)."""
    row = TenantClientContractSetting.objects.order_by('-updated_at').first()
    if row is None:
        row = TenantClientContractSetting.objects.create()
    return row


def _client_contract_settings_template_dict(settings_obj):
    return {
        'expired_contract_handling_mode': settings_obj.expired_contract_handling_mode,
        'grace_period_days': settings_obj.grace_period_days,
        'pre_expiry_notification_days': settings_obj.pre_expiry_notification_days,
        'post_expiry_notification_days': settings_obj.post_expiry_notification_days,
        'notification_frequency': settings_obj.notification_frequency,
        'notification_audience': settings_obj.notification_audience,
    }


def _validate_client_contract_period_against_settings(start_date, end_date, settings_obj):
    """Return field errors for contract period vs tenant Client Contract Settings."""
    errors = {}
    if not start_date or not end_date or end_date < start_date:
        return errors
    span_days = (end_date - start_date).days
    pre = int(settings_obj.pre_expiry_notification_days or 0)
    if pre > 0 and span_days < pre:
        errors['end_date'] = (
            f'Contract period must be at least {pre} day(s) so pre-expiry notifications '
            f'can apply (see Client Contract Settings).'
        )
    return errors


def _tenant_client_contracts_base_path():
    p = reverse('iroad_tenants:tenant_client_contract')
    return p if p.endswith('/') else f'{p}/'


def _tenant_client_contract_detail_path(contract_id):
    return f'{_tenant_client_contracts_base_path()}{contract_id}/detail/'


def _tenant_client_contract_edit_path(contract_id):
    return f'{_tenant_client_contracts_base_path()}{contract_id}/edit/'


def _tenant_client_contract_delete_path(contract_id):
    return f'{_tenant_client_contracts_base_path()}{contract_id}/delete/'


def _client_account_bootstrap_dict(account: TenantClientAccount, primary_contact=None):
    """JSON-serializable client header/overview for client-details.js bootstrap."""
    created = getattr(account, 'created_at', None)
    created_label = ''
    if created:
        created_label = timezone.localtime(created).strftime('%b %d, %Y, %I:%M %p')
    header_email = ''
    header_phone = ''
    if primary_contact is not None:
        header_email = (getattr(primary_contact, 'email', None) or '').strip()
        mob = (getattr(primary_contact, 'mobile_number', None) or '').strip()
        tel = (getattr(primary_contact, 'telephone_number', None) or '').strip()
        header_phone = mob or tel
    return {
        'account_no': account.account_no,
        'client_type': account.client_type,
        'status': account.status,
        'created_at': created_label,
        'name_arabic': account.name_arabic or '',
        'name_english': account.name_english or '',
        'display_name': account.display_name or '',
        'preferred_currency': account.preferred_currency or '',
        'billing_street_1': account.billing_street_1 or '',
        'billing_street_2': account.billing_street_2 or '',
        'billing_city': account.billing_city or '',
        'billing_region': account.billing_region or '',
        'postal_code': account.postal_code or '',
        'country': account.country or '',
        'commercial_registration_no': account.commercial_registration_no or '',
        'tax_registration_no': account.tax_registration_no or '',
        'national_id': account.national_id or '',
        'header_email': header_email,
        'header_phone': header_phone,
    }


def _resolve_tenant_favicon_url(request, tenant):
    """Return the default IR favicon for all tenant pages."""
    return (
        "https://ui-avatars.com/api/"
        "?name=IR&background=5051f9&color=fff&size=64&rounded=true&bold=true"
    )


def _tenant_context_from_session(request):
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    tenant_jti = auth_payload.get('jti')
    tenant = None
    if tenant_id:
        tenant = TenantProfile.objects.filter(pk=tenant_id).first()
    if tenant is None:
        _clear_tenant_bootstrap_session(request)
        return None
    if tenant.account_status != 'Active':
        _clear_tenant_bootstrap_session(request)
        return None
    if not tenant_jti:
        _clear_tenant_bootstrap_session(request)
        return None

    # Refresh Redis-backed tenant session on every workspace request so that
    # tenant kill-switch/mass revoke takes effect immediately.
    sec = TenantSecuritySettings.objects.first()
    timeout_minutes = max(60, int(getattr(sec, 'tenant_web_timeout_hours', 12)) * 60)
    if not refresh_tenant_session(str(tenant.tenant_id), str(tenant_jti), timeout_minutes):
        _clear_tenant_bootstrap_session(request)
        return None
    
    # Default to tenant owner profile.
    if tenant.first_name or tenant.last_name:
        display_name = f"{tenant.first_name} {tenant.last_name}".strip()
    else:
        display_name = (tenant.company_name or 'Tenant User').strip()
    display_email = (tenant.primary_email or 'tenant@example.com').strip()
    display_role = 'Tenant Admin'
    permission_forms = set()
    is_tenant_admin = True

    # If this tenant session belongs to a tenant user, override display identity
    # and collect role permissions for menu-level visibility.
    session_data = get_tenant_session(str(tenant.tenant_id), str(tenant_jti)) or {}
    reference_id = str(session_data.get('reference_id') or '').strip()
    if reference_id and reference_id != str(tenant.tenant_id):
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is not None:
            try:
                tenant_user = TenantUser.objects.filter(pk=reference_id).first()
                if tenant_user:
                    display_name = (tenant_user.full_name or tenant_user.username or display_name).strip()
                    display_email = (tenant_user.email or display_email).strip()
                    display_role = (tenant_user.role_name or 'Tenant User').strip()
                    is_tenant_admin = False
                    role = TenantRole.objects.filter(
                        role_name_en__iexact=(tenant_user.role_name or '').strip()
                    ).first()
                    if role:
                        permission_forms = set(
                            TenantRolePermission.objects.filter(
                                role=role,
                                can_view=True,
                            ).values_list('form_name', flat=True)
                        )
            finally:
                connection.set_schema_to_public()

    return {
        'tenant': tenant,
        'display_name': display_name,
        'display_email': display_email,
        'display_role': display_role,
        'tenant_favicon_url': _resolve_tenant_favicon_url(request, tenant),
        'avatar_name': display_name.replace(' ', '+'),
        'is_tenant_admin': is_tenant_admin,
        'perm_forms': permission_forms,
        'can_view_cargo_master': 'Cargo Master' in permission_forms,
        'can_view_booking': 'Booking' in permission_forms,
        'can_view_shipment': 'Shipment' in permission_forms,
        'can_view_sales_invoicing': 'Sales Invoicing' in permission_forms,
    }


def _tenant_redirect(request, route_name):
    tid = str(request.GET.get('tid') or request.POST.get('tid') or '').strip()
    base = reverse(route_name)
    if tid:
        return redirect(f'{base}?tid={tid}')
    return redirect(base)


def _clear_tenant_bootstrap_session(request):
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    jti = auth_payload.get('jti')
    if tenant_id and jti:
        revoke_tenant_session_key(str(tenant_id), str(jti))
    # Backward-compat cleanup for older session-based tenant bootstrap keys.
    for key in ('tenant_bootstrap_token', 'tenant_bootstrap_tenant_id', 'tenant_bootstrap_jti', 'tenant_bootstrap_expires_in'):
        request.session.pop(key, None)


def _activate_tenant_workspace_schema(request):
    """Switch DB connection to current tenant schema for tenant workspace ORM."""
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    if not tenant_id:
        return None

    connection.set_schema_to_public()
    registry = (
        TenantRegistry.objects.select_related('tenant_profile')
        .filter(tenant_profile_id=tenant_id)
        .first()
    )
    if registry is None:
        return None
    connection.set_tenant(registry)
    return registry


class TenantDashboardView(View):
    """Tenant dashboard rendered from app template copy."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(request, 'iroad_tenants/index.html', context)


def _tenant_cargo_master_access_guard(request, context):
    if context is None:
        response = redirect('login')
        clear_tenant_portal_cookie(response, request=request)
        return response
    if not context.get('is_tenant_admin') and not context.get('can_view_cargo_master'):
        messages.error(
            request,
            'You do not have permission to view Cargo Master.',
            extra_tags='tenant',
        )
        return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
    return None


class TenantCargoMasterListView(View):
    """CG-001 cargo list with search, filters, pagination."""

    template_name = 'iroad_tenants/Master_Data/cargo_master/All-cargo-masters.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        qs = TenantCargoMaster.objects.select_related('client_account', 'cargo_category')
        sq = request.GET.get('q', '').strip()
        cid = request.GET.get('client', '').strip()
        filter_client_id = ''

        status_raw = (request.GET.get('status') or '').strip().lower()
        if 'status' not in request.GET:
            qs = qs.filter(status=TenantCargoMaster.Status.ACTIVE)
            filter_status = ''
        elif not status_raw:
            qs = qs.filter(status=TenantCargoMaster.Status.ACTIVE)
            filter_status = 'active'
        elif status_raw == 'all':
            filter_status = 'all'
        elif status_raw == 'inactive':
            qs = qs.filter(status=TenantCargoMaster.Status.INACTIVE)
            filter_status = 'inactive'
        elif status_raw == 'active':
            qs = qs.filter(status=TenantCargoMaster.Status.ACTIVE)
            filter_status = 'active'
        else:
            qs = qs.filter(status=TenantCargoMaster.Status.ACTIVE)
            filter_status = 'active'

        if sq:
            qs = qs.filter(
                Q(display_name__icontains=sq)
                | Q(cargo_code__icontains=sq)
                | Q(client_sku_external_ref__icontains=sq)
                | Q(client_account__display_name__icontains=sq)
                | Q(cargo_category__name_english__icontains=sq)
                | Q(cargo_category__category_code__icontains=sq)
            )
        if cid:
            try:
                cid_uuid = uuid.UUID(cid)
                qs = qs.filter(client_account_id=cid_uuid)
                filter_client_id = str(cid_uuid)
            except ValueError:
                filter_client_id = ''

        qs_ordered = qs.order_by('-created_at')
        stats = _cargo_master_list_stats(qs_ordered)
        paginator = Paginator(qs_ordered, 10)
        try:
            page_no = max(1, int(request.GET.get('page') or 1))
        except ValueError:
            page_no = 1
        page = paginator.get_page(page_no)

        total_count = paginator.count
        if total_count == 0:
            ps, pe = 0, 0
        else:
            ps = (page.number - 1) * paginator.per_page + 1
            pe = ps + len(page.object_list) - 1

        def _page_url(page_num):
            q = request.GET.copy()
            try:
                pn = int(page_num)
            except (TypeError, ValueError):
                pn = 1
            if pn > 1:
                q['page'] = str(pn)
            else:
                q.pop('page', None)
            return '?' + q.urlencode()

        pagination_page_links = [(n, _page_url(n)) for n in page.paginator.page_range]
        prev_url = _page_url(page.previous_page_number()) if page.has_previous() else None
        next_url = _page_url(page.next_page_number()) if page.has_next() else None

        clients = list(
            TenantClientAccount.objects.filter(
                status=TenantClientAccount.Status.ACTIVE,
            ).order_by('display_name')[:500]
        )

        context.update(
            {
                'cargos_page': page,
                'search_q': sq,
                'filter_status': filter_status,
                'filter_client_id': filter_client_id,
                'pagination_page_links': pagination_page_links,
                'pagination_prev_url': prev_url,
                'pagination_next_url': next_url,
                'stats': stats,
                'pagination_start': ps,
                'pagination_end': pe,
                'pagination_total': total_count,
                'client_filter_choices': clients,
                'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
            }
        )
        try:
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantCargoMasterCreateView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-master.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            if not TenantCargoCategory.objects.filter(
                status=TenantCargoCategory.Status.ACTIVE,
            ).exists():
                messages.warning(
                    request,
                    'Create at least one active Cargo Category before adding cargo.',
                    extra_tags='tenant',
                )
            preview = _preview_next_cargo_master_code()
            initial = {}
            cid = (request.GET.get('client') or '').strip()
            if cid:
                try:
                    initial['client_account'] = uuid.UUID(cid)
                except ValueError:
                    pass
            form = TenantCargoMasterForm(initial=initial)
            context.update(
                {
                    'form': form,
                    'preview_cargo_code': preview,
                    'is_edit': False,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_resp = None
        try:
            form = TenantCargoMasterForm(request.POST, request.FILES)
            if not form.is_valid():
                preview = _preview_next_cargo_master_code()
                context.update(
                    {
                        'form': form,
                        'preview_cargo_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    code, seq = _next_auto_number_for_form(
                        CARGO_MASTER_AUTO_FORM_CODE,
                        CARGO_MASTER_AUTO_FORM_LABEL,
                        CARGO_MASTER_REF_PREFIX,
                    )
                    cargo = form.save(commit=False)
                    cargo.cargo_code = code
                    cargo.cargo_sequence = seq
                    cargo.full_clean()
                    cargo.save()
                    _save_cargo_master_attachments_from_request(request, cargo)
            except IntegrityError:
                logger.exception('Cargo Master create integrity violation')
                preview = _preview_next_cargo_master_code()
                form.add_error(
                    None,
                    ValidationError(
                        'Unable to allocate a unique cargo code. Please retry.',
                        code='cargo_integrity',
                    ),
                )
                context.update(
                    {
                        'form': form,
                        'preview_cargo_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the cargo record.', extra_tags='tenant')
                return render(request, self.template_name, context)
            except ValidationError as ve:
                preview = _preview_next_cargo_master_code()
                if getattr(ve, 'error_dict', None):
                    for field_name, errs in ve.error_dict.items():
                        for err in errs:
                            form.add_error(field_name, err)
                else:
                    for msg in getattr(ve, 'messages', []) or [str(ve)]:
                        form.add_error(None, msg)
                context.update(
                    {
                        'form': form,
                        'preview_cargo_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the cargo record.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Cargo {cargo.cargo_code} created successfully.',
                extra_tags='tenant',
            )
            redirect_resp = _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')
        finally:
            connection.set_schema_to_public()

        return redirect_resp


class TenantCargoMasterEditView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-master.html'

    def _load(self, cargo_id):
        return (
            TenantCargoMaster.objects.select_related('client_account', 'cargo_category')
            .filter(pk=cargo_id)
            .first()
        )

    def get(self, request, cargo_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            instance = self._load(cargo_id)
            if not instance:
                messages.error(request, 'Cargo record not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')

            form = TenantCargoMasterForm(instance=instance)
            context.update(
                {
                    'form': form,
                    'is_edit': True,
                    'cargo_instance': instance,
                    'existing_attachments': list(instance.attachments.all()),
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, cargo_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_resp = None
        try:
            instance = self._load(cargo_id)
            if not instance:
                messages.error(request, 'Cargo record not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')

            form = TenantCargoMasterForm(request.POST, request.FILES, instance=instance)
            if not form.is_valid():
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'cargo_instance': instance,
                        'existing_attachments': list(instance.attachments.all()),
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    cargo = form.save(commit=False)
                    cargo.full_clean()
                    cargo.save()
                    if request.FILES.getlist('attachments'):
                        _save_cargo_master_attachments_from_request(request, cargo)
            except ValidationError as ve:
                if getattr(ve, 'error_dict', None):
                    for field_name, errs in ve.error_dict.items():
                        for err in errs:
                            form.add_error(field_name, err)
                else:
                    for msg in getattr(ve, 'messages', []) or [str(ve)]:
                        form.add_error(None, msg)
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'cargo_instance': instance,
                        'existing_attachments': list(instance.attachments.all()),
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the cargo record.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Cargo {cargo.cargo_code} updated successfully.',
                extra_tags='tenant',
            )
            redirect_resp = _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')
        finally:
            connection.set_schema_to_public()

        return redirect_resp


class TenantCargoMasterDetailView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-master.html'

    def get(self, request, cargo_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            cargo = (
                TenantCargoMaster.objects.select_related('client_account', 'cargo_category')
                .filter(pk=cargo_id)
                .first()
            )
            if not cargo:
                messages.error(request, 'Cargo record not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')

            tid = (request.GET.get('tid') or '').strip()
            list_url = reverse('iroad_tenants:tenant_cargo_master_list')
            if tid:
                list_url = f'{list_url}?{urlencode({"tid": tid})}'
            edit_url = reverse(
                'iroad_tenants:tenant_cargo_master_edit',
                kwargs={'cargo_id': cargo.cargo_id},
            )
            if tid:
                edit_url = f'{edit_url}?{urlencode({"tid": tid})}'

            context.update(
                {
                    'form': TenantCargoMasterForm(instance=cargo),
                    'cargo_instance': cargo,
                    'existing_attachments': list(cargo.attachments.all()),
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    'back_to_list_url': list_url,
                    'edit_cargo_url': edit_url,
                    'portal_tid': tid,
                    'is_edit': True,
                    'is_view': True,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantCargoMasterDeleteView(View):
    def post(self, request, cargo_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            cargo = TenantCargoMaster.objects.filter(pk=cargo_id).first()
            if not cargo:
                messages.error(request, 'Cargo record not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')

            label = cargo.cargo_code
            cargo.delete()
            messages.success(request, f'Cargo {label} deleted.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_cargo_master_list')
        finally:
            connection.set_schema_to_public()


class TenantCargoCategoryListView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-category-config-list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            scope = (request.GET.get('scope') or 'all').lower()
            if scope not in ('all', 'active', 'inactive'):
                scope = 'all'

            qs = TenantCargoCategory.objects.all().order_by('-created_at')
            if scope == 'active':
                qs = qs.filter(status=TenantCargoCategory.Status.ACTIVE)
            elif scope == 'inactive':
                qs = qs.filter(status=TenantCargoCategory.Status.INACTIVE)

            sq = request.GET.get('q', '').strip()
            if sq:
                qs = qs.filter(
                    Q(name_english__icontains=sq)
                    | Q(name_arabic__icontains=sq)
                    | Q(category_code__icontains=sq)
                )
            paginator = Paginator(qs, 10)
            try:
                page_no = max(1, int(request.GET.get('page') or 1))
            except ValueError:
                page_no = 1
            page = paginator.get_page(page_no)
            stats = {
                'total': TenantCargoCategory.objects.count(),
                'active': TenantCargoCategory.objects.filter(
                    status=TenantCargoCategory.Status.ACTIVE
                ).count(),
                'inactive': TenantCargoCategory.objects.filter(
                    status=TenantCargoCategory.Status.INACTIVE
                ).count(),
            }
            context.update(
                {
                    'categories_page': page,
                    'search_q': sq,
                    'category_scope': scope,
                    'category_stats': stats,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantCargoCategoryCreateView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-category-config.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            preview = _preview_next_cargo_category_code()
            form = TenantCargoCategoryForm()
            context.update(
                {
                    'form': form,
                    'preview_category_code': preview,
                    'is_edit': False,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_resp = None
        try:
            form = TenantCargoCategoryForm(request.POST)
            if not form.is_valid():
                preview = _preview_next_cargo_category_code()
                context.update(
                    {
                        'form': form,
                        'preview_category_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    code, seq = _next_auto_number_for_form(
                        CARGO_CATEGORY_AUTO_FORM_CODE,
                        CARGO_CATEGORY_AUTO_FORM_LABEL,
                        CARGO_CATEGORY_REF_PREFIX,
                    )
                    cat = form.save(commit=False)
                    cat.category_code = code
                    cat.category_sequence = seq
                    cat.full_clean()
                    cat.save()
            except IntegrityError:
                preview = _preview_next_cargo_category_code()
                form.add_error(
                    None,
                    ValidationError(
                        'Unable to allocate a unique category code. Please retry.',
                        code='category_integrity',
                    ),
                )
                context.update(
                    {
                        'form': form,
                        'preview_category_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the category.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Category {cat.category_code} created successfully.',
                extra_tags='tenant',
            )
            redirect_resp = _tenant_redirect(request, 'iroad_tenants:tenant_cargo_category_list')
        finally:
            connection.set_schema_to_public()

        return redirect_resp


def _redirect_cargo_category_list(request):
    return _tenant_redirect(request, 'iroad_tenants:tenant_cargo_category_list')


class TenantCargoCategoryDetailView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-category-config.html'

    def get(self, request, category_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            category = TenantCargoCategory.objects.filter(pk=category_id).first()
            if not category:
                messages.error(request, 'Category not found.', extra_tags='tenant')
                return _redirect_cargo_category_list(request)

            tid = (request.GET.get('tid') or '').strip()
            list_url = reverse('iroad_tenants:tenant_cargo_category_list')
            if tid:
                list_url = f'{list_url}?{urlencode({"tid": tid})}'
            edit_url = reverse(
                'iroad_tenants:tenant_cargo_category_edit',
                kwargs={'category_id': category.category_id},
            )
            if tid:
                edit_url = f'{edit_url}?{urlencode({"tid": tid})}'

            context.update(
                {
                    'form': TenantCargoCategoryForm(instance=category),
                    'category_instance': category,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    'back_to_list_url': list_url,
                    'edit_category_url': edit_url,
                    'portal_tid': tid,
                    'is_edit': True,
                    'is_view': True,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantCargoCategoryEditView(View):
    template_name = 'iroad_tenants/Master_Data/cargo_master/Cargo-category-config.html'

    def _load(self, category_id):
        return TenantCargoCategory.objects.filter(pk=category_id).first()

    def get(self, request, category_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            instance = self._load(category_id)
            if not instance:
                messages.error(request, 'Category not found.', extra_tags='tenant')
                return _redirect_cargo_category_list(request)

            form = TenantCargoCategoryForm(instance=instance)
            context.update(
                {
                    'form': form,
                    'is_edit': True,
                    'category_instance': instance,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, category_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_resp = None
        try:
            instance = self._load(category_id)
            if not instance:
                messages.error(request, 'Category not found.', extra_tags='tenant')
                return _redirect_cargo_category_list(request)

            form = TenantCargoCategoryForm(request.POST, instance=instance)
            if not form.is_valid():
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'category_instance': instance,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            cat = form.save(commit=False)
            cat.full_clean()
            cat.save()
            messages.success(
                request,
                f'Category {cat.category_code} updated successfully.',
                extra_tags='tenant',
            )
            redirect_resp = _redirect_cargo_category_list(request)
        except ValidationError as ve:
            if getattr(ve, 'error_dict', None):
                for field_name, errs in ve.error_dict.items():
                    for err in errs:
                        form.add_error(field_name, err)
            else:
                for msg in getattr(ve, 'messages', []) or [str(ve)]:
                    form.add_error(None, msg)
            context.update(
                {
                    'form': form,
                    'is_edit': True,
                    'category_instance': instance,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            messages.error(request, 'Could not save the category.', extra_tags='tenant')
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

        return redirect_resp


class TenantCargoCategoryDeleteView(View):
    def post(self, request, category_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_cargo_master_access_guard(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            category = TenantCargoCategory.objects.filter(pk=category_id).first()
            if not category:
                messages.error(request, 'Category not found.', extra_tags='tenant')
                return _redirect_cargo_category_list(request)

            label = category.category_code
            try:
                category.delete()
            except ProtectedError:
                messages.error(
                    request,
                    'Cannot delete this category while cargo records reference it.',
                    extra_tags='tenant',
                )
                return _redirect_cargo_category_list(request)

            messages.success(request, f'Category {label} deleted.', extra_tags='tenant')
            return _redirect_cargo_category_list(request)
        finally:
            connection.set_schema_to_public()


class TenantSubscriptionPlanView(View):
    """Tenant subscription plan page with upgrade/downgrade/renewal actions."""

    _PLAN_ACTIONS = {'New_Subscription', 'Renewal', 'Upgrade', 'Downgrade'}

    def _resolve_payment_method(self, tenant, currency_code):
        has_default_card = TenantPaymentCard.objects.filter(
            tenant_profile=tenant,
            is_active=True,
            is_default=True,
        ).exists()
        if not has_default_card:
            return None
        # Card-based subscription flow uses online gateway only.
        return PaymentMethod.objects.filter(
            is_active=True,
            method_type='Online_Gateway',
            supported_currencies__contains=[currency_code],
        ).order_by('display_order').first()

    def _load_plan_context(self, tenant):
        current_plan = tenant.current_plan
        selected_currency = (
            SubscriptionOrder.objects.filter(tenant=tenant)
            .select_related('currency')
            .order_by('-created_at')
            .values_list('currency__currency_code', flat=True)
            .first()
        )
        if not selected_currency:
            selected_currency = (
                PlanPricingCycle.objects.select_related('currency')
                .filter(is_admin_only_cycle=False)
                .order_by('currency__currency_code')
                .values_list('currency__currency_code', flat=True)
                .first()
            )
        if not selected_currency:
            selected_currency = (
                Currency.objects.filter(is_active=True)
                .order_by('currency_code')
                .values_list('currency_code', flat=True)
                .first()
                or ''
            )

        eligible_plan_ids = PlanPricingCycle.objects.filter(
            is_admin_only_cycle=False,
            plan__is_active=True,
            plan__is_deleted=False,
        ).values_list('plan_id', flat=True).distinct()
        plans = list(
            SubscriptionPlan.objects.filter(
                is_active=True,
                is_deleted=False,
                plan_id__in=eligible_plan_ids,
            )
            .order_by('plan_name_en')
        )
        pricing_rows = (
            PlanPricingCycle.objects.select_related('currency')
            .filter(plan__in=plans, number_of_cycles__in=[1, 12], is_admin_only_cycle=False)
            .order_by('plan__plan_name_en', 'number_of_cycles', 'currency__currency_code')
        )
        pricing_map = {}
        for row in pricing_rows:
            key = (str(row.plan_id), row.currency_id)
            pricing_map.setdefault(key, {})[int(row.number_of_cycles)] = row

        current_monthly_price = None
        if current_plan and selected_currency:
            current_monthly = pricing_map.get(
                (str(current_plan.plan_id), selected_currency), {}
            ).get(1)
            if current_monthly:
                current_monthly_price = current_monthly.price

        plan_cards = []
        for plan in plans:
            prices_for_currency = pricing_map.get((str(plan.plan_id), selected_currency), {})
            monthly_row = prices_for_currency.get(1)
            yearly_row = prices_for_currency.get(12)
            if not monthly_row and not yearly_row:
                continue

            if monthly_row and yearly_row:
                default_cycle = 1
            elif monthly_row:
                default_cycle = 1
            else:
                default_cycle = 12
            default_row = monthly_row or yearly_row

            action_type = 'New_Subscription'
            action_label = 'Choose Plan'
            is_current = bool(current_plan and plan.plan_id == current_plan.plan_id)
            if is_current:
                action_type = 'Renewal'
                action_label = 'Renew Plan'
            elif current_plan and current_monthly_price is not None and monthly_row:
                if monthly_row.price >= current_monthly_price:
                    action_type = 'Upgrade'
                    action_label = 'Upgrade Plan'
                else:
                    action_type = 'Downgrade'
                    action_label = 'Downgrade Plan'

            plan_cards.append(
                {
                    'plan': plan,
                    'monthly_row': monthly_row,
                    'yearly_row': yearly_row,
                    'default_cycle': default_cycle,
                    'default_price': default_row.price if default_row else Decimal('0.00'),
                    'currency_code': selected_currency,
                    'is_current': is_current,
                    'action_type': action_type,
                    'action_label': action_label,
                }
            )

        has_yearly_option = any(card['yearly_row'] for card in plan_cards)
        faqs = list(
            SubscriptionFAQ.objects.filter(is_active=True)
            .order_by('display_order', 'created_at')
        )
        return {
            'plan_cards': plan_cards,
            'selected_currency': selected_currency,
            'has_yearly_option': has_yearly_option,
            'subscription_faqs': faqs,
        }

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        context.update(self._load_plan_context(context['tenant']))
        return render(request, 'iroad_tenants/Subscription_Manage/Subscription-plan.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        tenant = context['tenant']
        action_type = (request.POST.get('action_type') or '').strip()
        plan_id = (request.POST.get('plan_id') or '').strip()
        selected_cycle_raw = (request.POST.get('selected_cycle') or '1').strip()
        selected_currency = (request.POST.get('currency_code') or '').strip()
        try:
            selected_cycle = int(selected_cycle_raw)
        except ValueError:
            selected_cycle = 1

        if action_type not in self._PLAN_ACTIONS:
            messages.error(request, 'Invalid subscription action.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        plan = SubscriptionPlan.objects.filter(
            plan_id=plan_id,
            is_active=True,
            is_deleted=False,
        ).first()
        if not plan:
            messages.error(request, 'Selected plan is not available.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        currency = Currency.objects.filter(
            currency_code=selected_currency,
            is_active=True,
        ).first()
        if not currency:
            currency = (
                SubscriptionOrder.objects.filter(tenant=tenant)
                .select_related('currency')
                .order_by('-created_at')
                .values_list('currency__currency_code', flat=True)
                .first()
            )
            currency = Currency.objects.filter(currency_code=currency, is_active=True).first()
        if not currency:
            messages.error(request, 'No active currency is configured.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        pricing_row = PlanPricingCycle.objects.filter(
            plan=plan,
            currency=currency,
            number_of_cycles=selected_cycle,
            is_admin_only_cycle=False,
        ).first()
        if not pricing_row:
            messages.error(
                request,
                'Pricing is not configured for this cycle/currency.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        if action_type == 'Downgrade':
            error = validate_downgrade_order(tenant, plan)
            if error:
                messages.error(request, error, extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        tax = get_tax_code_for_tenant(tenant, client_ip=request.META.get('REMOTE_ADDR'))
        if tax is None:
            messages.error(
                request,
                'Tax settings are missing. Contact support.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        fx = get_fx_snapshot(currency.currency_code, strict=True)
        if fx is None:
            messages.error(
                request,
                'Exchange rate is missing for selected currency.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        payment_method = self._resolve_payment_method(tenant, currency.currency_code)
        if payment_method is None:
            messages.error(
                request,
                'Add a default payment card first. Offline bank transfer is not supported here.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_plan')

        tax_rate = tax.rate_percent or Decimal('0.00')
        plan_price = pricing_row.price
        pro_rata = Decimal('0.00')
        if action_type == 'Upgrade' and tenant.current_plan:
            old_price = resolve_upgrade_credit_basis_price(
                tenant.current_plan,
                currency.currency_code,
            )
            pro_rata = calculate_pro_rata_credit(tenant, old_price)
        line_total = (plan_price + pro_rata).quantize(Decimal('0.01'))
        sub_total = line_total
        tax_amount = (sub_total * tax_rate / Decimal('100')).quantize(Decimal('0.01'))
        grand_total = (sub_total + tax_amount).quantize(Decimal('0.01'))
        base_equiv = (grand_total * fx).quantize(Decimal('0.01'))

        with db_transaction.atomic():
            order = SubscriptionOrder.objects.create(
                tenant=tenant,
                order_classification=action_type,
                currency=currency,
                payment_method=payment_method,
                created_by=None,
                promo_code=None,
                tax_code=tax,
                sub_total=sub_total,
                discount_amount=Decimal('0.00'),
                tax_amount=tax_amount,
                grand_total=grand_total,
                exchange_rate_snapshot=fx,
                base_currency_equivalent=base_equiv,
                order_status='Pending_Payment',
            )
            OrderPlanLine.objects.create(
                order=order,
                plan=plan,
                number_of_cycles=selected_cycle,
                plan_price=plan_price,
                pro_rata_adjustment=pro_rata,
                line_total=line_total,
                plan_name_en_snapshot=plan.plan_name_en,
                plan_name_ar_snapshot=plan.plan_name_ar or '',
            )
            refresh_order_projected_fields(order)
            order.save(
                update_fields=[
                    'projected_plan',
                    'projected_expiry_date',
                    'projected_max_users',
                    'projected_max_internal_trucks',
                    'projected_max_external_trucks',
                    'projected_max_drivers',
                ]
            )
            sync_or_create_order_payment_transaction(order)

        if complete_order_payment_as_system(order, None):
            messages.success(
                request,
                f'{plan.plan_name_en} {action_type.replace("_", " ").lower()} completed successfully.',
                extra_tags='tenant',
            )
        else:
            messages.warning(
                request,
                'Order created, but payment capture did not complete.',
                extra_tags='tenant',
            )
        return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')


class TenantSubscriptionBillingView(View):
    """Tenant subscription billing page with live data."""

    @staticmethod
    def _parse_expiry(expiry_value):
        raw = (expiry_value or '').strip()
        if '/' not in raw:
            return None, None
        month_s, year_s = raw.split('/', 1)
        try:
            month = int(month_s)
            yy = int(year_s)
        except ValueError:
            return None, None
        if month < 1 or month > 12:
            return None, None
        year = 2000 + yy if yy < 100 else yy
        return month, year

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant = context['tenant']
        current_plan = tenant.current_plan

        latest_plan_line = (
            OrderPlanLine.objects.select_related('order')
            .filter(order__tenant=tenant)
            .order_by('-order__created_at')
            .first()
        )
        current_cycle = 1
        if latest_plan_line and latest_plan_line.number_of_cycles in (1, 12):
            current_cycle = latest_plan_line.number_of_cycles

        active_currency = (
            SubscriptionOrder.objects.filter(tenant=tenant)
            .select_related('currency')
            .order_by('-created_at')
            .values_list('currency__currency_code', flat=True)
            .first()
        ) or 'SAR'

        current_price = Decimal('0.00')
        if current_plan:
            current_pricing = PlanPricingCycle.objects.filter(
                plan=current_plan,
                currency_id=active_currency,
                number_of_cycles=current_cycle,
            ).first()
            if current_pricing:
                current_price = current_pricing.price

        invoices = list(
            StandardInvoice.objects.filter(tenant=tenant)
            .select_related('currency')
            .order_by('-issue_date')[:20]
        )
        start_of_year = timezone.now().date().replace(month=1, day=1)
        total_spent_ytd = sum(
            (
                inv.grand_total
                for inv in invoices
                if inv.issue_date
                and inv.issue_date.date() >= start_of_year
                and inv.status in ('Issued', 'Paid')
            ),
            Decimal('0.00'),
        )

        next_payment_due = tenant.subscription_expiry_date
        cards = list(
            TenantPaymentCard.objects.filter(
                tenant_profile=tenant,
                is_active=True,
            ).order_by('-is_default', '-updated_at')
        )
        # Safety normalization: keep exactly one default card per tenant.
        if cards:
            default_cards = [c for c in cards if c.is_default]
            if len(default_cards) != 1:
                keeper = default_cards[0] if default_cards else cards[0]
                TenantPaymentCard.objects.filter(
                    tenant_profile=tenant,
                    is_active=True,
                ).update(is_default=False)
                keeper.is_default = True
                keeper.save(update_fields=['is_default', 'updated_at'])
                cards = list(
                    TenantPaymentCard.objects.filter(
                        tenant_profile=tenant,
                        is_active=True,
                    ).order_by('-is_default', '-updated_at')
                )
        default_card = next((c for c in cards if c.is_default), cards[0] if cards else None)

        context.update(
            {
                'current_plan': current_plan,
                'current_cycle': current_cycle,
                'current_cycle_label': 'Yearly Billing' if current_cycle == 12 else 'Monthly Billing',
                'current_price': current_price,
                'active_currency': active_currency,
                'next_payment_due': next_payment_due,
                'invoices': invoices,
                'total_spent_ytd': total_spent_ytd,
                'default_card': default_card,
                'payment_cards': cards,
            }
        )
        return render(request, 'iroad_tenants/Subscription_Manage/Subscription-billing.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        tenant = context['tenant']
        action = (request.POST.get('action') or '').strip()
        if action == 'remove_card':
            target_card_id = (request.POST.get('card_id') or '').strip()
            target_card = TenantPaymentCard.objects.filter(
                tenant_profile=tenant,
                card_id=target_card_id,
                is_active=True,
            ).first()
            if not target_card:
                messages.error(request, 'Card to remove was not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
            active_cards = list(
                TenantPaymentCard.objects.filter(
                    tenant_profile=tenant,
                    is_active=True,
                ).order_by('-is_default', '-updated_at')
            )
            if len(active_cards) <= 1:
                messages.error(request, 'At least one payment card is required.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
            if target_card.is_default:
                messages.error(request, 'Current in-use card cannot be deleted.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
            was_default = target_card.is_default
            target_card.is_active = False
            target_card.is_default = False
            target_card.save(update_fields=['is_active', 'is_default', 'updated_at'])
            if was_default:
                replacement = TenantPaymentCard.objects.filter(
                    tenant_profile=tenant,
                    is_active=True,
                ).order_by('-updated_at').first()
                if replacement:
                    replacement.is_default = True
                    replacement.save(update_fields=['is_default', 'updated_at'])
            messages.success(request, 'Payment card removed successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')

        if action not in ('add_card', 'update_card'):
            messages.error(request, 'Invalid card action.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')

        cardholder_name = (request.POST.get('cardholderName') or '').strip()
        card_number = (request.POST.get('cardNumber') or '').strip().replace(' ', '')
        expiry = (request.POST.get('expiry') or '').strip()
        cvc = (request.POST.get('cvc') or '').strip()
        set_default = bool(request.POST.get('setAsDefault'))
        target_card_id = (request.POST.get('card_id') or '').strip()

        if not cardholder_name:
            messages.error(request, 'Card holder name is required.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')

        expiry_month, expiry_year = self._parse_expiry(expiry)
        if not expiry_month or not expiry_year:
            messages.error(request, 'Enter expiry in MM/YY format.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')

        if action == 'update_card':
            target_card = TenantPaymentCard.objects.filter(
                tenant_profile=tenant,
                card_id=target_card_id,
                is_active=True,
            ).first()
            if not target_card:
                messages.error(request, 'Card to update was not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
            # Update modal shows masked card/CVC by default. If masked value is posted,
            # retain existing stored last4 and only validate when a full new number is entered.
            if '•' in card_number or card_number == '':
                card_last4 = target_card.last4
            else:
                if not card_number.isdigit() or len(card_number) != 16:
                    messages.error(request, 'Enter a valid 16-digit card number.', extra_tags='tenant')
                    return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
                card_last4 = card_number[-4:]
            if not ('•' in cvc or cvc == '') and (not cvc.isdigit() or len(cvc) not in (3, 4)):
                messages.error(request, 'Enter a valid CVC.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
        else:
            target_card = None
            if not card_number.isdigit() or len(card_number) != 16:
                messages.error(request, 'Enter a valid 16-digit card number.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
            if not cvc.isdigit() or len(cvc) not in (3, 4):
                messages.error(request, 'Enter a valid CVC.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
            card_last4 = card_number[-4:]

        if set_default:
            TenantPaymentCard.objects.filter(
                tenant_profile=tenant,
                is_active=True,
            ).update(is_default=False)
        if target_card is not None:
            target_card.cardholder_name = cardholder_name
            target_card.brand = 'VISA'
            target_card.last4 = card_last4
            target_card.expiry_month = expiry_month
            target_card.expiry_year = expiry_year
            target_card.is_default = set_default or target_card.is_default
            target_card.save(
                update_fields=[
                    'cardholder_name',
                    'brand',
                    'last4',
                    'expiry_month',
                    'expiry_year',
                    'is_default',
                    'updated_at',
                ]
            )
            messages.success(request, 'Payment card updated successfully.', extra_tags='tenant')
        else:
            TenantPaymentCard.objects.create(
                tenant_profile=tenant,
                cardholder_name=cardholder_name,
                brand='VISA',
                last4=card_last4,
                expiry_month=expiry_month,
                expiry_year=expiry_year,
                is_default=set_default or not TenantPaymentCard.objects.filter(
                    tenant_profile=tenant,
                    is_active=True,
                ).exists(),
                is_active=True,
            )
            messages.success(request, 'Payment card saved successfully.', extra_tags='tenant')
        return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')


class TenantInvoiceDownloadView(View):
    """Download a single invoice PDF for the logged-in tenant."""

    def get(self, request, invoice_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        tenant = context['tenant']
        invoice = (
            StandardInvoice.objects.select_related('tenant')
            .filter(invoice_id=invoice_id, tenant=tenant)
            .first()
        )
        if invoice is None:
            return HttpResponse('Invoice not found.', status=404)

        pdf_bytes = generate_invoice_pdf_bytes(invoice)
        if pdf_bytes:
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = (
                f'attachment; filename="{invoice.invoice_number}.pdf"'
            )
            return response

        fallback = (
            f'Invoice: {invoice.invoice_number}\n'
            f'Status: {invoice.status}\n'
            f'Amount: {invoice.currency_id} {invoice.grand_total}\n'
            f'Due Date: {invoice.due_date or ""}\n'
        )
        response = HttpResponse(fallback, content_type='text/plain')
        response['Content-Disposition'] = (
            f'attachment; filename="{invoice.invoice_number}.txt"'
        )
        return response


class TenantInvoiceExportAllView(View):
    """Export tenant invoice history as CSV."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        tenant = context['tenant']
        invoices = (
            StandardInvoice.objects.select_related('currency')
            .filter(tenant=tenant)
            .order_by('-issue_date')
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                'Invoice Number',
                'Issue Date',
                'Due Date',
                'Plan',
                'Currency',
                'Sub Total',
                'Tax',
                'Discount',
                'Grand Total',
                'Status',
            ]
        )
        for inv in invoices:
            plan_name = ''
            first_line = inv.order.plan_lines.select_related('plan').first() if inv.order_id else None
            if first_line:
                plan_name = first_line.plan_name_en_snapshot or first_line.plan.plan_name_en
            writer.writerow(
                [
                    inv.invoice_number,
                    inv.issue_date.strftime('%Y-%m-%d') if inv.issue_date else '',
                    inv.due_date.strftime('%Y-%m-%d') if inv.due_date else '',
                    plan_name,
                    inv.currency_id,
                    f'{inv.sub_total}',
                    f'{inv.tax_amount}',
                    f'{inv.discount_amount}',
                    f'{inv.grand_total}',
                    inv.status,
                ]
            )

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="tenant_invoices.csv"'
        return response


def _build_login_session_events_context(request):
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = str(auth_payload.get('tenant_id') or '').strip()

    events = []

    # Live active sessions from Redis (tenant-specific).
    for session in get_all_active_tenant_sessions():
        if str(session.get('tenant_id') or '') != tenant_id:
            continue
        started_at = session.get('started_at')
        if not started_at:
            continue
        started_dt = parse_datetime(str(started_at))
        if started_dt is None:
            continue
        if timezone.is_naive(started_dt):
            started_dt = timezone.make_aware(started_dt, timezone.get_current_timezone())
        events.append(
            {
                'timestamp': started_dt,
                'action': 'Session Active',
                'module': 'Authentication',
                'performed_by': session.get('reference_name') or session.get('reference_id') or 'Tenant User',
                'event_type': 'active_session',
            }
        )

    successful_logins = 0
    failed_attempts = 0

    # Tenant user login history and failed attempts from tenant workspace schema.
    tenant_registry = _activate_tenant_workspace_schema(request)
    if tenant_registry is not None:
        try:
            users = list(
                TenantUser.objects.values(
                    'full_name',
                    'email',
                    'last_login_at',
                    'login_attempts',
                )
            )
            for user in users:
                if user.get('last_login_at'):
                    successful_logins += 1
                    events.append(
                        {
                            'timestamp': user.get('last_login_at'),
                            'action': 'Login Success',
                            'module': 'Authentication',
                            'performed_by': user.get('full_name') or user.get('email') or 'Tenant User',
                            'event_type': 'login_success',
                        }
                    )
                failed_attempts += int(user.get('login_attempts') or 0)
                if int(user.get('login_attempts') or 0) > 0:
                    events.append(
                        {
                            'timestamp': timezone.now(),
                            'action': f'Failed Attempts ({int(user.get("login_attempts") or 0)})',
                            'module': 'Security',
                            'performed_by': user.get('full_name') or user.get('email') or 'Tenant User',
                            'event_type': 'failed_attempt',
                        }
                    )
        finally:
            connection.set_schema_to_public()

    events.sort(key=lambda row: row.get('timestamp') or timezone.now(), reverse=True)
    paginator = Paginator(events, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    active_sessions = sum(1 for event in events if event.get('event_type') == 'active_session')
    total_events = len(events)

    rows = []
    start_index = (page_obj.number - 1) * paginator.per_page
    for index, event in enumerate(page_obj.object_list, start=start_index + 1):
        rows.append(
            {
                'sl_no': index,
                'timestamp': event.get('timestamp'),
                'action': event.get('action'),
                'module': event.get('module'),
                'performed_by': event.get('performed_by'),
            }
        )

    return {
        'login_session_total_events': total_events,
        'login_session_successful_logins': successful_logins,
        'login_session_active_sessions': active_sessions,
        'login_session_failed_attempts': failed_attempts,
        'login_session_rows': rows,
        'login_session_page_obj': page_obj,
    }


def _build_role_permission_changes_context(request):
    rows = []
    total_changes = 0
    active_roles = 0
    permissions_updated = 0
    roles_deleted = 0
    page_obj = Paginator([], 10).get_page(1)

    tenant_registry = _activate_tenant_workspace_schema(request)
    if tenant_registry is not None:
        try:
            role_events = list(
                TenantRole.objects.values(
                    'updated_at',
                    'role_name_en',
                    'status',
                    'created_by_label',
                    'created_at',
                )
            )
            permission_events = list(
                TenantRolePermission.objects.select_related('role').values(
                    'updated_at',
                    'module_name',
                    'form_name',
                    'role__role_name_en',
                    'role__created_by_label',
                    'created_at',
                )
            )

            active_roles = TenantRole.objects.filter(
                status=TenantRole.Status.ACTIVE
            ).count()
            permissions_updated = TenantRolePermission.objects.count()
            # This card is labeled "Roles Deleted" in UI; use non-active roles
            # as the closest live indicator since hard deletes are not tracked.
            roles_deleted = TenantRole.objects.exclude(
                status=TenantRole.Status.ACTIVE
            ).count()
            total_changes = len(role_events) + len(permission_events)

            raw_events = []
            for event in role_events:
                created_at = event.get('created_at')
                updated_at = event.get('updated_at')
                action = 'Role Updated'
                if created_at and updated_at and created_at == updated_at:
                    action = 'Role Created'
                if event.get('status') == TenantRole.Status.INACTIVE:
                    action = 'Role Disabled'
                raw_events.append(
                    {
                        'timestamp': updated_at,
                        'action': action,
                        'module': 'Roles',
                        'performed_by': event.get('created_by_label') or 'System',
                    }
                )

            for event in permission_events:
                created_at = event.get('created_at')
                updated_at = event.get('updated_at')
                action = 'Permission Updated'
                if created_at and updated_at and created_at == updated_at:
                    action = 'Permission Added'
                raw_events.append(
                    {
                        'timestamp': updated_at,
                        'action': action,
                        'module': event.get('module_name') or 'Permissions',
                        'performed_by': (
                            event.get('role__created_by_label')
                            or event.get('role__role_name_en')
                            or 'System'
                        ),
                    }
                )

            raw_events.sort(
                key=lambda item: item.get('timestamp') or timezone.now(),
                reverse=True,
            )
            paginator = Paginator(raw_events, 10)
            page_obj = paginator.get_page(request.GET.get('page'))
            start_index = (page_obj.number - 1) * paginator.per_page
            for index, event in enumerate(page_obj.object_list, start=start_index + 1):
                rows.append(
                    {
                        'sl_no': index,
                        'timestamp': event.get('timestamp'),
                        'action': event.get('action'),
                        'module': event.get('module'),
                        'performed_by': event.get('performed_by'),
                    }
                )
        finally:
            connection.set_schema_to_public()

    return {
        'role_permission_total_changes': total_changes,
        'role_permission_active_roles': active_roles,
        'role_permission_permissions_updated': permissions_updated,
        'role_permission_roles_deleted': roles_deleted,
        'role_permission_rows': rows,
        'role_permission_page_obj': page_obj,
    }


def _build_critical_account_changes_context(request):
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = str(auth_payload.get('tenant_id') or '').strip()
    search_query = (request.GET.get('search') or '').strip()
    if not tenant_id:
        empty_page = Paginator([], 10).get_page(1)
        return {
            'critical_account_total_changes': 0,
            'critical_account_billing_updates': 0,
            'critical_account_security_updates': 0,
            'critical_account_critical_alerts': 0,
            'critical_account_rows': [],
            'critical_account_page_obj': empty_page,
            'critical_account_search_query': search_query,
        }

    tenant_actor_label = 'Tenant Admin'
    tenant_user_map = {}
    tenant_user_ids = []
    tenant_obj = TenantProfile.objects.filter(pk=tenant_id).first()
    if tenant_obj:
        tenant_actor_label = (
            tenant_obj.primary_email
            or tenant_obj.company_name
            or tenant_actor_label
        )
    session_data = get_tenant_session(
        tenant_id,
        str(auth_payload.get('jti') or '').strip(),
    ) or {}
    reference_id = str(session_data.get('reference_id') or '').strip()
    tenant_registry = _activate_tenant_workspace_schema(request)
    if tenant_registry is not None:
        try:
            for user in TenantUser.objects.values('user_id', 'full_name', 'email'):
                user_id = str(user.get('user_id') or '').strip()
                if not user_id:
                    continue
                tenant_user_ids.append(user_id)
                tenant_user_map[user_id] = (
                    (user.get('full_name') or '').strip()
                    or (user.get('email') or '').strip()
                )

            if reference_id and reference_id != tenant_id:
                tenant_user = TenantUser.objects.filter(pk=reference_id).first()
                if tenant_user:
                    tenant_actor_label = (
                        tenant_user.full_name
                        or tenant_user.email
                        or tenant_actor_label
                    )
        finally:
            connection.set_schema_to_public()

    security_terms = (
        Q(module_name__icontains='security')
        | Q(module_name__icontains='auth')
        | Q(module_name__icontains='session')
        | Q(module_name__icontains='login')
    )
    billing_terms = (
        Q(module_name__icontains='billing')
        | Q(module_name__icontains='invoice')
        | Q(module_name__icontains='payment')
        | Q(module_name__icontains='subscription')
    )
    module_scope_q = Q(
        Q(module_name__icontains='security')
        | Q(module_name__icontains='auth')
        | Q(module_name__icontains='session')
        | Q(module_name__icontains='login')
        | Q(module_name__icontains='billing')
        | Q(module_name__icontains='invoice')
        | Q(module_name__icontains='payment')
        | Q(module_name__icontains='subscription')
        | Q(module_name__icontains='tenant')
        | Q(module_name__icontains='crm')
        | Q(module_name__icontains='note')
    )
    tenant_scope_q = (
        Q(record_id=tenant_id)
        | Q(old_payload__contains={'tenant_id': tenant_id})
        | Q(new_payload__contains={'tenant_id': tenant_id})
        | Q(old_payload__contains={'tenant_profile': tenant_id})
        | Q(new_payload__contains={'tenant_profile': tenant_id})
        | Q(old_payload__contains={'tenant': tenant_id})
        | Q(new_payload__contains={'tenant': tenant_id})
    )
    if tenant_user_ids:
        tenant_scope_q |= Q(record_id__in=tenant_user_ids)

    critical_qs = AuditLog.objects.filter(module_scope_q & tenant_scope_q).select_related('admin')
    if search_query:
        critical_qs = critical_qs.filter(
            Q(action_type__icontains=search_query)
            | Q(module_name__icontains=search_query)
            | Q(record_id__icontains=search_query)
            | Q(admin__email__icontains=search_query)
            | Q(admin__first_name__icontains=search_query)
            | Q(admin__last_name__icontains=search_query)
        )
    critical_qs = critical_qs.order_by('-timestamp')
    paginator = Paginator(critical_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    logs = list(page_obj.object_list)

    total_changes = critical_qs.count()
    billing_updates = critical_qs.filter(billing_terms).count()
    security_updates = critical_qs.filter(security_terms).count()
    critical_alerts = critical_qs.filter(
        Q(action_type='Delete') | Q(action_type='Status_Change')
    ).count()

    rows = []
    start_index = (page_obj.number - 1) * paginator.per_page
    for index, log in enumerate(logs, start=start_index + 1):
        module_name = (log.module_name or '').strip() or 'System'
        module_lower = module_name.lower()
        if any(key in module_lower for key in ('billing', 'invoice', 'payment', 'subscription')):
            normalized_module = 'Billing Settings'
        elif any(key in module_lower for key in ('security', 'auth', 'session', 'login')):
            normalized_module = 'Security Settings'
        else:
            normalized_module = 'Tenant Config'
        record_id = str(log.record_id or '').strip()
        performed_by_user = tenant_user_map.get(record_id, '')
        performed_by_admin = ''
        if log.admin_id and log.admin:
            performed_by_admin = (
                f'{(log.admin.first_name or "").strip()} {(log.admin.last_name or "").strip()}'.strip()
                or (log.admin.email or '').strip()
            )
        performed_by = (
            performed_by_user
            or performed_by_admin
            or tenant_actor_label
            or 'Tenant Admin'
        )
        rows.append(
            {
                'sl_no': index,
                'timestamp': log.timestamp,
                'action': f'{log.action_type} ({module_name})',
                'module': normalized_module,
                'performed_by': performed_by,
            }
        )

    return {
        'critical_account_total_changes': total_changes,
        'critical_account_billing_updates': billing_updates,
        'critical_account_security_updates': security_updates,
        'critical_account_critical_alerts': critical_alerts,
        'critical_account_rows': rows,
        'critical_account_page_obj': page_obj,
        'critical_account_search_query': search_query,
    }


class TenantRolePermissionChangesView(View):
    """Tenant audit page: role/permission changes (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        context.update(_build_role_permission_changes_context(request))
        return render(
            request,
            'iroad_tenants/Audit_log/Role--permission-changes.html',
            context,
        )


class TenantCriticalAccountChangesView(View):
    """Tenant audit page: critical account changes (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        context.update(_build_critical_account_changes_context(request))
        return render(
            request,
            'iroad_tenants/Audit_log/Critical-account-changes.html',
            context,
        )


class TenantLoginSessionEventsView(View):
    """Tenant audit page: login/session events (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        context.update(_build_login_session_events_context(request))
        return render(
            request,
            'iroad_tenants/Audit_log/Login--session-events.html',
            context,
        )


class TenantSimplePageView(View):
    """Render tenant templates via GET only."""

    template_name = ''

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(request, self.template_name, context)


def _get_singleton_client_account_settings():
    """Single settings row for the active tenant schema (isolated per-tenant DB).

    Prefer the most recently updated row so we never read stale flags if duplicate
    rows ever existed; settings POST success path consolidates to one row.
    """
    row = TenantClientAccountSetting.objects.order_by('-updated_at').first()
    if row is None:
        row = TenantClientAccountSetting.objects.create()
    return row


def _client_account_settings_template_dict(settings_obj):
    return {
        'require_national_id_individual': settings_obj.require_national_id_individual,
        'require_commercial_registration_business': (
            settings_obj.require_commercial_registration_business
        ),
        'require_tax_vat_registration_business': settings_obj.require_tax_vat_registration_business,
        'default_client_status': settings_obj.default_client_status,
        'default_client_type': settings_obj.default_client_type,
        'default_preferred_currency': settings_obj.default_preferred_currency or '',
    }


def _apply_client_account_defaults_from_settings(form_data, settings_obj):
    """Pre-fill new-client form from tenant-scoped Client Account Settings."""
    if settings_obj.default_client_status:
        form_data['status'] = settings_obj.default_client_status
    if settings_obj.default_client_type:
        form_data['client_type'] = settings_obj.default_client_type
    default_cur = (settings_obj.default_preferred_currency or '').strip()
    if default_cur:
        form_data['preferred_currency'] = default_cur


def _validate_client_account_document_rules(form_data, settings_obj, form_errors):
    """Enforce National ID / CR / VAT rules from the current tenant's settings."""
    from tenant_workspace.client_account_document_rules import (
        collect_client_account_document_rule_errors,
    )

    form_errors.update(
        collect_client_account_document_rule_errors(
            client_type=form_data.get('client_type'),
            national_id=form_data.get('national_id'),
            commercial_registration_no=form_data.get('commercial_registration_no'),
            tax_registration_no=form_data.get('tax_registration_no'),
            require_national_id_individual=bool(settings_obj.require_national_id_individual),
            require_commercial_registration_business=bool(
                settings_obj.require_commercial_registration_business
            ),
            require_tax_vat_registration_business=bool(
                settings_obj.require_tax_vat_registration_business
            ),
        )
    )


def _merge_validation_error_into_form_errors(exc, form_errors):
    """Map Django ``ValidationError`` (e.g. from ``TenantClientAccount.save``) to form field errors."""
    if hasattr(exc, 'message_dict') and exc.message_dict:
        for field, msgs in exc.message_dict.items():
            if isinstance(msgs, (list, tuple)) and msgs:
                form_errors[field] = str(msgs[0])
            elif msgs:
                form_errors[field] = str(msgs)
            else:
                form_errors[field] = str(exc)
    elif getattr(exc, 'messages', None):
        joined = '; '.join(str(m) for m in exc.messages)
        form_errors.setdefault('__all__', joined)


class TenantClientAccountView(View):
    """List client accounts from the current tenant workspace schema."""

    template_name = 'iroad_tenants/Clients_Management/Client-account.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            client_accounts = list(
                TenantClientAccount.objects.all().order_by('-created_at', '-account_no')
            )
            context.update(
                {
                    'client_accounts': client_accounts,
                    'client_accounts_count': len(client_accounts),
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientAccountSettingsView(View):
    """Load/save client CRM defaults in the current tenant workspace schema only."""

    template_name = 'iroad_tenants/Clients_Management/Client-account-setting.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            settings_obj = _get_singleton_client_account_settings()
            context.update(
                {
                    'settings_data': _client_account_settings_template_dict(settings_obj),
                    'settings_errors': {},
                    'currency_options': _active_currency_options(),
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            settings_data = {
                'require_national_id_individual': bool(
                    request.POST.get('require_national_id_individual')
                ),
                'require_commercial_registration_business': bool(
                    request.POST.get('require_commercial_registration_business')
                ),
                'require_tax_vat_registration_business': bool(
                    request.POST.get('require_tax_vat_registration_business')
                ),
                'default_client_status': (request.POST.get('default_client_status') or '').strip()
                or TenantClientAccount.Status.ACTIVE,
                'default_client_type': (request.POST.get('default_client_type') or '').strip()
                or TenantClientAccount.ClientType.INDIVIDUAL,
                'default_preferred_currency': (request.POST.get('default_preferred_currency') or '').strip(),
            }
            settings_errors = {}
            if settings_data['default_client_status'] not in {
                TenantClientAccount.Status.ACTIVE,
                TenantClientAccount.Status.INACTIVE,
            }:
                settings_errors['default_client_status'] = 'Invalid default status.'
            if settings_data['default_client_type'] not in {
                TenantClientAccount.ClientType.INDIVIDUAL,
                TenantClientAccount.ClientType.BUSINESS,
            }:
                settings_errors['default_client_type'] = 'Invalid default client type.'
            if settings_data['default_preferred_currency']:
                valid_codes = {
                    c['currency_code'] for c in _active_currency_options()
                }
                if settings_data['default_preferred_currency'] not in valid_codes:
                    settings_errors['default_preferred_currency'] = (
                        'Choose an active currency from the list, or leave the default currency empty.'
                    )

            if settings_errors:
                context.update(
                    {
                        'settings_data': settings_data,
                        'settings_errors': settings_errors,
                        'currency_options': _active_currency_options(),
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(
                    request,
                    'Please fix the highlighted errors.',
                    extra_tags='tenant',
                )
                return render(request, self.template_name, context)

            keeper = TenantClientAccountSetting.objects.order_by('-updated_at').first()
            if keeper is None:
                keeper = TenantClientAccountSetting.objects.create()
            else:
                TenantClientAccountSetting.objects.exclude(pk=keeper.pk).delete()
            settings_obj = keeper
            settings_obj.require_national_id_individual = settings_data[
                'require_national_id_individual'
            ]
            settings_obj.require_commercial_registration_business = settings_data[
                'require_commercial_registration_business'
            ]
            settings_obj.require_tax_vat_registration_business = settings_data[
                'require_tax_vat_registration_business'
            ]
            settings_obj.default_client_status = settings_data['default_client_status']
            settings_obj.default_client_type = settings_data['default_client_type']
            settings_obj.default_preferred_currency = settings_data['default_preferred_currency']
            settings_obj.save()
            messages.success(
                request,
                'Client account settings saved for this workspace.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account_settings')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountCreateView(View):
    template_name = 'iroad_tenants/Clients_Management/Client-account-new.html'

    CLIENT_FORM_CODE = 'client-account'
    CLIENT_FORM_LABEL = 'Client Account'
    CLIENT_REF_PREFIX = 'CA'

    def _base_form_data(self):
        return {
            'account_no': '',
            'created_at': timezone.localtime().strftime('%b %d, %Y, %I:%M %p'),
            'client_type': TenantClientAccount.ClientType.INDIVIDUAL,
            'status': TenantClientAccount.Status.ACTIVE,
            'name_arabic': '',
            'name_english': '',
            'display_name': '',
            'preferred_currency': '',
            'billing_street_1': '',
            'billing_street_2': '',
            'billing_city': '',
            'billing_region': '',
            'postal_code': '',
            'country': '',
            'credit_limit_amount': '',
            'limit_currency_code': 'SAR',
            'payment_term_days': '',
            'national_id': '',
            'commercial_registration_no': '',
            'tax_registration_no': '',
        }

    def _collect_form_data(self, request):
        data = self._base_form_data()
        for key in data.keys():
            if key in {'status', 'client_type'}:
                data[key] = (request.POST.get(key) or '').strip() or data[key]
            else:
                data[key] = (request.POST.get(key) or '').strip()
        data['limit_currency_code'] = data['limit_currency_code'] or 'SAR'
        return data

    def _build_preview_account_no(self):
        config, _ = AutoNumberConfiguration.objects.get_or_create(
            form_code=self.CLIENT_FORM_CODE,
            defaults={
                'form_label': self.CLIENT_FORM_LABEL,
                'number_of_digits': 4,
                'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
                'is_unique': True,
            },
        )
        sequence = AutoNumberSequence.objects.filter(form_code=self.CLIENT_FORM_CODE).first()
        next_number = int(sequence.next_number if sequence else 1)
        return _render_tenant_ref_no(next_number, config, prefix=self.CLIENT_REF_PREFIX)

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            settings_obj = _get_singleton_client_account_settings()
            form_data = self._base_form_data()
            form_data['account_no'] = self._build_preview_account_no()
            _apply_client_account_defaults_from_settings(form_data, settings_obj)
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                    'currency_options': _active_currency_options(),
                    'settings_data': _client_account_settings_template_dict(settings_obj),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        form_data = self._collect_form_data(request)
        form_errors = {}
        try:
            settings_obj = _get_singleton_client_account_settings()
            if form_data['client_type'] not in {
                TenantClientAccount.ClientType.INDIVIDUAL,
                TenantClientAccount.ClientType.BUSINESS,
            }:
                form_errors['client_type'] = 'Invalid client type selected.'
            if form_data['status'] not in {
                TenantClientAccount.Status.ACTIVE,
                TenantClientAccount.Status.INACTIVE,
            }:
                form_errors['status'] = 'Invalid status selected.'
            if not form_data['name_english']:
                form_errors['name_english'] = 'Name (English) is required.'
            if not form_data['display_name']:
                form_errors['display_name'] = 'Display Name is required.'
            if not form_data['preferred_currency']:
                form_errors['preferred_currency'] = 'Preferred Currency is required.'
            if not form_data['billing_street_1']:
                form_errors['billing_street_1'] = 'Billing Street 1 is required.'
            if not form_data['billing_city']:
                form_errors['billing_city'] = 'Billing City is required.'
            if not form_data['country']:
                form_errors['country'] = 'Country is required.'
            if not form_errors.get('client_type'):
                _validate_client_account_document_rules(form_data, settings_obj, form_errors)

            credit_limit_raw = form_data['credit_limit_amount'] or '0'
            payment_term_raw = form_data['payment_term_days'] or '0'
            try:
                credit_limit_amount = Decimal(credit_limit_raw)
                if credit_limit_amount < 0:
                    raise ValueError
            except Exception:
                form_errors['credit_limit_amount'] = 'Credit Limit Amount must be 0 or greater.'
                credit_limit_amount = Decimal('0')
            try:
                payment_term_days = int(payment_term_raw)
                if payment_term_days < 0:
                    raise ValueError
            except Exception:
                form_errors['payment_term_days'] = 'Payment Term (Days) must be 0 or greater.'
                payment_term_days = 0

            if form_errors:
                form_data['account_no'] = self._build_preview_account_no()
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'currency_options': _active_currency_options(),
                        'settings_data': _client_account_settings_template_dict(settings_obj),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            account_no, account_sequence = _next_auto_number_for_form(
                form_code=self.CLIENT_FORM_CODE,
                form_label=self.CLIENT_FORM_LABEL,
                prefix=self.CLIENT_REF_PREFIX,
            )
            try:
                TenantClientAccount.objects.create(
                    account_no=account_no,
                    account_sequence=account_sequence,
                    client_type=form_data['client_type'],
                    status=form_data['status'],
                    name_arabic=form_data['name_arabic'],
                    name_english=form_data['name_english'],
                    display_name=form_data['display_name'],
                    preferred_currency=form_data['preferred_currency'],
                    billing_street_1=form_data['billing_street_1'],
                    billing_street_2=form_data['billing_street_2'],
                    billing_city=form_data['billing_city'],
                    billing_region=form_data['billing_region'],
                    postal_code=form_data['postal_code'],
                    country=form_data['country'],
                    credit_limit_amount=credit_limit_amount,
                    limit_currency_code=form_data['limit_currency_code'] or 'SAR',
                    payment_term_days=payment_term_days,
                    national_id=form_data['national_id'],
                    commercial_registration_no=form_data['commercial_registration_no'],
                    tax_registration_no=form_data['tax_registration_no'],
                    created_by_label=(context.get('display_name') or '').strip(),
                )
            except ValidationError as exc:
                _merge_validation_error_into_form_errors(exc, form_errors)
                form_data['account_no'] = self._build_preview_account_no()
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'currency_options': _active_currency_options(),
                        'settings_data': _client_account_settings_template_dict(settings_obj),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)
            messages.success(
                request,
                f'Client account {account_no} created successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountEditView(TenantClientAccountCreateView):
    """Edit an existing client account using the same form as create."""

    def _form_data_from_account(self, account):
        return {
            'account_no': account.account_no,
            'created_at': timezone.localtime(account.created_at).strftime('%b %d, %Y, %I:%M %p'),
            'client_type': account.client_type,
            'status': account.status,
            'name_arabic': account.name_arabic or '',
            'name_english': account.name_english or '',
            'display_name': account.display_name or '',
            'preferred_currency': account.preferred_currency or '',
            'billing_street_1': account.billing_street_1 or '',
            'billing_street_2': account.billing_street_2 or '',
            'billing_city': account.billing_city or '',
            'billing_region': account.billing_region or '',
            'postal_code': account.postal_code or '',
            'country': account.country or '',
            'credit_limit_amount': str(account.credit_limit_amount),
            'limit_currency_code': account.limit_currency_code or 'SAR',
            'payment_term_days': str(account.payment_term_days),
            'national_id': account.national_id or '',
            'commercial_registration_no': account.commercial_registration_no or '',
            'tax_registration_no': account.tax_registration_no or '',
        }

    def get(self, request, account_no):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            account = TenantClientAccount.objects.filter(account_no=(account_no or '').strip()).first()
            if account is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            settings_obj = _get_singleton_client_account_settings()
            form_data = self._form_data_from_account(account)
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': True,
                    'editing_account_no': account.account_no,
                    'currency_options': _active_currency_options(),
                    'settings_data': _client_account_settings_template_dict(settings_obj),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, account_no):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            account = TenantClientAccount.objects.filter(account_no=(account_no or '').strip()).first()
            if account is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            form_data = self._collect_form_data(request)
            form_data['account_no'] = account.account_no
            form_errors = {}
            settings_obj = _get_singleton_client_account_settings()
            if form_data['client_type'] not in {
                TenantClientAccount.ClientType.INDIVIDUAL,
                TenantClientAccount.ClientType.BUSINESS,
            }:
                form_errors['client_type'] = 'Invalid client type selected.'
            if form_data['status'] not in {
                TenantClientAccount.Status.ACTIVE,
                TenantClientAccount.Status.INACTIVE,
            }:
                form_errors['status'] = 'Invalid status selected.'
            if not form_data['name_english']:
                form_errors['name_english'] = 'Name (English) is required.'
            if not form_data['display_name']:
                form_errors['display_name'] = 'Display Name is required.'
            if not form_data['preferred_currency']:
                form_errors['preferred_currency'] = 'Preferred Currency is required.'
            if not form_data['billing_street_1']:
                form_errors['billing_street_1'] = 'Billing Street 1 is required.'
            if not form_data['billing_city']:
                form_errors['billing_city'] = 'Billing City is required.'
            if not form_data['country']:
                form_errors['country'] = 'Country is required.'
            if not form_errors.get('client_type'):
                _validate_client_account_document_rules(form_data, settings_obj, form_errors)

            credit_limit_raw = form_data['credit_limit_amount'] or '0'
            payment_term_raw = form_data['payment_term_days'] or '0'
            try:
                credit_limit_amount = Decimal(credit_limit_raw)
                if credit_limit_amount < 0:
                    raise ValueError
            except Exception:
                form_errors['credit_limit_amount'] = 'Credit Limit Amount must be 0 or greater.'
                credit_limit_amount = Decimal('0')
            try:
                payment_term_days = int(payment_term_raw)
                if payment_term_days < 0:
                    raise ValueError
            except Exception:
                form_errors['payment_term_days'] = 'Payment Term (Days) must be 0 or greater.'
                payment_term_days = 0

            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': True,
                        'editing_account_no': account.account_no,
                        'currency_options': _active_currency_options(),
                        'settings_data': _client_account_settings_template_dict(settings_obj),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            account.client_type = form_data['client_type']
            account.status = form_data['status']
            account.name_arabic = form_data['name_arabic']
            account.name_english = form_data['name_english']
            account.display_name = form_data['display_name']
            account.preferred_currency = form_data['preferred_currency']
            account.billing_street_1 = form_data['billing_street_1']
            account.billing_street_2 = form_data['billing_street_2']
            account.billing_city = form_data['billing_city']
            account.billing_region = form_data['billing_region']
            account.postal_code = form_data['postal_code']
            account.country = form_data['country']
            account.credit_limit_amount = credit_limit_amount
            account.limit_currency_code = form_data['limit_currency_code'] or 'SAR'
            account.payment_term_days = payment_term_days
            account.national_id = form_data['national_id']
            account.commercial_registration_no = form_data['commercial_registration_no']
            account.tax_registration_no = form_data['tax_registration_no']
            try:
                account.save()
            except ValidationError as exc:
                _merge_validation_error_into_form_errors(exc, form_errors)
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': True,
                        'editing_account_no': account.account_no,
                        'currency_options': _active_currency_options(),
                        'settings_data': _client_account_settings_template_dict(settings_obj),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)
            messages.success(
                request,
                f'Client account {account.account_no} updated successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountToggleStatusView(View):
    def post(self, request, account_no):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            account = TenantClientAccount.objects.filter(account_no=(account_no or '').strip()).first()
            if account is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            account.status = (
                TenantClientAccount.Status.INACTIVE
                if account.status == TenantClientAccount.Status.ACTIVE
                else TenantClientAccount.Status.ACTIVE
            )
            account.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'Status changed to {account.status}.', extra_tags='tenant')
            if (request.POST.get('return_to') or '').strip() == 'details':
                q = {'id': account.account_no}
                tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
                if tid:
                    q['tid'] = tid
                return redirect(
                    f"{reverse('iroad_tenants:tenant_client_details')}?{urlencode(q)}"
                )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountDeleteView(View):
    def post(self, request, account_no):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            account = TenantClientAccount.objects.filter(account_no=(account_no or '').strip()).first()
            if account is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            label = account.account_no
            try:
                account.delete()
            except ProtectedError:
                messages.error(
                    request,
                    'This client cannot be deleted while addresses or other records still reference it.',
                    extra_tags='tenant',
                )
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            messages.success(request, f'Client account {label} deleted.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientSalesReportView(View):
    """Per-account sales report placeholder until reporting is implemented."""

    template_name = 'iroad_tenants/Clients_Management/Client-sales-report.html'

    def get(self, request, account_no):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            account = TenantClientAccount.objects.filter(account_no=(account_no or '').strip()).first()
            if account is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            context.update(
                {
                    'client_account': account,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentsView(View):
    """Create client attachment (POST) bound to ``TenantClientAccount``."""

    template_name = 'iroad_tenants/Clients_Management/Client-attachments.html'

    def _account_queryset(self):
        return TenantClientAccount.objects.all().order_by('account_no')

    def _default_form_data(self):
        return {
            'attachment_date': timezone.localdate().isoformat(),
            'is_expiry_applicable': 'false',
            'expiry_date': '',
            'file_notes': '',
            'client_account': '',
        }

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            form_data = self._default_form_data()
            pre = (request.GET.get('account') or request.GET.get('client') or '').strip()
            try:
                match = resolve(request.path_info)
            except Exception:
                match = None
            # Bare ``/attachments/`` (e.g. old bookmarks): send users to the list; keep ``/create/`` and ``?account=`` for the form.
            if (
                match
                and match.url_name == 'tenant_client_attachments'
                and not pre
            ):
                list_url = reverse('iroad_tenants:tenant_client_attachments_list')
                tid = (request.GET.get('tid') or '').strip()
                if tid:
                    list_url = f'{list_url}?{urlencode({"tid": tid})}'
                return redirect(list_url)
            if pre:
                form_data['client_account'] = pre
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'attachment_form_action': reverse(
                        'iroad_tenants:tenant_client_attachments_create',
                    ),
                    'is_edit_mode': False,
                    'editing_attachment': None,
                    'portal_tid': (request.GET.get('tid') or '').strip(),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        form_data = self._default_form_data()
        form_data['client_account'] = (request.POST.get('client_account') or '').strip()
        form_data['attachment_date'] = (request.POST.get('attachment_date') or '').strip()
        form_data['is_expiry_applicable'] = (request.POST.get('is_expiry_applicable') or '').strip()
        form_data['expiry_date'] = (request.POST.get('expiry_date') or '').strip()
        form_data['file_notes'] = (request.POST.get('file_notes') or '').strip()

        form_errors = {}
        account = None
        if not form_data['client_account']:
            form_errors['client_account'] = 'Select a client account.'
        else:
            account = TenantClientAccount.objects.filter(
                account_no=form_data['client_account'],
            ).first()
            if account is None:
                form_errors['client_account'] = 'Client account not found.'

        ad = parse_date(form_data['attachment_date']) if form_data['attachment_date'] else None
        if not ad:
            form_errors['attachment_date'] = 'Enter a valid attachment date.'

        is_expiry = form_data['is_expiry_applicable'] == 'true'
        ex = None
        if is_expiry:
            ex = parse_date(form_data['expiry_date']) if form_data['expiry_date'] else None
            if not ex:
                form_errors['expiry_date'] = 'Expiry date is required when expiry applies.'
        else:
            form_data['expiry_date'] = ''

        upload = request.FILES.get('attachment_file')
        upload_err = _validate_client_attachment_upload(upload)
        if upload_err:
            form_errors['attachment_file'] = upload_err

        if form_errors:
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': form_errors,
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'attachment_form_action': reverse(
                        'iroad_tenants:tenant_client_attachments_create',
                    ),
                    'is_edit_mode': False,
                    'editing_attachment': None,
                    'portal_tid': (request.POST.get('tid') or request.GET.get('tid') or '').strip(),
                }
            )
            messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
            try:
                return render(request, self.template_name, context)
            finally:
                connection.set_schema_to_public()

        try:
            with db_transaction.atomic():
                attachment_no, attachment_sequence = _next_auto_number_for_form(
                    form_code=CLIENT_ATTACHMENT_AUTO_FORM_CODE,
                    form_label=CLIENT_ATTACHMENT_AUTO_FORM_LABEL,
                    prefix=CLIENT_ATTACHMENT_REF_PREFIX,
                )
                TenantClientAttachment.objects.create(
                    attachment_no=attachment_no,
                    attachment_sequence=attachment_sequence,
                    attachment_date=ad,
                    is_expiry_applicable=is_expiry,
                    expiry_date=ex,
                    attachment_file=upload,
                    file_notes=form_data['file_notes'],
                    created_by_label=(context.get('display_name') or '').strip(),
                    client_account=account,
                )
        except Exception:
            logger.exception('Tenant client attachment create failed')
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {'attachment_file': 'Could not save the file. Try again.'},
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'attachment_form_action': reverse(
                        'iroad_tenants:tenant_client_attachments_create',
                    ),
                    'is_edit_mode': False,
                    'editing_attachment': None,
                    'portal_tid': (request.POST.get('tid') or request.GET.get('tid') or '').strip(),
                }
            )
            messages.error(request, 'Upload failed.', extra_tags='tenant')
            try:
                return render(request, self.template_name, context)
            finally:
                connection.set_schema_to_public()

        messages.success(
            request,
            f'Attachment {attachment_no} uploaded for {account.account_no}.',
            extra_tags='tenant',
        )
        connection.set_schema_to_public()
        list_url = reverse('iroad_tenants:tenant_client_attachments_list')
        tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
        if tid:
            list_url = f'{list_url}?{urlencode({"tid": tid})}'
        return redirect(list_url)


def _redirect_client_attachment_list(request):
    url = reverse('iroad_tenants:tenant_client_attachments_list')
    tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
    if tid:
        url = f'{url}?{urlencode({"tid": tid})}'
    return redirect(url)


def _tenant_client_attachments_base_path():
    """Path prefix for attachment URLs under ``tenant_client_attachments``."""
    p = reverse('iroad_tenants:tenant_client_attachments')
    return p if p.endswith('/') else f'{p}/'


def _tenant_client_attachment_detail_path(attachment_id):
    return f'{_tenant_client_attachments_base_path()}{attachment_id}/detail/'


def _redirect_client_contact_list(request):
    url = reverse('iroad_tenants:tenant_client_contacts_list')
    tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
    if tid:
        url = f'{url}?{urlencode({"tid": tid})}'
    return redirect(url)


def _tenant_client_contacts_base_path():
    """Path prefix for contact CRUD URLs, ending with ``/`` (from ``tenant_client_contacts``)."""
    p = reverse('iroad_tenants:tenant_client_contacts')
    return p if p.endswith('/') else f'{p}/'


def _tenant_client_contact_edit_path(contact_id):
    return f'{_tenant_client_contacts_base_path()}{contact_id}/edit/'


def _tenant_client_contact_delete_path(contact_id):
    return f'{_tenant_client_contacts_base_path()}{contact_id}/delete/'


def _tenant_client_contact_detail_path(contact_id):
    return f'{_tenant_client_contacts_base_path()}{contact_id}/detail/'


class TenantClientAttachmentEditView(View):
    """Edit metadata / optionally replace file for an existing tenant client attachment."""

    template_name = 'iroad_tenants/Clients_Management/Client-attachments.html'

    def _account_queryset(self):
        return TenantClientAccount.objects.all().order_by('account_no')

    def _default_form_data(self):
        return {
            'attachment_date': timezone.localdate().isoformat(),
            'is_expiry_applicable': 'false',
            'expiry_date': '',
            'file_notes': '',
            'client_account': '',
        }

    def get(self, request, attachment_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            att = (
                TenantClientAttachment.objects.select_related('client_account')
                .filter(pk=attachment_id)
                .first()
            )
            if att is None:
                messages.error(request, 'Attachment not found.', extra_tags='tenant')
                return _redirect_client_attachment_list(request)
            form_data = self._default_form_data()
            form_data['client_account'] = att.client_account.account_no
            form_data['attachment_date'] = att.attachment_date.isoformat()
            form_data['is_expiry_applicable'] = 'true' if att.is_expiry_applicable else 'false'
            form_data['expiry_date'] = att.expiry_date.isoformat() if att.expiry_date else ''
            form_data['file_notes'] = att.file_notes or ''
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'attachment_form_action': reverse(
                        'iroad_tenants:tenant_client_attachment_edit',
                        kwargs={'attachment_id': att.attachment_id},
                    ),
                    'is_edit_mode': True,
                    'editing_attachment': att,
                    'portal_tid': (request.GET.get('tid') or '').strip(),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, attachment_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            att = (
                TenantClientAttachment.objects.select_related('client_account')
                .filter(pk=attachment_id)
                .first()
            )
            if att is None:
                messages.error(request, 'Attachment not found.', extra_tags='tenant')
                return _redirect_client_attachment_list(request)

            form_data = self._default_form_data()
            form_data['client_account'] = (request.POST.get('client_account') or '').strip()
            form_data['attachment_date'] = (request.POST.get('attachment_date') or '').strip()
            form_data['is_expiry_applicable'] = (
                request.POST.get('is_expiry_applicable') or ''
            ).strip()
            form_data['expiry_date'] = (request.POST.get('expiry_date') or '').strip()
            form_data['file_notes'] = (request.POST.get('file_notes') or '').strip()

            form_errors = {}
            account = None
            if not form_data['client_account']:
                form_errors['client_account'] = 'Select a client account.'
            else:
                account = TenantClientAccount.objects.filter(
                    account_no=form_data['client_account'],
                ).first()
                if account is None:
                    form_errors['client_account'] = 'Client account not found.'

            ad = parse_date(form_data['attachment_date']) if form_data['attachment_date'] else None
            if not ad:
                form_errors['attachment_date'] = 'Enter a valid attachment date.'

            is_expiry = form_data['is_expiry_applicable'] == 'true'
            ex = None
            if is_expiry:
                ex = parse_date(form_data['expiry_date']) if form_data['expiry_date'] else None
                if not ex:
                    form_errors['expiry_date'] = 'Expiry date is required when expiry applies.'
            else:
                form_data['expiry_date'] = ''

            upload = request.FILES.get('attachment_file')
            if upload:
                upload_err = _validate_client_attachment_upload(upload)
                if upload_err:
                    form_errors['attachment_file'] = upload_err

            _edit_ctx = {
                'form_data': form_data,
                'client_account_options': list(self._account_queryset()),
                'tenant_schema_name': tenant_registry.schema_name,
                'attachment_form_action': reverse(
                    'iroad_tenants:tenant_client_attachment_edit',
                    kwargs={'attachment_id': att.attachment_id},
                ),
                'is_edit_mode': True,
                'editing_attachment': att,
                'portal_tid': (request.POST.get('tid') or request.GET.get('tid') or '').strip(),
            }

            if form_errors:
                context.update({**_edit_ctx, 'form_errors': form_errors})
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    att.client_account = account
                    att.attachment_date = ad
                    att.is_expiry_applicable = is_expiry
                    att.expiry_date = ex
                    att.file_notes = form_data['file_notes']
                    if upload:
                        if att.attachment_file:
                            att.attachment_file.delete(save=False)
                        att.attachment_file = upload
                    att.save()
            except Exception:
                logger.exception('Tenant client attachment update failed')
                context.update(
                    {
                        **_edit_ctx,
                        'form_errors': {
                            'attachment_file': 'Could not save the file. Try again.',
                        },
                    }
                )
                messages.error(request, 'Update failed.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Attachment {att.attachment_no} updated.',
                extra_tags='tenant',
            )
            return _redirect_client_attachment_list(request)
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentDeleteView(View):
    def post(self, request, attachment_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            att = TenantClientAttachment.objects.filter(pk=attachment_id).first()
            if att is None:
                messages.error(request, 'Attachment not found.', extra_tags='tenant')
                return _redirect_client_attachment_list(request)
            label = att.attachment_no
            if att.attachment_file:
                att.attachment_file.delete(save=False)
            att.delete()
            messages.success(request, f'Attachment {label} deleted.', extra_tags='tenant')
            return _redirect_client_attachment_list(request)
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentDetailView(View):
    """Read-only full-page attachment detail."""

    template_name = 'iroad_tenants/Clients_Management/Client-attachment-detail.html'

    def get(self, request, attachment_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            attachment = (
                TenantClientAttachment.objects.select_related('client_account')
                .filter(pk=attachment_id)
                .first()
            )
            if attachment is None:
                messages.error(request, 'Attachment not found.', extra_tags='tenant')
                return _redirect_client_attachment_list(request)
            tid = (request.GET.get('tid') or '').strip()
            list_url = reverse('iroad_tenants:tenant_client_attachments_list')
            if tid:
                list_url = f'{list_url}?{urlencode({"tid": tid})}'
            try:
                edit_url = reverse(
                    'iroad_tenants:tenant_client_attachment_edit',
                    kwargs={'attachment_id': attachment.attachment_id},
                )
            except NoReverseMatch:
                edit_url = f'{_tenant_client_attachments_base_path()}{attachment.attachment_id}/edit/'
            if tid:
                edit_url = f'{edit_url}?{urlencode({"tid": tid})}'
            file_url = ''
            try:
                if attachment.attachment_file:
                    file_url = attachment.attachment_file.url
            except Exception:
                file_url = ''
            context.update(
                {
                    'attachment': attachment,
                    'tenant_schema_name': tenant_registry.schema_name,
                    'back_to_list_url': list_url,
                    'edit_attachment_url': edit_url,
                    'attachment_file_url': file_url,
                    'portal_tid': tid,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentsListView(View):
    """List all tenant client attachments with summary stats."""

    template_name = 'iroad_tenants/Clients_Management/Client-attachments-list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            att = TenantClientAttachment
            qs = (
                TenantClientAttachment.objects.select_related('client_account')
                .order_by('-created_at')
                .all()
            )
            rows = list(qs)
            tid = (request.GET.get('tid') or '').strip()
            base = _tenant_client_attachments_base_path()
            for row in rows:
                try:
                    detail_u = reverse(
                        'iroad_tenants:tenant_client_attachment_detail',
                        kwargs={'attachment_id': row.attachment_id},
                    )
                except NoReverseMatch:
                    detail_u = _tenant_client_attachment_detail_path(row.attachment_id)
                if tid:
                    detail_u = f'{detail_u}?{urlencode({"tid": tid})}'
                row.list_detail_url = detail_u
            attachment_stats = {
                'total': len(rows),
                'valid': sum(1 for r in rows if r.computed_status == att.Status.VALID),
                'does_not_expire': sum(
                    1 for r in rows if r.computed_status == att.Status.DOES_NOT_EXPIRE
                ),
                'expired': sum(1 for r in rows if r.computed_status == att.Status.EXPIRED),
            }
            context.update(
                {
                    'client_attachments': rows,
                    'client_attachments_count': len(rows),
                    'attachment_stats': attachment_stats,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContactsView(View):
    """Create client contact (GET form / POST save), optional ``?account=`` pre-select."""

    template_name = 'iroad_tenants/Clients_Management/Client-contacts.html'

    def _account_queryset(self):
        return TenantClientAccount.objects.all().order_by('account_no')

    def _default_form_data(self):
        return {
            'client_account': '',
            'name': '',
            'email': '',
            'mobile_number': '',
            'telephone_number': '',
            'extension': '',
            'position': '',
            'is_primary': '',
        }

    def _tid_for_redirect(self, request):
        return (request.GET.get('tid') or request.POST.get('tid') or '').strip()

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            form_data = self._default_form_data()
            pre = (request.GET.get('account') or request.GET.get('client') or '').strip()
            try:
                match = resolve(request.path_info)
            except Exception:
                match = None
            # Bare ``/contacts/`` (e.g. old bookmarks): send users to the list; keep ``/create/`` and ``?account=`` for the form.
            if (
                match
                and match.url_name == 'tenant_client_contacts'
                and not pre
            ):
                list_url = reverse('iroad_tenants:tenant_client_contacts_list')
                tid = (request.GET.get('tid') or '').strip()
                if tid:
                    list_url = f'{list_url}?{urlencode({"tid": tid})}'
                return redirect(list_url)
            if pre:
                form_data['client_account'] = pre
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'portal_tid': self._tid_for_redirect(request),
                    'contact_form_action': reverse(
                        'iroad_tenants:tenant_client_contacts_create',
                    ),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        form_data = self._default_form_data()
        form_data['client_account'] = (request.POST.get('client_account') or '').strip()
        form_data['name'] = (request.POST.get('name') or '').strip()
        form_data['email'] = (request.POST.get('email') or '').strip()
        form_data['mobile_number'] = (request.POST.get('mobile_number') or '').strip()
        form_data['telephone_number'] = (request.POST.get('telephone_number') or '').strip()
        form_data['extension'] = (request.POST.get('extension') or '').strip()
        form_data['position'] = (request.POST.get('position') or '').strip()
        form_data['is_primary'] = (
            'true' if (request.POST.get('is_primary') in ('true', 'on', '1')) else ''
        )

        form_errors = {}
        account = None
        if not form_data['client_account']:
            form_errors['client_account'] = 'Select a client account.'
        else:
            account = TenantClientAccount.objects.filter(
                account_no=form_data['client_account'],
            ).first()
            if account is None:
                form_errors['client_account'] = 'Client account not found.'

        if not form_data['name']:
            form_errors['name'] = 'Enter the contact name.'

        if form_data['email']:
            try:
                validate_email(form_data['email'])
            except ValidationError:
                form_errors['email'] = 'Enter a valid email address.'

        if form_errors:
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': form_errors,
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'portal_tid': self._tid_for_redirect(request),
                    'contact_form_action': reverse(
                        'iroad_tenants:tenant_client_contacts_create',
                    ),
                }
            )
            messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
            try:
                return render(request, self.template_name, context)
            finally:
                connection.set_schema_to_public()

        is_primary = bool(form_data['is_primary'])
        try:
            with db_transaction.atomic():
                if is_primary:
                    TenantClientContact.objects.filter(
                        client_account=account,
                        is_primary=True,
                    ).update(is_primary=False)
                TenantClientContact.objects.create(
                    name=form_data['name'],
                    email=form_data['email'],
                    mobile_number=form_data['mobile_number'],
                    telephone_number=form_data['telephone_number'],
                    extension=form_data['extension'],
                    position=form_data['position'],
                    is_primary=is_primary,
                    created_by_label=(context.get('display_name') or '').strip(),
                    client_account=account,
                )
        except Exception:
            logger.exception('Tenant client contact create failed')
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {'__all__': 'Could not save the contact. Try again.'},
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'portal_tid': self._tid_for_redirect(request),
                    'contact_form_action': reverse(
                        'iroad_tenants:tenant_client_contacts_create',
                    ),
                }
            )
            messages.error(request, 'Save failed.', extra_tags='tenant')
            try:
                return render(request, self.template_name, context)
            finally:
                connection.set_schema_to_public()

        messages.success(
            request,
            f'Contact {form_data["name"]} added for {account.account_no}.',
            extra_tags='tenant',
        )
        connection.set_schema_to_public()
        list_url = reverse('iroad_tenants:tenant_client_contacts_list')
        tid = self._tid_for_redirect(request)
        if tid:
            list_url = f'{list_url}?{urlencode({"tid": tid})}'
        return redirect(list_url)


class TenantClientContactEditView(View):
    """Edit an existing tenant client contact."""

    template_name = 'iroad_tenants/Clients_Management/Client-contacts.html'

    def _account_queryset(self):
        return TenantClientAccount.objects.all().order_by('account_no')

    def _default_form_data(self):
        return {
            'client_account': '',
            'name': '',
            'email': '',
            'mobile_number': '',
            'telephone_number': '',
            'extension': '',
            'position': '',
            'is_primary': '',
        }

    def _tid(self, request):
        return (request.GET.get('tid') or request.POST.get('tid') or '').strip()

    def get(self, request, contact_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contact = (
                TenantClientContact.objects.select_related('client_account')
                .filter(pk=contact_id)
                .first()
            )
            if contact is None:
                messages.error(request, 'Contact not found.', extra_tags='tenant')
                return _redirect_client_contact_list(request)
            form_data = self._default_form_data()
            form_data['client_account'] = contact.client_account.account_no
            form_data['name'] = contact.name
            form_data['email'] = contact.email or ''
            form_data['mobile_number'] = contact.mobile_number or ''
            form_data['telephone_number'] = contact.telephone_number or ''
            form_data['extension'] = contact.extension or ''
            form_data['position'] = contact.position or ''
            form_data['is_primary'] = 'true' if contact.is_primary else ''
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': list(self._account_queryset()),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'portal_tid': self._tid(request),
                    'contact_form_action': _tenant_client_contact_edit_path(
                        contact.contact_id,
                    ),
                    'is_edit_mode': True,
                    'editing_contact': contact,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, contact_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contact = (
                TenantClientContact.objects.select_related('client_account')
                .filter(pk=contact_id)
                .first()
            )
            if contact is None:
                messages.error(request, 'Contact not found.', extra_tags='tenant')
                return _redirect_client_contact_list(request)

            form_data = self._default_form_data()
            form_data['client_account'] = (request.POST.get('client_account') or '').strip()
            form_data['name'] = (request.POST.get('name') or '').strip()
            form_data['email'] = (request.POST.get('email') or '').strip()
            form_data['mobile_number'] = (request.POST.get('mobile_number') or '').strip()
            form_data['telephone_number'] = (request.POST.get('telephone_number') or '').strip()
            form_data['extension'] = (request.POST.get('extension') or '').strip()
            form_data['position'] = (request.POST.get('position') or '').strip()
            form_data['is_primary'] = (
                'true' if (request.POST.get('is_primary') in ('true', 'on', '1')) else ''
            )

            form_errors = {}
            account = None
            if not form_data['client_account']:
                form_errors['client_account'] = 'Select a client account.'
            else:
                account = TenantClientAccount.objects.filter(
                    account_no=form_data['client_account'],
                ).first()
                if account is None:
                    form_errors['client_account'] = 'Client account not found.'

            if not form_data['name']:
                form_errors['name'] = 'Enter the contact name.'

            if form_data['email']:
                try:
                    validate_email(form_data['email'])
                except ValidationError:
                    form_errors['email'] = 'Enter a valid email address.'

            _edit_ctx = {
                'form_data': form_data,
                'client_account_options': list(self._account_queryset()),
                'tenant_schema_name': tenant_registry.schema_name,
                'contact_form_action': _tenant_client_contact_edit_path(
                    contact.contact_id,
                ),
                'is_edit_mode': True,
                'editing_contact': contact,
                'portal_tid': self._tid(request),
            }

            if form_errors:
                context.update({**_edit_ctx, 'form_errors': form_errors})
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            is_primary = bool(form_data['is_primary'])
            try:
                with db_transaction.atomic():
                    if is_primary:
                        TenantClientContact.objects.filter(
                            client_account=account,
                            is_primary=True,
                        ).exclude(pk=contact.contact_id).update(is_primary=False)
                    contact.client_account = account
                    contact.name = form_data['name']
                    contact.email = form_data['email']
                    contact.mobile_number = form_data['mobile_number']
                    contact.telephone_number = form_data['telephone_number']
                    contact.extension = form_data['extension']
                    contact.position = form_data['position']
                    contact.is_primary = is_primary
                    contact.save()
            except Exception:
                logger.exception('Tenant client contact update failed')
                context.update(
                    {
                        **_edit_ctx,
                        'form_errors': {'__all__': 'Could not save the contact. Try again.'},
                    }
                )
                messages.error(request, 'Update failed.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Contact {form_data["name"]} updated.',
                extra_tags='tenant',
            )
            return _redirect_client_contact_list(request)
        finally:
            connection.set_schema_to_public()


class TenantClientContactDeleteView(View):
    def post(self, request, contact_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contact = TenantClientContact.objects.filter(pk=contact_id).first()
            if contact is None:
                messages.error(request, 'Contact not found.', extra_tags='tenant')
                return _redirect_client_contact_list(request)
            label = contact.name
            contact.delete()
            messages.success(request, f'Contact {label} deleted.', extra_tags='tenant')
            return _redirect_client_contact_list(request)
        finally:
            connection.set_schema_to_public()


class TenantClientContactDetailView(View):
    """Read-only full-page contact detail (same UX pattern as Users Administration view mode)."""

    template_name = 'iroad_tenants/Clients_Management/Client-contact-detail.html'

    def get(self, request, contact_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contact = (
                TenantClientContact.objects.select_related('client_account')
                .filter(pk=contact_id)
                .first()
            )
            if contact is None:
                messages.error(request, 'Contact not found.', extra_tags='tenant')
                return _redirect_client_contact_list(request)
            tid = (request.GET.get('tid') or '').strip()
            list_url = reverse('iroad_tenants:tenant_client_contacts_list')
            if tid:
                list_url = f'{list_url}?{urlencode({"tid": tid})}'
            try:
                edit_url = reverse(
                    'iroad_tenants:tenant_client_contact_edit',
                    kwargs={'contact_id': contact.contact_id},
                )
            except NoReverseMatch:
                edit_url = _tenant_client_contact_edit_path(contact.contact_id)
            if tid:
                edit_url = f'{edit_url}?{urlencode({"tid": tid})}'
            context.update(
                {
                    'contact': contact,
                    'tenant_schema_name': tenant_registry.schema_name,
                    'back_to_list_url': list_url,
                    'edit_contact_url': edit_url,
                    'portal_tid': tid,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContactsListView(View):
    template_name = 'iroad_tenants/Clients_Management/Client-contacts-list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contacts = list(
                TenantClientContact.objects.select_related('client_account').order_by(
                    '-created_at'
                )
            )
            contact_stats = {
                'total': len(contacts),
                'primary': sum(1 for c in contacts if c.is_primary),
                'secondary': sum(1 for c in contacts if not c.is_primary),
                'client_accounts': TenantClientAccount.objects.count(),
            }
            tid = (request.GET.get('tid') or '').strip()
            base = _tenant_client_contacts_base_path()
            for contact in contacts:
                try:
                    edit_u = reverse(
                        'iroad_tenants:tenant_client_contact_edit',
                        kwargs={'contact_id': contact.contact_id},
                    )
                except NoReverseMatch:
                    edit_u = f'{base}{contact.contact_id}/edit/'
                if tid:
                    edit_u = f'{edit_u}?{urlencode({"tid": tid})}'
                contact.list_edit_url = edit_u
                try:
                    del_u = reverse(
                        'iroad_tenants:tenant_client_contact_delete',
                        kwargs={'contact_id': contact.contact_id},
                    )
                except NoReverseMatch:
                    del_u = f'{base}{contact.contact_id}/delete/'
                contact.list_delete_action_url = del_u
                try:
                    detail_u = reverse(
                        'iroad_tenants:tenant_client_contact_detail',
                        kwargs={'contact_id': contact.contact_id},
                    )
                except NoReverseMatch:
                    detail_u = _tenant_client_contact_detail_path(contact.contact_id)
                if tid:
                    detail_u = f'{detail_u}?{urlencode({"tid": tid})}'
                contact.list_detail_url = detail_u
            context.update(
                {
                    'client_contacts': contacts,
                    'client_contacts_count': len(contacts),
                    'contact_stats': contact_stats,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContractView(View):
    template_name = 'iroad_tenants/Clients_Management/Client-contract.html'

    def _account_queryset(self):
        return TenantClientAccount.objects.all().order_by('account_no')

    def _default_form_data(self):
        return {
            'contract_no': '',
            'client_account': '',
            'start_date': '',
            'end_date': '',
            'notes': '',
        }

    def _build_create_context(self, request, tenant_registry, form_data, form_errors):
        form_data = dict(form_data)
        if not form_data.get('contract_no'):
            form_data['contract_no'] = _preview_next_contract_code()
        settings_row = _get_singleton_client_contract_settings()
        return {
            'form_data': form_data,
            'form_errors': form_errors,
            'client_account_options': list(self._account_queryset()),
            'tenant_schema_name': tenant_registry.schema_name,
            'portal_tid': (request.GET.get('tid') or request.POST.get('tid') or '').strip(),
            'contract_form_action': reverse(
                'iroad_tenants:tenant_client_contract_create',
            ),
            'contract_settings': _client_contract_settings_template_dict(settings_row),
        }

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            form_data = self._default_form_data()
            pre = (request.GET.get('account') or request.GET.get('client') or '').strip()
            try:
                match = resolve(request.path_info)
            except Exception:
                match = None
            # Bare ``/contracts/`` (e.g. old bookmarks): send users to the list; keep ``/create/`` and ``?account=`` for the form.
            if (
                match
                and match.url_name == 'tenant_client_contract'
                and not pre
            ):
                list_url = reverse('iroad_tenants:tenant_client_contract_list')
                tid = (request.GET.get('tid') or '').strip()
                if tid:
                    list_url = f'{list_url}?{urlencode({"tid": tid})}'
                return redirect(list_url)
            if pre:
                form_data['client_account'] = pre
            context.update(self._build_create_context(request, tenant_registry, form_data, {}))
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            form_data = self._default_form_data()
            form_data['client_account'] = (request.POST.get('client_account') or '').strip()
            form_data['start_date'] = (request.POST.get('start_date') or '').strip()
            form_data['end_date'] = (request.POST.get('end_date') or '').strip()
            form_data['notes'] = (request.POST.get('notes') or '').strip()

            form_errors = {}
            account = None
            if not form_data['client_account']:
                form_errors['client_account'] = 'Select a client account.'
            else:
                account = TenantClientAccount.objects.filter(
                    account_no=form_data['client_account'],
                ).first()
                if account is None:
                    form_errors['client_account'] = 'Client account not found.'
                elif hasattr(account, 'contract'):
                    form_errors['client_account'] = 'This client already has a contract.'

            start_date = parse_date(form_data['start_date']) if form_data['start_date'] else None
            end_date = parse_date(form_data['end_date']) if form_data['end_date'] else None
            if not start_date:
                form_errors['start_date'] = 'Enter a valid start date.'
            if not end_date:
                form_errors['end_date'] = 'Enter a valid end date.'
            if start_date and end_date and end_date < start_date:
                form_errors['end_date'] = 'End date must be on or after start date.'

            if start_date and end_date and end_date >= start_date:
                settings_row = _get_singleton_client_contract_settings()
                for key, msg in _validate_client_contract_period_against_settings(
                    start_date, end_date, settings_row
                ).items():
                    form_errors.setdefault(key, msg)

            upload = request.FILES.get('contract_attachment')
            upload_err = _validate_client_contract_upload(upload, allow_empty=False)
            if upload_err:
                form_errors['contract_attachment'] = upload_err

            if form_errors:
                context.update(
                    self._build_create_context(request, tenant_registry, form_data, form_errors)
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            with db_transaction.atomic():
                contract_no, contract_sequence = _next_auto_number_for_form(
                    form_code=CLIENT_CONTRACT_AUTO_FORM_CODE,
                    form_label=CLIENT_CONTRACT_AUTO_FORM_LABEL,
                    prefix=CLIENT_CONTRACT_REF_PREFIX,
                )
                TenantClientContract.objects.create(
                    contract_no=contract_no,
                    contract_sequence=contract_sequence,
                    start_date=start_date,
                    end_date=end_date,
                    status=_contract_status_for_dates(start_date, end_date),
                    notes=form_data['notes'],
                    contract_attachment=upload,
                    created_by_label=(context.get('display_name') or '').strip(),
                    client_account=account,
                )
            messages.success(
                request,
                f'Contract {contract_no} created for {account.account_no}.',
                extra_tags='tenant',
            )
            list_url = reverse('iroad_tenants:tenant_client_contract_list')
            tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
            if tid:
                list_url = f'{list_url}?{urlencode({"tid": tid})}'
            return redirect(list_url)
        except Exception:
            logger.exception('Tenant client contract create failed')
            context.update(
                self._build_create_context(
                    request,
                    tenant_registry,
                    form_data,
                    {'contract_attachment': 'Could not save the contract. Try again.'},
                )
            )
            messages.error(request, 'Contract save failed.', extra_tags='tenant')
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContractDetailView(View):
    """Read-only full-page client contract detail."""

    template_name = 'iroad_tenants/Clients_Management/Client-contract-detail.html'

    def get(self, request, contract_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contract = (
                TenantClientContract.objects.select_related('client_account')
                .filter(pk=contract_id)
                .first()
            )
            if contract is None:
                messages.error(request, 'Contract not found.', extra_tags='tenant')
                return _redirect_client_contract_list(request)
            tid = (request.GET.get('tid') or '').strip()
            list_url = reverse('iroad_tenants:tenant_client_contract_list')
            if tid:
                list_url = f'{list_url}?{urlencode({"tid": tid})}'
            try:
                edit_url = reverse(
                    'iroad_tenants:tenant_client_contract_edit',
                    kwargs={'contract_id': contract.contract_id},
                )
            except NoReverseMatch:
                edit_url = _tenant_client_contract_edit_path(contract.contract_id)
            if tid:
                edit_url = f'{edit_url}?{urlencode({"tid": tid})}'
            file_url = ''
            try:
                if contract.contract_attachment:
                    file_url = contract.contract_attachment.url
            except Exception:
                file_url = ''
            context.update(
                {
                    'contract': contract,
                    'tenant_schema_name': tenant_registry.schema_name,
                    'back_to_list_url': list_url,
                    'edit_contract_url': edit_url,
                    'contract_file_url': file_url,
                    'portal_tid': tid,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContractEditView(View):
    """Edit an existing tenant client contract (same form as create)."""

    template_name = 'iroad_tenants/Clients_Management/Client-contract.html'

    def _account_queryset(self):
        return TenantClientAccount.objects.all().order_by('account_no')

    def _edit_context(
        self,
        request,
        tenant_registry,
        contract,
        form_data,
        form_errors,
    ):
        tid = (request.GET.get('tid') or request.POST.get('tid') or '').strip()
        list_url = reverse('iroad_tenants:tenant_client_contract_list')
        if tid:
            list_url = f'{list_url}?{urlencode({"tid": tid})}'
        settings_row = _get_singleton_client_contract_settings()
        return {
            'form_data': form_data,
            'form_errors': form_errors,
            'client_account_options': list(self._account_queryset()),
            'tenant_schema_name': tenant_registry.schema_name,
            'portal_tid': tid,
            'back_to_list_url': list_url,
            'contract_form_action': reverse(
                'iroad_tenants:tenant_client_contract_edit',
                kwargs={'contract_id': contract.contract_id},
            ),
            'is_edit_mode': True,
            'editing_contract': contract,
            'contract_settings': _client_contract_settings_template_dict(settings_row),
        }

    def get(self, request, contract_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contract = (
                TenantClientContract.objects.select_related('client_account')
                .filter(pk=contract_id)
                .first()
            )
            if contract is None:
                messages.error(request, 'Contract not found.', extra_tags='tenant')
                return _redirect_client_contract_list(request)
            form_data = {
                'contract_no': contract.contract_no,
                'client_account': contract.client_account.account_no,
                'start_date': contract.start_date.isoformat(),
                'end_date': contract.end_date.isoformat(),
                'notes': contract.notes or '',
            }
            context.update(
                self._edit_context(request, tenant_registry, contract, form_data, {})
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, contract_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contract = (
                TenantClientContract.objects.select_related('client_account')
                .filter(pk=contract_id)
                .first()
            )
            if contract is None:
                messages.error(request, 'Contract not found.', extra_tags='tenant')
                return _redirect_client_contract_list(request)

            form_data = {
                'contract_no': contract.contract_no,
                'client_account': contract.client_account.account_no,
                'start_date': (request.POST.get('start_date') or '').strip(),
                'end_date': (request.POST.get('end_date') or '').strip(),
                'notes': (request.POST.get('notes') or '').strip(),
            }

            form_errors = {}
            start_date = parse_date(form_data['start_date']) if form_data['start_date'] else None
            end_date = parse_date(form_data['end_date']) if form_data['end_date'] else None
            if not start_date:
                form_errors['start_date'] = 'Enter a valid start date.'
            if not end_date:
                form_errors['end_date'] = 'Enter a valid end date.'
            if start_date and end_date and end_date < start_date:
                form_errors['end_date'] = 'End date must be on or after start date.'

            if start_date and end_date and end_date >= start_date:
                settings_row = _get_singleton_client_contract_settings()
                for key, msg in _validate_client_contract_period_against_settings(
                    start_date, end_date, settings_row
                ).items():
                    form_errors.setdefault(key, msg)

            upload = request.FILES.get('contract_attachment')
            allow_empty = contract.has_contract_file
            upload_err = _validate_client_contract_upload(upload, allow_empty=allow_empty)
            if upload_err:
                form_errors['contract_attachment'] = upload_err

            if form_errors:
                context.update(
                    self._edit_context(request, tenant_registry, contract, form_data, form_errors)
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    contract.start_date = start_date
                    contract.end_date = end_date
                    contract.notes = form_data['notes']
                    contract.status = _contract_status_for_dates(start_date, end_date)
                    if upload:
                        if contract.contract_attachment:
                            contract.contract_attachment.delete(save=False)
                        contract.contract_attachment = upload
                    contract.save()
            except Exception:
                logger.exception('Tenant client contract update failed')
                context.update(
                    self._edit_context(
                        request,
                        tenant_registry,
                        contract,
                        form_data,
                        {'contract_attachment': 'Could not save the contract. Try again.'},
                    )
                )
                messages.error(request, 'Update failed.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Contract {contract.contract_no} updated.',
                extra_tags='tenant',
            )
            return _redirect_client_contract_list(request)
        finally:
            connection.set_schema_to_public()


class TenantClientContractDeleteView(View):
    def post(self, request, contract_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            contract = TenantClientContract.objects.filter(pk=contract_id).first()
            if contract is None:
                messages.error(request, 'Contract not found.', extra_tags='tenant')
                return _redirect_client_contract_list(request)
            label = contract.contract_no
            if contract.contract_attachment:
                contract.contract_attachment.delete(save=False)
            contract.delete()
            messages.success(request, f'Contract {label} deleted.', extra_tags='tenant')
            return _redirect_client_contract_list(request)
        finally:
            connection.set_schema_to_public()


class TenantClientContractListView(View):
    template_name = 'iroad_tenants/Clients_Management/Client-contract-list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            rows = list(
                TenantClientContract.objects.select_related('client_account').order_by(
                    '-created_at'
                )
            )
            tid = (request.GET.get('tid') or '').strip()
            base = _tenant_client_contracts_base_path()
            for row in rows:
                cid = row.contract_id
                try:
                    detail_u = reverse(
                        'iroad_tenants:tenant_client_contract_detail',
                        kwargs={'contract_id': cid},
                    )
                except NoReverseMatch:
                    detail_u = _tenant_client_contract_detail_path(cid)
                if tid:
                    detail_u = f'{detail_u}?{urlencode({"tid": tid})}'
                row.list_detail_url = detail_u
                try:
                    edit_u = reverse(
                        'iroad_tenants:tenant_client_contract_edit',
                        kwargs={'contract_id': cid},
                    )
                except NoReverseMatch:
                    edit_u = _tenant_client_contract_edit_path(cid)
                if tid:
                    edit_u = f'{edit_u}?{urlencode({"tid": tid})}'
                row.list_edit_url = edit_u
                try:
                    del_u = reverse(
                        'iroad_tenants:tenant_client_contract_delete',
                        kwargs={'contract_id': cid},
                    )
                except NoReverseMatch:
                    del_u = _tenant_client_contract_delete_path(cid)
                row.list_delete_action_url = del_u
            today = timezone.localdate()
            soon_cutoff = today + timezone.timedelta(days=30)
            contract_stats = {
                'total': len(rows),
                'active': sum(1 for r in rows if r.status == TenantClientContract.Status.ACTIVE),
                'upcoming': sum(
                    1 for r in rows if r.status == TenantClientContract.Status.UPCOMING
                ),
                'expired': sum(1 for r in rows if r.status == TenantClientContract.Status.EXPIRED),
                'expiring_soon': sum(
                    1
                    for r in rows
                    if r.end_date and today <= r.end_date <= soon_cutoff and r.status != 'Expired'
                ),
            }
            context.update(
                {
                    'client_contracts': rows,
                    'client_contracts_count': len(rows),
                    'contract_stats': contract_stats,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContractSettingsView(View):
    """Load/save client contract notification rules in the current tenant workspace schema."""

    template_name = 'iroad_tenants/Clients_Management/Client-contract-settings.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            settings_obj = _get_singleton_client_contract_settings()
            context.update(
                {
                    'settings_data': _client_contract_settings_template_dict(settings_obj),
                    'settings_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            mode = (request.POST.get('expired_contract_handling_mode') or '').strip()
            grace_raw = (request.POST.get('grace_period_days') or '').strip()
            pre_raw = (request.POST.get('pre_expiry_notification_days') or '').strip()
            post_raw = (request.POST.get('post_expiry_notification_days') or '').strip()
            freq = (request.POST.get('notification_frequency') or '').strip()
            audience = (request.POST.get('notification_audience') or '').strip()

            settings_data = {
                'expired_contract_handling_mode': mode,
                'grace_period_days': grace_raw,
                'pre_expiry_notification_days': pre_raw,
                'post_expiry_notification_days': post_raw,
                'notification_frequency': freq,
                'notification_audience': audience,
            }
            settings_errors = {}

            valid_modes = {c[0] for c in TenantClientContractSetting.ExpiredHandling.choices}
            if mode not in valid_modes:
                settings_errors['expired_contract_handling_mode'] = 'Select a valid handling mode.'

            valid_freq = {c[0] for c in TenantClientContractSetting.NotificationFrequency.choices}
            if freq not in valid_freq:
                settings_errors['notification_frequency'] = 'Select a valid frequency.'

            valid_audience = {c[0] for c in TenantClientContractSetting.NotificationAudience.choices}
            if audience not in valid_audience:
                settings_errors['notification_audience'] = 'Select a valid audience.'

            def _parse_days(raw, field_key, *, required=False, allow_zero=True):
                if raw == '':
                    if required:
                        settings_errors[field_key] = 'Enter a number of days.'
                    return None
                try:
                    v = int(raw)
                except (TypeError, ValueError):
                    settings_errors[field_key] = 'Enter a whole number of days.'
                    return None
                if v < 0:
                    settings_errors[field_key] = 'Days cannot be negative.'
                    return None
                if not allow_zero and v == 0:
                    settings_errors[field_key] = 'Enter a value greater than zero.'
                    return None
                if v > 3660:
                    settings_errors[field_key] = 'Use a value of 3660 days or less.'
                    return None
                return v

            grace_val = _parse_days(grace_raw, 'grace_period_days')
            if pre_raw == '':
                pre_val = 0
            else:
                pre_val = _parse_days(pre_raw, 'pre_expiry_notification_days', allow_zero=True)
            if post_raw == '':
                post_val = 0
            else:
                post_val = _parse_days(post_raw, 'post_expiry_notification_days', allow_zero=True)

            if (
                mode == TenantClientContractSetting.ExpiredHandling.DEACTIVATE_AFTER_GRACE
                and 'grace_period_days' not in settings_errors
            ):
                if grace_val is None and grace_raw == '':
                    settings_errors['grace_period_days'] = (
                        'Enter a grace period when using Deactivate After Grace.'
                    )
                elif grace_val is not None and grace_val < 1:
                    settings_errors['grace_period_days'] = 'Grace period must be at least 1 day.'

            if settings_errors:
                context.update(
                    {
                        'settings_data': settings_data,
                        'settings_errors': settings_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(
                    request,
                    'Please fix the highlighted errors.',
                    extra_tags='tenant',
                )
                return render(request, self.template_name, context)

            keeper = TenantClientContractSetting.objects.order_by('-updated_at').first()
            prev_grace = keeper.grace_period_days if keeper is not None else 30
            if keeper is None:
                keeper = TenantClientContractSetting.objects.create()
            else:
                TenantClientContractSetting.objects.exclude(pk=keeper.pk).delete()
            settings_obj = keeper
            settings_obj.expired_contract_handling_mode = mode
            # Grace input is disabled unless mode is Deactivate After Grace; omitted POST keeps prev_grace.
            settings_obj.grace_period_days = grace_val if grace_val is not None else prev_grace
            settings_obj.pre_expiry_notification_days = pre_val if pre_val is not None else 0
            settings_obj.post_expiry_notification_days = post_val if post_val is not None else 0
            settings_obj.notification_frequency = freq
            settings_obj.notification_audience = audience
            settings_obj.save()
            messages.success(
                request,
                'Client contract settings saved for this workspace.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_contract_settings')
        finally:
            connection.set_schema_to_public()


class TenantClientDetailsView(View):
    """Client overview; loads account + attachments from tenant schema when ``?id=`` matches."""

    template_name = 'iroad_tenants/Clients_Management/client-details.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            account_no = (request.GET.get('id') or '').strip()
            client_account = None
            client_attachments = []
            client_addresses = []
            client_contacts = []
            primary_contact = None
            client_account_bootstrap = None
            if account_no:
                client_account = TenantClientAccount.objects.filter(
                    account_no=account_no,
                ).first()
                if client_account:
                    client_contacts = list(
                        TenantClientContact.objects.filter(
                            client_account=client_account,
                        ).order_by('-is_primary', '-created_at')
                    )
                    primary_contact = next(
                        (c for c in client_contacts if c.is_primary),
                        None,
                    )
                    client_account_bootstrap = _client_account_bootstrap_dict(
                        client_account,
                        primary_contact,
                    )
                    client_attachments = list(
                        TenantClientAttachment.objects.filter(
                            client_account=client_account,
                        ).order_by('-attachment_date', '-created_at')
                    )
                    client_addresses = list(
                        TenantAddressMaster.objects.filter(
                            client_account=client_account,
                        )
                        .select_related('country', 'client_account')
                        .order_by('-created_at')
                    )
                    tid_addr = (request.GET.get('tid') or '').strip()
                    for addr in client_addresses:
                        try:
                            edit_u = reverse(
                                'iroad_tenants:tenant_address_master_edit',
                                kwargs={'address_id': addr.address_id},
                            )
                        except NoReverseMatch:
                            edit_u = (
                                f'/master-data/addresses/{addr.address_id}/edit/'
                            )
                        if tid_addr:
                            edit_u = f'{edit_u}?{urlencode({"tid": tid_addr})}'
                        addr.list_edit_url = edit_u
            client_cargo_masters = []
            client_contract = None
            if client_account:
                client_cargo_masters = list(
                    TenantCargoMaster.objects.filter(client_account=client_account)
                    .select_related('cargo_category')
                    .order_by('-created_at')
                )
                tid_cargo = (request.GET.get('tid') or '').strip()
                for c in client_cargo_masters:
                    try:
                        edit_u = reverse(
                            'iroad_tenants:tenant_cargo_master_edit',
                            kwargs={'cargo_id': c.cargo_id},
                        )
                    except NoReverseMatch:
                        edit_u = f'/master-data/cargo/{c.cargo_id}/edit/'
                    if tid_cargo:
                        edit_u = f'{edit_u}?{urlencode({"tid": tid_cargo})}'
                    c.list_edit_url = edit_u
                    try:
                        detail_u = reverse(
                            'iroad_tenants:tenant_cargo_master_detail',
                            kwargs={'cargo_id': c.cargo_id},
                        )
                    except NoReverseMatch:
                        detail_u = f'/master-data/cargo/{c.cargo_id}/'
                    if tid_cargo:
                        detail_u = f'{detail_u}?{urlencode({"tid": tid_cargo})}'
                    c.list_detail_url = detail_u
                    try:
                        del_u = reverse(
                            'iroad_tenants:tenant_cargo_master_delete',
                            kwargs={'cargo_id': c.cargo_id},
                        )
                    except NoReverseMatch:
                        del_u = f'/master-data/cargo/{c.cargo_id}/delete/'
                    c.list_delete_action_url = del_u
                client_contract = (
                    TenantClientContract.objects.filter(client_account=client_account)
                    .select_related('client_account')
                    .first()
                )
                if client_contract:
                    tid = (request.GET.get('tid') or '').strip()
                    cid = client_contract.contract_id
                    try:
                        detail_u = reverse(
                            'iroad_tenants:tenant_client_contract_detail',
                            kwargs={'contract_id': cid},
                        )
                    except NoReverseMatch:
                        detail_u = _tenant_client_contract_detail_path(cid)
                    if tid:
                        detail_u = f'{detail_u}?{urlencode({"tid": tid})}'
                    client_contract.list_detail_url = detail_u
                    try:
                        edit_u = reverse(
                            'iroad_tenants:tenant_client_contract_edit',
                            kwargs={'contract_id': cid},
                        )
                    except NoReverseMatch:
                        edit_u = _tenant_client_contract_edit_path(cid)
                    if tid:
                        edit_u = f'{edit_u}?{urlencode({"tid": tid})}'
                    client_contract.list_edit_url = edit_u
                    try:
                        del_u = reverse(
                            'iroad_tenants:tenant_client_contract_delete',
                            kwargs={'contract_id': cid},
                        )
                    except NoReverseMatch:
                        del_u = _tenant_client_contract_delete_path(cid)
                    client_contract.list_delete_action_url = del_u
            client_lookup_failed = bool(account_no) and client_account is None
            context.update(
                {
                    'tenant_schema_name': tenant_registry.schema_name,
                    'client_account': client_account,
                    'client_attachments': client_attachments,
                    'client_contacts': client_contacts,
                    'primary_contact': primary_contact if client_account else None,
                    'client_account_bootstrap': client_account_bootstrap,
                    'client_lookup_failed': client_lookup_failed,
                    'client_contract': client_contract,
                    'client_addresses': client_addresses,
                    'client_cargo_masters': client_cargo_masters,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


def _tenant_address_master_access(request, context):
    if context is None:
        response = redirect('login')
        clear_tenant_portal_cookie(response, request=request)
        return response
    if not context.get('is_tenant_admin'):
        messages.error(
            request,
            'You do not have access to Address Master.',
            extra_tags='tenant',
        )
        return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
    return None


def _format_digits_display(value: str) -> str:
    """Group digits for list display (+966 50 123 4567 style, simplified)."""
    d = ''.join(ch for ch in (value or '') if ch.isdigit())
    if not d:
        return '—'
    if len(d) <= 12:
        return ' '.join(d[i : i + 3] for i in range(0, len(d), 3))
    return d


def _hydrate_address_master_list_rows(addresses_page):
    """Annotate pagination rows for list UI (Country master + display strings)."""
    rows = list(addresses_page.object_list)
    codes = {getattr(r, 'country_id', None) for r in rows}
    codes.discard(None)
    cmap = {}
    if codes:
        with schema_context('public'):
            for c in Country.objects.filter(pk__in=codes):
                cmap[c.country_code] = {
                    'label': f'{c.country_code} — {c.name_en}',
                    'code': c.country_code,
                    'name_en': (c.name_en or '').strip(),
                }

    for row in rows:
        cid = getattr(row, 'country_id', None)
        if cid and cid in cmap:
            info = cmap[cid]
            city = (row.city or '').strip()
            name_en = info['name_en']
            setattr(row, 'country_display_label', info['label'])
            setattr(row, 'country_code_short', info['code'])
            setattr(
                row,
                'city_country_cell',
                f'{city} / {name_en}' if city else f'— / {name_en}',
            )
        else:
            setattr(row, 'country_display_label', '—')
            setattr(row, 'country_code_short', '—')
            setattr(row, 'city_country_cell', '—')
        setattr(row, 'phone_display_cell', _format_digits_display(row.mobile_no_1))


def _address_master_list_stats(filtered_qs):
    addr = TenantAddressMaster
    return {
        'total': filtered_qs.count(),
        'pickup_only': filtered_qs.filter(
            address_category=addr.AddressCategory.PICKUP_ADDRESS
        ).count(),
        'delivery_only': filtered_qs.filter(
            address_category=addr.AddressCategory.DELIVERY_ADDRESS
        ).count(),
        'both': filtered_qs.filter(address_category=addr.AddressCategory.BOTH).count(),
    }


class TenantAddressMasterListView(View):
    """AD-001 list with search/filter and deactivate (inactive) via POST."""

    template_name = 'iroad_tenants/Master_Data/address_master_list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        qs = TenantAddressMaster.objects.select_related('client_account')
        sq = request.GET.get('q', '').strip()
        cid = request.GET.get('client', '').strip()
        filter_client_id = ''

        # AD-001: default list = Active only; All / Inactive only when explicitly requested.
        status_raw = (request.GET.get('status') or '').strip().lower()
        if 'status' not in request.GET:
            qs = qs.filter(status=TenantAddressMaster.Status.ACTIVE)
            filter_status = ''
        elif not status_raw:
            qs = qs.filter(status=TenantAddressMaster.Status.ACTIVE)
            filter_status = 'active'
        elif status_raw == 'all':
            filter_status = 'all'
        elif status_raw == 'inactive':
            qs = qs.filter(status=TenantAddressMaster.Status.INACTIVE)
            filter_status = 'inactive'
        elif status_raw == 'active':
            qs = qs.filter(status=TenantAddressMaster.Status.ACTIVE)
            filter_status = 'active'
        else:
            qs = qs.filter(status=TenantAddressMaster.Status.ACTIVE)
            filter_status = 'active'

        if sq:
            qs = qs.filter(
                Q(display_name__icontains=sq)
                | Q(address_code__icontains=sq)
                | Q(city__icontains=sq)
                | Q(client_account__display_name__icontains=sq)
            )
        if cid:
            try:
                cid_uuid = uuid.UUID(cid)
                qs = qs.filter(client_account_id=cid_uuid)
                filter_client_id = str(cid_uuid)
            except ValueError:
                filter_client_id = ''

        qs_ordered = qs.order_by('-created_at')
        stats = _address_master_list_stats(qs_ordered)
        paginator = Paginator(qs_ordered, 10)
        try:
            page_no = max(1, int(request.GET.get('page') or 1))
        except ValueError:
            page_no = 1
        page = paginator.get_page(page_no)
        _hydrate_address_master_list_rows(page)

        total_count = paginator.count
        if total_count == 0:
            ps, pe = 0, 0
        else:
            ps = (page.number - 1) * paginator.per_page + 1
            pe = ps + len(page.object_list) - 1

        def _page_url(page_num):
            q = request.GET.copy()
            q.pop('stype', None)
            try:
                pn = int(page_num)
            except (TypeError, ValueError):
                pn = 1
            if pn > 1:
                q['page'] = str(pn)
            else:
                q.pop('page', None)
            return '?' + q.urlencode()

        pagination_page_links = [(n, _page_url(n)) for n in page.paginator.page_range]
        prev_url = _page_url(page.previous_page_number()) if page.has_previous() else None
        next_url = _page_url(page.next_page_number()) if page.has_next() else None

        clients = list(
            TenantClientAccount.objects.filter(
                status=TenantClientAccount.Status.ACTIVE,
            ).order_by('display_name')[:500]
        )

        context.update(
            {
                'addresses_page': page,
                'search_q': sq,
                'filter_status': filter_status,
                'filter_client_id': filter_client_id,
                'pagination_page_links': pagination_page_links,
                'pagination_prev_url': prev_url,
                'pagination_next_url': next_url,
                'stats': stats,
                'pagination_start': ps,
                'pagination_end': pe,
                'pagination_total': total_count,
                'client_filter_choices': clients,
                'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
            }
        )
        try:
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        """Set status Active / Inactivate (PCS: keep row, no delete)."""

        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return denied

        if request.POST.get('action') != 'set_status':
            return self.get(request)

        address_id = (request.POST.get('address_id') or '').strip()
        new_status = (request.POST.get('new_status') or '').strip()
        if new_status not in (
            TenantAddressMaster.Status.ACTIVE,
            TenantAddressMaster.Status.INACTIVE,
        ):
            messages.error(request, 'Invalid status.', extra_tags='tenant')
            rq = (request.POST.get('redirect_query') or '').strip()
            base = reverse('iroad_tenants:tenant_address_master')
            if rq:
                return redirect(f'{base}?{rq}')
            return _tenant_redirect(request, 'iroad_tenants:tenant_address_master')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            addr = TenantAddressMaster.objects.filter(pk=address_id).first()
            if not addr:
                messages.error(request, 'Address not found.', extra_tags='tenant')
            else:
                addr.status = new_status
                addr.save(update_fields=['status', 'updated_at'])
                messages.success(request, f'Address set to {new_status.lower()}.', extra_tags='tenant')
        finally:
            connection.set_schema_to_public()

        rq = (request.POST.get('redirect_query') or '').strip()
        base = reverse('iroad_tenants:tenant_address_master')
        if rq:
            return redirect(f'{base}?{rq}')
        return _tenant_redirect(request, 'iroad_tenants:tenant_address_master')


class TenantAddressMasterCreateView(View):

    template_name = 'iroad_tenants/Master_Data/address_master_form.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            preview = _preview_next_address_master_code()

            initial = {}
            cid = (request.GET.get('client') or '').strip()
            if cid:
                try:
                    initial['client_account'] = uuid.UUID(cid)
                except ValueError:
                    pass

            form = TenantAddressMasterForm(
                initial=initial,
            )
            context.update(
                {
                    'form': form,
                    'preview_address_code': preview,
                    'is_edit': False,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_resp = None
        try:
            logger.info(
                'Address Master create POST: keys=%s',
                sorted(request.POST.keys()),
            )
            form = TenantAddressMasterForm(
                request.POST,
            )

            if not form.is_valid():
                logger.warning(
                    'Address Master create validation failed errors=%s',
                    form.errors.as_json(),
                )
                preview = _preview_next_address_master_code()
                context.update(
                    {
                        'form': form,
                        'preview_address_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    addr_code, addr_seq = _next_auto_number_for_form(
                        ADDRESS_MASTER_AUTO_FORM_CODE,
                        ADDRESS_MASTER_AUTO_FORM_LABEL,
                        ADDRESS_MASTER_REF_PREFIX,
                    )
                    addr = form.save(commit=False)
                    addr.address_code = addr_code
                    addr.address_sequence = addr_seq
                    addr.save()
            except IntegrityError:
                logger.exception('Address Master create integrity violation')
                preview = _preview_next_address_master_code()
                form.add_error(
                    None,
                    ValidationError(
                        'Unable to allocate a unique address code. Please retry.',
                        code='address_integrity',
                    ),
                )
                context.update(
                    {
                        'form': form,
                        'preview_address_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the address.', extra_tags='tenant')
                return render(request, self.template_name, context)
            except ValidationError as ve:
                logger.warning('Address Master create raised ValidationError: %s', ve)
                preview = _preview_next_address_master_code()
                if getattr(ve, 'error_dict', None):
                    for field_name, errs in ve.error_dict.items():
                        for err in errs:
                            form.add_error(field_name, err)
                else:
                    for msg in getattr(ve, 'messages', []) or [str(ve)]:
                        form.add_error(None, msg)
                context.update(
                    {
                        'form': form,
                        'preview_address_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the address.', extra_tags='tenant')
                return render(request, self.template_name, context)
            except Exception:
                logger.exception('Address Master create save failed')
                preview = _preview_next_address_master_code()
                form.add_error(
                    None,
                    ValidationError(
                        'Saving failed unexpectedly. Try again or contact support.',
                        code='address_save_failed',
                    ),
                )
                context.update(
                    {
                        'form': form,
                        'preview_address_code': preview,
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save the address.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'Address {addr.address_code} created successfully.',
                extra_tags='tenant',
            )

            redirect_resp = _tenant_redirect(request, 'iroad_tenants:tenant_address_master')
        finally:
            connection.set_schema_to_public()

        return redirect_resp


class TenantAddressMasterEditView(View):

    template_name = 'iroad_tenants/Master_Data/address_master_form.html'

    def _load(self, address_id):
        return TenantAddressMaster.objects.select_related('client_account').filter(
            pk=address_id
        ).first()

    def get(self, request, address_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            instance = self._load(address_id)
            if not instance:
                messages.error(request, 'Address not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_address_master')

            form = TenantAddressMasterForm(
                instance=instance,
            )

            context.update(
                {
                    'form': form,
                    'is_edit': True,
                    'address_record': instance,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, address_id):
        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return denied

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_resp = None
        try:
            instance = self._load(address_id)
            if not instance:
                messages.error(request, 'Address not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_address_master')

            logger.info(
                'Address Master edit POST address_id=%s keys=%s',
                address_id,
                sorted(request.POST.keys()),
            )
            form = TenantAddressMasterForm(
                request.POST,
                instance=instance,
            )

            if not form.is_valid():
                logger.warning(
                    'Address Master edit validation failed address_id=%s errors=%s',
                    address_id,
                    form.errors.as_json(),
                )
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'address_record': instance,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                with db_transaction.atomic():
                    form.save()
            except IntegrityError:
                logger.exception('Address Master edit integrity violation address_id=%s', address_id)
                form.add_error(
                    None,
                    ValidationError(
                        'Conflict while saving this address.',
                        code='address_integrity',
                    ),
                )
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'address_record': instance,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save changes.', extra_tags='tenant')
                return render(request, self.template_name, context)
            except ValidationError as ve:
                logger.warning('Address Master edit ValidationError address_id=%s detail=%s', address_id, ve)
                if getattr(ve, 'error_dict', None):
                    for field_name, errs in ve.error_dict.items():
                        for err in errs:
                            form.add_error(field_name, err)
                else:
                    for msg in getattr(ve, 'messages', []) or [str(ve)]:
                        form.add_error(None, msg)
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'address_record': instance,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save changes.', extra_tags='tenant')
                return render(request, self.template_name, context)
            except Exception:
                logger.exception('Address Master edit save failed address_id=%s', address_id)
                form.add_error(
                    None,
                    ValidationError(
                        'Saving failed unexpectedly. Try again or contact support.',
                        code='address_save_failed',
                    ),
                )
                context.update(
                    {
                        'form': form,
                        'is_edit': True,
                        'address_record': instance,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Could not save changes.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(request, 'Address updated successfully.', extra_tags='tenant')
            redirect_resp = _tenant_redirect(request, 'iroad_tenants:tenant_address_master')
        finally:
            connection.set_schema_to_public()

        return redirect_resp


class TenantAddressLocationOptionsView(View):
    """AJAX options for Address Master location dropdowns."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        denied = _tenant_address_master_access(request, context)
        if denied:
            return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=401)

        country_id = (request.GET.get('country') or '').strip()
        province = (request.GET.get('province') or '').strip()
        try:
            qs = TenantLocationMaster.active_serviceable_objects.all()
            if country_id:
                qs = qs.filter(country_id=country_id)
            provinces = list(
                qs.exclude(province='')
                .values_list('province', flat=True)
                .distinct()
                .order_by('province')
            )
            cities = []
            if province:
                cities = list(
                    qs.filter(province=province)
                    .values_list('display_label', flat=True)
                    .distinct()
                    .order_by('display_label')
                )
            return JsonResponse(
                {
                    'ok': True,
                    'provinces': provinces,
                    'cities': cities,
                }
            )
        finally:
            connection.set_schema_to_public()


class TenantMyAccountView(View):
    """Tenant self account summary page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(request, 'iroad_tenants/my_account.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        tenant = context['tenant']
        
        # Personal Info (Only name and password are now editable)
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        
        # Password Change
        password = request.POST.get('password', '')

        # Password Validation
        if password:
            if len(password) < 8:
                messages.error(request, "Password must be at least 8 characters.", extra_tags='tenant')
                return render(request, 'iroad_tenants/my_account.html', context)

        try:
            # Update Names
            tenant.first_name = first_name
            tenant.last_name = last_name
            
            # Update Password if provided
            if password:
                tenant.portal_bootstrap_password_hash = make_password(password)
            
            tenant.save()
            
            messages.success(request, "Profile updated successfully.", extra_tags='tenant')
            # Refresh context to show new values
            context = _tenant_context_from_session(request)
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}", extra_tags='tenant')

        return render(request, 'iroad_tenants/my_account.html', context)


class TenantAutoNumberConfigurationView(View):
    """Tenant auto number configuration page."""

    ORGANIZATION_FORM_CODE = 'organization-profile'
    ORGANIZATION_FORM_LABEL = 'Organization Profile'
    USERS_FORM_CODE = 'users-administration'
    USERS_FORM_LABEL = 'Users Administration'
    CLIENT_ACCOUNT_FORM_CODE = 'client-account'
    CLIENT_ACCOUNT_FORM_LABEL = 'Client Account'
    CLIENT_CONTRACT_FORM_CODE = CLIENT_CONTRACT_AUTO_FORM_CODE
    CLIENT_CONTRACT_FORM_LABEL = CLIENT_CONTRACT_AUTO_FORM_LABEL
    ALLOWED_SEQUENCE_FORMATS = {'numeric', 'alpha', 'alphanumeric'}

    FORM_LABELS = {
        ORGANIZATION_FORM_CODE: ORGANIZATION_FORM_LABEL,
        USERS_FORM_CODE: USERS_FORM_LABEL,
        CLIENT_ACCOUNT_FORM_CODE: CLIENT_ACCOUNT_FORM_LABEL,
        CLIENT_CONTRACT_FORM_CODE: CLIENT_CONTRACT_FORM_LABEL,
        ADDRESS_MASTER_AUTO_FORM_CODE: ADDRESS_MASTER_AUTO_FORM_LABEL,
        CARGO_MASTER_AUTO_FORM_CODE: CARGO_MASTER_AUTO_FORM_LABEL,
        CARGO_CATEGORY_AUTO_FORM_CODE: CARGO_CATEGORY_AUTO_FORM_LABEL,
        LOCATION_MASTER_AUTO_FORM_CODE: LOCATION_MASTER_AUTO_FORM_LABEL,
        ROUTE_MASTER_AUTO_FORM_CODE: ROUTE_MASTER_AUTO_FORM_LABEL,
    }

    @staticmethod
    def _normalize_form_code(raw):
        """Match URL/post variants (e.g. Cargo-master, cargo_master) to FORM_LABELS keys."""
        if raw is None:
            return ''
        s = str(raw).strip()
        if not s:
            return ''
        return s.replace('_', '-').lower()

    def _auto_number_list_url(self, request, form_code):
        q = {'form_code': form_code}
        tid = (request.POST.get('tid') or request.GET.get('tid') or '').strip()
        if tid:
            q['tid'] = tid
        return f"{reverse('iroad_tenants:tenant_auto_number_configuration')}?{urlencode(q)}"

    def _load_config(self, form_code):
        config, _ = AutoNumberConfiguration.objects.get_or_create(
            form_code=form_code,
            defaults={
                'form_label': self.FORM_LABELS.get(form_code, form_code),
                'number_of_digits': 4,
                'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
                'is_unique': True,
            },
        )
        return config

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            raw_form = request.GET.get('form_code')
            if raw_form is None or not str(raw_form).strip():
                requested_form_code = self.ORGANIZATION_FORM_CODE
            else:
                requested_form_code = self._normalize_form_code(raw_form)
                if requested_form_code not in self.FORM_LABELS:
                    requested_form_code = self.ORGANIZATION_FORM_CODE
            config = self._load_config(requested_form_code)
            sequence = AutoNumberSequence.objects.filter(form_code=requested_form_code).first()
            base_next_number = sequence.next_number if sequence else 1
        finally:
            connection.set_schema_to_public()

        context.update(
            {
                'auto_number_config': config,
                'auto_number_form_code': requested_form_code,
                'auto_number_form_label': self.FORM_LABELS.get(requested_form_code, requested_form_code),
                'base_next_number': base_next_number,
                'auto_number_enabled_form_codes': list(self.FORM_LABELS.keys()),
                'tenant_schema_name': tenant_registry.schema_name,
            }
        )
        return render(
            request,
            'iroad_tenants/configuration/Auto-number-configuration.html',
            context,
        )

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        redirect_url = self._auto_number_list_url(request, self.ORGANIZATION_FORM_CODE)
        try:
            selected_form = self._normalize_form_code(request.POST.get('form_code'))
            if selected_form not in self.FORM_LABELS:
                messages.error(
                    request,
                    'Invalid auto number form selected.',
                    extra_tags='tenant',
                )
            else:
                try:
                    config = self._load_config(selected_form)
                    digits_raw = (request.POST.get('number_of_digits') or '').strip()
                    sequence_format = (request.POST.get('sequence_format') or '').strip().lower()

                    if not digits_raw.isdigit() or not (1 <= int(digits_raw) <= 10):
                        raise ValueError('Number of digits must be between 1 and 10.')
                    if sequence_format not in self.ALLOWED_SEQUENCE_FORMATS:
                        raise ValueError('Invalid sequence format selected.')

                    config.number_of_digits = int(digits_raw)
                    config.sequence_format = sequence_format
                    config.is_unique = request.POST.get('is_unique') == 'on'
                    config.form_label = self.FORM_LABELS[selected_form]
                    config.save(update_fields=[
                        'number_of_digits',
                        'sequence_format',
                        'is_unique',
                        'form_label',
                        'updated_at',
                    ])
                    messages.success(
                        request,
                        f'Auto number configuration saved for {self.FORM_LABELS[selected_form]}.',
                        extra_tags='tenant',
                    )
                except ValueError as exc:
                    messages.error(request, str(exc), extra_tags='tenant')
                redirect_url = self._auto_number_list_url(request, selected_form)
        finally:
            connection.set_schema_to_public()

        return redirect(redirect_url)


class TenantLogoutView(View):
    """Clear tenant session and redirect to login."""

    def get(self, request):
        self._clear_tenant_session(request)
        response = redirect('login')
        clear_tenant_portal_cookie(response, request=request)
        return response

    def post(self, request):
        self._clear_tenant_session(request)
        response = redirect('login')
        clear_tenant_portal_cookie(response, request=request)
        return response

    @staticmethod
    def _clear_tenant_session(request):
        _clear_tenant_bootstrap_session(request)


class TenantOrganizationProfileView(View):
    """View organization profile."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            owner_label = _owner_user_label(profile.owner_user_id)
            context.update({
                'org': profile,
                'owner_label': owner_label,
                'org_status_label': _organization_status_from_tenant(context['tenant']),
                'logo_display_name': _logo_display_name(profile),
                'tenant_schema_name': tenant_registry.schema_name,
            })
        finally:
            connection.set_schema_to_public()
        return render(request, 'iroad_tenants/Administration/Organization-profile.html', context)


class TenantOrganizationProfileEditView(View):
    """Edit organization profile."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            context.update(_organization_form_context(profile))
            context['org_status_label'] = _organization_status_from_tenant(context['tenant'])
            context['tenant_schema_name'] = tenant_registry.schema_name
        finally:
            connection.set_schema_to_public()
        return render(request, 'iroad_tenants/Administration/Organization-profile-view.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            _apply_organization_profile_post(request, profile)
            profile.save()
            messages.success(request, 'Organization profile updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_organization_profile')
        except ValueError as exc:
            messages.error(request, str(exc), extra_tags='tenant')
            context.update(_organization_form_context(profile))
            context['org_status_label'] = _organization_status_from_tenant(context['tenant'])
            context['tenant_schema_name'] = tenant_registry.schema_name
            return render(request, 'iroad_tenants/Administration/Organization-profile-view.html', context)
        finally:
            connection.set_schema_to_public()


class TenantLocationMasterListView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Location-master-list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to view Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            qs = TenantLocationMaster.objects.select_related('country')
            search_q = (request.GET.get('q') or '').strip()
            if search_q:
                qs = qs.filter(
                    Q(location_code__icontains=search_q)
                    | Q(display_label__icontains=search_q)
                    | Q(location_name_english__icontains=search_q)
                    | Q(location_name_arabic__icontains=search_q)
                    | Q(province__icontains=search_q)
                    | Q(country__name_en__icontains=search_q)
                )

            status_filter = (request.GET.get('status') or 'all').strip().lower()
            if status_filter == 'active':
                qs = qs.filter(status=TenantLocationMaster.Status.ACTIVE)
            elif status_filter == 'inactive':
                qs = qs.filter(status=TenantLocationMaster.Status.INACTIVE)
            else:
                status_filter = 'all'

            serviceable_filter = (request.GET.get('serviceable') or 'all').strip().lower()
            if serviceable_filter == 'yes':
                qs = qs.filter(is_serviceable=True)
            elif serviceable_filter == 'no':
                qs = qs.filter(is_serviceable=False)
            else:
                serviceable_filter = 'all'

            qs = qs.order_by('-created_at')
            stats = {
                'total': TenantLocationMaster.objects.count(),
                'serviceable': TenantLocationMaster.objects.filter(is_serviceable=True).count(),
                'non_serviceable': TenantLocationMaster.objects.filter(is_serviceable=False).count(),
                'inactive': TenantLocationMaster.objects.filter(
                    status=TenantLocationMaster.Status.INACTIVE
                ).count(),
            }
            paginator = Paginator(qs, 10)
            try:
                page_no = max(1, int(request.GET.get('page') or 1))
            except ValueError:
                page_no = 1
            page = paginator.get_page(page_no)
            context.update(
                {
                    'locations_page': page,
                    'search_q': search_q,
                    'filter_status': status_filter,
                    'filter_serviceable': serviceable_filter,
                    'location_stats': stats,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        except ProgrammingError:
            # Tenant schema is missing the latest migration table(s).
            messages.error(
                request,
                'Location Master is not initialized for this tenant yet. '
                'Please run tenant migrations and reload.',
                extra_tags='tenant',
            )
            context.update(
                {
                    'locations': [],
                    'location_stats': {
                        'total': 0,
                        'serviceable': 0,
                        'non_serviceable': 0,
                        'inactive': 0,
                    },
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantLocationMasterCreateView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Location-master.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to view Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            context.update(
                {
                    'form': TenantLocationMasterForm(allow_inactive_status=False),
                    'preview_location_code': _preview_next_location_master_code(),
                    'is_edit': False,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to view Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            form = TenantLocationMasterForm(request.POST, allow_inactive_status=False)
            if not form.is_valid():
                context.update(
                    {
                        'form': form,
                        'preview_location_code': _preview_next_location_master_code(),
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                return render(request, self.template_name, context)

            try:
                location_code, location_sequence = _next_auto_number_for_form(
                    LOCATION_MASTER_AUTO_FORM_CODE,
                    LOCATION_MASTER_AUTO_FORM_LABEL,
                    LOCATION_MASTER_REF_PREFIX,
                )
                location = form.save(commit=False)
                location.location_code = location_code
                location.location_sequence = location_sequence
                location.full_clean()
                location.save()
            except IntegrityError:
                form.add_error(
                    'display_label',
                    'A location with this country/province/display label already exists.',
                )
                context.update(
                    {
                        'form': form,
                        'preview_location_code': _preview_next_location_master_code(),
                        'is_edit': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                return render(request, self.template_name, context)

            messages.success(
                request,
                f'{location.location_code} created successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')
        finally:
            connection.set_schema_to_public()


class TenantRouteMasterListView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Route-master-list.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to view Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            qs = TenantRouteMaster.objects.select_related('origin_point', 'destination_point')
            search_q = (request.GET.get('q') or '').strip()
            route_scope = (request.GET.get('scope') or 'all').strip().lower()
            if search_q:
                qs = qs.filter(
                    Q(route_code__icontains=search_q)
                    | Q(route_label__icontains=search_q)
                    | Q(origin_point__display_label__icontains=search_q)
                    | Q(destination_point__display_label__icontains=search_q)
                )
            if route_scope == 'domestic':
                qs = qs.filter(route_type=TenantRouteMaster.RouteType.DOMESTIC)
            elif route_scope == 'international':
                qs = qs.filter(route_type=TenantRouteMaster.RouteType.INTERNATIONAL)

            routes_page = Paginator(qs.order_by('-created_at'), 25).get_page(
                request.GET.get('page') or 1
            )
            stats_qs = TenantRouteMaster.objects.all()
            route_stats = {
                'total': stats_qs.count(),
                'active': stats_qs.filter(status=TenantRouteMaster.Status.ACTIVE).count(),
                'with_customs': stats_qs.filter(has_customs=True).count(),
                'with_toll_gates': stats_qs.filter(has_toll_gates=True).count(),
            }
            context.update(
                {
                    'routes_page': routes_page,
                    'search_q': search_q,
                    'route_scope': route_scope,
                    'route_stats': route_stats,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantLocationMasterDeleteView(View):
    def post(self, request, location_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to modify Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        try:
            location = TenantLocationMaster.objects.filter(pk=location_id).first()
            if not location:
                messages.error(request, 'Location not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')

            code = location.location_code
            try:
                location.delete()
            except ProtectedError:
                messages.error(
                    request,
                    'This location cannot be deleted because it is referenced by other records.',
                    extra_tags='tenant',
                )
                return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')

            messages.success(request, f'{code} deleted successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')
        finally:
            connection.set_schema_to_public()


class TenantLocationMasterDetailView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Location-master.html'

    def get(self, request, location_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to view Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            location = TenantLocationMaster.objects.select_related('country').filter(
                pk=location_id
            ).first()
            if not location:
                messages.error(request, 'Location not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')
            context.update(
                {
                    'form': TenantLocationMasterForm(
                        instance=location,
                        allow_inactive_status=True,
                    ),
                    'location': location,
                    'preview_location_code': location.location_code,
                    'is_edit': True,
                    'is_view': True,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantLocationMasterEditView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Location-master.html'

    def _get_location(self, location_id):
        return TenantLocationMaster.objects.select_related('country').filter(pk=location_id).first()

    def get(self, request, location_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to view Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            location = self._get_location(location_id)
            if not location:
                messages.error(request, 'Location not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')
            context.update(
                {
                    'form': TenantLocationMasterForm(
                        instance=location,
                        allow_inactive_status=True,
                    ),
                    'location': location,
                    'preview_location_code': location.location_code,
                    'is_edit': True,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, location_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(
                request,
                'You do not have permission to view Route Management.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            location = self._get_location(location_id)
            if not location:
                messages.error(request, 'Location not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')

            form = TenantLocationMasterForm(
                request.POST,
                instance=location,
                allow_inactive_status=True,
            )
            if not form.is_valid():
                context.update(
                    {
                        'form': form,
                        'location': location,
                        'preview_location_code': location.location_code,
                        'is_edit': True,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                return render(request, self.template_name, context)

            location = form.save(commit=False)
            location.full_clean()
            location.save()
            messages.success(
                request,
                f'{location.location_code} updated successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_location_master_list')
        finally:
            connection.set_schema_to_public()


class TenantRouteMasterCreateView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Route-master.html'

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to view Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')

        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            context.update(
                {
                    'form': TenantRouteMasterForm(allow_inactive_status=False),
                    'preview_route_code': _preview_next_route_master_code(),
                    'is_edit': False,
                    'is_view': False,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to view Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            form = TenantRouteMasterForm(request.POST, allow_inactive_status=False)
            if not form.is_valid():
                context.update(
                    {
                        'form': form,
                        'preview_route_code': _preview_next_route_master_code(),
                        'is_edit': False,
                        'is_view': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)
            try:
                route_code, route_seq = _next_auto_number_for_form(
                    ROUTE_MASTER_AUTO_FORM_CODE,
                    ROUTE_MASTER_AUTO_FORM_LABEL,
                    ROUTE_MASTER_REF_PREFIX,
                )
                route = form.save(commit=False)
                route.route_code = route_code
                route.route_sequence = route_seq
                route.full_clean()
                route.save()
            except IntegrityError:
                form.add_error('route_label', 'A route with this type/origin/destination already exists.')
                context.update(
                    {
                        'form': form,
                        'preview_route_code': _preview_next_route_master_code(),
                        'is_edit': False,
                        'is_view': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                return render(request, self.template_name, context)

            messages.success(request, f'{route.route_code} created successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
        finally:
            connection.set_schema_to_public()


class TenantRouteMasterDetailView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Route-master.html'

    def get(self, request, route_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to view Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            route = TenantRouteMaster.objects.select_related('origin_point', 'destination_point').filter(
                pk=route_id
            ).first()
            if not route:
                messages.error(request, 'Route not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
            context.update(
                {
                    'form': TenantRouteMasterForm(instance=route, allow_inactive_status=True),
                    'route': route,
                    'preview_route_code': route.route_code,
                    'is_edit': False,
                    'is_view': True,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantRouteMasterEditView(View):
    template_name = 'iroad_tenants/Master_Data/location_master/Route-master.html'

    def _get_route(self, route_id):
        return TenantRouteMaster.objects.select_related('origin_point', 'destination_point').filter(
            pk=route_id
        ).first()

    def get(self, request, route_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to view Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            route = self._get_route(route_id)
            if not route:
                messages.error(request, 'Route not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
            context.update(
                {
                    'form': TenantRouteMasterForm(instance=route, allow_inactive_status=True),
                    'route': route,
                    'preview_route_code': route.route_code,
                    'is_edit': True,
                    'is_view': False,
                    'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()

    def post(self, request, route_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to view Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            route = self._get_route(route_id)
            if not route:
                messages.error(request, 'Route not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
            form = TenantRouteMasterForm(request.POST, instance=route, allow_inactive_status=True)
            if not form.is_valid():
                context.update(
                    {
                        'form': form,
                        'route': route,
                        'preview_route_code': route.route_code,
                        'is_edit': True,
                        'is_view': False,
                        'tenant_schema_name': getattr(tenant_registry, 'schema_name', ''),
                    }
                )
                return render(request, self.template_name, context)
            route = form.save(commit=False)
            route.full_clean()
            route.save()
            messages.success(request, f'{route.route_code} updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
        finally:
            connection.set_schema_to_public()


class TenantRouteMasterDeleteView(View):
    def post(self, request, route_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        if not context.get('is_tenant_admin'):
            messages.error(request, 'You do not have permission to modify Route Management.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_dashboard')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            route = TenantRouteMaster.objects.filter(pk=route_id).first()
            if not route:
                messages.error(request, 'Route not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
            code = route.route_code
            route.delete()
            messages.success(request, f'{code} deleted successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_route_master_list')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationView(View):
    """Tenant users administration list page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            search_query = (request.GET.get('q') or '').strip()
            users_qs = TenantUser.objects.all()
            if search_query:
                users_qs = users_qs.filter(
                    Q(full_name__icontains=search_query)
                    | Q(email__icontains=search_query)
                    | Q(role_name__icontains=search_query)
                    | Q(username__icontains=search_query)
                    | Q(tenant_ref_no__icontains=search_query)
                )
            tenant_users = list(users_qs.order_by('-created_at', '-updated_at')[:100])

            all_users_qs = TenantUser.objects.all()
            total_users = all_users_qs.count()
            active_users = all_users_qs.filter(status=TenantUser.Status.ACTIVE).count()
            inactive_users = total_users - active_users
            locked_accounts = all_users_qs.filter(login_attempts__gte=3).count()
            context.update(
                {
                    'tenant_users': tenant_users,
                    'users_total_count': total_users,
                    'users_active_count': active_users,
                    'users_inactive_count': inactive_users,
                    'users_locked_count': locked_accounts,
                    'search_query': search_query,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
        finally:
            connection.set_schema_to_public()
        return render(
            request,
            'iroad_tenants/User_Management/Users-administration.html',
            context,
        )


TENANT_USER_ROLE_OPTIONS = ['Administrator', 'Finance Manager', 'Operations Staff', 'Sales Executive']
TENANT_PERMISSION_MATRIX = [
    {'module_name': 'Master Data', 'form_name': 'Cargo Master'},
    {'module_name': 'Commercial', 'form_name': 'Sales Order'},
    {'module_name': 'Operations', 'form_name': 'Booking'},
    {'module_name': 'Operations', 'form_name': 'Shipment'},
    {'module_name': 'Finance', 'form_name': 'Sales Invoicing'},
    {'module_name': 'Finance', 'form_name': 'Purchase Invoicing'},
]


def _tenant_role_name_options():
    role_names = list(
        TenantRole.objects.order_by('role_name_en').values_list('role_name_en', flat=True)
    )
    if role_names:
        return role_names
    return TENANT_USER_ROLE_OPTIONS


def _tenant_user_login_url(request):
    configured_url = (getattr(settings, 'TENANT_PORTAL_LOGIN_URL', '') or '').strip()
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = str(auth_payload.get('tenant_id') or '').strip()
    if configured_url:
        if tenant_id and 'tid=' not in configured_url:
            separator = '&' if '?' in configured_url else '?'
            return f'{configured_url}{separator}tid={tenant_id}'
        return configured_url
    login_url = request.build_absolute_uri(reverse('login'))
    if tenant_id:
        login_url = f'{login_url}?tid={tenant_id}'
    return login_url


def _send_tenant_user_welcome_email(*, request, tenant_user, plaintext_password, role_name):
    context_dict = {
        'name': tenant_user.full_name,
        'email': tenant_user.email,
        'password': plaintext_password,
        'role_name': role_name,
        'login_url': _tenant_user_login_url(request),
        'user_name': tenant_user.full_name,
    }
    sent = send_named_notification_email(
        'TENANT_USER_WELCOME',
        recipient_email=tenant_user.email,
        context_dict=context_dict,
        language='en',
        default_subject='Welcome to iRoad - Tenant User Access',
        trigger_source='TemplateName: TENANT_USER_WELCOME',
        force_django_smtp=True,
    )
    if sent:
        return True
    return send_named_notification_email(
        'SUBADMIN_WELCOME',
        recipient_email=tenant_user.email,
        context_dict=context_dict,
        language='en',
        default_subject='Welcome to iRoad - Your Login Credentials',
        trigger_source='TemplateName: SUBADMIN_WELCOME',
        force_django_smtp=True,
    )


def _tenant_user_form_data_from_post(request):
    return {
        'username': (request.POST.get('username') or '').strip(),
        'full_name': (request.POST.get('full_name') or '').strip(),
        'email': (request.POST.get('email') or '').strip().lower(),
        'mobile_country_code': (request.POST.get('mobile_country_code') or '').strip(),
        'mobile_no': (request.POST.get('mobile_no') or '').strip(),
        'status': 'Active' if request.POST.get('status') == 'on' else 'Inactive',
        'roles': request.POST.getlist('roles'),
    }


def _tenant_user_form_data_from_model(tenant_user):
    return {
        'username': tenant_user.username,
        'full_name': tenant_user.full_name,
        'email': tenant_user.email,
        'mobile_country_code': tenant_user.mobile_country_code,
        'mobile_no': tenant_user.mobile_no,
        'status': tenant_user.status,
        'roles': [tenant_user.role_name] if tenant_user.role_name else [],
    }


class TenantUsersAdministrationCreateView(View):
    """Tenant users administration create page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            context.update(
                {
                    'role_options': _tenant_role_name_options(),
                    'form_data': {
                        'mobile_country_code': '',
                        'status': '',
                        'roles': [],
                    },
                    'form_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': False,
                    'is_view_mode': False,
                }
            )
            return render(
                request,
                'iroad_tenants/User_Management/Users-administration-create.html',
                context,
            )
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        form_data = _tenant_user_form_data_from_post(request)
        password = (request.POST.get('password') or '').strip()
        form_errors = {}

        try:
            role_options = _tenant_role_name_options()
            if not form_data['username']:
                form_errors['username'] = 'Username is required.'
            if not form_data['full_name']:
                form_errors['full_name'] = 'Full Name is required.'
            if not form_data['email']:
                form_errors['email'] = 'Email is required.'
            if not form_data['roles']:
                form_errors['roles'] = 'Select at least one role.'
            else:
                invalid_roles = [role for role in form_data['roles'] if role not in role_options]
                if invalid_roles:
                    form_errors['roles'] = 'Selected role is invalid. Please choose from Roles master.'
            if not password:
                form_errors['password'] = 'Password is required.'
            elif len(password) < 8:
                form_errors['password'] = 'Password must be at least 8 characters.'

            if form_data['username'] and TenantUser.objects.filter(username__iexact=form_data['username']).exists():
                form_errors['username'] = 'This username already exists in this tenant.'
            if form_data['email'] and TenantUser.objects.filter(email__iexact=form_data['email']).exists():
                form_errors['email'] = 'This email already exists in this tenant.'
            tenant_primary_email = (context['tenant'].primary_email or '').strip().lower()
            if form_data['email'] and tenant_primary_email and form_data['email'] == tenant_primary_email:
                form_errors['email'] = (
                    'Tenant user email cannot be the same as the tenant primary login email.'
                )

            if form_errors:
                context.update(
                    {
                        'role_options': role_options,
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': False,
                        'is_view_mode': False,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Users-administration-create.html',
                    context,
                )

            user_ref_no, account_sequence = _next_auto_number_for_form(
                form_code='users-administration',
                form_label='Users Administration',
                prefix='USR',
            )

            selected_role = form_data['roles'][0] if form_data['roles'] else 'Administrator'
            tenant_user = TenantUser.objects.create(
                tenant_ref_no=user_ref_no,
                account_sequence=account_sequence,
                username=form_data['username'],
                full_name=form_data['full_name'],
                email=form_data['email'],
                mobile_country_code=form_data['mobile_country_code'],
                mobile_no=form_data['mobile_no'],
                password_hash=make_password(password),
                temp_password_expires_at=timezone.now() + timezone.timedelta(hours=24),
                role_name=selected_role,
                status=form_data['status'],
                created_by_label=(context.get('display_name') or '').strip(),
            )
            try:
                email_sent = _send_tenant_user_welcome_email(
                    request=request,
                    tenant_user=tenant_user,
                    plaintext_password=password,
                    role_name=selected_role,
                )
                if email_sent:
                    messages.success(
                        request,
                        'Login credentials email sent to the user.',
                        extra_tags='tenant',
                    )
                else:
                    messages.warning(
                        request,
                        'User created, but no active notification template found for login email.',
                        extra_tags='tenant',
                    )
            except Exception:
                logger.exception(
                    'Tenant user welcome email failed for %s',
                    tenant_user.email,
                )
                messages.warning(
                    request,
                    'User created, but login email could not be sent. Please verify email gateway/template settings.',
                    extra_tags='tenant',
                )
            messages.success(request, 'Tenant user created successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationEditView(View):
    """Tenant users edit/view page."""

    def get(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
            is_view_mode = request.GET.get('mode') == 'view'
            role_options = _tenant_role_name_options()
            if tenant_user.role_name and tenant_user.role_name not in role_options:
                role_options = [tenant_user.role_name, *role_options]
            context.update(
                {
                    'role_options': role_options,
                    'form_data': _tenant_user_form_data_from_model(tenant_user),
                    'form_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': True,
                    'is_view_mode': is_view_mode,
                    'editing_user': tenant_user,
                }
            )
            return render(
                request,
                'iroad_tenants/User_Management/Users-administration-create.html',
                context,
            )
        finally:
            connection.set_schema_to_public()

    def post(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')

            form_data = _tenant_user_form_data_from_post(request)
            form_errors = {}
            role_options = _tenant_role_name_options()
            if tenant_user.role_name and tenant_user.role_name not in role_options:
                role_options = [tenant_user.role_name, *role_options]

            if not form_data['username']:
                form_errors['username'] = 'Username is required.'
            if not form_data['full_name']:
                form_errors['full_name'] = 'Full Name is required.'
            if not form_data['email']:
                form_errors['email'] = 'Email is required.'
            if not form_data['roles']:
                form_errors['roles'] = 'Select at least one role.'
            else:
                invalid_roles = [role for role in form_data['roles'] if role not in role_options]
                if invalid_roles:
                    form_errors['roles'] = 'Selected role is invalid. Please choose from Roles master.'
            if form_data['username'] and TenantUser.objects.filter(username__iexact=form_data['username']).exclude(pk=tenant_user.pk).exists():
                form_errors['username'] = 'This username already exists in this tenant.'
            if form_data['email'] and TenantUser.objects.filter(email__iexact=form_data['email']).exclude(pk=tenant_user.pk).exists():
                form_errors['email'] = 'This email already exists in this tenant.'
            tenant_primary_email = (context['tenant'].primary_email or '').strip().lower()
            if form_data['email'] and tenant_primary_email and form_data['email'] == tenant_primary_email:
                form_errors['email'] = (
                    'Tenant user email cannot be the same as the tenant primary login email.'
                )

            if form_errors:
                context.update(
                    {
                        'role_options': role_options,
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': True,
                        'is_view_mode': False,
                        'editing_user': tenant_user,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Users-administration-create.html',
                    context,
                )

            tenant_user.username = form_data['username']
            tenant_user.full_name = form_data['full_name']
            tenant_user.email = form_data['email']
            tenant_user.mobile_country_code = form_data['mobile_country_code']
            tenant_user.mobile_no = form_data['mobile_no']
            tenant_user.status = form_data['status']
            tenant_user.role_name = form_data['roles'][0]
            tenant_user.save()

            messages.success(request, 'Tenant user updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationToggleStatusView(View):
    """Activate/deactivate tenant user."""

    def post(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
            tenant_user.status = (
                TenantUser.Status.INACTIVE
                if tenant_user.status == TenantUser.Status.ACTIVE
                else TenantUser.Status.ACTIVE
            )
            tenant_user.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'User status changed to {tenant_user.status}.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationDeleteView(View):
    """Delete tenant user from current tenant schema."""

    def post(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
            tenant_user.delete()
            messages.success(request, 'User deleted successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationExportView(View):
    """Export current tenant users as CSV."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_users = TenantUser.objects.all().order_by('created_at', 'updated_at')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="tenant_users_export.csv"'

            writer = csv.writer(response)
            writer.writerow([
                'User Ref No',
                'User ID',
                'Full Name',
                'Email',
                'Username',
                'Role',
                'Status',
                'Last Login',
                'Login Attempts',
                'Created By',
                'Created At',
                'Updated At',
            ])
            for tenant_user in tenant_users:
                writer.writerow([
                    tenant_user.tenant_ref_no,
                    str(tenant_user.user_id),
                    tenant_user.full_name,
                    tenant_user.email,
                    tenant_user.username,
                    tenant_user.role_name,
                    tenant_user.status,
                    tenant_user.last_login_at.isoformat() if tenant_user.last_login_at else '',
                    tenant_user.login_attempts,
                    tenant_user.created_by_label,
                    tenant_user.created_at.isoformat() if tenant_user.created_at else '',
                    tenant_user.updated_at.isoformat() if tenant_user.updated_at else '',
                ])
            return response
        finally:
            connection.set_schema_to_public()


def _tenant_role_form_data_from_post(request):
    return {
        'role_name_en': (request.POST.get('role_name_en') or '').strip(),
        'role_name_ar': (request.POST.get('role_name_ar') or '').strip(),
        'description_en': (request.POST.get('description_en') or '').strip(),
        'description_ar': (request.POST.get('description_ar') or '').strip(),
        'status': 'Active' if request.POST.get('status') == 'on' else 'Inactive',
    }


def _tenant_role_form_data_from_model(role):
    return {
        'role_name_en': role.role_name_en,
        'role_name_ar': role.role_name_ar,
        'description_en': role.description_en,
        'description_ar': role.description_ar,
        'created_by_label': role.created_by_label,
        'status': role.status,
    }


def _permissions_payload_from_post(request):
    rows = []
    for idx, item in enumerate(TENANT_PERMISSION_MATRIX):
        rows.append(
            {
                'module_name': item['module_name'],
                'form_name': item['form_name'],
                'can_view': request.POST.get(f'perm_{idx}_view') == 'on',
                'can_create': request.POST.get(f'perm_{idx}_create') == 'on',
                'can_edit': request.POST.get(f'perm_{idx}_edit') == 'on',
                'can_delete': request.POST.get(f'perm_{idx}_delete') == 'on',
                'can_post': request.POST.get(f'perm_{idx}_post') == 'on',
                'can_approve': request.POST.get(f'perm_{idx}_approve') == 'on',
                'can_export': request.POST.get(f'perm_{idx}_export') == 'on',
                'can_print': request.POST.get(f'perm_{idx}_print') == 'on',
            }
        )
    return rows


def _permissions_by_key(role):
    perms = {}
    for permission in role.permissions.all():
        key = f'{permission.module_name}|{permission.form_name}'
        perms[key] = {
            'can_view': permission.can_view,
            'can_create': permission.can_create,
            'can_edit': permission.can_edit,
            'can_delete': permission.can_delete,
            'can_post': permission.can_post,
            'can_approve': permission.can_approve,
            'can_export': permission.can_export,
            'can_print': permission.can_print,
        }
    return perms


def _permission_matrix_with_values(permission_map=None):
    permission_map = permission_map or {}
    matrix_rows = []
    for item in TENANT_PERMISSION_MATRIX:
        key = f"{item['module_name']}|{item['form_name']}"
        matrix_rows.append(
            {
                'module_name': item['module_name'],
                'form_name': item['form_name'],
                'can_view': permission_map.get(key, {}).get('can_view', False),
                'can_create': permission_map.get(key, {}).get('can_create', False),
                'can_edit': permission_map.get(key, {}).get('can_edit', False),
                'can_delete': permission_map.get(key, {}).get('can_delete', False),
                'can_post': permission_map.get(key, {}).get('can_post', False),
                'can_approve': permission_map.get(key, {}).get('can_approve', False),
                'can_export': permission_map.get(key, {}).get('can_export', False),
                'can_print': permission_map.get(key, {}).get('can_print', False),
            }
        )
    return matrix_rows


class TenantRolesPermissionsView(View):
    """Tenant roles and permissions list page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_roles = list(TenantRole.objects.all().order_by('-created_at', '-updated_at')[:100])
            total_roles = len(tenant_roles)
            active_roles = sum(1 for role in tenant_roles if role.status == TenantRole.Status.ACTIVE)
            inactive_roles = sum(1 for role in tenant_roles if role.status == TenantRole.Status.INACTIVE)
            draft_roles = sum(1 for role in tenant_roles if role.status == TenantRole.Status.DRAFT)
            context.update(
                {
                    'tenant_roles': tenant_roles,
                    'roles_total_count': total_roles,
                    'roles_active_count': active_roles,
                    'roles_inactive_count': inactive_roles,
                    'roles_draft_count': draft_roles,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
        finally:
            connection.set_schema_to_public()
        return render(
            request,
            'iroad_tenants/User_Management/Role/Roles--permissions.html',
            context,
        )


class TenantRolesPermissionsCreateView(View):
    """Tenant role create page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        context.update(
            {
                'form_data': {
                    'status': 'Active',
                    'created_by_label': (context.get('display_name') or '').strip(),
                },
                'form_errors': {},
                'permission_matrix': _permission_matrix_with_values(),
                'is_edit_mode': False,
                'is_view_mode': False,
            }
        )
        return render(
            request,
            'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
            context,
        )

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        form_data = _tenant_role_form_data_from_post(request)
        form_data['created_by_label'] = (context.get('display_name') or '').strip()
        permissions_payload = _permissions_payload_from_post(request)
        form_errors = {}
        try:
            if not form_data['role_name_en']:
                form_errors['role_name_en'] = 'Role name in English is required.'
            if not form_data['role_name_ar']:
                form_errors['role_name_ar'] = 'Role name in Arabic is required.'
            if form_data['role_name_en'] and TenantRole.objects.filter(
                role_name_en__iexact=form_data['role_name_en']
            ).exists():
                form_errors['role_name_en'] = 'This role name already exists in this tenant.'
            if form_data['role_name_ar'] and TenantRole.objects.filter(
                role_name_ar__iexact=form_data['role_name_ar']
            ).exists():
                form_errors['role_name_ar'] = 'This Arabic role name already exists in this tenant.'

            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'permission_matrix': permissions_payload,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': False,
                        'is_view_mode': False,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
                    context,
                )

            tenant_role = TenantRole.objects.create(
                role_name_en=form_data['role_name_en'],
                role_name_ar=form_data['role_name_ar'],
                description_en=form_data['description_en'],
                description_ar=form_data['description_ar'],
                status=form_data['status'],
                created_by_label=(context.get('display_name') or '').strip(),
            )
            TenantRolePermission.objects.bulk_create(
                [
                    TenantRolePermission(
                        role=tenant_role,
                        module_name=item['module_name'],
                        form_name=item['form_name'],
                        can_view=item['can_view'],
                        can_create=item['can_create'],
                        can_edit=item['can_edit'],
                        can_delete=item['can_delete'],
                        can_post=item['can_post'],
                        can_approve=item['can_approve'],
                        can_export=item['can_export'],
                        can_print=item['can_print'],
                    )
                    for item in permissions_payload
                ]
            )
            messages.success(request, 'Role created successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsEditView(View):
    """Tenant role edit/view page."""

    def get(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).prefetch_related('permissions').first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
            is_view_mode = request.GET.get('mode') == 'view'
            context.update(
                {
                    'form_data': {
                        **_tenant_role_form_data_from_model(tenant_role),
                        'created_by_label': (context.get('display_name') or '').strip(),
                    },
                    'form_errors': {},
                    'permission_matrix': _permission_matrix_with_values(_permissions_by_key(tenant_role)),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': True,
                    'is_view_mode': is_view_mode,
                    'editing_role': tenant_role,
                }
            )
            return render(
                request,
                'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
                context,
            )
        finally:
            connection.set_schema_to_public()

    def post(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        form_data = _tenant_role_form_data_from_post(request)
        form_data['created_by_label'] = (context.get('display_name') or '').strip()
        permissions_payload = _permissions_payload_from_post(request)
        form_errors = {}
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')

            if not form_data['role_name_en']:
                form_errors['role_name_en'] = 'Role name in English is required.'
            if not form_data['role_name_ar']:
                form_errors['role_name_ar'] = 'Role name in Arabic is required.'
            if form_data['role_name_en'] and TenantRole.objects.filter(
                role_name_en__iexact=form_data['role_name_en']
            ).exclude(pk=tenant_role.pk).exists():
                form_errors['role_name_en'] = 'This role name already exists in this tenant.'
            if form_data['role_name_ar'] and TenantRole.objects.filter(
                role_name_ar__iexact=form_data['role_name_ar']
            ).exclude(pk=tenant_role.pk).exists():
                form_errors['role_name_ar'] = 'This Arabic role name already exists in this tenant.'

            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'permission_matrix': permissions_payload,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': True,
                        'is_view_mode': False,
                        'editing_role': tenant_role,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
                    context,
                )

            tenant_role.role_name_en = form_data['role_name_en']
            tenant_role.role_name_ar = form_data['role_name_ar']
            tenant_role.description_en = form_data['description_en']
            tenant_role.description_ar = form_data['description_ar']
            tenant_role.status = form_data['status']
            tenant_role.created_by_label = (context.get('display_name') or '').strip()
            tenant_role.save()

            TenantRolePermission.objects.filter(role=tenant_role).delete()
            TenantRolePermission.objects.bulk_create(
                [
                    TenantRolePermission(
                        role=tenant_role,
                        module_name=item['module_name'],
                        form_name=item['form_name'],
                        can_view=item['can_view'],
                        can_create=item['can_create'],
                        can_edit=item['can_edit'],
                        can_delete=item['can_delete'],
                        can_post=item['can_post'],
                        can_approve=item['can_approve'],
                        can_export=item['can_export'],
                        can_print=item['can_print'],
                    )
                    for item in permissions_payload
                ]
            )
            messages.success(request, 'Role updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsToggleStatusView(View):
    """Activate/deactivate tenant role."""

    def post(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
            tenant_role.status = (
                TenantRole.Status.INACTIVE
                if tenant_role.status == TenantRole.Status.ACTIVE
                else TenantRole.Status.ACTIVE
            )
            tenant_role.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'Role status changed to {tenant_role.status}.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsDeleteView(View):
    """Delete tenant role from current tenant schema."""

    def post(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
            tenant_role.delete()
            messages.success(request, 'Role deleted successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsExportView(View):
    """Export current tenant roles as CSV."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_roles = TenantRole.objects.all().order_by('created_at', 'updated_at')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="tenant_roles_export.csv"'

            writer = csv.writer(response)
            writer.writerow(
                [
                    'Role ID',
                    'Role Name (English)',
                    'Role Name (Arabic)',
                    'Description (English)',
                    'Description (Arabic)',
                    'Status',
                    'Created By',
                    'Created At',
                    'Updated At',
                ]
            )
            for tenant_role in tenant_roles:
                writer.writerow(
                    [
                        str(tenant_role.role_id),
                        tenant_role.role_name_en,
                        tenant_role.role_name_ar,
                        tenant_role.description_en,
                        tenant_role.description_ar,
                        tenant_role.status,
                        tenant_role.created_by_label,
                        tenant_role.created_at.isoformat() if tenant_role.created_at else '',
                        tenant_role.updated_at.isoformat() if tenant_role.updated_at else '',
                    ]
                )
            return response
        finally:
            connection.set_schema_to_public()


def _active_currency_options():
    """Active ISO currencies from superadmin master data (``master_currencies``)."""
    return list(
        Currency.objects.filter(is_active=True)
        .order_by('name_en', 'currency_code')
        .values('currency_code', 'name_en')
    )


def _organization_form_context(profile):
    selected_timezone = (profile.timezone or 'Asia/Riyadh').strip() or 'Asia/Riyadh'
    return {
        'org': profile,
        'owner_label': _owner_user_label(profile.owner_user_id),
        'logo_display_name': _logo_display_name(profile),
        'countries': list(
            Country.objects.filter(is_active=True).order_by('name_en').values(
                'country_code',
                'name_en',
            ),
        ),
        'currencies': list(
            Currency.objects.filter(is_active=True).order_by('currency_code').values(
                'currency_code',
                'name_en',
            ),
        ),
        'date_format_choices': OrganizationProfile.DATE_FORMAT_CHOICES,
        'number_format_choices': OrganizationProfile.NUMBER_FORMAT_CHOICES,
        'negative_format_choices': OrganizationProfile.NEGATIVE_FORMAT_CHOICES,
        'language_choices': OrganizationProfile.SYSTEM_LANGUAGE_CHOICES,
        'selected_timezone': selected_timezone,
        'timezone_choices': [
            'Asia/Riyadh',
            'UTC',
            'Asia/Dubai',
            'Europe/London',
        ],
        'org_status_label': 'Active',
    }


def _owner_user_label(owner_user_id):
    if not owner_user_id:
        return 'N/A'
    # In tenant workspace, owner_user_id is seeded from signup tenant profile id.
    tenant_owner = TenantProfile.objects.filter(pk=owner_user_id).first()
    if tenant_owner:
        tenant_name = (
            f"{(tenant_owner.first_name or '').strip()} {(tenant_owner.last_name or '').strip()}"
        ).strip()
        if tenant_name:
            return tenant_name
        return (tenant_owner.company_name or tenant_owner.primary_email or 'N/A').strip()

    # Fallback: support admin user ids if used by future migrations.
    owner = AdminUser.objects.filter(pk=owner_user_id).first()
    if owner:
        label = f'{owner.first_name} {owner.last_name}'.strip()
        return label or owner.email
    return 'N/A'


def _logo_display_name(profile):
    if not getattr(profile, 'logo_file', None):
        return ''
    return os.path.basename(profile.logo_file.name or '')


def _organization_status_from_tenant(tenant):
    """Map superadmin account status to Organization Profile read-only status."""
    status = (getattr(tenant, 'account_status', '') or '').strip()
    if status == 'Active':
        return 'Active'
    if status.startswith('Suspended_'):
        return 'Suspended'
    # Keep UI constrained to the documented values.
    return 'Suspended'


def _get_or_create_organization_profile(tenant):
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code='organization-profile',
        defaults={
            'form_label': 'Organization Profile',
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    # Use a deterministic "active" record in case historical duplicates exist.
    profile = (
        OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
    )
    if profile:
        if not profile.owner_user_id:
            profile.owner_user_id = str(tenant.pk)
            profile.save(update_fields=['owner_user_id', 'updated_at'])
        return profile

    seq, _ = AutoNumberSequence.objects.get_or_create(
        form_code='organization-profile',
        defaults={'next_number': 1},
    )
    account_sequence = seq.next_number
    ref_no = _render_tenant_ref_no(account_sequence, config, prefix='ORG')

    default_currency = (
        Currency.objects.filter(is_active=True).order_by('currency_code').first()
    )
    default_country = (
        Country.objects.filter(is_active=True).order_by('name_en').first()
    )

    profile = OrganizationProfile.objects.create(
        tenant_ref_no=ref_no,
        account_sequence=account_sequence,
        owner_user_id=str(tenant.pk),
        name_ar=tenant.company_name or '',
        name_en=tenant.company_name or '',
        cr_number=tenant.registration_number or '',
        tax_number=tenant.tax_number or '',
        primary_email=tenant.primary_email or '',
        primary_mobile=tenant.primary_phone or '',
        country_code=(default_country.country_code if default_country else ''),
        base_currency_code=(default_currency.currency_code if default_currency else ''),
        timezone='Asia/Riyadh',
    )
    seq.next_number = account_sequence + 1
    seq.save(update_fields=['next_number', 'updated_at'])
    return profile


def _sync_tenant_ref_if_config_changed(profile):
    config = AutoNumberConfiguration.objects.filter(
        form_code='organization-profile',
    ).first()
    if not config:
        return
    expected = _render_tenant_ref_no(profile.account_sequence, config, prefix='ORG')
    if profile.tenant_ref_no != expected:
        profile.tenant_ref_no = expected
        profile.save(update_fields=['tenant_ref_no', 'updated_at'])


def _render_tenant_ref_no(sequence, config, prefix='ORG'):
    n = int(sequence or 1)
    digits = max(1, int(config.number_of_digits or 4))
    if config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHA:
        rendered = _int_to_alpha(n).rjust(digits, 'A')
    elif config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHANUMERIC:
        number_digits = max(1, digits - 1)
        rendered = f'{_int_to_alpha(n)}{str(n).zfill(number_digits)}'
    else:
        rendered = str(n).zfill(digits)
    return f'{prefix}-{rendered}'


def _next_auto_number_for_form(form_code, form_label, prefix):
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=form_code,
        defaults={
            'form_label': form_label,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence, _ = AutoNumberSequence.objects.get_or_create(
        form_code=form_code,
        defaults={'next_number': 1},
    )
    account_sequence = int(sequence.next_number or 1)
    ref_no = _render_tenant_ref_no(account_sequence, config, prefix=prefix)
    sequence.next_number = account_sequence + 1
    sequence.save(update_fields=['next_number', 'updated_at'])
    return ref_no, account_sequence


def _preview_next_address_master_code():
    """Next AD-xxxx preview in tenant schema without consuming the sequence."""
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=ADDRESS_MASTER_AUTO_FORM_CODE,
        defaults={
            'form_label': ADDRESS_MASTER_AUTO_FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence = AutoNumberSequence.objects.filter(
        form_code=ADDRESS_MASTER_AUTO_FORM_CODE,
    ).first()
    next_seq = sequence.next_number if sequence else 1
    return _render_tenant_ref_no(next_seq, config, prefix=ADDRESS_MASTER_REF_PREFIX)


def _preview_next_cargo_master_code():
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=CARGO_MASTER_AUTO_FORM_CODE,
        defaults={
            'form_label': CARGO_MASTER_AUTO_FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence = AutoNumberSequence.objects.filter(form_code=CARGO_MASTER_AUTO_FORM_CODE).first()
    next_seq = sequence.next_number if sequence else 1
    return _render_tenant_ref_no(next_seq, config, prefix=CARGO_MASTER_REF_PREFIX)


def _preview_next_cargo_category_code():
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=CARGO_CATEGORY_AUTO_FORM_CODE,
        defaults={
            'form_label': CARGO_CATEGORY_AUTO_FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence = AutoNumberSequence.objects.filter(form_code=CARGO_CATEGORY_AUTO_FORM_CODE).first()
    next_seq = sequence.next_number if sequence else 1
    return _render_tenant_ref_no(next_seq, config, prefix=CARGO_CATEGORY_REF_PREFIX)


def _preview_next_location_master_code():
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=LOCATION_MASTER_AUTO_FORM_CODE,
        defaults={
            'form_label': LOCATION_MASTER_AUTO_FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence = AutoNumberSequence.objects.filter(form_code=LOCATION_MASTER_AUTO_FORM_CODE).first()
    next_seq = sequence.next_number if sequence else 1
    return _render_tenant_ref_no(next_seq, config, prefix=LOCATION_MASTER_REF_PREFIX)


def _preview_next_route_master_code():
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=ROUTE_MASTER_AUTO_FORM_CODE,
        defaults={
            'form_label': ROUTE_MASTER_AUTO_FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence = AutoNumberSequence.objects.filter(form_code=ROUTE_MASTER_AUTO_FORM_CODE).first()
    next_seq = sequence.next_number if sequence else 1
    return _render_tenant_ref_no(next_seq, config, prefix=ROUTE_MASTER_REF_PREFIX)


def _validate_cargo_attachment_upload(upload):
    if not upload:
        return ''
    try:
        size = int(upload.size)
    except (TypeError, ValueError):
        size = 0
    if size > MAX_CARGO_ATTACHMENT_BYTES:
        return 'Each attachment must be 10MB or smaller.'
    return ''


def _save_cargo_master_attachments_from_request(request, cargo):
    for upload in request.FILES.getlist('attachments'):
        err = _validate_cargo_attachment_upload(upload)
        if err:
            raise ValidationError(err)
        TenantCargoMasterAttachment.objects.create(cargo_master=cargo, file=upload)


def _cargo_master_list_stats(qs):
    """Stats over current filtered queryset (not paginated slice)."""
    total = qs.count()
    active = qs.filter(status=TenantCargoMaster.Status.ACTIVE).count()
    refrigerated = qs.filter(refrigerated_goods=True).count()
    dangerous = qs.filter(dangerous_goods=True).count()
    return {
        'total': total,
        'active': active,
        'refrigerated': refrigerated,
        'dangerous': dangerous,
    }


def _preview_next_contract_code():
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=CLIENT_CONTRACT_AUTO_FORM_CODE,
        defaults={
            'form_label': CLIENT_CONTRACT_AUTO_FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence = AutoNumberSequence.objects.filter(
        form_code=CLIENT_CONTRACT_AUTO_FORM_CODE,
    ).first()
    next_seq = sequence.next_number if sequence else 1
    return _render_tenant_ref_no(next_seq, config, prefix=CLIENT_CONTRACT_REF_PREFIX)


def _int_to_alpha(value):
    num = max(1, int(value))
    chars = []
    while num > 0:
        num, rem = divmod(num - 1, 26)
        chars.append(chr(65 + rem))
    return ''.join(reversed(chars))


def _apply_organization_profile_post(request, profile):
    post = request.POST
    name_ar = (post.get('name_ar') or '').strip()
    name_en = (post.get('name_en') or '').strip()
    cr_number = (post.get('cr_number') or '').strip()
    tax_number = (post.get('tax_number') or '').strip()
    country_code = (post.get('country_code') or '').strip().upper()
    city = (post.get('city') or '').strip()
    street = (post.get('street') or '').strip()
    address_line_1 = (post.get('address_line_1') or '').strip()
    primary_email = (post.get('primary_email') or '').strip()
    primary_mobile = (post.get('primary_mobile') or '').strip()

    # Preserve existing required values when user updates only a subset
    # (e.g. uploading logo), instead of wiping them to empty strings.
    profile.name_ar = name_ar or profile.name_ar
    profile.name_en = name_en or profile.name_en
    profile.cr_number = cr_number or profile.cr_number
    profile.tax_number = tax_number or profile.tax_number
    profile.country_code = country_code or profile.country_code
    profile.city = city or profile.city
    profile.district = (post.get('district') or '').strip()
    profile.street = street or profile.street
    profile.building_no = (post.get('building_no') or '').strip()
    profile.postal_code = (post.get('postal_code') or '').strip()
    profile.address_line_1 = address_line_1 or profile.address_line_1
    profile.address_line_2 = (post.get('address_line_2') or '').strip()
    profile.primary_email = primary_email or profile.primary_email
    profile.primary_mobile = primary_mobile or profile.primary_mobile
    profile.website = (post.get('website') or '').strip()
    if 'secondary_currency_code' in post:
        profile.secondary_currency_code = (post.get('secondary_currency_code') or '').strip().upper()
    if 'support_email' in post:
        profile.support_email = (post.get('support_email') or '').strip()
    if 'support_mobile_1' in post:
        profile.support_mobile_1 = (post.get('support_mobile_1') or '').strip()
    if 'support_mobile_2' in post:
        profile.support_mobile_2 = (post.get('support_mobile_2') or '').strip()
    if 'driver_instructions' in post:
        profile.driver_instructions = (post.get('driver_instructions') or '').strip()
    profile.system_language = (post.get('system_language') or 'en').strip()
    profile.timezone = (post.get('timezone') or 'Asia/Riyadh').strip()
    profile.date_format = (post.get('date_format') or 'DD/MM/YYYY').strip()
    profile.number_format = (post.get('number_format') or '1,234.56').strip()
    profile.negative_format = (post.get('negative_format') or '-100').strip()

    new_base_currency = (post.get('base_currency_code') or '').strip().upper()
    if profile.base_currency_code and new_base_currency and new_base_currency != profile.base_currency_code:
        raise ValueError('Base Currency is immutable after initial setup.')
    if not profile.base_currency_code:
        profile.base_currency_code = new_base_currency

    logo_file = request.FILES.get('logo_file')
    clear_logo = (post.get('clear_logo') or '').strip() == '1'
    if clear_logo:
        if profile.logo_file:
            profile.logo_file.delete(save=False)
        profile.logo_file = None
    if logo_file:
        ext = os.path.splitext(logo_file.name or '')[1].lower() or '.png'
        logo_file.name = f'org_{profile.id}_{uuid.uuid4().hex[:10]}{ext}'
        profile.logo_file = logo_file

    # Keep updates resilient for partially-initialized legacy records:
    # allow partial saves (e.g. logo upload) while still validating
    # critical format rules when values are provided.
    if profile.cr_number and not profile.cr_number.isdigit():
        raise ValueError('CR Number must be numeric.')
