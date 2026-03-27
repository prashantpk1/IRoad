import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force UTF-8 output to avoid UnicodeEncodeError on Windows consoles.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

django.setup()

# Now import models AFTER django.setup()
from superadmin.models import Role, AdminUser  # noqa: E402


def seed_roles():
    print("\n--- Seeding Roles ---")
    roles = [
        {
            "role_name_en": "Super Admin",
            "role_name_ar": "مدير النظام",
            "description": "Full access to all modules and configurations",
            "is_system_default": True,
            "status": "Active",
        },
        {
            "role_name_en": "Sales",
            "role_name_ar": "المبيعات",
            "description": "Manages tenant onboarding and subscription orders",
            "is_system_default": True,
            "status": "Active",
        },
        {
            "role_name_en": "Support",
            "role_name_ar": "الدعم الفني",
            "description": "Handles support tickets and tenant communication",
            "is_system_default": True,
            "status": "Active",
        },
    ]

    for role_data in roles:
        role, created = Role.objects.get_or_create(
            role_name_en=role_data["role_name_en"],
            defaults=role_data,
        )
        if created:
            print(f"  ✅ Role created: {role.role_name_en}")
        else:
            print(f"  ⏭️  Role already exists: {role.role_name_en}")


def seed_root_admin():
    print("\n--- Seeding Root Admin ---")
    try:
        super_admin_role = Role.objects.get(role_name_en="Super Admin")
    except Role.DoesNotExist:
        print("  ❌ ERROR: Super Admin role not found. Run seed_roles first.")
        return

    try:
        admin, created = AdminUser.objects.get_or_create(
            email="admin@iroad.com",
            defaults={
                "first_name": "Root",
                "last_name": "Admin",
                "status": "Active",
                "is_root": True,
                "role": super_admin_role,
            },
        )

        if created:
            admin.set_password("Admin@1234")
            admin.save()
            print(f"  ✅ Root admin created: {admin.email}")
            print(f"  ✅ Password set: Admin@1234")
            print(f"  ✅ Role assigned: {super_admin_role.role_name_en}")
        else:
            # Make sure role is assigned even if admin already existed.
            updated = False
            if not admin.is_root:
                admin.is_root = True
                updated = True
            if admin.role_id != super_admin_role.pk:
                admin.role = super_admin_role
                updated = True
            if admin.status != "Active":
                admin.status = "Active"
                updated = True

            if updated:
                admin.save()
                print(f"  ✅ Root admin ensured: {admin.email}")
                print(f"  ✅ Role assigned: {super_admin_role.role_name_en}")
            else:
                print(f"  ⏭️  Root admin already exists: {admin.email}")

    except Exception as e:
        print(f"  ❌ ERROR while seeding Root Admin: {e}")


def seed_security_settings():
    print("\n--- Seeding Admin Security Settings ---")
    from superadmin.models import AdminSecuritySettings

    _, created = AdminSecuritySettings.objects.get_or_create(
        setting_id="ADMIN-SEC-CONF",
        defaults={
            "session_timeout_minutes": 240,
            "max_failed_logins": 3,
            "lockout_duration_minutes": 30,
        },
    )
    if created:
        print("  ✅ Admin Security Settings created with defaults")
        print("  ✅ Session timeout: 240 minutes")
        print("  ✅ Max failed logins: 3")
        print("  ✅ Lockout duration: 30 minutes")
    else:
        print("  ⏭️  Admin Security Settings already exists")


def seed_countries():
    print("\n--- Seeding Countries ---")
    from superadmin.models import Country

    countries = [
        {'country_code': 'SA', 'name_en': 'Saudi Arabia',
         'name_ar': 'المملكة العربية السعودية', 'is_active': True},
        {'country_code': 'AE', 'name_en': 'United Arab Emirates',
         'name_ar': 'الإمارات العربية المتحدة', 'is_active': True},
        {'country_code': 'KW', 'name_en': 'Kuwait',
         'name_ar': 'الكويت', 'is_active': True},
        {'country_code': 'BH', 'name_en': 'Bahrain',
         'name_ar': 'البحرين', 'is_active': True},
        {'country_code': 'QA', 'name_en': 'Qatar',
         'name_ar': 'قطر', 'is_active': True},
        {'country_code': 'OM', 'name_en': 'Oman',
         'name_ar': 'عُمان', 'is_active': True},
        {'country_code': 'JO', 'name_en': 'Jordan',
         'name_ar': 'الأردن', 'is_active': True},
        {'country_code': 'EG', 'name_en': 'Egypt',
         'name_ar': 'مصر', 'is_active': True},
        {'country_code': 'US', 'name_en': 'United States',
         'name_ar': 'الولايات المتحدة الأمريكية', 'is_active': True},
        {'country_code': 'GB', 'name_en': 'United Kingdom',
         'name_ar': 'المملكة المتحدة', 'is_active': True},
        {'country_code': 'IN', 'name_en': 'India',
         'name_ar': 'الهند', 'is_active': True},
        {'country_code': 'PK', 'name_en': 'Pakistan',
         'name_ar': 'باكستان', 'is_active': True},
        {'country_code': 'TR', 'name_en': 'Turkey',
         'name_ar': 'تركيا', 'is_active': True},
        {'country_code': 'DE', 'name_en': 'Germany',
         'name_ar': 'ألمانيا', 'is_active': True},
        {'country_code': 'FR', 'name_en': 'France',
         'name_ar': 'فرنسا', 'is_active': True},
    ]

    created_count = 0
    skipped_count = 0
    for data in countries:
        obj, created = Country.objects.get_or_create(
            country_code=data['country_code'],
            defaults=data,
        )
        if created:
            print(f"  ✅ Country created: {obj.name_en}")
            created_count += 1
        else:
            print(f"  ⏭️  Already exists: {obj.name_en}")
            skipped_count += 1

    print(f"  Total: {created_count} created, {skipped_count} skipped")


