import os
import re
import sys
import json
import subprocess
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.test import Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings

from django.core.validators import MinValueValidator, MaxValueValidator
from superadmin.models import (
    AdminUser,
    TaxCode,
    Country,
    GeneralTaxSettings,
    LegalIdentity,
    GlobalSystemRules,
    BaseCurrencyConfig,
    Currency,
    ExchangeRate,
    FXRateChangeLog,
)
from superadmin.forms import (
    TaxCodeForm,
    GlobalSystemRulesForm,
    ExchangeRateForm,
)

# Allow Django test client host
try:
    allowed = list(getattr(settings, "ALLOWED_HOSTS", []))
    if "testserver" not in allowed:
        allowed.append("testserver")
    settings.ALLOWED_HOSTS = allowed
except Exception:
    pass


def run_cmd(cmd):
    p = subprocess.run(
        cmd,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
    )
    try:
        out = p.stdout.decode("utf-8", errors="ignore") if isinstance(p.stdout, (bytes, bytearray)) else str(p.stdout)
    except Exception:
        out = str(p.stdout)
    return p.returncode, out


def get_root_user():
    return AdminUser.objects.get(email="admin@iroad.com")


def page_text(resp):
    try:
        return resp.content.decode("utf-8", errors="ignore")
    except Exception:
        return str(resp.content)


results = []


def chk(label, ok, err=None):
    if ok:
        results.append((label, True, None))
    else:
        results.append((label, False, err or "Condition failed"))


def find_substring_near(text, needle, window=800):
    idx = text.find(needle)
    if idx < 0:
        return None
    start = max(0, idx - window)
    end = min(len(text), idx + window)
    return text[start:end]


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def assert_condition(label, fn):
    try:
        ok, err = fn()
        chk(label, ok, err)
    except Exception as e:
        chk(label, False, f"Exception: {e}")


#
# MODELS CHECK
#
assert_condition(
    "TaxCode model exists, tax_code is PK",
    lambda: (
        hasattr(TaxCode, "_meta")
        and TaxCode._meta.pk is not None
        and TaxCode._meta.pk.name == "tax_code",
        None,
    ),
)


def _rate_validators():
    f = TaxCode._meta.get_field("rate_percent")
    mins = [v for v in f.validators if isinstance(v, MinValueValidator)]
    maxs = [v for v in f.validators if isinstance(v, MaxValueValidator)]
    min_ok = any(getattr(v, "limit_value", None) == 0 for v in mins)
    max_ok = any(getattr(v, "limit_value", None) == 100 for v in maxs)
    return min_ok, max_ok, f.validators


def validators_ok():
    try:
        min_ok, max_ok, vals = _rate_validators()
        return (min_ok and max_ok), None
    except Exception as e:
        return False, str(e)


chk("rate_percent has min 0 max 100 validators", validators_ok()[0], validators_ok()[1])

chk(
    "applicable_country_code FK to Country, null allowed",
    TaxCode._meta.get_field("applicable_country_code").null is True
    and getattr(TaxCode._meta.get_field("applicable_country_code").remote_field, "model", None)
    is Country,
    None,
)

chk(
    "is_default_for_country and is_international_default exist",
    "is_default_for_country" in [f.name for f in TaxCode._meta.fields]
    and "is_international_default" in [f.name for f in TaxCode._meta.fields],
    None,
)

chk(
    "GeneralTaxSettings model, fixed PK GLOBAL-TAX-SETTING",
    GeneralTaxSettings._meta.pk.name == "setting_id"
    and GeneralTaxSettings._meta.get_field("setting_id").default == "GLOBAL-TAX-SETTING",
    None,
)

gv = GeneralTaxSettings._meta.get_field("location_verification").choices
chk(
    "location_verification has 3 choices",
    len(list(gv)) == 3,
    f"Got {len(list(gv))} choices",
)

