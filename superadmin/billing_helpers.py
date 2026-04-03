from decimal import Decimal
from datetime import date, timedelta


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
            days=plan.base_cycle_days * plan_line.number_of_cycles)
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
        extra = plan.base_cycle_days * plan_line.number_of_cycles
        if tenant.subscription_expiry_date:
            proj_expiry = tenant.subscription_expiry_date + timedelta(days=extra)
        else:
            proj_expiry = date.today() + timedelta(days=extra)

    elif classification == 'Upgrade' and plan_line:
        plan = plan_line.plan
        proj_plan = plan
        proj_expiry = date.today() + timedelta(
            days=plan.base_cycle_days * plan_line.number_of_cycles)
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


def get_fx_snapshot(currency_code):
    """
    Get current FX rate snapshot for a currency.
    Returns 1.000000 if currency is base currency.
    """
    from .models import BaseCurrencyConfig, ExchangeRate

    try:
        base_config = BaseCurrencyConfig.objects.get(
            setting_id='GLOBAL-BASE-CURRENCY')
        if base_config.base_currency_id == currency_code:
            return Decimal('1.000000')
    except Exception:
        return Decimal('1.000000')

    try:
        fx = ExchangeRate.objects.get(
            currency_id=currency_code, is_active=True)
        return fx.exchange_rate
    except ExchangeRate.DoesNotExist:
        return Decimal('1.000000')


def get_tax_code_for_tenant(tenant):
    """
    Dynamic tax routing based on tenant country.
    1. Try to find active default tax for tenant country
    2. Fall back to international default
    """
    from .models import TaxCode

    if tenant.country_id:
        tax = TaxCode.objects.filter(
            applicable_country_code=tenant.country_id,
            is_default_for_country=True,
            is_active=True
        ).first()
        if tax:
            return tax

    # Fallback to international default
    return TaxCode.objects.filter(
        is_international_default=True,
        is_active=True
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
        customer_address='',
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

    # Create line items from plan lines
    for plan_line in order.plan_lines.all():
        InvoiceLineItem(
            invoice=invoice,
            item_description=(
                f"{plan_line.plan.plan_name_en} - "
                f"{plan_line.number_of_cycles} cycle(s)"),
            quantity=Decimal('1.00'),
            unit_price=plan_line.plan_price,
            tax_rate=tax_rate,
            tax_amount=(
                plan_line.line_total *
                tax_rate / 100
            ).quantize(Decimal('0.01')),
            line_total=plan_line.line_total,
        ).save()

    # Create line items from addon lines
    for addon_line in order.addon_lines.all():
        InvoiceLineItem(
            invoice=invoice,
            item_description=(
                f"Add-on: {addon_line.get_add_on_type_display()} "
                f"x {addon_line.quantity}"),
            quantity=Decimal(str(addon_line.quantity)),
            unit_price=addon_line.unit_price,
            tax_rate=tax_rate,
            tax_amount=(
                addon_line.line_total *
                tax_rate / 100
            ).quantize(Decimal('0.01')),
            line_total=addon_line.line_total,
        ).save()

    return invoice


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
                    days=plan.base_cycle_days *
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
                    days=plan.base_cycle_days *
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

    tenant.save()
    # TODO Phase 10: Send provisioning event to
    #               tenant isolated DB here


def fulfill_paid_order(order, admin_user, ltv_amount):
    """
    Run side effects after an order is marked Paid: invoice, tenant
    provisioning, promo redemption count, lifetime value.

    Call inside transaction.atomic(); order.order_status should already
    be Saved as Paid. ltv_amount is normally the payment transaction amount.
    """
    from .models import PromoCode, StandardInvoice, TenantProfile

    if not StandardInvoice.objects.filter(order=order).exists():
        generate_invoice_from_order(order, admin_user)

    provision_tenant_from_order(order)

    if order.promo_code_id:
        pc = PromoCode.objects.select_for_update().get(pk=order.promo_code_id)
        pc.current_uses = (pc.current_uses or 0) + 1
        pc.save(update_fields=['current_uses'])

    ten = TenantProfile.objects.select_for_update().get(pk=order.tenant_id)
    ten.total_ltv = (
        ten.total_ltv + ltv_amount
    ).quantize(Decimal('0.01'))
    ten.save(update_fields=['total_ltv', 'updated_at'])
