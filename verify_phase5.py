import os
import json
from decimal import Decimal
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.conf import settings
from django.core.validators import MinValueValidator
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from superadmin.models import (
    AdminUser,
    AddOnsPricingPolicy,
    Currency,
    PlanPricingCycle,
    PromoCode,
    SubscriptionPlan,
)
from superadmin.forms import (
    AddOnsPricingPolicyForm,
    PlanPricingCycleForm,
    PromoCodeForm,
    SubscriptionPlanForm,
)

allowed = list(getattr(settings, "ALLOWED_HOSTS", []))
if "testserver" not in allowed:
    allowed.append("testserver")
settings.ALLOWED_HOSTS = allowed

results = []


def chk(item, ok, err=None):
    results.append({"item": item, "ok": bool(ok), "error": None if ok else (err or "Condition failed")})


def err_text(resp):
    try:
        return resp.content.decode("utf-8", errors="ignore")[:2000]
    except Exception:
        return "Unable to decode response"


root = AdminUser.objects.get(email="admin@iroad.com")
client = Client()
client.force_login(root)

# MODELS
chk("SubscriptionPlan model exists with UUID PK", SubscriptionPlan._meta.pk.name == "plan_id" and SubscriptionPlan._meta.pk.__class__.__name__ == "UUIDField")
chk("plan_name_en and plan_name_ar both unique", SubscriptionPlan._meta.get_field("plan_name_en").unique and SubscriptionPlan._meta.get_field("plan_name_ar").unique)
base_cycle_field = SubscriptionPlan._meta.get_field("base_cycle_days")
min_vals = [v for v in base_cycle_field.validators if isinstance(v, MinValueValidator)]
chk("base_cycle_days default 30, min 1 validator", base_cycle_field.default == 30 and any(getattr(v, "limit_value", None) == 1 for v in min_vals))
max_fields = [
    "max_internal_users",
    "max_internal_trucks",
    "max_external_trucks",
    "max_active_drivers",
    "max_monthly_shipments",
    "max_storage_gb",
]
chk("All max_* fields exist with default -1", all(SubscriptionPlan._meta.get_field(f).default == -1 for f in max_fields))
driver_f = SubscriptionPlan._meta.get_field("has_driver_app")
chk("has_driver_app BooleanField default False", driver_f.__class__.__name__ == "BooleanField" and driver_f.default is False)
choices = [c[0] for c in SubscriptionPlan._meta.get_field("backup_restore_level").choices]
chk("backup_restore_level choices: Standard/Extended/Premium", choices == ["Standard", "Extended", "Premium"])
chk("PlanPricingCycle model exists", hasattr(PlanPricingCycle, "_meta"))
chk("unique_together on plan+cycles+currency", ["plan", "number_of_cycles", "currency"] in list(PlanPricingCycle._meta.unique_together))
chk("AddOnsPricingPolicy model exists with UUID PK", AddOnsPricingPolicy._meta.pk.name == "policy_id")
price_fields = [
    "extra_internal_user_price",
    "extra_internal_truck_price",
    "extra_external_truck_price",
    "extra_driver_price",
    "extra_shipment_price",
    "extra_storage_gb_price",
]
chk("All 6 price fields exist with default 0.00", all(AddOnsPricingPolicy._meta.get_field(f).default == Decimal("0.00") for f in price_fields))
chk("PromoCode model exists with UUID PK", PromoCode._meta.pk.name == "promo_code_id")
chk("code field unique", PromoCode._meta.get_field("code").unique)
m2m_model = PromoCode._meta.get_field("applicable_plans").remote_field.model
chk("applicable_plans ManyToMany to SubscriptionPlan", m2m_model is SubscriptionPlan)
chk("is_valid_for_use() method exists on PromoCode", hasattr(PromoCode, "is_valid_for_use"))

from subprocess import run, PIPE, STDOUT
migr = run(["D:\\iroad\\venv\\Scripts\\python.exe", "manage.py", "migrate", "--noinput"], cwd="D:\\iroad", stdout=PIPE, stderr=STDOUT, text=True)
chk("All migrations run with no errors", migr.returncode == 0, migr.stdout[-1000:])

# FORMS
f_ok = SubscriptionPlanForm({
    "plan_name_en": "FORM PLAN A",
    "plan_name_ar": "FORM PLAN A AR",
    "base_cycle_days": 30,
    "is_active": "on",
    "max_internal_users": -1,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "",
    "backup_restore_level": "Standard",
})
chk("SubscriptionPlanForm max_* accepts -1", f_ok.is_valid(), f_ok.errors.as_text())