chk(
    "LegalIdentity model, fixed PK GLOBAL-LEGAL-IDENTITY",
    LegalIdentity._meta.pk.name == "identity_id"
    and LegalIdentity._meta.get_field("identity_id").default == "GLOBAL-LEGAL-IDENTITY",
    None,
)

logo_field = LegalIdentity._meta.get_field("company_logo")
chk(
    "company_logo is ImageField with upload_to='legal/'",
    logo_field.__class__.__name__ == "ImageField" and getattr(logo_field, "upload_to", None) == "legal/",
    f"type={logo_field.__class__.__name__} upload_to={getattr(logo_field,'upload_to',None)}",
)

chk(
    "company_country_code FK to Country",
    getattr(LegalIdentity._meta.get_field("company_country_code").remote_field, "model", None)
    is Country,
    None,
)

gpr = GlobalSystemRules._meta.get_field("rule_id")
chk(
    "GlobalSystemRules model, fixed PK GLOBAL-SYSTEM-RULES",
    GlobalSystemRules._meta.pk.name == "rule_id" and gpr.default == "GLOBAL-SYSTEM-RULES",
    None,
)

grace_vals = [v for v in GlobalSystemRules._meta.get_field("grace_period_days").validators if isinstance(v, MinValueValidator)]
chk(
    "grace_period_days min 0 validator",
    any(getattr(v, "limit_value", None) == 0 for v in grace_vals),
    None,
)

std_field = GlobalSystemRules._meta.get_field("standard_billing_cycle")
std_vals = [v for v in std_field.validators if isinstance(v, MinValueValidator)]
chk(
    "standard_billing_cycle default 30 min 1 validator",
    std_field.default == 30 and any(getattr(v, "limit_value", None) == 1 for v in std_vals),
    f"default={std_field.default} validators={[getattr(v,'limit_value',None) for v in std_vals]}",
)

base_pk = BaseCurrencyConfig._meta.get_field("setting_id")
chk(
    "BaseCurrencyConfig model, fixed PK GLOBAL-BASE-CURRENCY",
    BaseCurrencyConfig._meta.pk.name == "setting_id" and base_pk.default == "GLOBAL-BASE-CURRENCY",
    None,
)

chk(
    "base_currency FK to Currency",
    getattr(BaseCurrencyConfig._meta.get_field("base_currency").remote_field, "model", None)
    is Currency,
    None,
)

fx_id_field = ExchangeRate._meta.get_field("fx_id")
chk(
    "ExchangeRate model with UUID PK",
    fx_id_field.__class__.__name__ == "UUIDField" and ExchangeRate._meta.pk.name == "fx_id",
    f"pk={ExchangeRate._meta.pk.name} type={fx_id_field.__class__.__name__}",
)

ex_rate_field = ExchangeRate._meta.get_field("exchange_rate")
chk(
    "exchange_rate DecimalField 10,6 precision",
    ex_rate_field.__class__.__name__ == "DecimalField"
    and ex_rate_field.max_digits == 10
    and ex_rate_field.decimal_places == 6,
    f"type={ex_rate_field.__class__.__name__} max_digits={ex_rate_field.max_digits} decimal_places={ex_rate_field.decimal_places}",
)

# FXRateChangeLog immutability
try:
    c = Currency.objects.exclude(currency_code=(
        BaseCurrencyConfig.objects.get_or_create(setting_id="GLOBAL-BASE-CURRENCY")[0].base_currency_id
    )).first() or Currency.objects.first()
    log = FXRateChangeLog.objects.create(currency=c, old_rate=Decimal("0.1"), new_rate=Decimal("0.2"), notes="tmp", changed_by=get_root_user())
    raised_update = False
    try:
        log.save()
    except PermissionError:
        raised_update = True
    raised_del = False
    try:
        log.delete()
    except PermissionError:
        raised_del = True
    chk("FXRateChangeLog save() raises on update attempt", raised_update, None if raised_update else "PermissionError not raised")
    chk("FXRateChangeLog delete() raises on delete attempt", raised_del, None if raised_del else "PermissionError not raised")
