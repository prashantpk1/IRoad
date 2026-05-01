import csv
from decimal import Decimal
from django.core.exceptions import ValidationError
import re

import logging
import io
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.validators import validate_email
from django.core.paginator import Paginator
from django.db import connection
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
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
    TenantClientAccount,
    TenantClientAttachment,
    TenantClientContact,
    TenantClientContract,
    TenantClientContractSetting,
    TenantClientAccountSetting,
    TenantRole,
    TenantRolePermission,
    TenantUser,
)
from iroad_tenants.models import TenantPaymentCard, TenantRegistry

logger = logging.getLogger(__name__)


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
                TenantClientAccount.objects.order_by('-created_at')
            )
        finally:
            connection.set_schema_to_public()
        context.update(
            {
                'client_accounts': client_accounts,
                'client_accounts_count': len(client_accounts),
                'tenant_schema_name': tenant_registry.schema_name,
            }
        )
        return render(request, self.template_name, context)


class TenantClientAccountSettingsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-account-setting.html'

    def _get_client_account_settings(self):
        return TenantClientAccountSetting.objects.get_or_create(
            defaults={
                'require_national_id_individual': True,
                'require_commercial_registration_business': False,
                'require_tax_vat_registration_business': False,
                'default_client_status': TenantClientAccountSetting.DefaultClientStatus.ACTIVE,
                'default_client_type': TenantClientAccountSetting.DefaultClientType.INDIVIDUAL,
                'default_preferred_currency': '',
            }
        )[0]

    def _available_currencies(self):
        return list(
            Currency.objects.filter(is_active=True)
            .order_by('name_en')
            .values('currency_code', 'name_en')
        )

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
            settings_obj = self._get_client_account_settings()
            context.update(
                {
                    'settings_data': settings_obj,
                    'currency_options': self._available_currencies(),
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
            settings_obj = self._get_client_account_settings()
            default_status = (request.POST.get('default_client_status') or '').strip()
            default_type = (request.POST.get('default_client_type') or '').strip()
            default_currency = (request.POST.get('default_preferred_currency') or '').strip().upper()

            errors = {}
            if default_status not in {
                TenantClientAccountSetting.DefaultClientStatus.ACTIVE,
                TenantClientAccountSetting.DefaultClientStatus.INACTIVE,
            }:
                errors['default_client_status'] = 'Invalid default status selected.'
            if default_type not in {
                TenantClientAccountSetting.DefaultClientType.INDIVIDUAL,
                TenantClientAccountSetting.DefaultClientType.BUSINESS,
            }:
                errors['default_client_type'] = 'Invalid default client type selected.'

            if default_currency:
                currency_exists = Currency.objects.filter(
                    currency_code=default_currency,
                    is_active=True,
                ).exists()
                if not currency_exists:
                    errors['default_preferred_currency'] = 'Default preferred currency must exist in active Currency Master.'

            if errors:
                context.update(
                    {
                        'settings_data': settings_obj,
                        'settings_errors': errors,
                        'currency_options': self._available_currencies(),
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted setting errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            settings_obj.require_national_id_individual = request.POST.get('require_national_id_individual') == 'on'
            settings_obj.require_commercial_registration_business = (
                request.POST.get('require_commercial_registration_business') == 'on'
            )
            settings_obj.require_tax_vat_registration_business = (
                request.POST.get('require_tax_vat_registration_business') == 'on'
            )
            settings_obj.default_client_status = default_status
            settings_obj.default_client_type = default_type
            settings_obj.default_preferred_currency = default_currency
            settings_obj.save()

            messages.success(request, 'Client account settings saved successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account_settings')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountCreateView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-account-new.html'

    CLIENT_FORM_CODE = 'client-account'
    CLIENT_FORM_LABEL = 'Client Account'
    CLIENT_REF_PREFIX = 'CA'

    def _get_client_account_settings(self):
        return TenantClientAccountSetting.objects.get_or_create(
            defaults={
                'require_national_id_individual': True,
                'require_commercial_registration_business': False,
                'require_tax_vat_registration_business': False,
                'default_client_status': TenantClientAccountSetting.DefaultClientStatus.ACTIVE,
                'default_client_type': TenantClientAccountSetting.DefaultClientType.INDIVIDUAL,
                'default_preferred_currency': '',
            }
        )[0]

    def _currency_options(self):
        return list(
            Currency.objects.filter(is_active=True)
            .order_by('name_en')
            .values('currency_code', 'name_en')
        )

    def _base_form_data(self):
        return {
            'account_no': '',
            'created_at': timezone.localtime().strftime('%b %d, %Y, %I:%M %p'),
            'client_type': TenantClientAccount.ClientType.INDIVIDUAL,
            'status': TenantClientAccount.Status.ACTIVE,
            'name_arabic': '',
            'name_english': '',
            'display_name': '',
            'national_id': '',
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

    def _validate_form_data(self, form_data):
        form_errors = {}
        settings_obj = self._get_client_account_settings()
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

        if form_data['client_type'] == TenantClientAccount.ClientType.INDIVIDUAL:
            if settings_obj.require_national_id_individual and not form_data['national_id']:
                form_errors['national_id'] = 'National ID is required for Individual client type.'
            # Business-only values should not carry for individual clients.
            form_data['commercial_registration_no'] = ''
            form_data['tax_registration_no'] = ''

        if form_data['client_type'] == TenantClientAccount.ClientType.BUSINESS:
            # Individual-only values should not carry for business clients.
            form_data['national_id'] = ''
            if (
                settings_obj.require_commercial_registration_business
                and not form_data['commercial_registration_no']
            ):
                form_errors['commercial_registration_no'] = (
                    'Commercial Registration No. is required for Business client type.'
                )
            if (
                settings_obj.require_tax_vat_registration_business
                and not form_data['tax_registration_no']
            ):
                form_errors['tax_registration_no'] = (
                    'Tax/VAT Registration No. is required for Business client type.'
                )

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
        return form_errors, credit_limit_amount, payment_term_days

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
            settings_obj = self._get_client_account_settings()
            form_data['client_type'] = settings_obj.default_client_type or TenantClientAccount.ClientType.INDIVIDUAL
            form_data['status'] = settings_obj.default_client_status or TenantClientAccount.Status.ACTIVE
            form_data['preferred_currency'] = settings_obj.default_preferred_currency or ''
            form_data['account_no'] = self._build_preview_account_no()
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'settings_data': settings_obj,
                    'currency_options': self._currency_options(),
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
        try:
            form_errors, credit_limit_amount, payment_term_days = self._validate_form_data(form_data)

            if form_errors:
                form_data['account_no'] = self._build_preview_account_no()
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'settings_data': self._get_client_account_settings(),
                        'currency_options': self._currency_options(),
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
                national_id=form_data['national_id'],
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


class TenantClientAccountEditView(TenantClientAccountCreateView):
    """Edit existing tenant client account."""

    def _form_data_from_model(self, client):
        return {
            'account_no': client.account_no,
            'created_at': timezone.localtime(client.created_at).strftime('%b %d, %Y, %I:%M %p'),
            'client_type': client.client_type,
            'status': client.status,
            'name_arabic': client.name_arabic,
            'name_english': client.name_english,
            'display_name': client.display_name,
            'national_id': client.national_id,
            'preferred_currency': client.preferred_currency,
            'billing_street_1': client.billing_street_1,
            'billing_street_2': client.billing_street_2,
            'billing_city': client.billing_city,
            'billing_region': client.billing_region,
            'postal_code': client.postal_code,
            'country': client.country,
            'credit_limit_amount': str(client.credit_limit_amount),
            'limit_currency_code': client.limit_currency_code or 'SAR',
            'payment_term_days': str(client.payment_term_days),
            'commercial_registration_no': client.commercial_registration_no,
            'tax_registration_no': client.tax_registration_no,
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
            client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            context.update(
                {
                    'form_data': self._form_data_from_model(client),
                    'form_errors': {},
                    'settings_data': self._get_client_account_settings(),
                    'currency_options': self._currency_options(),
                    'is_edit_mode': True,
                    'editing_account_no': client.account_no,
                    'tenant_schema_name': tenant_registry.schema_name,
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
        form_data = self._collect_form_data(request)
        form_data['account_no'] = account_no
        try:
            client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')

            form_errors, credit_limit_amount, payment_term_days = self._validate_form_data(form_data)
            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'settings_data': self._get_client_account_settings(),
                        'currency_options': self._currency_options(),
                        'is_edit_mode': True,
                        'editing_account_no': account_no,
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            client.client_type = form_data['client_type']
            client.status = form_data['status']
            client.name_arabic = form_data['name_arabic']
            client.name_english = form_data['name_english']
            client.display_name = form_data['display_name']
            client.national_id = form_data['national_id']
            client.preferred_currency = form_data['preferred_currency']
            client.billing_street_1 = form_data['billing_street_1']
            client.billing_street_2 = form_data['billing_street_2']
            client.billing_city = form_data['billing_city']
            client.billing_region = form_data['billing_region']
            client.postal_code = form_data['postal_code']
            client.country = form_data['country']
            client.credit_limit_amount = credit_limit_amount
            client.limit_currency_code = form_data['limit_currency_code'] or 'SAR'
            client.payment_term_days = payment_term_days
            client.commercial_registration_no = form_data['commercial_registration_no']
            client.tax_registration_no = form_data['tax_registration_no']
            client.save()

            messages.success(
                request,
                f'Client account {account_no} updated successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountToggleStatusView(View):
    """Activate/deactivate tenant client account."""

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
            client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            client.status = (
                TenantClientAccount.Status.INACTIVE
                if client.status == TenantClientAccount.Status.ACTIVE
                else TenantClientAccount.Status.ACTIVE
            )
            client.save(update_fields=['status', 'updated_at'])
            messages.success(
                request,
                f'Client account {account_no} status changed to {client.status}.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientAccountDeleteView(View):
    """Delete tenant client account."""

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
            client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
            client.delete()
            messages.success(
                request,
                f'Client account {account_no} deleted successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')
        finally:
            connection.set_schema_to_public()


class TenantClientSalesReportView(View):
    """Entry action for Client Details -> Create Sales Report button."""

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
            client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client is None:
                messages.error(request, 'Client account not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_account')

            # Phase 1 bridge: Sales Report module URL is not implemented yet.
            # Route user to billing/invoice area with contextual toast.
            messages.info(
                request,
                f'Sales Report flow for {account_no} will open in billing module. (Phase 1 bridge)',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_subscription_billing')
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-attachments.html'

    ATTACHMENT_FORM_CODE = 'client-attachment'
    ATTACHMENT_FORM_LABEL = 'Client Attachment'
    ATTACHMENT_REF_PREFIX = 'ATT'
    ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.gif'}
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

    def _client_account_options(self):
        return list(
            TenantClientAccount.objects.order_by('account_no').values(
                'account_no',
                'display_name',
                'name_english',
            )
        )

    def _base_form_data(self):
        return {
            'client_account': '',
            'attachment_date': timezone.localdate().isoformat(),
            'is_expiry_applicable': 'false',
            'expiry_date': '',
            'file_notes': '',
        }

    def _collect_form_data(self, request):
        return {
            'client_account': (request.POST.get('client_account') or '').strip(),
            'attachment_date': (request.POST.get('attachment_date') or '').strip(),
            'is_expiry_applicable': (request.POST.get('is_expiry_applicable') or '').strip(),
            'expiry_date': (request.POST.get('expiry_date') or '').strip(),
            'file_notes': (request.POST.get('file_notes') or '').strip(),
        }

    def _build_preview_attachment_no(self):
        config, _ = AutoNumberConfiguration.objects.get_or_create(
            form_code=self.ATTACHMENT_FORM_CODE,
            defaults={
                'form_label': self.ATTACHMENT_FORM_LABEL,
                'number_of_digits': 6,
                'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
                'is_unique': True,
            },
        )
        sequence = AutoNumberSequence.objects.filter(form_code=self.ATTACHMENT_FORM_CODE).first()
        next_number = int(sequence.next_number if sequence else 1)
        return _render_tenant_ref_no(next_number, config, prefix=self.ATTACHMENT_REF_PREFIX)

    def _validate_form(self, form_data, request):
        errors = {}
        client_account = TenantClientAccount.objects.filter(
            account_no=form_data['client_account']
        ).first()
        if client_account is None:
            errors['client_account'] = 'Please select a valid Client Account.'

        attachment_date = parse_date(form_data['attachment_date'] or '')
        if attachment_date is None:
            errors['attachment_date'] = 'Attachment Date is required.'

        is_expiry_applicable = form_data['is_expiry_applicable'] == 'true'
        expiry_date = None
        if is_expiry_applicable:
            expiry_date = parse_date(form_data['expiry_date'] or '')
            if expiry_date is None:
                errors['expiry_date'] = 'Expiry Date is required when expiry is applicable.'

        attachment_file = request.FILES.get('attachment_file')
        if attachment_file is None:
            errors['attachment_file'] = 'Attachment File is required.'
        else:
            ext = os.path.splitext(attachment_file.name or '')[1].lower()
            if ext not in self.ALLOWED_EXTENSIONS:
                errors['attachment_file'] = 'Unsupported file type.'
            elif attachment_file.size and attachment_file.size > self.MAX_FILE_SIZE_BYTES:
                errors['attachment_file'] = 'Attachment file must be 10MB or smaller.'

        return errors, client_account, attachment_date, is_expiry_applicable, expiry_date, attachment_file

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
            # Keep legacy /attachments/ URL list-first in sidebar/navigation.
            # Dedicated create route: /attachments/create/
            if (
                request.resolver_match
                and request.resolver_match.url_name == 'tenant_client_attachments'
                and not (request.GET.get('client_account') or '').strip()
            ):
                return _tenant_redirect(request, 'iroad_tenants:tenant_client_attachments_list')

            form_data = self._base_form_data()
            prefilled_account = (request.GET.get('client_account') or '').strip()
            if prefilled_account:
                form_data['client_account'] = prefilled_account
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': self._client_account_options(),
                    'preview_attachment_no': self._build_preview_attachment_no(),
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
        try:
            (
                errors,
                client_account,
                attachment_date,
                is_expiry_applicable,
                expiry_date,
                attachment_file,
            ) = self._validate_form(form_data, request)
            if errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': errors,
                        'client_account_options': self._client_account_options(),
                        'preview_attachment_no': self._build_preview_attachment_no(),
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            attachment_no, attachment_sequence = _next_auto_number_for_form(
                form_code=self.ATTACHMENT_FORM_CODE,
                form_label=self.ATTACHMENT_FORM_LABEL,
                prefix=self.ATTACHMENT_REF_PREFIX,
            )
            original_ext = os.path.splitext(attachment_file.name or '')[1].lower()
            safe_ext = original_ext if original_ext in self.ALLOWED_EXTENSIONS else '.bin'
            attachment_file.name = (
                f'att_{attachment_no.replace("-", "").lower()}_{uuid.uuid4().hex[:10]}{safe_ext}'
            )
            TenantClientAttachment.objects.create(
                attachment_no=attachment_no,
                attachment_sequence=attachment_sequence,
                client_account=client_account,
                attachment_date=attachment_date,
                is_expiry_applicable=is_expiry_applicable,
                expiry_date=expiry_date if is_expiry_applicable else None,
                attachment_file=attachment_file,
                file_notes=form_data['file_notes'],
                created_by_label=(context.get('display_name') or '').strip(),
            )
            messages.success(
                request,
                f'Client attachment {attachment_no} uploaded successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_attachments_list')
        finally:
            connection.set_schema_to_public()


class TenantClientAttachmentsListView(TenantSimplePageView):
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
            attachments = list(
                TenantClientAttachment.objects.select_related('client_account').order_by('-created_at')
            )
            stats = {
                'total': len(attachments),
                'valid': sum(1 for item in attachments if item.status == TenantClientAttachment.Status.VALID),
                'expired': sum(1 for item in attachments if item.status == TenantClientAttachment.Status.EXPIRED),
                'does_not_expire': sum(
                    1
                    for item in attachments
                    if item.status == TenantClientAttachment.Status.DOES_NOT_EXPIRE
                ),
            }
            context.update(
                {
                    'client_attachments': attachments,
                    'client_attachments_count': len(attachments),
                    'attachment_stats': stats,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContactsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contacts.html'

    def _client_account_options(self):
        return list(
            TenantClientAccount.objects.order_by('account_no').values(
                'account_no',
                'display_name',
                'name_english',
            )
        )

    def _base_form_data(self):
        return {
            'client_account': '',
            'name': '',
            'email': '',
            'mobile_number': '',
            'telephone_number': '',
            'extension': '',
            'position': '',
            'is_primary': 'false',
        }

    def _collect_form_data(self, request):
        return {
            'client_account': (request.POST.get('client_account') or '').strip(),
            'name': (request.POST.get('name') or '').strip(),
            'email': (request.POST.get('email') or '').strip(),
            'mobile_number': (request.POST.get('mobile_number') or '').strip(),
            'telephone_number': (request.POST.get('telephone_number') or '').strip(),
            'extension': (request.POST.get('extension') or '').strip(),
            'position': (request.POST.get('position') or '').strip(),
            'is_primary': (request.POST.get('is_primary') or '').strip(),
        }

    def _validate_form_data(self, form_data):
        errors = {}
        client_account = TenantClientAccount.objects.filter(
            account_no=form_data['client_account']
        ).first()
        if client_account is None:
            errors['client_account'] = 'Please select a valid Client Account.'

        if not form_data['name']:
            errors['name'] = 'Name is required.'

        is_primary = str(form_data['is_primary']).lower() in {'true', 'on', '1', 'yes'}

        if form_data['email']:
            try:
                validate_email(form_data['email'])
            except ValidationError:
                errors['email'] = 'Please enter a valid email address.'

        phone_pattern = re.compile(r'^[0-9+\-\s()]+$')
        if form_data['mobile_number'] and not phone_pattern.match(form_data['mobile_number']):
            errors['mobile_number'] = 'Mobile Number should contain only numeric/phone characters.'
        if form_data['telephone_number'] and not phone_pattern.match(form_data['telephone_number']):
            errors['telephone_number'] = 'Telephone Number should contain only numeric/phone characters.'
        if form_data['extension'] and not re.fullmatch(r'[0-9]+', form_data['extension']):
            errors['extension'] = 'Extension should contain digits only.'

        if client_account is not None:
            has_any_contact = TenantClientContact.objects.filter(
                client_account=client_account
            ).exists()
            has_primary_contact = TenantClientContact.objects.filter(
                client_account=client_account,
                is_primary=True,
            ).exists()
            # Hard rule: every client account must always have one primary contact.
            if (not has_any_contact or not has_primary_contact) and not is_primary:
                errors['is_primary'] = 'Client account must have a Primary Contact. First contact must be marked as Primary.'

        if is_primary and not (
            form_data['email'] or form_data['mobile_number'] or form_data['telephone_number']
        ):
            errors['is_primary'] = (
                'Primary Contact requires at least one reachable method: Email, Mobile, or Telephone.'
            )

        return errors, client_account, is_primary

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
            prefilled_account = (request.GET.get('client_account') or '').strip()
            if prefilled_account:
                form_data['client_account'] = prefilled_account
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': self._client_account_options(),
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
        try:
            form_errors, client_account, is_primary = self._validate_form_data(form_data)
            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'client_account_options': self._client_account_options(),
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            try:
                TenantClientContact.objects.create(
                    client_account=client_account,
                    name=form_data['name'],
                    email=form_data['email'],
                    mobile_number=form_data['mobile_number'],
                    telephone_number=form_data['telephone_number'],
                    extension=form_data['extension'],
                    position=form_data['position'],
                    is_primary=is_primary,
                    created_by_label=(context.get('display_name') or '').strip(),
                )
            except ValidationError as exc:
                error_payload = {}
                if hasattr(exc, 'message_dict'):
                    for field_name, field_messages in exc.message_dict.items():
                        if field_messages:
                            error_payload[field_name] = '; '.join(field_messages)
                elif getattr(exc, 'messages', None):
                    error_payload['is_primary'] = '; '.join(exc.messages)
                if not error_payload:
                    error_payload['is_primary'] = 'Invalid contact data.'
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': error_payload,
                        'client_account_options': self._client_account_options(),
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            messages.success(request, 'Client contact created successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_contacts_list')
        finally:
            connection.set_schema_to_public()


class TenantClientContactsListView(TenantSimplePageView):
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
                TenantClientContact.objects.select_related('client_account').order_by('-created_at')
            )
            stats = {
                'total': len(contacts),
                'primary': sum(1 for c in contacts if c.is_primary),
                'secondary': sum(1 for c in contacts if not c.is_primary),
                'client_accounts': len({str(c.client_account_id) for c in contacts}),
            }
            context.update(
                {
                    'client_contacts': contacts,
                    'client_contacts_count': len(contacts),
                    'contact_stats': stats,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContractView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contract.html'

    CONTRACT_FORM_CODE = 'client-contract'
    CONTRACT_FORM_LABEL = 'Client Contract'
    CONTRACT_REF_PREFIX = 'CC'
    ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.gif'}
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

    def _get_contract_settings(self):
        return TenantClientContractSetting.objects.get_or_create(
            defaults={
                'expired_contract_handling_mode': TenantClientContractSetting.ExpiredContractHandlingMode.DO_NOTHING,
                'grace_period_days': 30,
                'pre_expiry_notification_days': 30,
                'post_expiry_notification_days': 30,
                'notification_frequency': TenantClientContractSetting.NotificationFrequency.DAILY,
                'notification_audience': TenantClientContractSetting.NotificationAudience.SYSTEM_ADMIN,
            }
        )[0]

    def _client_account_options(self):
        return list(
            TenantClientAccount.objects.order_by('account_no').values(
                'account_no',
                'display_name',
                'name_english',
            )
        )

    def _base_form_data(self):
        return {
            'contract_no': '',
            'client_account': '',
            'start_date': '',
            'end_date': '',
            'notes': '',
        }

    def _collect_form_data(self, request):
        return {
            'contract_no': (request.POST.get('contract_no') or '').strip(),
            'client_account': (request.POST.get('client_account') or '').strip(),
            'start_date': (request.POST.get('start_date') or '').strip(),
            'end_date': (request.POST.get('end_date') or '').strip(),
            'notes': (request.POST.get('notes') or '').strip(),
        }

    def _build_preview_contract_no(self):
        config, _ = AutoNumberConfiguration.objects.get_or_create(
            form_code=self.CONTRACT_FORM_CODE,
            defaults={
                'form_label': self.CONTRACT_FORM_LABEL,
                'number_of_digits': 6,
                'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
                'is_unique': True,
            },
        )
        sequence = AutoNumberSequence.objects.filter(form_code=self.CONTRACT_FORM_CODE).first()
        next_number = int(sequence.next_number if sequence else 1)
        return _render_tenant_ref_no(next_number, config, prefix=self.CONTRACT_REF_PREFIX)

    def _validate_form_data(self, form_data, request):
        errors = {}
        client_account = TenantClientAccount.objects.filter(
            account_no=form_data['client_account']
        ).first()
        if client_account is None:
            errors['client_account'] = 'Please select a valid Client Account.'

        start_date = parse_date(form_data['start_date'] or '')
        end_date = parse_date(form_data['end_date'] or '')
        if start_date is None:
            errors['start_date'] = 'Start Date is required.'
        if end_date is None:
            errors['end_date'] = 'End Date is required.'
        if start_date is not None and end_date is not None and end_date <= start_date:
            errors['end_date'] = 'End Date must be greater than Start Date.'

        if client_account is not None and TenantClientContract.objects.filter(
            client_account=client_account
        ).exists():
            errors['client_account'] = 'This Client Account already has a contract in Phase 1.'

        contract_attachment = request.FILES.get('contract_attachment')
        if contract_attachment is None:
            errors['contract_attachment'] = 'Contract Attachment is required.'
        else:
            ext = os.path.splitext(contract_attachment.name or '')[1].lower()
            if ext not in self.ALLOWED_EXTENSIONS:
                errors['contract_attachment'] = 'Unsupported attachment file type.'
            elif contract_attachment.size and contract_attachment.size > self.MAX_FILE_SIZE_BYTES:
                errors['contract_attachment'] = 'Contract attachment must be 10MB or smaller.'

        return errors, client_account, start_date, end_date, contract_attachment

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
            form_data['contract_no'] = self._build_preview_contract_no()
            prefilled_account = (request.GET.get('client_account') or '').strip()
            if prefilled_account:
                form_data['client_account'] = prefilled_account
            context.update(
                {
                    'form_data': form_data,
                    'form_errors': {},
                    'client_account_options': self._client_account_options(),
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
        try:
            # Contract settings are tenant-level and used later by daily checks / notifications.
            # Keeping this call here guarantees the settings row exists in every tenant schema.
            self._get_contract_settings()
            (
                form_errors,
                client_account,
                start_date,
                end_date,
                contract_attachment,
            ) = self._validate_form_data(form_data, request)
            if form_errors:
                if not form_data['contract_no']:
                    form_data['contract_no'] = self._build_preview_contract_no()
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'client_account_options': self._client_account_options(),
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            contract_no, contract_sequence = _next_auto_number_for_form(
                form_code=self.CONTRACT_FORM_CODE,
                form_label=self.CONTRACT_FORM_LABEL,
                prefix=self.CONTRACT_REF_PREFIX,
            )
            TenantClientContract.objects.create(
                contract_no=contract_no,
                contract_sequence=contract_sequence,
                client_account=client_account,
                start_date=start_date,
                end_date=end_date,
                notes=form_data['notes'],
                contract_attachment=contract_attachment,
                created_by_label=(context.get('display_name') or '').strip(),
            )
            messages.success(
                request,
                f'Client contract {contract_no} created successfully.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_contract_list')
        finally:
            connection.set_schema_to_public()


class TenantClientContractListView(TenantSimplePageView):
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
            contracts = list(
                TenantClientContract.objects.select_related('client_account').order_by('-created_at')
            )
            today = timezone.localdate()
            expiring_soon_days = 30
            stats = {
                'total': len(contracts),
                'active': sum(1 for c in contracts if c.status == TenantClientContract.Status.ACTIVE),
                'upcoming': sum(1 for c in contracts if c.status == TenantClientContract.Status.UPCOMING),
                'expiring_soon': sum(
                    1
                    for c in contracts
                    if c.status == TenantClientContract.Status.ACTIVE
                    and 0 <= (c.end_date - today).days <= expiring_soon_days
                ),
                'expired': sum(1 for c in contracts if c.status == TenantClientContract.Status.EXPIRED),
            }
            context.update(
                {
                    'client_contracts': contracts,
                    'client_contracts_count': len(contracts),
                    'contract_stats': stats,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
        finally:
            connection.set_schema_to_public()


class TenantClientContractSettingsView(TenantSimplePageView):
    template_name = 'iroad_tenants/Clients_Management/Client-contract-settings.html'

    def _get_contract_settings(self):
        return TenantClientContractSetting.objects.get_or_create(
            defaults={
                'expired_contract_handling_mode': TenantClientContractSetting.ExpiredContractHandlingMode.DO_NOTHING,
                'grace_period_days': 30,
                'pre_expiry_notification_days': 30,
                'post_expiry_notification_days': 30,
                'notification_frequency': TenantClientContractSetting.NotificationFrequency.DAILY,
                'notification_audience': TenantClientContractSetting.NotificationAudience.SYSTEM_ADMIN,
            }
        )[0]

    def _validate_form_data(self, form_data):
        errors = {}

        if form_data['expired_contract_handling_mode'] not in {
            TenantClientContractSetting.ExpiredContractHandlingMode.AUTO_DEACTIVATE,
            TenantClientContractSetting.ExpiredContractHandlingMode.DO_NOTHING,
            TenantClientContractSetting.ExpiredContractHandlingMode.DEACTIVATE_AFTER_GRACE,
        }:
            errors['expired_contract_handling_mode'] = 'Invalid handling mode.'

        if form_data['notification_frequency'] not in {
            TenantClientContractSetting.NotificationFrequency.ONCE,
            TenantClientContractSetting.NotificationFrequency.DAILY,
            TenantClientContractSetting.NotificationFrequency.WEEKLY,
        }:
            errors['notification_frequency'] = 'Invalid notification frequency.'

        if form_data['notification_audience'] not in {
            TenantClientContractSetting.NotificationAudience.SYSTEM_ADMIN,
            TenantClientContractSetting.NotificationAudience.ADMIN_FINANCE,
        }:
            errors['notification_audience'] = 'Invalid notification audience.'

        def parse_int_with_range(value, field_key, min_val, max_val):
            try:
                parsed = int(value)
            except Exception:
                errors[field_key] = f'{field_key.replace("_", " ").title()} must be a number.'
                return min_val
            if parsed < min_val or parsed > max_val:
                errors[field_key] = (
                    f'{field_key.replace("_", " ").title()} must be between {min_val} and {max_val}.'
                )
            return parsed

        grace_period_days = parse_int_with_range(
            form_data['grace_period_days'], 'grace_period_days', 0, 365
        )
        pre_expiry_notification_days = parse_int_with_range(
            form_data['pre_expiry_notification_days'], 'pre_expiry_notification_days', 0, 180
        )
        post_expiry_notification_days = parse_int_with_range(
            form_data['post_expiry_notification_days'], 'post_expiry_notification_days', 0, 180
        )

        if (
            form_data['expired_contract_handling_mode']
            != TenantClientContractSetting.ExpiredContractHandlingMode.DEACTIVATE_AFTER_GRACE
        ):
            grace_period_days = 30 if grace_period_days < 0 else grace_period_days

        return (
            errors,
            grace_period_days,
            pre_expiry_notification_days,
            post_expiry_notification_days,
        )

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
            settings_obj = self._get_contract_settings()
            context.update(
                {
                    'settings_data': settings_obj,
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
            settings_obj = self._get_contract_settings()
            form_data = {
                'expired_contract_handling_mode': (
                    request.POST.get('expired_contract_handling_mode') or ''
                ).strip(),
                'grace_period_days': (request.POST.get('grace_period_days') or '').strip(),
                'pre_expiry_notification_days': (
                    request.POST.get('pre_expiry_notification_days') or ''
                ).strip(),
                'post_expiry_notification_days': (
                    request.POST.get('post_expiry_notification_days') or ''
                ).strip(),
                'notification_frequency': (request.POST.get('notification_frequency') or '').strip(),
                'notification_audience': (request.POST.get('notification_audience') or '').strip(),
            }

            (
                settings_errors,
                grace_period_days,
                pre_expiry_notification_days,
                post_expiry_notification_days,
            ) = self._validate_form_data(form_data)

            if settings_errors:
                for key, value in form_data.items():
                    setattr(settings_obj, key, value)
                context.update(
                    {
                        'settings_data': settings_obj,
                        'settings_errors': settings_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                    }
                )
                messages.error(request, 'Please fix the highlighted setting errors.', extra_tags='tenant')
                return render(request, self.template_name, context)

            settings_obj.expired_contract_handling_mode = form_data['expired_contract_handling_mode']
            settings_obj.grace_period_days = grace_period_days
            settings_obj.pre_expiry_notification_days = pre_expiry_notification_days
            settings_obj.post_expiry_notification_days = post_expiry_notification_days
            settings_obj.notification_frequency = form_data['notification_frequency']
            settings_obj.notification_audience = form_data['notification_audience']
            settings_obj.save()

            messages.success(request, 'Client contract settings saved successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_client_contract_settings')
        finally:
            connection.set_schema_to_public()


class TenantClientDetailsView(TenantSimplePageView):
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
            client = None
            if account_no:
                client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client is None:
                client = TenantClientAccount.objects.order_by('-created_at').first()

            client_detail = None
            client_contacts = []
            client_attachments = []
            client_contract = None
            primary_contact = None
            if client is not None:
                client_contacts = list(
                    TenantClientContact.objects.filter(client_account=client).order_by('-is_primary', 'name')
                )
                primary_contact = next((item for item in client_contacts if item.is_primary), None)
                if primary_contact is None and client_contacts:
                    primary_contact = client_contacts[0]
                client_attachments = list(
                    TenantClientAttachment.objects.filter(client_account=client).order_by('-created_at')
                )
                client_contract = TenantClientContract.objects.filter(client_account=client).first()
                created_at = timezone.localtime(client.created_at).strftime('%b %d, %Y, %I:%M %p')
                client_detail = {
                    'account_no': client.account_no,
                    'client_type': client.client_type,
                    'status': client.status,
                    'created_at': created_at,
                    'name_arabic': client.name_arabic,
                    'name_english': client.name_english,
                    'display_name': client.display_name,
                    'preferred_currency': client.preferred_currency,
                    'billing_street_1': client.billing_street_1,
                    'billing_street_2': client.billing_street_2,
                    'billing_city': client.billing_city,
                    'billing_region': client.billing_region,
                    'postal_code': client.postal_code,
                    'country': client.country,
                    'commercial_registration_no': client.commercial_registration_no,
                    'tax_registration_no': client.tax_registration_no,
                }

            context.update(
                {
                    'client_detail': client_detail,
                    'client_contacts': client_contacts,
                    'client_attachments': client_attachments,
                    'client_contract': client_contract,
                    'primary_contact': primary_contact,
                    'client_not_found': client_detail is None,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
            return render(request, self.template_name, context)
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
    ALLOWED_SEQUENCE_FORMATS = {'numeric', 'alpha', 'alphanumeric'}

    FORM_LABELS = {
        ORGANIZATION_FORM_CODE: ORGANIZATION_FORM_LABEL,
        USERS_FORM_CODE: USERS_FORM_LABEL,
        CLIENT_ACCOUNT_FORM_CODE: CLIENT_ACCOUNT_FORM_LABEL,
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
