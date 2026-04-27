
import os

po_file_path = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.po"

translations = {
    "Administration": "الإدارة",
    "System Users Management": "إدارة مستخدمي النظام",
    "Users Analytics": "تحليلات المستخدمين",
    "Roles Master": "سجل الأدوار",
    "Admin Users": "مستخدمي النظام",
    "Subscription Plans Management": "إدارة باقات الاشتراك",
    "Subscription Plans": "باقات الاشتراك",
    "Add-ons Pricing": "أسعار الإضافات",
    "Promo Codes": "أكواد الخصم",
    "Subscribers CRM & Billing": "إدارة المشتركين والفوترة",
    "Subscribers List": "قائمة المشتركين",
    "Subscription Orders": "طلبات الاشتراك",
    "Transactions Ledger": "سجل المعاملات",
    "Standard Invoices": "الفواتير القياسية",
    "Communication & Alerts": "الاتصالات والتنبيهات",
    "Gateway Settings": "إعدادات البوابات",
    "Notification Templates": "قوالب الإشعارات",
    "Events Mapping": "ربط الأحداث",
    "System Banners": "لافتات النظام",
    "Internal Alerts": "التنبيهات الداخلية",
    "Comm Logs": "سجلات الاتصال",
    "Payment Infrastructure": "البنية التحتية للمدفوعات",
    "Bank Accounts": "الحسابات البنكية",
    "Payment Gateways": "بوابات الدفع",
    "Payment Methods": "طرق الدفع",
    "Global Master Data": "البيانات الأساسية العالمية",
    "Countries Master": "سجل الدول",
    "Currencies Master": "سجل العملات",
    "System Configurations & Tax": "إعدادات النظام والضرائب",
    "Tax Codes": "الأكواد الضريبية",
    "General Tax Settings": "إعدادات الضرائب العامة",
    "Legal Identity": "الهوية القانونية",
    "Global System Rules": "قواعد النظام العالمية",
    "Base Currency": "العملة الأساسية",
    "Exchange Rates": "أسعار الصرف",
    "FX Change Log": "سجل تغيير أسعار الصرف",
    "Support Management": "إدارة الدعم الفني",
    "Support Categories": "فئات الدعم",
    "Canned Responses": "الردود الجاهزة",
    "Support Tickets": "تذاكر الدعم",
    "Security & Audit": "الأمن والتدقيق",
    "Access Log": "سجل الوصول",
    "Admin Security": "أمن المسؤولين",
    "Active Sessions Monitor": "مراقبة الجلسات النشطة",
    "Audit Log": "سجل التدقيق",
    "System Users Analytics": "تحليلات مستخدمي النظام",
    "Staff overview and activity insights": "نظرة عامة على الموظفين ورؤى النشاط",
    "Total Active Staff": "إجمالي الموظفين النشطين",
    "Suspended Accounts": "الحسابات الموقوفة",
    "Pending Activation": "في انتظار التفعيل",
    "2FA Adoption Rate": "معدل اعتماد التحقق الثنائي",
    "Stale Accounts": "الحسابات غير النشطة",
    "Accounts inactive for 30+ days (Active only)": "الحسابات غير النشطة لأكثر من 30 يوماً (النشطة فقط)",
    "Last Login": "آخر تسجيل دخول",
    "Days Since Login": "الأيام منذ آخر دخول",
    "All clear": "الكل نشط",
    "All accounts are active recently": "جميع الحسابات كانت نشطة مؤخراً",
    "Role Distribution": "توزيع الأدوار",
    "Active users per role": "المستخدمون النشطون لكل دور",
    "Role Name": "اسم الدور",
    "User Count": "عدد المستخدمين",
    "Recently Added Users": "المستخدمون المضافون حديثاً",
    "Created At": "تاريخ الإنشاء",
    "Pending": "قيد التفعيل",
    "Suspended": "موقوف",
    "Locked": "مغلق",
    "Queue": "قائمة الانتظار",
    "Adoption": "الاعتماد",
    "Unassigned": "غير معين",
}

with open(po_file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

existing_msgids = set()
for line in lines:
    if line.startswith("msgid "):
        msgid = line[7:-2]
        existing_msgids.add(msgid)

with open(po_file_path, "a", encoding="utf-8") as f:
    for msgid, msgstr in translations.items():
        if msgid not in existing_msgids:
            f.write(f'\nmsgid "{msgid}"\n')
            f.write(f'msgstr "{msgstr}"\n')

print("Updated django.po with missing translations.")