except Exception as e:
    chk("FXRateChangeLog save() raises on update attempt", False, f"Exception: {e}")
    chk("FXRateChangeLog delete() raises on delete attempt", False, f"Exception: {e}")


# all migrations run with no errors (run migrate)
code, out = run_cmd([sys.executable, "manage.py", "migrate", "--noinput"])
chk("All migrations run with no errors", code == 0, out[-5000:])


#
# SEED CHECK
#
def counts_for_seed():
    return {
        "tax_count": TaxCode.objects.count(),
        "tax_s15": TaxCode.objects.filter(tax_code="S-15").count(),
        "tax_z0": TaxCode.objects.filter(tax_code="Z-0").count(),
        "gts_count": GeneralTaxSettings.objects.count(),
        "gss_count": GlobalSystemRules.objects.count(),
        "base_count": BaseCurrencyConfig.objects.count(),
        "fxlog_count": FXRateChangeLog.objects.count(),
    }


before_counts = counts_for_seed()
seed_code1, seed_out1 = run_cmd([sys.executable, "seed_superadmin.py"])
after_counts_1 = counts_for_seed()

seed_code2, seed_out2 = run_cmd([sys.executable, "seed_superadmin.py"])
after_counts_2 = counts_for_seed()

chk("python seed_superadmin.py runs with no errors", seed_code1 == 0, seed_out1[-5000:])
chk(
    "S-15 tax code seeded (SA, 15%)",
    TaxCode.objects.filter(tax_code="S-15", applicable_country_code__country_code="SA", rate_percent=Decimal("15.00")).exists(),
    None,
)
chk(
    "Z-0 tax code seeded (International, 0%)",
    TaxCode.objects.filter(
        tax_code="Z-0",
        applicable_country_code__isnull=True,
        rate_percent=Decimal("0.00"),
        is_international_default=True,
    ).exists(),
    None,
)
chk(
    "GeneralTaxSettings seeded with Profile_Only",
    GeneralTaxSettings.objects.filter(setting_id="GLOBAL-TAX-SETTING", location_verification="Profile_Only").exists(),
    None,
)
chk(
    "GlobalSystemRules seeded — timezone Asia/Riyadh",
    GlobalSystemRules.objects.filter(rule_id="GLOBAL-SYSTEM-RULES", system_timezone="Asia/Riyadh").exists(),
    None,
)
chk(
    "BaseCurrencyConfig seeded — SAR",
    BaseCurrencyConfig.objects.filter(setting_id="GLOBAL-BASE-CURRENCY", base_currency__currency_code="SAR").exists(),
    None,
)
chk(
    "Run again — zero duplicates",
    after_counts_2 == after_counts_1,
    f"Counts changed: before={before_counts} after1={after_counts_1} after2={after_counts_2}",
)


#
# FORMS CHECK
#
try:
    _ = TaxCodeForm(is_edit=True)
    chk("TaxCodeForm has is_edit kwarg", True, None)
except Exception as e:
    chk("TaxCodeForm has is_edit kwarg", False, f"Exception: {e}")

tax_s15 = TaxCode.objects.get(tax_code="S-15")
form_edit = TaxCodeForm(instance=tax_s15, is_edit=True)
chk("tax_code disabled on edit", bool(getattr(form_edit.fields.get("tax_code"), "disabled", False)), None)


def tax_conflict_test(both_defaults):
    data = {
        "tax_code": "T-CONFLICT-TEST",
        "name_en": "Test EN",
        "name_ar": "Test AR",
        "rate_percent": "10.00",
        "applicable_country_code": "SA",
        "is_default_for_country": both_defaults,
        "is_international_default": both_defaults,
        "is_active": True,
    }
    f = TaxCodeForm(data, is_edit=False)
    return f