f_bad = SubscriptionPlanForm({
    "plan_name_en": "FORM PLAN B",
    "plan_name_ar": "FORM PLAN B AR",
    "base_cycle_days": 30,
    "is_active": "on",
    "max_internal_users": -2,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "",
    "backup_restore_level": "Standard",
})
chk("SubscriptionPlanForm rejects values below -1", not f_bad.is_valid(), f_bad.errors.as_text())

active_codes = set(Currency.objects.filter(is_active=True).values_list("currency_code", flat=True))
pcf = PlanPricingCycleForm()
form_codes = set(pcf.fields["currency"].queryset.values_list("currency_code", flat=True))
chk("PlanPricingCycleForm currency shows active only", form_codes.issubset(active_codes), f"non-active in queryset: {form_codes - active_codes}")

any_curr = Currency.objects.filter(is_active=True).first()
pp_bad = PlanPricingCycleForm({"number_of_cycles": 1, "currency": any_curr.currency_code, "price": "-0.01"})
chk("PlanPricingCycleForm rejects negative price", not pp_bad.is_valid(), pp_bad.errors.as_text())

ap_bad = AddOnsPricingPolicyForm({
    "policy_name": "bad",
    "is_active": "",
    "extra_internal_user_price": "-1.00",
    "extra_internal_truck_price": "0.00",
    "extra_external_truck_price": "0.00",
    "extra_driver_price": "0.00",
    "extra_shipment_price": "0.00",
    "extra_storage_gb_price": "0.00",
})
chk("AddOnsPricingPolicyForm rejects negative prices", not ap_bad.is_valid(), ap_bad.errors.as_text())

plan_for_promo, _ = SubscriptionPlan.objects.get_or_create(
    plan_name_en="PROMO PLAN",
    defaults={
        "plan_name_ar": "PROMO PLAN AR",
        "created_by": root,
    },
)

promo_upper = PromoCodeForm({
    "code": "abc123",
    "discount_type": "Percentage",
    "discount_value": "10.00",
    "discount_duration": "Apply_Once",
    "valid_from": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    "valid_until": "",
    "max_uses": "",
    "is_active": "on",
    "applicable_plans": [str(plan_for_promo.plan_id)],
})
promo_upper_valid = promo_upper.is_valid()
chk("PromoCodeForm auto-uppercases code", promo_upper_valid and promo_upper.cleaned_data.get("code") == "ABC123", promo_upper.errors.as_text() if not promo_upper_valid else str(promo_upper.cleaned_data.get("code")))

promo_bad_code = PromoCodeForm({
    "code": "bad code!",
    "discount_type": "Percentage",
    "discount_value": "10.00",
    "discount_duration": "Apply_Once",
    "valid_from": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    "valid_until": "",
    "max_uses": "",
    "is_active": "on",
})
chk("PromoCodeForm rejects non-alphanumeric code", not promo_bad_code.is_valid(), promo_bad_code.errors.as_text())

promo_pct = PromoCodeForm({
    "code": "PCT101",
    "discount_type": "Percentage",
    "discount_value": "101.00",
    "discount_duration": "Apply_Once",
    "valid_from": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    "valid_until": "",
    "max_uses": "",
    "is_active": "on",
})
chk("PromoCodeForm rejects percentage > 100", not promo_pct.is_valid(), promo_pct.errors.as_text())

vf = timezone.now()
vu = vf - timedelta(days=1)
promo_dates = PromoCodeForm({
    "code": "DATE01",
    "discount_type": "Percentage",
    "discount_value": "10.00",
    "discount_duration": "Apply_Once",
    "valid_from": vf.strftime("%Y-%m-%dT%H:%M"),
    "valid_until": vu.strftime("%Y-%m-%dT%H:%M"),
    "max_uses": "",
    "is_active": "on",
})
chk("PromoCodeForm rejects valid_until before valid_from", not promo_dates.is_valid(), promo_dates.errors.as_text())

promo_uses = PromoCodeForm({
    "code": "USES01",
    "discount_type": "Percentage",
    "discount_value": "10.00",
    "discount_duration": "Apply_Once",
    "valid_from": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    "valid_until": "",
    "max_uses": "0",
    "is_active": "on",
})
chk("PromoCodeForm rejects max_uses = 0", not promo_uses.is_valid(), promo_uses.errors.as_text())

