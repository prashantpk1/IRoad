
import os

po_file_path = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\locale\ar\LC_MESSAGES\django.po"

translations = {
    "Role": "الدور",
    "Subscribers CRM & Billing": "إدارة المشتركين والفوترة",
    "Communication & Alerts": "الاتصالات والتنبيهات",
    "System Configurations & Tax": "إعدادات النظام والضرائب",
    "Security & Audit": "الأمن والتدقيق",
    "User Count": "عدد المستخدمين",
    "Recently Added Users": "المستخدمون المضافون حديثاً",
    "Admin Users": "مستخدمين النظام",
    "Roles Master": "سجل الأدوار",
    "Users Analytics": "تحليلات المستخدمين",
    "Role Name": "اسم الدور",
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

print("Updated django.po with more missing translations.")
