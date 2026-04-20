from pathlib import Path
import struct

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed Arabic gettext entries for UI strings."

    def handle(self, *args, **options):
        translations = {
            "Switch Language": "تبديل اللغة",
            "Notifications": "الإشعارات",
            "Dashboard": "لوحة القيادة",
            "Super Admin": "المشرف العام",
            "Super Admin Dashboard": "لوحة تحكم المشرف العام",
            "My Account": "حسابي",
            "Sign out": "تسجيل الخروج",
            "Search shipments, clients, addresses...": "ابحث عن الشحنات والعملاء والعناوين...",
            "Welcome back": "مرحباً بعودتك",
            "Here's what's happening with your system today": "نظرة عامة على نشاط نظامك اليوم",
            "Total Revenue This Month": "إجمالي الإيرادات هذا الشهر",
            "Active Subscribers": "المشتركين النشطين",
            "Pending Approvals": "الموافقات المعلقة",
            "No notifications": "لا توجد إشعارات",
            "You are yet to receive notifications": "لم تصلك إشعارات بعد",
            "Active": "نشط",
            "Inactive": "غير نشط",
            "Save": "حفظ",
            "Cancel": "إلغاء",
            "Delete": "حذف",
            "Edit": "تعديل",
            "Add": "إضافة",
            "Back": "رجوع",
            "Next": "التالي",
            "Previous": "السابق",
            "Search...": "بحث...",
            "User Management": "إدارة المستخدمين",
            "Subadmin": "مسؤول فرعي",
            "Subscriptions": "الاشتراكات",
            "Subscription Packages": "باقات الاشتراك",
            "Reports": "التقارير",
            "Subscription Report": "تقرير الاشتراكات",
            "Companies": "الشركات",
            "Company List": "قائمة الشركات",
            "Configuration": "الإعدادات",
            "Dropdown Master": "إدارة القوائم",
            "Languages": "اللغات",
            "Email Templates": "قوالب البريد",
            "Analytics": "التحليلات",
            "Email Configuration": "إعدادات البريد",
            "Settings": "الإعدادات",
            "No records found": "لم يتم العثور على سجلات",
            "No data available": "لا توجد بيانات",
            "Pending Liquidity": "السيولة المعلقة",
            "Ticket Health": "صحة التذاكر",
            "Revenue Forecast & Trend": "توقعات الإيرادات والاتجاه",
            "Actions": "الإجراءات",
            "Name": "الاسم",
            "Email": "البريد الإلكتروني",
            "Status": "الحالة",
            "Description": "الوصف",
            "Close": "إغلاق",
            "Done": "تم",
        }

        locale_dir = Path(settings.BASE_DIR) / "locale" / "ar" / "LC_MESSAGES"
        locale_dir.mkdir(parents=True, exist_ok=True)
        po_path = locale_dir / "django.po"

        lines = [
            'msgid ""',
            'msgstr ""',
            '"Project-Id-Version: iRoad\\n"',
            '"POT-Creation-Date: 2026-04-20 00:00+0000\\n"',
            '"PO-Revision-Date: 2026-04-20 00:00+0000\\n"',
            '"Language: ar\\n"',
            '"MIME-Version: 1.0\\n"',
            '"Content-Type: text/plain; charset=UTF-8\\n"',
            '"Content-Transfer-Encoding: 8bit\\n"',
            "",
        ]

        for msgid in sorted(translations):
            msgstr = translations[msgid]
            escaped_id = msgid.replace("\\", "\\\\").replace('"', '\\"')
            escaped_str = msgstr.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'msgid "{escaped_id}"')
            lines.append(f'msgstr "{escaped_str}"')
            lines.append("")

        po_path.write_text("\n".join(lines), encoding="utf-8")
        mo_path = locale_dir / "django.mo"
        self._write_mo_file(mo_path, translations)

        self.stdout.write(self.style.SUCCESS(f"Seeded translation file: {po_path}"))
        self.stdout.write(self.style.SUCCESS(f"Compiled translation file: {mo_path}"))

    @staticmethod
    def _write_mo_file(path: Path, translations: dict[str, str]) -> None:
        """Write a minimal GNU MO file without external msgfmt dependency."""
        # The empty msgid metadata entry is required so gettext picks UTF-8.
        metadata = (
            "Project-Id-Version: iRoad\n"
            "POT-Creation-Date: 2026-04-20 00:00+0000\n"
            "PO-Revision-Date: 2026-04-20 00:00+0000\n"
            "Language: ar\n"
            "MIME-Version: 1.0\n"
            "Content-Type: text/plain; charset=UTF-8\n"
            "Content-Transfer-Encoding: 8bit\n"
        )

        catalog = {"": metadata}
        catalog.update(translations)
        keys = sorted(catalog)
        ids = [k.encode("utf-8") for k in keys]
        strs = [catalog[k].encode("utf-8") for k in keys]

        n = len(keys)
        header_size = 7 * 4
        id_table_offset = header_size
        str_table_offset = id_table_offset + n * 8
        data_offset = str_table_offset + n * 8

        id_entries = []
        str_entries = []
        data = b""
        cursor = data_offset

        for b in ids:
            id_entries.append((len(b), cursor))
            data += b + b"\x00"
            cursor += len(b) + 1

        for b in strs:
            str_entries.append((len(b), cursor))
            data += b + b"\x00"
            cursor += len(b) + 1

        with path.open("wb") as f:
            # magic, version, nstrings, orig_tab_offset, trans_tab_offset, hash_size, hash_offset
            f.write(struct.pack("<Iiiiiii", 0x950412DE, 0, n, id_table_offset, str_table_offset, 0, 0))
            for length, offset in id_entries:
                f.write(struct.pack("<ii", length, offset))
            for length, offset in str_entries:
                f.write(struct.pack("<ii", length, offset))
            f.write(data)
