from decimal import Decimal
from datetime import date, timedelta
import ipaddress
import logging
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)


def get_global_system_rules():
    """
    Return the single global rules row, creating the default record if needed.
    """
    from .models import GlobalSystemRules

    obj, _created = GlobalSystemRules.objects.get_or_create(
        rule_id='GLOBAL-SYSTEM-RULES',
        defaults={
            'system_timezone': 'Asia/Riyadh',
            'default_date_format': 'DD/MM/YYYY',
            'grace_period_days': 3,
            'standard_billing_cycle': 30,
        },
    )
    return obj


def get_subscription_grace_days():
    """Grace period used by the expiry suspension job."""
    return int(get_global_system_rules().grace_period_days or 0)


def get_standard_billing_cycle_days():
    """Default billing cycle used where no plan-specific cycle exists."""
    return int(get_global_system_rules().standard_billing_cycle or 30)


def get_plan_cycle_days(plan):
    """Use plan cycle when available, otherwise fall back to global rules."""
    cycle_days = getattr(plan, 'base_cycle_days', None)
    if cycle_days:
        return int(cycle_days)
    return get_standard_billing_cycle_days()


def calculate_promo_discount(promo, sub_total, for_plan=None):
    """Return discount amount from validated promo, capped to sub_total."""
    if not promo:
        return Decimal('0.00')
    ok, _msg = promo.is_valid_for_use(for_plan=for_plan)
    if not ok:
        return Decimal('0.00')
    if promo.discount_type == 'Percentage':
        raw = sub_total * promo.discount_value / Decimal('100')
        return raw.quantize(Decimal('0.01'))
    return min(promo.discount_value, sub_total).quantize(Decimal('0.01'))


def refresh_order_projected_fields(order):
    """
    Update order.projected_* from classification and lines
    (preview of post-payment state).
    """
    tenant = order.tenant
    customer_address_snapshot = ''
    if getattr(tenant, 'country_id', None) and getattr(tenant, 'country', None):
        customer_address_snapshot = tenant.country.name_en or ''
    classification = order.order_classification
    plan_line = order.plan_lines.first() if order.plan_lines.exists() else None

    proj_plan = tenant.current_plan
    proj_expiry = tenant.subscription_expiry_date
    proj_u = tenant.active_max_users
    proj_it = tenant.active_max_internal_trucks
    proj_et = tenant.active_max_external_trucks
    proj_d = tenant.active_max_drivers

    if classification == 'New_Subscription' and plan_line:
        plan = plan_line.plan
        proj_plan = plan
        proj_expiry = date.today() + timedelta(
            days=get_plan_cycle_days(plan) * plan_line.number_of_cycles)
        if plan.max_internal_users != -1:
            proj_u = plan.max_internal_users
        if plan.max_internal_trucks != -1:
            proj_it = plan.max_internal_trucks
        if plan.max_external_trucks != -1:
            proj_et = plan.max_external_trucks
        if plan.max_active_drivers != -1:
            proj_d = plan.max_active_drivers

    elif classification == 'Renewal' and plan_line:
        plan = plan_line.plan
        proj_plan = plan
        extra = get_plan_cycle_days(plan) * plan_line.number_of_cycles
        if tenant.subscription_expiry_date:
            proj_expiry = tenant.subscription_expiry_date + timedelta(days=extra)
        else:
            proj_expiry = date.today() + timedelta(days=extra)

    elif classification == 'Upgrade' and plan_line:
        plan = plan_line.plan
        proj_plan = plan
        proj_expiry = date.today() + timedelta(
            days=get_plan_cycle_days(plan) * plan_line.number_of_cycles)
        if plan.max_internal_users != -1:
            proj_u = plan.max_internal_users
        if plan.max_internal_trucks != -1:
            proj_it = plan.max_internal_trucks
        if plan.max_external_trucks != -1:
            proj_et = plan.max_external_trucks
        if plan.max_active_drivers != -1:
            proj_d = plan.max_active_drivers

    elif classification == 'Downgrade' and plan_line:
        plan = plan_line.plan
        proj_plan = plan
        proj_expiry = tenant.subscription_expiry_date
        if plan.max_internal_users != -1:
            proj_u = plan.max_internal_users
        if plan.max_internal_trucks != -1:
            proj_it = plan.max_internal_trucks
        if plan.max_external_trucks != -1:
            proj_et = plan.max_external_trucks
        if plan.max_active_drivers != -1:
            proj_d = plan.max_active_drivers

    elif classification == 'Add_ons':
        for addon_line in order.addon_lines.all():
            qty = addon_line.quantity
            if addon_line.action_type == 'Reduce':
                qty = -qty
            if addon_line.add_on_type == 'Extra_User':
                proj_u += qty
            elif addon_line.add_on_type == 'Extra_Internal_Truck':
                proj_it += qty
            elif addon_line.add_on_type == 'Extra_External_Truck':
                proj_et += qty
            elif addon_line.add_on_type == 'Extra_Driver':
                proj_d += qty
        proj_plan = tenant.current_plan
        proj_expiry = tenant.subscription_expiry_date

    order.projected_plan = proj_plan
    order.projected_expiry_date = proj_expiry
    order.projected_max_users = proj_u
    order.projected_max_internal_trucks = proj_it
    order.projected_max_external_trucks = proj_et
    order.projected_max_drivers = proj_d


