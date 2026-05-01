import csv
from decimal import Decimal

import logging
import io
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, connection
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime
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
    TenantClientAccount,
    TenantRole,
    TenantRolePermission,
    TenantUser,
)
from iroad_tenants.models import TenantPaymentCard, TenantRegistry
from iroad_tenants.forms_tenant_address import TenantAddressMasterForm

logger = logging.getLogger(__name__)

ADDRESS_MASTER_AUTO_FORM_CODE = 'address-master'
ADDRESS_MASTER_AUTO_FORM_LABEL = 'Address Master'
ADDRESS_MASTER_REF_PREFIX = 'AD'


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


class TenantClientAccountView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-account.html'


class TenantClientAccountSettingsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-account-setting.html'


class TenantClientAccountCreateView(TenantSimplePageView):
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
            form_data = self._base_form_data()
            form_data['account_no'] = self._build_preview_account_no()
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
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
        form_data = self._collect_form_data(request)
        form_errors = {}
        try:
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
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            account_no, account_sequence = _next_auto_number_for_form(
                form_code=self.CLIENT_FORM_CODE,
                form_label=self.CLIENT_FORM_LABEL,
                prefix=self.CLIENT_REF_PREFIX,
            )
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
                commercial_registration_no=form_data['commercial_registration_no'],
                tax_registration_no=form_data['tax_registration_no'],
                created_by_label=(context.get('display_name') or '').strip(),
            )
            messages.success(
                request,
                f'Client account {account_no} created successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-attachments.html'


class TenantClientAttachmentsListView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-attachments-list.html'


class TenantClientContactsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contacts.html'


class TenantClientContactsListView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contacts-list.html'


class TenantClientContractView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contract.html'


class TenantClientContractListView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contract-list.html'


class TenantClientContractSettingsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contract-settings.html'


class TenantClientDetailsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/client-details.html'


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
                is_create=True,
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
                is_create=True,
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
                is_create=False,
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
                is_create=False,
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
    ALLOWED_SEQUENCE_FORMATS = {'numeric', 'alpha', 'alphanumeric'}

    FORM_LABELS = {
        ORGANIZATION_FORM_CODE: ORGANIZATION_FORM_LABEL,
        USERS_FORM_CODE: USERS_FORM_LABEL,
        CLIENT_ACCOUNT_FORM_CODE: CLIENT_ACCOUNT_FORM_LABEL,
        ADDRESS_MASTER_AUTO_FORM_CODE: ADDRESS_MASTER_AUTO_FORM_LABEL,
    }

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
            requested_form_code = (request.GET.get('form_code') or self.ORGANIZATION_FORM_CODE).strip()
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

        selected_form = (request.POST.get('form_code') or '').strip()
        if selected_form not in self.FORM_LABELS:
            messages.error(
                request,
                'Invalid auto number form selected.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_auto_number_configuration')

        try:
            config = self._load_config(selected_form)
            digits_raw = (request.POST.get('number_of_digits') or '').strip()
            sequence_format = (request.POST.get('sequence_format') or '').strip()

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
        finally:
            connection.set_schema_to_public()

        return redirect(f"{reverse('iroad_tenants:tenant_auto_number_configuration')}?form_code={selected_form}")


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
        rendered = _int_to_alpha(n)
    elif config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHANUMERIC:
        rendered = f'A{str(n).zfill(digits)}'
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