conflict_form = TaxCodeForm(
    {
        "tax_code": "T-CONFLICT-1",
        "name_en": "Test EN",
        "name_ar": "Test AR",
        "rate_percent": "10.00",
        "applicable_country_code": "SA",
        "is_default_for_country": "on",
        "is_international_default": "on",
        "is_active": "on",
    },
    is_edit=False,
)
chk(
    "Both defaults True on same record raises error",
    not conflict_form.is_valid() and "cannot be both country default" in conflict_form.errors.as_text().lower(),
    conflict_form.errors.as_text(),
)


conf_country_missing = TaxCodeForm(
    {
        "tax_code": "T-NO-COUNTRY-1",
        "name_en": "Test EN",
        "name_ar": "Test AR",
        "rate_percent": "10.00",
        "applicable_country_code": "",
        "is_default_for_country": "on",
        "is_international_default": "",
        "is_active": "on",
    },
    is_edit=False,
)
chk(
    "Country required when is_default_for_country=True",
    not conf_country_missing.is_valid()
    and "Country must be selected when setting as country default".lower()
    in conf_country_missing.errors.as_text().lower(),
    conf_country_missing.errors.as_text(),
)

dup_country_form = TaxCodeForm(
    {
        "tax_code": "T-DUP-COUNTRY-1",
        "name_en": "Test EN",
        "name_ar": "Test AR",
        "rate_percent": "10.00",
        "applicable_country_code": "SA",
        "is_default_for_country": "on",
        "is_international_default": "",
        "is_active": "on",
    },
    is_edit=False,
)
chk(
    "Duplicate country default raises error",
    not dup_country_form.is_valid()
    and "A default tax code already exists for this country".lower()
    in dup_country_form.errors.as_text().lower(),
    dup_country_form.errors.as_text(),
)

dup_int_form = TaxCodeForm(
    {
        "tax_code": "T-DUP-INTERN-1",
        "name_en": "Test EN",
        "name_ar": "Test AR",
        "rate_percent": "10.00",
        "applicable_country_code": "",
        "is_default_for_country": "",
        "is_international_default": "on",
        "is_active": "on",
    },
    is_edit=False,
)
chk(
    "Duplicate international default raises error",
    not dup_int_form.is_valid()
    and "An international default tax code already exists".lower()
    in dup_int_form.errors.as_text().lower(),
    dup_int_form.errors.as_text(),
)

gts_form_valid = GlobalSystemRulesForm(
    {
        "system_timezone": "Asia/Riyadh",
        "default_date_format": "DD/MM/YYYY",
        "grace_period_days": 3,
        "standard_billing_cycle": 30,
    }
)
chk("GlobalSystemRulesForm timezone validation works", gts_form_valid.is_valid(), gts_form_valid.errors.as_text() if not gts_form_valid.is_valid() else None)

gts_form_invalid = GlobalSystemRulesForm(
    {
        "system_timezone": "BadZone",
        "default_date_format": "DD/MM/YYYY",
        "grace_period_days": 3,
        "standard_billing_cycle": 30,
    }
)
chk(
    "Invalid timezone 'BadZone' raises validation error",
    not gts_form_invalid.is_valid()
    and "Invalid timezone".lower() in gts_form_invalid.errors.as_text().lower(),
    gts_form_invalid.errors.as_text(),
)

base_code = BaseCurrencyConfig.objects.get(setting_id="GLOBAL-BASE-CURRENCY").base_currency.currency_code
ex_form = ExchangeRateForm(base_currency_code=base_code)
currency_codes = set(ex_form.fields["currency"].queryset.values_list("currency_code", flat=True))
chk("ExchangeRateForm excludes base currency from dropdown", base_code not in currency_codes, f"base_code={base_code} present={base_code in currency_codes}")