def sync_or_create_order_payment_transaction(order):
    """
    Keep a pending Order_Payment transaction in sync with order totals.
    (Shared with Control Panel order workflow and automated billing.)
    """
    from .models import Transaction

    txn = Transaction.objects.filter(
        order=order,
        transaction_type='Order_Payment',
    ).first()
    if txn:
        txn.amount = order.grand_total
        txn.currency = order.currency
        txn.exchange_rate_snapshot = order.exchange_rate_snapshot
        txn.base_currency_equivalent_amount = order.base_currency_equivalent
        txn.payment_method = order.payment_method
        if txn.status == 'Pending':
            txn.save(update_fields=[
                'amount', 'currency', 'exchange_rate_snapshot',
                'base_currency_equivalent_amount', 'payment_method',
                'updated_at',
            ])
        return txn
    return Transaction.objects.create(
        tenant=order.tenant,
        order=order,
        transaction_type='Order_Payment',
        payment_method=order.payment_method,
        currency=order.currency,
        amount=order.grand_total,
        exchange_rate_snapshot=order.exchange_rate_snapshot,
        base_currency_equivalent_amount=order.base_currency_equivalent,
        status='Pending',
    )


def complete_order_payment_as_system(order, admin_user=None):
    """
    Mark order Paid and run fulfillment (invoice, tenant, LTV) without CP UI.
    ``admin_user`` may be None or the root user for audit context.
    """
    from django.db import transaction as db_transaction
    from .models import Transaction, SubscriptionOrder

    with db_transaction.atomic():
        ord_row = SubscriptionOrder.objects.select_for_update().get(pk=order.pk)
        sync_or_create_order_payment_transaction(ord_row)
        txn = (
            Transaction.objects.select_for_update()
            .filter(
                order=ord_row,
                transaction_type='Order_Payment',
                status='Pending',
            )
            .first()
        )
        if not txn:
            logger.error(
                'Automated pay: no pending txn for order %s',
                ord_row.order_id,
            )
            return False
        if ord_row.grand_total < Decimal('0.01'):
            logger.warning(
                'Automated pay: grand_total too small for txn for order %s',
                ord_row.order_id,
            )
            return False
        txn.status = 'Completed'
        txn.reviewed_by = admin_user
        txn.save(update_fields=[
            'status', 'reviewed_by', 'updated_at',
        ])
        ord_row.order_status = 'Paid'
        ord_row.save(update_fields=['order_status', 'updated_at'])
        fulfill_paid_order(ord_row, admin_user, txn.amount)
    return True


def plan_line_invoice_label(plan_line):
    """Immutable label for invoice PDF (uses DB snapshot when present)."""
    name = (plan_line.plan_name_en_snapshot or '').strip()
    if not name and plan_line.plan_id:
        name = plan_line.plan.plan_name_en
    return f"{name} - {plan_line.number_of_cycles} cycle(s)"


def addon_line_invoice_label(addon_line):
    lab = (addon_line.add_on_type_label_snapshot or '').strip()
    if not lab:
        lab = addon_line.get_add_on_type_display()
    return f"Add-on: {lab} x {addon_line.quantity}"


def create_automated_renewal_after_scheduled_downgrade(tenant, new_plan):
    """
    After scheduled downgrade applies at cycle end: create a Renewal order for
    the next period at the new plan's list price, invoice, and mark Paid
    (system) so revenue and expiry stay aligned.
    """
    from django.db import transaction as db_transaction

    from .models import (
        AdminUser,
        Currency,
        OrderPlanLine,
        PaymentMethod,
        PlanPricingCycle,
        SubscriptionOrder,
    )

    last = (
        SubscriptionOrder.objects.filter(tenant=tenant)
        .order_by('-created_at')
        .first()
    )
    currency = last.currency if last else None
    if not currency:
        currency = Currency.objects.filter(is_active=True).first()
    if not currency:
        logger.error(
            'Downgrade renewal: no currency for tenant %s',
            tenant.tenant_id,
        )
        return None

    ppc = PlanPricingCycle.objects.filter(
        plan=new_plan,
        currency=currency,
        number_of_cycles=1,
    ).first()
    if not ppc:
        logger.warning(
            'Downgrade renewal: no 1-cycle pricing for plan %s currency %s',
            new_plan.plan_id,
            currency.currency_code,
        )
        return None

    tax = get_tax_code_for_tenant(tenant, client_ip=None)
    tax_rate = tax.rate_percent if tax else Decimal('0.00')
    fx = get_fx_snapshot(currency.currency_code, strict=True)
    if fx is None:
        logger.error(
            'Downgrade renewal: missing active FX rate for currency %s',
            currency.currency_code,
        )
        return None
    pm = PaymentMethod.objects.filter(is_active=True).first()

    plan_price = ppc.price
    line_total = plan_price
    sub_total = line_total
    taxable_base = sub_total.quantize(Decimal('0.01'))
    tax_amount = (
        taxable_base * tax_rate / Decimal('100')
    ).quantize(Decimal('0.01'))
    grand_total = (taxable_base + tax_amount).quantize(Decimal('0.01'))
    base_equiv = (grand_total * fx).quantize(Decimal('0.01'))

    system_admin = AdminUser.objects.filter(is_root=True).first()

    with db_transaction.atomic():
        order = SubscriptionOrder.objects.create(
            tenant=tenant,
            order_classification='Renewal',
            currency=currency,
            payment_method=pm,
            created_by=system_admin,
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
            plan=new_plan,
            number_of_cycles=1,
            plan_price=plan_price,
            pro_rata_adjustment=Decimal('0.00'),
            line_total=line_total,
            plan_name_en_snapshot=new_plan.plan_name_en,
            plan_name_ar_snapshot=new_plan.plan_name_ar or '',
        )
        refresh_order_projected_fields(order)
        order.save(update_fields=[
            'projected_plan', 'projected_expiry_date',
            'projected_max_users', 'projected_max_internal_trucks',
            'projected_max_external_trucks', 'projected_max_drivers',
        ])

    if grand_total >= Decimal('0.01'):
        sync_or_create_order_payment_transaction(order)
        complete_order_payment_as_system(order, system_admin)
    else:
        order.order_status = 'Draft'
        order.save(update_fields=['order_status', 'updated_at'])
        logger.warning(
            'Downgrade renewal: total below minimum charge; left as Draft %s',
            order.order_id,
        )
    return order