def seed_currencies():
    print("\n--- Seeding Currencies ---")
    from superadmin.models import Currency

    currencies = [
        {'currency_code': 'SAR', 'name_en': 'Saudi Riyal',
         'name_ar': 'الريال السعودي', 'currency_symbol': 'ريال',
         'decimal_places': 2, 'is_active': True},
        {'currency_code': 'USD', 'name_en': 'US Dollar',
         'name_ar': 'الدولار الأمريكي', 'currency_symbol': '$',
         'decimal_places': 2, 'is_active': True},
        {'currency_code': 'AED', 'name_en': 'UAE Dirham',
         'name_ar': 'درهم إماراتي', 'currency_symbol': 'د.إ',
         'decimal_places': 2, 'is_active': True},
        {'currency_code': 'KWD', 'name_en': 'Kuwaiti Dinar',
         'name_ar': 'دينار كويتي', 'currency_symbol': 'د.ك',
         'decimal_places': 3, 'is_active': True},
        {'currency_code': 'QAR', 'name_en': 'Qatari Riyal',
         'name_ar': 'ريال قطري', 'currency_symbol': 'ر.ق',
         'decimal_places': 2, 'is_active': True},
        {'currency_code': 'BHD', 'name_en': 'Bahraini Dinar',
         'name_ar': 'دينار بحريني', 'currency_symbol': 'د.ب',
         'decimal_places': 3, 'is_active': True},
        {'currency_code': 'OMR', 'name_en': 'Omani Rial',
         'name_ar': 'ريال عُماني', 'currency_symbol': 'ر.ع',
         'decimal_places': 3, 'is_active': True},
        {'currency_code': 'EUR', 'name_en': 'Euro',
         'name_ar': 'يورو', 'currency_symbol': '€',
         'decimal_places': 2, 'is_active': True},
        {'currency_code': 'GBP', 'name_en': 'British Pound',
         'name_ar': 'الجنيه الإسترليني', 'currency_symbol': '£',
         'decimal_places': 2, 'is_active': True},
        {'currency_code': 'EGP', 'name_en': 'Egyptian Pound',
         'name_ar': 'الجنيه المصري', 'currency_symbol': 'ج.م',
         'decimal_places': 2, 'is_active': True},
    ]

    created_count = 0
    skipped_count = 0
    for data in currencies:
        obj, created = Currency.objects.get_or_create(
            currency_code=data['currency_code'],
            defaults=data,
        )
        if created:
            print(
                f"  ✅ Currency created: {obj.name_en} "
                f"({obj.currency_symbol})"
            )
            created_count += 1
        else:
            print(f"  ⏭️  Already exists: {obj.name_en}")
            skipped_count += 1

    print(f"  Total: {created_count} created, {skipped_count} skipped")


def seed_tax_codes():
    print("\n--- Seeding Tax Codes ---")
    from superadmin.models import TaxCode, Country

    try:
        sa_country = Country.objects.get(country_code='SA')
    except Country.DoesNotExist:
        sa_country = None
        print("  ⚠️  SA country not found — "
              "tax codes seeded without country link")

    tax_codes = [
        {
            'tax_code': 'S-15',
            'name_en': 'Standard VAT 15%',
            'name_ar': 'ضريبة القيمة المضافة 15%',
            'rate_percent': '15.00',
            'applicable_country_code': sa_country,
            'is_default_for_country': True,
            'is_international_default': False,
            'is_active': True,
        },
        {
            'tax_code': 'Z-0',
            'name_en': 'Zero Rate (International)',
            'name_ar': 'معدل صفري (دولي)',
            'rate_percent': '0.00',
            'applicable_country_code': None,
            'is_default_for_country': False,
            'is_international_default': True,
            'is_active': True,
        },
    ]

    for data in tax_codes:
        obj, created = TaxCode.objects.get_or_create(
            tax_code=data['tax_code'],
            defaults=data
        )
        if created:
            print(f"  ✅ Tax code created: {obj.name_en}")
        else:
            print(f"  ⏭️  Already exists: {obj.name_en}")