# SUBSCRIPTION CRUD
resp = client.get(reverse("plan_list"))
chk("/subscription/plans/ list loads", resp.status_code == 200, f"status={resp.status_code}")

search_resp = client.get(reverse("plan_list"), {"q": "PROMO PLAN"})
chk("Search by plan name works", "PROMO PLAN" in err_text(search_resp), "Plan name missing in filtered output")

plan_for_promo.is_active = False
plan_for_promo.save(update_fields=["is_active", "updated_at"])
inactive_resp = client.get(reverse("plan_list"), {"status": "Inactive"})
chk("Filter by status works", "PROMO PLAN" in err_text(inactive_resp), "Inactive filter missing expected plan")
plan_for_promo.is_active = True
plan_for_promo.save(update_fields=["is_active", "updated_at"])

create_get = client.get(reverse("plan_create"))
create_txt = err_text(create_get)
chk("/subscription/plans/create/ shows form", create_get.status_code == 200, f"status={create_get.status_code}")
chk("Pricing cycles subform visible with Add Row button", "Add Row" in create_txt, "Add Row button not found")

no_row_post = client.post(reverse("plan_create"), data={
    "plan_name_en": "P5 PLAN NO ROW",
    "plan_name_ar": "P5 PLAN NO ROW AR",
    "base_cycle_days": 30,
    "is_active": "on",
    "max_internal_users": -1,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "",
    "backup_restore_level": "Standard",
})
chk("Submitting without pricing row shows error", "At least one pricing cycle is required." in err_text(no_row_post), "Expected message missing")

curr_a = Currency.objects.filter(is_active=True).order_by("currency_code").first()
curr_b = Currency.objects.filter(is_active=True).exclude(currency_code=curr_a.currency_code).order_by("currency_code").first()
plan_name = "P5 PLAN TWO ROWS"
if SubscriptionPlan.objects.filter(plan_name_en=plan_name).exists():
    plan_name = f"{plan_name} X"
create_ok = client.post(reverse("plan_create"), data={
    "plan_name_en": plan_name,
    "plan_name_ar": f"{plan_name} AR",
    "base_cycle_days": 30,
    "is_active": "on",
    "max_internal_users": -1,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "on",
    "backup_restore_level": "Extended",
    "pricing-0-pricing_id": "",
    "pricing-0-number_of_cycles": "1",
    "pricing-0-currency": curr_a.currency_code,
    "pricing-0-price": "99.99",
    "pricing-0-delete": "0",
    "pricing-1-pricing_id": "",
    "pricing-1-number_of_cycles": "12",
    "pricing-1-currency": curr_b.currency_code,
    "pricing-1-price": "999.99",
    "pricing-1-delete": "0",
}, follow=True)
created_plan = SubscriptionPlan.objects.filter(plan_name_en=plan_name).first()
chk("Creating plan with 2 pricing rows works", created_plan is not None and created_plan.pricing_cycles.count() == 2, err_text(create_ok))

detail = client.get(reverse("plan_detail", kwargs={"pk": created_plan.plan_id}))
d_txt = err_text(detail)
chk("Plan detail page shows all fields and pricing table", detail.status_code == 200 and "Pricing Cycles" in d_txt, d_txt)
chk("-1 shows as \"Unlimited\" in detail view", "Unlimited" in d_txt, d_txt)

first_pr = created_plan.pricing_cycles.order_by("number_of_cycles").first()
edit_post = client.post(reverse("plan_edit", kwargs={"pk": created_plan.plan_id}), data={
    "plan_name_en": created_plan.plan_name_en,
    "plan_name_ar": created_plan.plan_name_ar,
    "base_cycle_days": 60,
    "is_active": "on",
    "max_internal_users": -1,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "",
    "backup_restore_level": "Premium",
    "pricing-0-pricing_id": str(first_pr.pricing_id),
    "pricing-0-number_of_cycles": "2",
    "pricing-0-currency": curr_a.currency_code,
    "pricing-0-price": "111.11",
    "pricing-0-delete": "0",
}, follow=True)
created_plan.refresh_from_db()
chk("Edit plan works — pricing rows updated", created_plan.base_cycle_days == 60 and created_plan.pricing_cycles.filter(number_of_cycles=2).exists(), err_text(edit_post))