def scan_active_subscriptions_for_renewal(days_until_expiry=14):
    """
    Ref: CP-PCS-P1 §2.1 - Pro-Rata & Auto-Billing.
    Identify expiring subscriptions and generate automated renewal orders.
    """
    from datetime import date, timedelta
    from .models import TenantProfile, SubscriptionOrder
    
    threshold = date.today() + timedelta(days=days_until_expiry)
    candidates = TenantProfile.objects.filter(
        account_status='Active',
        subscription_expiry_date__isnull=False,
        subscription_expiry_date__lte=threshold,
        current_plan__isnull=False,
    )
    
    generated = 0
    for tenant in candidates:
        # Avoid duplicate pending orders for the same cycle
        existing = SubscriptionOrder.objects.filter(
            tenant=tenant,
            order_classification__in=['Renewal', 'New_Subscription'],
            order_status__in=['Draft', 'Pending_Payment']
        ).exists()
        
        if not existing:
            # Use the automated renewal helper to create next cycle's draft/payment
            create_automated_renewal_after_scheduled_downgrade(tenant, tenant.current_plan)
            generated += 1
            
    return generated


def get_next_invoice_number():
    """
    Generate sequential invoice number.
    Format: INV-YYYY-NNNN
    e.g. INV-2026-0001
    """
    from django.utils import timezone
    from .models import StandardInvoice

    year = timezone.now().year
    prefix = f"INV-{year}-"

    last_invoice = StandardInvoice.objects.filter(
        invoice_number__startswith=prefix
    ).order_by('-invoice_number').first()

    if last_invoice:
        last_seq = int(last_invoice.invoice_number.split('-')[-1])
        new_seq = last_seq + 1
    else:
        new_seq = 1

    return f"{prefix}{str(new_seq).zfill(4)}"


def get_next_credit_note_number():
    """
    Generate sequential credit note number.
    Format: CN-YYYY-NNNN
    e.g. CN-2026-0001
    """
    from django.utils import timezone
    from .models import StandardInvoice

    year = timezone.now().year
    prefix = f"CN-{year}-"
    last = StandardInvoice.objects.filter(
        invoice_number__startswith=prefix
    ).order_by('-invoice_number').first()
    if last:
        last_seq = int(last.invoice_number.split('-')[-1])
        new_seq = last_seq + 1
    else:
        new_seq = 1
    return f"{prefix}{str(new_seq).zfill(4)}"


def get_fx_snapshot(currency_code, strict=False):
    """
    Get current FX rate snapshot for a currency.
    Returns 1.000000 if currency is base currency.
    For non-base currencies, when ``strict=True`` and no active FX row exists,
    returns None so callers can block invalid financial postings.
    """
    from .models import BaseCurrencyConfig, ExchangeRate

    try:
        base_config = BaseCurrencyConfig.objects.get(
            setting_id='GLOBAL-BASE-CURRENCY')
    except Exception:
        return Decimal('1.000000')

    if base_config.base_currency_id == currency_code:
        return Decimal('1.000000')

    try:
        fx = ExchangeRate.objects.get(
            currency_id=currency_code, is_active=True)
        return fx.exchange_rate
    except ExchangeRate.DoesNotExist:
        if strict:
            return None
        return Decimal('1.000000')