non_base_currency = Currency.objects.exclude(currency_code=base_code).order_by("currency_code").first()
ex_form_zero = ExchangeRateForm(
    {
        "currency": non_base_currency.currency_code,
        "exchange_rate": "0",
        "is_active": "on",
    },
    base_currency_code=base_code,
)
chk("Exchange rate 0 or negative raises validation error", not ex_form_zero.is_valid(), ex_form_zero.errors.as_text())


#
# TAX CODES CRUD CHECK (via Client)
#
client = Client()
root = get_root_user()
client.force_login(root)

tax_list_url = reverse("tax_code_list")
resp = client.get(tax_list_url)
text = page_text(resp)
chk("/system-config/tax-codes/ list loads", resp.status_code == 200, f"status={resp.status_code}")
chk(
    "S-15 and Z-0 visible in list",
    ("S-15" in text) and ("Z-0" in text),
    "Missing codes",
)

sub_s15 = find_substring_near(text, "S-15")
sub_z0 = find_substring_near(text, "Z-0")
chk(
    "Country Default and Int. Default badges show correctly",
    sub_s15 is not None
    and "#0d6efd" in sub_s15
    and "background:#0d6efd" in sub_s15
    and sub_z0 is not None
    and "#6f42c1" in sub_z0,
    "Badge colors not found near expected codes",
)

new_code = "T-VERIFY-1"
while TaxCode.objects.filter(tax_code=new_code).exists():
    new_code = f"T-VERIFY-{len(new_code)+1}"

create_payload = {
    "tax_code": new_code,
    "name_en": "Verify EN",
    "name_ar": "Verify AR",
    "rate_percent": "5.00",
    "applicable_country_code": "",
    "is_active": "on",
    # defaults omitted => False
}
create_resp = client.post(reverse("tax_code_create"), data=create_payload, follow=True)
created_ok = TaxCode.objects.filter(tax_code=new_code).exists()
chk("Create new tax code works", created_ok, "Create POST failed")

edit_resp = client.get(reverse("tax_code_edit", kwargs={"pk": new_code}))
edit_text = page_text(edit_resp)
chk(
    "tax_code locked on edit",
    edit_resp.status_code == 200 and "name=\"tax_code\"" in edit_text and "disabled" in edit_text[edit_text.find("name=\"tax_code\""):edit_text.find("name=\"tax_code\"")+300],
    "Disabled tax_code not found in edit page",
)

old_active = TaxCode.objects.get(tax_code=new_code).is_active
_ = client.post(reverse("tax_code_toggle", kwargs={"pk": new_code}), data={}, follow=True)
new_active = TaxCode.objects.get(tax_code=new_code).is_active
chk("Toggle status works", new_active != old_active, None)

del_resp = client.post(reverse("tax_code_delete", kwargs={"pk": new_code}), data={}, follow=True)
del_text = page_text(del_resp)
chk(
    "Delete redirects with error",
    "Tax codes cannot be deleted. Deactivate instead." in del_text,
    "Expected delete error message not found",
)


#
# SINGLE-RECORD CONFIG CHECK
#
gts_url = reverse("general_tax_settings")
resp = client.get(gts_url)
chk("/system-config/general-tax-settings/ loads", resp.status_code == 200, f"status={resp.status_code}")

GeneralTaxSettings.objects.get(setting_id="GLOBAL-TAX-SETTING").location_verification
old_loc = GeneralTaxSettings.objects.get(setting_id="GLOBAL-TAX-SETTING").location_verification
post_payload = {
    # boolean checkbox included optionally
    "prices_include_tax": "on",
    "location_verification": "Audit_Only",
}
resp = client.post(gts_url, data=post_payload, follow=True)
new_loc = GeneralTaxSettings.objects.get(setting_id="GLOBAL-TAX-SETTING").location_verification
chk("Saving location_verification change works", new_loc != old_loc and new_loc == "Audit_Only", resp.content.decode("utf-8", errors="ignore"))