def seed_general_tax_settings():
    print("\n--- Seeding General Tax Settings ---")
    from superadmin.models import GeneralTaxSettings

    obj, created = GeneralTaxSettings.objects.get_or_create(
        setting_id='GLOBAL-TAX-SETTING',
        defaults={
            'prices_include_tax': False,
            'location_verification': 'Profile_Only',
        }
    )
    if created:
        print("  ✅ General Tax Settings created")
        print("  ✅ prices_include_tax: False")
        print("  ✅ location_verification: Profile_Only")
    else:
        print("  ⏭️  General Tax Settings already exists")


def seed_global_system_rules():
    print("\n--- Seeding Global System Rules ---")
    from superadmin.models import GlobalSystemRules

    obj, created = GlobalSystemRules.objects.get_or_create(
        rule_id='GLOBAL-SYSTEM-RULES',
        defaults={
            'system_timezone': 'Asia/Riyadh',
            'default_date_format': 'DD/MM/YYYY',
            'grace_period_days': 3,
            'standard_billing_cycle': 30,
        }
    )
    if created:
        print("  ✅ Global System Rules created")
        print("  ✅ Timezone: Asia/Riyadh")
        print("  ✅ Grace period: 3 days")
        print("  ✅ Billing cycle: 30 days")
    else:
        print("  ⏭️  Global System Rules already exists")


def seed_base_currency():
    print("\n--- Seeding Base Currency Config ---")
    from superadmin.models import BaseCurrencyConfig, Currency

    try:
        sar = Currency.objects.get(currency_code='SAR')
    except Currency.DoesNotExist:
        print("  ❌ ERROR: SAR currency not found. "
              "Run seed_currencies first.")
        return

    obj, created = BaseCurrencyConfig.objects.get_or_create(
        setting_id='GLOBAL-BASE-CURRENCY',
        defaults={'base_currency': sar}
    )
    if created:
        print("  ✅ Base Currency set to: SAR")
    else:
        print("  ⏭️  Base Currency already configured: "
              f"{obj.base_currency_id}")


def seed_tenant_security_settings():
    print("\n--- Seeding Tenant Security Settings ---")
    from superadmin.models import TenantSecuritySettings

    obj, created = TenantSecuritySettings.objects.get_or_create(
        setting_id='TENANT-SEC-CONF',
        defaults={
            'tenant_web_timeout_hours': 12,
            'driver_app_timeout_days': 30,
            'max_failed_logins': 5,
            'lockout_duration_minutes': 15,
        }
    )
    if created:
        print("  ✅ Tenant Security Settings created")
        print("  ✅ Web timeout: 12 hours")
        print("  ✅ Driver app timeout: 30 days")
        print("  ✅ Max failed logins: 5")
        print("  ✅ Lockout: 15 minutes")
    else:
        print("  ⏭️  Tenant Security Settings already exists")


def main():
    print("=" * 50)
    print("  IRoad Super Admin — Master Seed Script")
    print("=" * 50)

    try:
        seed_roles()
        seed_root_admin()
        seed_security_settings()
        seed_countries()
        seed_currencies()
        seed_tax_codes()
        seed_general_tax_settings()
        seed_global_system_rules()
        seed_base_currency()
        seed_tenant_security_settings()

        # Future phases will add their seed functions here:
        # seed_security_settings()  ← Phase 2 ✅ (called above)
        # seed_countries()         ← Phase 3 ✅ (now active above)
        # seed_currencies()        ← Phase 3 ✅ (now active above)
        # seed_tax_codes()         ← Phase 4 ✅ (now active above)
        # seed_general_tax_settings() ← Phase 4 ✅ (now active above)
        # seed_global_system_rules()  ← Phase 4 ✅ (now active above)
        # seed_base_currency()        ← Phase 4 ✅ (now active above)
        # seed_tenant_security_settings() ← Phase 10 ✅ (now active above)
        # seed_plans()             ← Phase 5

        print("\n" + "=" * 50)
        print("  ✅ All seeding completed successfully")
        print("=" * 50)
    except Exception as e:
        print(f"\n  ❌ Seeding failed: {e}")


if __name__ == "__main__":
    main()