def convert_amount_between_currencies(amount, from_code, to_code):
    """
    Convert a monetary amount from from_code to to_code using base-currency
    FX snapshots (same convention as get_fx_snapshot / order totals).
    """
    from_code = str(from_code or '')
    to_code = str(to_code or '')
    amt = Decimal(amount)
    if amt <= 0:
        return Decimal('0.00')
    if from_code == to_code:
        return amt.quantize(Decimal('0.01'))
    fx_from = get_fx_snapshot(from_code)
    fx_to = get_fx_snapshot(to_code)
    if fx_to <= 0:
        return Decimal('0.00')
    in_base = amt * fx_from
    return (in_base / fx_to).quantize(Decimal('0.01'))


def resolve_upgrade_credit_basis_price(plan, target_currency_code):
    """
    One-cycle list price of `plan` in `target_currency_code` for upgrade
    pro-rata credit (Section 2.3.2.A).

    Resolution order:
    1. PlanPricingCycle (plan, target currency, number_of_cycles=1)
    2. Same currency: price / number_of_cycles for the smallest priced tier
    3. Any currency: 1-cycle rows converted via FX
    4. Any tier: per-cycle price (price/cycles), then FX if needed
    """
    from .models import PlanPricingCycle

    if not plan or not target_currency_code:
        return Decimal('0.00')

    target_id = getattr(
        target_currency_code, 'currency_code', str(target_currency_code))

    qs = PlanPricingCycle.objects.filter(plan=plan)

    row = qs.filter(
        currency_id=target_id,
        number_of_cycles=1,
    ).first()
    if row:
        return row.price

    same_currency = list(
        qs.filter(currency_id=target_id).order_by('number_of_cycles'))
    if same_currency:
        r = same_currency[0]
        nc = int(r.number_of_cycles) if r.number_of_cycles else 1
        if nc <= 0:
            nc = 1
        return (r.price / Decimal(nc)).quantize(Decimal('0.01'))

    for r in qs.filter(number_of_cycles=1).order_by('currency_id'):
        conv = convert_amount_between_currencies(
            r.price, r.currency_id, target_id)
        if conv > 0:
            return conv

    for r in qs.order_by('number_of_cycles', 'currency_id'):
        nc = int(r.number_of_cycles) if r.number_of_cycles else 0
        if nc <= 0:
            continue
        per_cycle = r.price / Decimal(nc)
        if r.currency_id == target_id:
            return per_cycle.quantize(Decimal('0.01'))
        conv = convert_amount_between_currencies(
            per_cycle, r.currency_id, target_id)
        if conv > 0:
            return conv

    return Decimal('0.00')


def _is_routable_public_ip(ip_str):
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str.split('%')[0].strip())
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_reserved
            or ip.is_link_local
            or ip.is_multicast
        )
    except ValueError:
        return False


def country_iso_from_ip(client_ip):
    """
    Optional GeoIP2 country (ISO 3166-1 alpha-2). Requires ``GEOIP2_COUNTRY_DB``
    (MaxMind GeoLite2-Country.mmdb path) in settings. Returns None if unset.
    """
    if not client_ip or not _is_routable_public_ip(client_ip):
        return None
    try:
        from django.conf import settings
    except Exception:
        return None

    db_path = getattr(settings, 'GEOIP2_COUNTRY_DB', '') or ''
    if not db_path:
        return None
    if not Path(db_path).is_file():
        logger.warning('GEOIP2_COUNTRY_DB path configured but file missing: %s', db_path)
        return None
    try:
        import geoip2.database
        with geoip2.database.Reader(db_path) as reader:
            return reader.country(client_ip).country.iso_code
    except Exception:
        return None


def get_tax_code_for_tenant(tenant, client_ip=None):
    """
    Tax routing: prefer geolocated country from ``client_ip`` when configured,
    else tenant profile country, then international default (CP-PCS-P1 P9).
    """
    from .models import TaxCode

    resolved_country = country_iso_from_ip(client_ip) if client_ip else None
    if not resolved_country and getattr(tenant, 'country_id', None):
        resolved_country = tenant.country_id

    if resolved_country:
        tax = TaxCode.objects.filter(
            applicable_country_code_id=resolved_country,
            is_default_for_country=True,
            is_active=True,
        ).first()
        if tax:
            return tax

    return TaxCode.objects.filter(
        is_international_default=True,
        is_active=True,
    ).first()


def calculate_pro_rata_credit(tenant, plan_price):
    """
    For Upgrade: calculate credit from unused days
    of current plan.
    Returns Decimal credit amount (negative adjustment).
    """
    today = date.today()

    if not tenant.subscription_expiry_date or \
            not tenant.subscription_start_date:
        return Decimal('0.00')

    total_days = (
        tenant.subscription_expiry_date -
        tenant.subscription_start_date
    ).days

    days_remaining = (
        tenant.subscription_expiry_date - today
    ).days

    if total_days <= 0 or days_remaining <= 0:
        return Decimal('0.00')

    daily_rate = plan_price / Decimal(str(total_days))
    credit = daily_rate * Decimal(str(days_remaining))

    # Return as negative (deduction from new plan)
    return -credit.quantize(Decimal('0.01'))