li_url = reverse("legal_identity")
resp = client.get(li_url)
chk("/system-config/legal-identity/ loads", resp.status_code == 200, f"status={resp.status_code}")

# Try logo upload and preview
li_obj = LegalIdentity.objects.get(identity_id="GLOBAL-LEGAL-IDENTITY")
try:
    from PIL import Image
    import io

    img = Image.new("RGB", (10, 10), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    uploaded = SimpleUploadedFile("verify_logo.png", buf.read(), content_type="image/png")

    post_data = {
        "company_name_en": li_obj.company_name_en,
        "company_name_ar": li_obj.company_name_ar,
        "company_country_code": li_obj.company_country_code_id or "",
        "commercial_register": li_obj.commercial_register,
        "tax_number": li_obj.tax_number,
        "registered_address": li_obj.registered_address,
        "support_email": li_obj.support_email,
        "support_phone": li_obj.support_phone or "",
    }
    post_data["company_logo"] = uploaded
    resp = client.post(li_url, data=post_data, follow=True)
    li_obj.refresh_from_db()
    preview_resp = client.get(li_url)
    preview_text = page_text(preview_resp)
    chk(
        "Logo upload works and preview shows",
        li_obj.company_logo is not None and "img" in preview_text and "legal/" in preview_text,
        "Upload/preview did not show expected content",
    )
except Exception as e:
    chk("Logo upload works and preview shows", False, f"PIL/ImageField upload test failed: {e}")

gss_url = reverse("global_system_rules")
resp = client.get(gss_url)
chk("/system-config/global-system-rules/ loads", resp.status_code == 200, f"status={resp.status_code}")

old_tz = GlobalSystemRules.objects.get(rule_id="GLOBAL-SYSTEM-RULES").system_timezone
resp = client.post(gss_url, data={
    "system_timezone": "UTC",
    "default_date_format": GlobalSystemRules.objects.get(rule_id="GLOBAL-SYSTEM-RULES").default_date_format,
    "grace_period_days": GlobalSystemRules.objects.get(rule_id="GLOBAL-SYSTEM-RULES").grace_period_days,
    "standard_billing_cycle": GlobalSystemRules.objects.get(rule_id="GLOBAL-SYSTEM-RULES").standard_billing_cycle,
}, follow=True)
new_tz = GlobalSystemRules.objects.get(rule_id="GLOBAL-SYSTEM-RULES").system_timezone
chk("Saving timezone change works", new_tz == "UTC" and new_tz != old_tz, resp.content.decode("utf-8", errors="ignore"))

resp = client.post(gss_url, data={
    "system_timezone": "BadZone",
    "default_date_format": "DD/MM/YYYY",
    "grace_period_days": 3,
    "standard_billing_cycle": 30,
})
resp_text = page_text(resp)
chk("Invalid timezone shows validation error", "Invalid timezone" in resp_text, resp_text[:5000])

bc_url = reverse("base_currency")
resp = client.get(bc_url)
bc_text = page_text(resp)
chk("/system-config/base-currency/ loads", resp.status_code == 200, f"status={resp.status_code}")
chk("Warning message visible on base currency page", "accounting root currency" in bc_text.lower(), "Warning text not found")

base_obj = BaseCurrencyConfig.objects.get(setting_id="GLOBAL-BASE-CURRENCY")
current_base = base_obj.base_currency.currency_code
alt = Currency.objects.exclude(currency_code=current_base).order_by("currency_code").first()
resp = client.post(bc_url, data={"base_currency": alt.currency_code}, follow=True)
base_obj.refresh_from_db()
chk("Changing base currency saves correctly", base_obj.base_currency.currency_code == alt.currency_code, resp.content.decode("utf-8", errors="ignore"))

# Phase 5 TODO comment presence in views.py
views_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "superadmin", "views.py")
with open(views_py, "r", encoding="utf-8") as f:
    views_txt = f.read()