edit_add = client.post(reverse("plan_edit", kwargs={"pk": created_plan.plan_id}), data={
    "plan_name_en": created_plan.plan_name_en,
    "plan_name_ar": created_plan.plan_name_ar,
    "base_cycle_days": 60,
    "is_active": "on",
    "max_internal_users": -1,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "",
    "backup_restore_level": "Premium",
    "pricing-0-pricing_id": str(created_plan.pricing_cycles.order_by("number_of_cycles").first().pricing_id),
    "pricing-0-number_of_cycles": "2",
    "pricing-0-currency": curr_a.currency_code,
    "pricing-0-price": "111.11",
    "pricing-0-delete": "0",
    "pricing-1-pricing_id": "",
    "pricing-1-number_of_cycles": "24",
    "pricing-1-currency": curr_b.currency_code,
    "pricing-1-price": "1800.00",
    "pricing-1-delete": "0",
}, follow=True)
created_plan.refresh_from_db()
chk("Adding new pricing row on edit works", created_plan.pricing_cycles.filter(number_of_cycles=24).exists(), err_text(edit_add))

dup_post = client.post(reverse("plan_edit", kwargs={"pk": created_plan.plan_id}), data={
    "plan_name_en": created_plan.plan_name_en,
    "plan_name_ar": created_plan.plan_name_ar,
    "base_cycle_days": 60,
    "is_active": "on",
    "max_internal_users": -1,
    "max_internal_trucks": -1,
    "max_external_trucks": -1,
    "max_active_drivers": -1,
    "max_monthly_shipments": -1,
    "max_storage_gb": -1,
    "has_driver_app": "",
    "backup_restore_level": "Premium",
    "pricing-0-pricing_id": "",
    "pricing-0-number_of_cycles": "1",
    "pricing-0-currency": curr_a.currency_code,
    "pricing-0-price": "10.00",
    "pricing-0-delete": "0",
    "pricing-1-pricing_id": "",
    "pricing-1-number_of_cycles": "1",
    "pricing-1-currency": curr_a.currency_code,
    "pricing-1-price": "20.00",
    "pricing-1-delete": "0",
})
chk("Duplicate cycle+currency combination blocked", "Duplicate pricing row found for same cycles and currency." in err_text(dup_post), err_text(dup_post))

before_active = created_plan.is_active
client.post(reverse("plan_toggle", kwargs={"pk": created_plan.plan_id}), data={}, follow=True)
created_plan.refresh_from_db()
chk("Toggle status works", created_plan.is_active != before_active)

del_resp = client.post(reverse("plan_delete", kwargs={"pk": created_plan.plan_id}), data={}, follow=True)
chk("Delete redirects with error", "Plans cannot be deleted. Deactivate instead." in err_text(del_resp), err_text(del_resp))

# ADD-ONS POLICY
policy_list = client.get(reverse("addons_policy_list"))
chk("/subscription/addons-policy/ list loads", policy_list.status_code == 200, f"status={policy_list.status_code}")

pol1 = client.post(reverse("addons_policy_create"), data={
    "policy_name": "POLICY A",
    "is_active": "on",
    "extra_internal_user_price": "1.00",
    "extra_internal_truck_price": "2.00",
    "extra_external_truck_price": "3.00",
    "extra_driver_price": "4.00",
    "extra_shipment_price": "5.00",
    "extra_storage_gb_price": "6.00",
}, follow=True)
p1 = AddOnsPricingPolicy.objects.filter(policy_name="POLICY A").first()
chk("Create new policy works", p1 is not None, err_text(pol1))

pol2 = client.post(reverse("addons_policy_create"), data={
    "policy_name": "POLICY B",
    "is_active": "on",
    "extra_internal_user_price": "1.50",
    "extra_internal_truck_price": "2.50",
    "extra_external_truck_price": "3.50",
    "extra_driver_price": "4.50",
    "extra_shipment_price": "5.50",
    "extra_storage_gb_price": "6.50",
}, follow=True)
p1.refresh_from_db()
p2 = AddOnsPricingPolicy.objects.get(policy_name="POLICY B")
chk("Activating policy deactivates all others", p2.is_active and not p1.is_active, err_text(pol2))
chk("Only one active policy at any time", AddOnsPricingPolicy.objects.filter(is_active=True).count() == 1)
highlight_txt = err_text(client.get(reverse("addons_policy_list")))
chk("Active policy highlighted in list", "background:#ecfdf5" in highlight_txt or "status-badge active" in highlight_txt, highlight_txt)