def tenant_usage_exceeds_plan_limits(tenant, plan):
    """
    Compare tenant active caps to plan limits. -1 on plan means unlimited.
    Returns a list of user-facing violation messages (empty if OK).
    """
    msgs = []
    if plan.max_internal_users != -1 and tenant.active_max_users > plan.max_internal_users:
        msgs.append(
            f'Active user allowance ({tenant.active_max_users}) exceeds the '
            f'target plan limit ({plan.max_internal_users}).'
        )
    if plan.max_internal_trucks != -1 and tenant.active_max_internal_trucks > plan.max_internal_trucks:
        msgs.append(
            f'Active internal truck allowance ({tenant.active_max_internal_trucks}) exceeds '
            f'the target plan limit ({plan.max_internal_trucks}).'
        )
    if plan.max_external_trucks != -1 and tenant.active_max_external_trucks > plan.max_external_trucks:
        msgs.append(
            f'Active external truck allowance ({tenant.active_max_external_trucks}) exceeds '
            f'the target plan limit ({plan.max_external_trucks}).'
        )
    if plan.max_active_drivers != -1 and tenant.active_max_drivers > plan.max_active_drivers:
        msgs.append(
            f'Active driver allowance ({tenant.active_max_drivers}) exceeds the '
            f'target plan limit ({plan.max_active_drivers}).'
        )
    return msgs


def validate_downgrade_order(tenant, target_plan):
    """
    Enforce Section 2.3.2.B: subscriber must have a current plan, cycle end date,
    and usage within the lower plan caps. Returns error string or None.
    """
    if not tenant.current_plan_id:
        return 'Subscriber must have a current plan to downgrade.'
    if tenant.current_plan_id == target_plan.plan_id:
        return 'Select a different plan than the current subscription plan.'
    if not tenant.subscription_expiry_date:
        return (
            'Subscriber must have a subscription expiry date to schedule a '
            'downgrade (end of current billing cycle).'
        )
    violations = tenant_usage_exceeds_plan_limits(tenant, target_plan)
    if violations:
        return ' '.join(violations)
    return None


def fulfill_immediate_plan_downgrade(tenant, target_plan):
    """
    Apply lower plan and caps now; clear any scheduled downgrade fields.
    Does not save the tenant — caller must save.
    """
    tenant.current_plan = target_plan
    tenant.scheduled_downgrade_plan = None
    tenant.scheduled_downgrade_effective_date = None
    if target_plan.max_internal_users != -1:
        tenant.active_max_users = target_plan.max_internal_users
    if target_plan.max_internal_trucks != -1:
        tenant.active_max_internal_trucks = target_plan.max_internal_trucks
    if target_plan.max_external_trucks != -1:
        tenant.active_max_external_trucks = target_plan.max_external_trucks
    if target_plan.max_active_drivers != -1:
        tenant.active_max_drivers = target_plan.max_active_drivers


def apply_due_scheduled_downgrades(as_of=None):
    """
    For tenants with scheduled_downgrade_effective_date <= as_of, apply the
    pending plan and clear schedule. Returns number of tenants updated.
    """
    from django.db import transaction as db_transaction
    from .models import TenantProfile

    as_of = as_of or date.today()
    candidate_ids = list(
        TenantProfile.objects.filter(
            scheduled_downgrade_plan__isnull=False,
            scheduled_downgrade_effective_date__isnull=False,
            scheduled_downgrade_effective_date__lte=as_of,
        ).values_list('pk', flat=True)
    )
    applied = 0
    for tid in candidate_ids:
        with db_transaction.atomic():
            tenant = TenantProfile.objects.select_for_update().select_related(
                'scheduled_downgrade_plan',
            ).filter(pk=tid).first()
            if not tenant or not tenant.scheduled_downgrade_plan_id:
                continue
            eff = tenant.scheduled_downgrade_effective_date
            if not eff or eff > as_of:
                continue
            plan = tenant.scheduled_downgrade_plan
            fulfill_immediate_plan_downgrade(tenant, plan)
            tenant.save()
            applied += 1
            try:
                create_automated_renewal_after_scheduled_downgrade(tenant, plan)
            except Exception:
                logger.exception(
                    'Scheduled downgrade renewal billing failed tenant=%s',
                    tenant.tenant_id,
                )
    return applied


def calculate_addon_prorata(
        unit_price, base_cycle_days, expiry_date):
    """
    For Add-ons: calculate co-terming price.
    Tenant billed only for remaining days in current cycle.
    Returns (cycles_fraction, line_total)
    """
    today = date.today()
    days_remaining = (expiry_date - today).days

    if days_remaining <= 0:
        days_remaining = base_cycle_days

    cycles_fraction = Decimal(str(days_remaining)) / \
        Decimal(str(base_cycle_days))

    line_total = (unit_price * cycles_fraction).quantize(
        Decimal('0.01'))

    return cycles_fraction, line_total