chk("TODO comment present for Phase 5 lock", "TODO Phase 5: Check if any financial transactions" in views_txt, "TODO comment not found")


#
# EXCHANGE RATES CHECK
#
fx_list_url = reverse("fx_rate_list")
resp = client.get(fx_list_url)
fx_text = page_text(resp)
chk("/system-config/exchange-rates/ list loads", resp.status_code == 200, f"status={resp.status_code}")

base_code_now = BaseCurrencyConfig.objects.get(setting_id="GLOBAL-BASE-CURRENCY").base_currency.currency_code
chk("Base currency shown in info bar", "Base Currency" in fx_text and base_code_now in fx_text, "Base currency info missing")

active_rates = ExchangeRate.objects.filter(is_active=True).values_list("currency__currency_code", flat=True).distinct()
candidate = Currency.objects.exclude(currency_code=base_code_now).exclude(currency_code__in=active_rates).order_by("currency_code").first()

if candidate is None:
    # if everything has active rate, deactivate one temporarily to allow create test
    existing = ExchangeRate.objects.filter(is_active=True).exclude(currency__currency_code=base_code_now).first()
    existing.is_active = False
    existing.save(update_fields=["is_active", "updated_at", "updated_by"])
    candidate = existing.currency

ex_create_payload = {"currency": candidate.currency_code, "exchange_rate": "1.234567", "is_active": "on"}
before_fxlog = FXRateChangeLog.objects.count()
resp = client.post(reverse("fx_rate_create"), data=ex_create_payload, follow=True)
rate_obj = ExchangeRate.objects.filter(currency=candidate).order_by("-updated_at").first()
fxlog_created = FXRateChangeLog.objects.filter(currency=candidate, notes="Initial rate set").exists()
chk(
    "Create exchange rate works",
    rate_obj is not None and rate_obj.currency_id == candidate.currency_code and rate_obj.is_active is True,
    resp.content.decode("utf-8", errors="ignore")[:2000],
)
chk("FX Change Log auto-created on new rate save", fxlog_created and FXRateChangeLog.objects.count() >= before_fxlog + 1, None)

created_rate = ExchangeRate.objects.get(currency=candidate, is_active=True)
old_rate = created_rate.exchange_rate
change_notes = "Verify edit"
edit_payload = {"exchange_rate": "2.345678", "is_active": "on", "change_notes": change_notes}
before_fxlog2 = FXRateChangeLog.objects.count()
resp = client.post(reverse("fx_rate_edit", kwargs={"pk": created_rate.fx_id}), data=edit_payload, follow=True)
created_rate.refresh_from_db()
log_latest = FXRateChangeLog.objects.filter(currency=candidate, notes=change_notes).order_by("-changed_at").first()
chk("Editing rate saves and creates change log entry", log_latest is not None and created_rate.exchange_rate == Decimal("2.345678"), resp.content.decode("utf-8", errors="ignore")[:2000])

chk("Old rate captured correctly before save", log_latest is not None and log_latest.old_rate == old_rate, None)

chk("Base currency excluded from currency dropdown", f'value="{base_code_now}"' not in page_text(client.get(reverse("fx_rate_create")).__class__), None)

# Duplicate active rate blocked
dup_payload = {"currency": candidate.currency_code, "exchange_rate": "3.456789", "is_active": "on"}
dup_resp = client.post(reverse("fx_rate_create"), data=dup_payload)
dup_text = page_text(dup_resp)
chk(
    "Duplicate active rate for same currency blocked",
    "An active rate already exists for this currency. Edit it instead." in dup_text,
    dup_text[:2000],
)

fx_log_url = reverse("fx_change_log")
resp = client.get(fx_log_url)
log_text = page_text(resp)
chk("/system-config/fx-change-log/ loads", resp.status_code == 200, f"status={resp.status_code}")