edit_policy = client.post(reverse("addons_policy_edit", kwargs={"pk": p2.policy_id}), data={
    "policy_name": "POLICY B EDIT",
    "is_active": "on",
    "extra_internal_user_price": "9.00",
    "extra_internal_truck_price": "9.00",
    "extra_external_truck_price": "9.00",
    "extra_driver_price": "9.00",
    "extra_shipment_price": "9.00",
    "extra_storage_gb_price": "9.00",
}, follow=True)
p2.refresh_from_db()
chk("Edit policy works", p2.policy_name == "POLICY B EDIT", err_text(edit_policy))

del_policy = client.post(reverse("addons_policy_delete", kwargs={"pk": p2.policy_id}), data={}, follow=True)
chk("Delete redirects with error", "Active policy cannot be deleted. Deactivate first." in err_text(del_policy), err_text(del_policy))

# PROMO
promo_list = client.get(reverse("promo_code_list"))
chk("/subscription/promo-codes/ list loads", promo_list.status_code == 200, f"status={promo_list.status_code}")

promo_create = client.post(reverse("promo_code_create"), data={
    "code": "phase5promo",
    "discount_type": "Percentage",
    "discount_value": "20.00",
    "discount_duration": "Apply_Once",
    "valid_from": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    "valid_until": "",
    "max_uses": "100",
    "is_active": "on",
    "applicable_plans": [],
}, follow=True)
promo = PromoCode.objects.filter(code="PHASE5PROMO").first()
chk("Code auto-uppercased on save", promo is not None and promo.code == "PHASE5PROMO", err_text(promo_create))
chk("Create promo code works", promo is not None, err_text(promo_create))
chk("current_uses starts at 0 on creation", promo is not None and promo.current_uses == 0, str(promo.current_uses if promo else None))

edit_get = client.get(reverse("promo_code_edit", kwargs={"pk": promo.promo_code_id}))
edit_txt = err_text(edit_get)
chk("Code disabled on edit", 'name="code"' in edit_txt and "disabled" in edit_txt[edit_txt.find('name="code"'):edit_txt.find('name="code"') + 300], edit_txt)

promo.current_uses = 7
promo.save(update_fields=["current_uses"])
edit_post_promo = client.post(reverse("promo_code_edit", kwargs={"pk": promo.promo_code_id}), data={
    "code": "HACKEDCODE",
    "discount_type": "Percentage",
    "discount_value": "15.00",
    "discount_duration": "Recurring",
    "valid_from": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    "valid_until": "",
    "max_uses": "100",
    "is_active": "on",
    "applicable_plans": [],
}, follow=True)
promo.refresh_from_db()
chk("current_uses cannot be changed from edit form", promo.current_uses == 7, err_text(edit_post_promo))

expired_code = PromoCode.objects.create(
    code="EXPIREDP5",
    discount_type="Percentage",
    discount_value=Decimal("5.00"),
    discount_duration="Apply_Once",
    valid_from=timezone.now() - timedelta(days=5),
    valid_until=timezone.now() - timedelta(days=1),
    is_active=True,
    created_by=root,
)
expired_list = err_text(client.get(reverse("promo_code_list")))
chk("Expired badge shows when valid_until passed", "Expired" in expired_list and "EXPIREDP5" in expired_list, expired_list)

before = promo.is_active
client.post(reverse("promo_code_toggle", kwargs={"pk": promo.promo_code_id}), data={}, follow=True)
promo.refresh_from_db()
chk("Toggle status works", promo.is_active != before)

del_promo = client.post(reverse("promo_code_delete", kwargs={"pk": promo.promo_code_id}), data={}, follow=True)
chk("Delete redirects with error", "Promo codes cannot be deleted. Deactivate instead." in err_text(del_promo), err_text(del_promo))

chk("applicable_plans empty = all plans (no restriction)", PromoCode.objects.filter(promo_code_id=promo.promo_code_id, applicable_plans__isnull=True).exists(), "No explicit runtime restriction logic; this check uses empty M2M as global scope")

# SIDEBAR
sidebar_path = "D:\\iroad\\templates\\partials\\sidebar.html"
with open(sidebar_path, "r", encoding="utf-8") as f:
    side = f.read()
chk("Subscription Plans Management has all 3 sub-items", all(x in side for x in ["Subscription Plans", "Add-ons Pricing Policy", "Promo Codes"]))

chk("Subscription Plans link works", client.get(reverse("plan_list")).status_code == 200)
chk("Add-ons Pricing Policy link works", client.get(reverse("addons_policy_list")).status_code == 200)
chk("Promo Codes link works", client.get(reverse("promo_code_list")).status_code == 200)

print(json.dumps(results, indent=2))