def generate_invoice_from_order(order, admin_user):
    """
    Auto-generate StandardInvoice when order becomes Paid.
    Snapshots all supplier/customer data at this moment.
    Creates line items from order lines.
    Returns the created invoice.
    """
    from .models import (
        StandardInvoice,
        InvoiceLineItem,
        LegalIdentity,
    )

    # Get IRoad legal identity for supplier snapshot
    try:
        legal = LegalIdentity.objects.get(
            identity_id='GLOBAL-LEGAL-IDENTITY')
        supplier_name = legal.company_name_en
        supplier_tax = legal.tax_number
    except LegalIdentity.DoesNotExist:
        supplier_name = "IRoad Technology"
        supplier_tax = ""

    tenant = order.tenant
    customer_address_snapshot = ''
    if getattr(tenant, 'country', None):
        customer_address_snapshot = tenant.country.name_en or ''

    # Calculate taxable amount
    taxable = order.sub_total - order.discount_amount
    tax_rate = Decimal('0.00')
    if order.tax_code:
        tax_rate = order.tax_code.rate_percent

    # Create invoice header
    invoice = StandardInvoice(
        invoice_number=get_next_invoice_number(),
        order=order,
        tenant=tenant,
        tax_code=order.tax_code,
        due_date=date.today(),
        status='Issued',
        # Supplier snapshot
        supplier_name=supplier_name,
        supplier_tax_number=supplier_tax,
        # Customer snapshot
        customer_name=tenant.company_name,
        customer_tax_number=tenant.tax_number or '',
        customer_address=customer_address_snapshot,
        # Financials
        sub_total=order.sub_total,
        discount_amount=order.discount_amount,
        taxable_amount=taxable,
        tax_amount=order.tax_amount,
        grand_total=order.grand_total,
        currency=order.currency,
        exchange_rate_snapshot=order.exchange_rate_snapshot,
        base_currency_equivalent_amount=(
            order.grand_total * order.exchange_rate_snapshot
        ).quantize(Decimal('0.01')),
    )
    invoice.save()

    # Create line items from plan lines (line_total includes tax per CP-PCS-P5)
    for plan_line in order.plan_lines.all():
        qty = Decimal('1.00')
        unit = (plan_line.line_total or Decimal('0.00')).quantize(Decimal('0.01'))
        tax_amt = ((qty * unit) * tax_rate / 100).quantize(Decimal('0.01'))
        InvoiceLineItem(
            invoice=invoice,
            item_description=plan_line_invoice_label(plan_line),
            quantity=qty,
            unit_price=unit,
            tax_rate=tax_rate,
            tax_amount=tax_amt,
            line_total=(qty * unit + tax_amt).quantize(Decimal('0.01')),
        ).save()

    # Create line items from addon lines (support Reduce by negative quantity)
    for addon_line in order.addon_lines.all():
        sign = Decimal('-1.00') if addon_line.action_type == 'Reduce' else Decimal('1.00')
        qty = (Decimal(str(addon_line.quantity or 0)) * sign).quantize(Decimal('0.01'))
        if qty == 0:
            continue
        raw_total = (addon_line.line_total or Decimal('0.00')).quantize(Decimal('0.01'))
        unit = (raw_total / qty).quantize(Decimal('0.01'))
        tax_amt = ((qty * unit) * tax_rate / 100).quantize(Decimal('0.01'))
        InvoiceLineItem(
            invoice=invoice,
            item_description=addon_line_invoice_label(addon_line),
            quantity=qty,
            unit_price=unit,
            tax_rate=tax_rate,
            tax_amount=tax_amt,
            line_total=(qty * unit + tax_amt).quantize(Decimal('0.01')),
        ).save()

    return invoice