chk(
    "Old rate, new rate, changed by all visible",
    str(old_rate) in log_text and "Verify edit" in log_text and root.email in log_text,
    "Expected values not found",
)

# No edit/delete buttons anywhere on change log
fx_log_template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "system_config", "exchange_rates", "fx_log.html")
with open(fx_log_template_path, "r", encoding="utf-8") as f:
    fx_log_template = f.read()
chk("No edit or delete buttons on change log", ("Edit" not in fx_log_template and "delete" not in fx_log_template.lower() and "toggle" not in fx_log_template.lower()), None)

# Filter by currency works
other_currency = Currency.objects.exclude(currency_code=base_code_now).exclude(currency_code=candidate.currency_code).order_by("currency_code").first()
if other_currency:
    # create another log entry quickly by updating existing rate if needed
    other_rate = ExchangeRate.objects.filter(currency=other_currency).order_by("-updated_at").first()
    if other_rate:
        FXRateChangeLog.objects.create(
            currency=other_currency,
            old_rate=other_rate.exchange_rate,
            new_rate=other_rate.exchange_rate,
            notes="tmp filter",
            changed_by=root,
        )
resp = client.get(fx_log_url, data={"currency": candidate.currency_code})
filter_text = page_text(resp)
chk(
    "Filter by currency works on change log",
    candidate.currency_code in filter_text and ("tmp filter" not in filter_text or (other_currency is None)),
    "Filter result did not constrain to expected currency",
)


#
# SIDEBAR CHECK
#
side = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "partials", "sidebar.html")
with open(side, "r", encoding="utf-8") as f:
    sidebar_template = f.read()

expected_names = [
    "Tax Codes Master",
    "General Tax Settings",
    "Legal Identity",
    "Global System Rules",
    "Base Currency",
    "Exchange Rates Manager",
    "FX Rate Change Log",
]
for name in expected_names:
    ok = name in sidebar_template
    chk("System Configurations & Tax menu has all sub-items", ok if name == expected_names[-1] else ok, None)
    # the above calls would duplicate; we only want the item once. We'll adjust below.

# Replace duplicates by a single accurate check
results = [r for r in results if r[0] != "System Configurations & Tax menu has all sub-items"]
chk(
    "System Configurations & Tax menu has all sub-items",
    all(n in sidebar_template for n in expected_names),
    "Some sidebar sub-items missing in template",
)

sub_urls = [
    ("tax_code_list", "Tax Codes Master"),
    ("general_tax_settings", "General Tax Settings"),
    ("legal_identity", "Legal Identity"),
    ("global_system_rules", "Global System Rules"),
    ("base_currency", "Base Currency"),
    ("fx_rate_list", "Exchange Rates Manager"),
    ("fx_change_log", "FX Rate Change Log"),
]
sub_get_ok = True
bad = []
for url_name, label in sub_urls:
    r = client.get(reverse(url_name))
    if r.status_code != 200:
        sub_get_ok = False
        bad.append(f"{label}:{r.status_code}")
chk("All sub-item links work correctly", sub_get_ok, ", ".join(bad) if bad else None)

def active_check(url_name, label):
    r = client.get(reverse(url_name))
    t = page_text(r)
    # Look for the link text and ensure active class exists close to it.
    idx = t.find(label)
    if idx < 0:
        return False, "Label not found"
    window = t[max(0, idx - 300):idx + 300]
    return ("submenu-link active" in window) or (("submenu-link" in window and "active" in window)), f"Active class not found near {label}"

active_all = True
active_bad = []
for url_name, label in sub_urls:
    ok, err = active_check(url_name, label)
    if not ok:
        active_all = False
        active_bad.append(err)
chk("Active state correct on each page", active_all, "; ".join(active_bad))


# Sort results by insertion order already preserved. Print.
print(json.dumps(
    [
        {"item": label, "ok": ok, "error": err}
        for (label, ok, err) in results
    ],
    indent=2,
    ensure_ascii=True,
))