def send_invoice_paid_notification(invoice, use_async_tasks=False):
    """
    Dispatch Invoice_Paid notification to tenant billing email.
    Uses Event Mapping engine when configured, with direct email fallback.
    """
    if not invoice or not getattr(invoice, 'tenant', None):
        return False
    recipient = (invoice.tenant.primary_email or '').strip()
    if not recipient:
        return False

    amount_display = f'{invoice.grand_total} {invoice.currency_id}'.strip()
    context = {
        'invoice_number': invoice.invoice_number,
        'invoice_amount': str(invoice.grand_total),
        'invoice_amount_display': amount_display,
        'currency_code': invoice.currency_id,
        'company_name': invoice.customer_name,
        'tenant_name': invoice.customer_name,
        'issue_date': invoice.issue_date.strftime('%Y-%m-%d') if invoice.issue_date else '',
        'due_date': invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else '',
        'invoice_status': invoice.status or 'Issued',
        'invoice_sub_total': str(invoice.sub_total),
        'invoice_discount_amount': str(invoice.discount_amount),
        'invoice_tax_amount': str(invoice.tax_amount),
        'invoice_grand_total': str(invoice.grand_total),
        'invoice_taxable_amount': str(invoice.taxable_amount),
        'customer_tax_number': invoice.customer_tax_number or '',
        'customer_address': invoice.customer_address or '',
    }

    try:
        from .communication_helpers import (
            dispatch_event_notification,
            ensure_default_notification_templates,
            send_named_notification_email,
            _build_branding_context,
        )
        
        # Inject centralized branding (logo, company name, initials)
        context.update(_build_branding_context())
        
        # Backward compatibility if any legacy templates still use 'company_logo'
        context['company_logo'] = context.get('brand_logo_url', '')
        context['company_logo_img'] = (
            f'<img src="{context["company_logo"]}" alt="Company Logo" '
            'style="max-height:60px;width:auto;">'
            if context['company_logo'] else ''
        )
        context['line_items'] = list(
            invoice.line_items.values(
                'item_description',
                'quantity',
                'unit_price',
                'tax_rate',
                'tax_amount',
                'line_total',
            )
        )
        # Ensure default invoice template exists before direct named dispatch.
        ensure_default_notification_templates()

        # Prefer dedicated invoice template with stable design and variables.
        sent = send_named_notification_email(
            'INVOICE_PAID',
            recipient_email=recipient,
            context_dict=context,
            language='en',
            default_subject=f'Invoice {invoice.invoice_number} issued',
            trigger_source='TemplateName: INVOICE_PAID',
        )
        if sent:
            return True

        sent = dispatch_event_notification(
            'Invoice_Paid',
            recipient_email=recipient,
            context_dict=context,
            use_async_tasks=use_async_tasks,
        )
        if sent:
            return True
    except Exception:
        logger.exception(
            'Invoice_Paid mapped notification failed for invoice %s',
            invoice.invoice_number,
        )

    try:
        from .communication_helpers import send_transactional_email
        subject = f'Invoice {invoice.invoice_number} issued'
        text_body = (
            f'Hello,\n\n'
            f'Your invoice {invoice.invoice_number} is issued.\n'
            f'Amount: {invoice.grand_total} {invoice.currency_id}\n\n'
            f'Thank you.'
        )
        html_body = (
            '<p>Hello,</p>'
            f'<p>Your invoice <strong>{invoice.invoice_number}</strong> is issued.</p>'
            f'<p><strong>Amount:</strong> {invoice.grand_total} {invoice.currency_id}</p>'
            '<p>Thank you.</p>'
        )
        return send_transactional_email(
            recipient,
            subject,
            text_body,
            html_body,
            trigger_source='Event: Invoice_Paid',
            client_id=str(invoice.tenant_id),
        )
    except Exception:
        logger.exception(
            'Fallback invoice email failed for invoice %s',
            invoice.invoice_number,
        )
        return False


def generate_credit_note_from_invoice(original_invoice, admin_user=None):
    """
    Create a negative StandardInvoice as a credit note for an existing invoice.
    (Implements CP-PCS-P5 §4.5.4 'Credit Note' concept without changing UI.)
    """
    from .models import InvoiceLineItem, StandardInvoice

    if not original_invoice:
        return None
    # Avoid duplicates: only one credit note per original invoice number
    existing = StandardInvoice.objects.filter(
        invoice_number__icontains=f"FOR-{original_invoice.invoice_number}",
        order=original_invoice.order,
    ).first()
    if existing:
        return existing

    credit = StandardInvoice(
        invoice_number=f"{get_next_credit_note_number()}-FOR-{original_invoice.invoice_number}",
        order=original_invoice.order,
        tenant=original_invoice.tenant,
        tax_code=original_invoice.tax_code,
        due_date=date.today(),
        status='Issued',
        supplier_name=original_invoice.supplier_name,
        supplier_tax_number=original_invoice.supplier_tax_number,
        customer_name=original_invoice.customer_name,
        customer_tax_number=original_invoice.customer_tax_number,
        customer_address=original_invoice.customer_address,
        sub_total=(-original_invoice.sub_total).quantize(Decimal('0.01')),
        discount_amount=(-original_invoice.discount_amount).quantize(Decimal('0.01')),
        taxable_amount=(-original_invoice.taxable_amount).quantize(Decimal('0.01')),
        tax_amount=(-original_invoice.tax_amount).quantize(Decimal('0.01')),
        grand_total=(-original_invoice.grand_total).quantize(Decimal('0.01')),
        currency=original_invoice.currency,
        exchange_rate_snapshot=original_invoice.exchange_rate_snapshot,
        base_currency_equivalent_amount=(
            -original_invoice.base_currency_equivalent_amount
        ).quantize(Decimal('0.01')),
    )
    credit.save()

    for li in original_invoice.line_items.all():
        InvoiceLineItem(
            invoice=credit,
            item_description=f"Credit: {li.item_description}",
            quantity=(-li.quantity).quantize(Decimal('0.01')),
            unit_price=li.unit_price,
            tax_rate=li.tax_rate,
            tax_amount=(-li.tax_amount).quantize(Decimal('0.01')),
            line_total=(-li.line_total).quantize(Decimal('0.01')),
        ).save()

    return credit


def provision_tenant_from_order(order):
    """
    Update tenant subscription limits when order is Paid.
    Called after invoice is generated.
    """
    tenant = order.tenant
    classification = order.order_classification

    if classification == 'New_Subscription':
        if order.plan_lines.exists():
            plan_line = order.plan_lines.first()
            plan = plan_line.plan
            tenant.current_plan = plan
            tenant.subscription_start_date = date.today()
            tenant.subscription_expiry_date = (
                date.today() + timedelta(
                    days=get_plan_cycle_days(plan) *
                    plan_line.number_of_cycles))
            if plan.max_internal_users != -1:
                tenant.active_max_users = \
                    plan.max_internal_users
            if plan.max_internal_trucks != -1:
                tenant.active_max_internal_trucks = \
                    plan.max_internal_trucks
            if plan.max_external_trucks != -1:
                tenant.active_max_external_trucks = \
                    plan.max_external_trucks
            if plan.max_active_drivers != -1:
                tenant.active_max_drivers = \
                    plan.max_active_drivers

    elif classification == 'Renewal':
        if order.projected_expiry_date:
            tenant.subscription_expiry_date = \
                order.projected_expiry_date

    elif classification == 'Upgrade':
        if order.plan_lines.exists():
            plan_line = order.plan_lines.first()
            plan = plan_line.plan
            tenant.current_plan = plan
            tenant.subscription_start_date = date.today()
            tenant.subscription_expiry_date = (
                date.today() + timedelta(
                    days=get_plan_cycle_days(plan) *
                    plan_line.number_of_cycles))
            if plan.max_internal_users != -1:
                tenant.active_max_users = plan.max_internal_users
            if plan.max_internal_trucks != -1:
                tenant.active_max_internal_trucks = plan.max_internal_trucks
            if plan.max_external_trucks != -1:
                tenant.active_max_external_trucks = plan.max_external_trucks
            if plan.max_active_drivers != -1:
                tenant.active_max_drivers = plan.max_active_drivers

    elif classification == 'Add_ons':
        for addon_line in order.addon_lines.all():
            qty = addon_line.quantity
            if addon_line.action_type == 'Reduce':
                qty = -qty
            if addon_line.add_on_type == 'Extra_User':
                tenant.active_max_users += qty
            elif addon_line.add_on_type == \
                    'Extra_Internal_Truck':
                tenant.active_max_internal_trucks += qty
            elif addon_line.add_on_type == \
                    'Extra_External_Truck':
                tenant.active_max_external_trucks += qty
            elif addon_line.add_on_type == 'Extra_Driver':
                tenant.active_max_drivers += qty

    elif classification == 'Downgrade':
        # Section 2.3.2.B: retain current plan until cycle end; then switch.
        if order.plan_lines.exists():
            plan_line = order.plan_lines.first()
            target_plan = plan_line.plan
            eff = tenant.subscription_expiry_date
            if eff and eff <= date.today():
                fulfill_immediate_plan_downgrade(tenant, target_plan)
            elif eff:
                tenant.scheduled_downgrade_plan = target_plan
                tenant.scheduled_downgrade_effective_date = eff

    tenant.save()
    
    # CP-PCS-P1 §1.1: Ensure isolated database schema (django-tenants)
    try:
        from iroad_tenants.services import ensure_tenant_schema_registry
        ensure_tenant_schema_registry(tenant)
    except Exception:
        logger.exception(
            "Failed to provision isolated database schema for tenant %s",
            tenant.tenant_id
        )


def fulfill_paid_order(order, admin_user, ltv_amount):
    """
    Run side effects after an order is marked Paid: invoice, tenant
    provisioning, promo redemption count, lifetime value.

    Call inside transaction.atomic(); order.order_status should already
    be Saved as Paid. ltv_amount is normally the payment transaction amount.
    """
    from .models import PromoCode, StandardInvoice, TenantProfile

    # Ref: CP-PCS-P1 §5.3 - Transactional Immutability (Snapshots)
    for pl in order.plan_lines.all():
        if not pl.plan_name_en_snapshot:
            pl.plan_name_en_snapshot = pl.plan.plan_name_en
            pl.plan_name_ar_snapshot = pl.plan.plan_name_ar or ''
            pl.save(update_fields=['plan_name_en_snapshot', 'plan_name_ar_snapshot'])

    for al in order.addon_lines.all():
        if not al.add_on_type_label_snapshot:
            al.add_on_type_label_snapshot = al.get_add_on_type_display()
            al.save(update_fields=['add_on_type_label_snapshot'])

    created_invoice = None
    if not StandardInvoice.objects.filter(order=order).exists():
        created_invoice = generate_invoice_from_order(order, admin_user)

    provision_tenant_from_order(order)

    if order.promo_code_id:
        pc = PromoCode.objects.select_for_update().get(pk=order.promo_code_id)
        pc.current_uses = (pc.current_uses or 0) + 1
        update_fields = ['current_uses']
        if pc.max_uses is not None and pc.current_uses >= pc.max_uses:
            pc.is_active = False
            update_fields.append('is_active')
        pc.save(update_fields=update_fields)

    ten = TenantProfile.objects.select_for_update().get(pk=order.tenant_id)
    ten.total_ltv = (
        ten.total_ltv + ltv_amount
    ).quantize(Decimal('0.01'))
    ten.save(update_fields=['total_ltv', 'updated_at'])

    if created_invoice is not None:
        send_invoice_paid_notification(created_invoice, use_async_tasks=False)
