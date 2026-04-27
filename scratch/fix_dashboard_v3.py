
import os

file_path = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\templates\dashboard\dashboard.html"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Translate JS Chart Labels
content = content.replace("labels: ['Open', 'Overdue']", "labels: [isArabic ? 'مفتوح' : 'Open', isArabic ? 'متأخر' : 'Overdue']")
content = content.replace("labels: ['Orders', 'Transfers']", "labels: [isArabic ? 'طلبات' : 'Orders', isArabic ? 'تحويلات' : 'Transfers']")
content = content.replace("label: 'Revenue (SAR)'", "label: isArabic ? 'الإيرادات (ريال)' : 'Revenue (SAR)'")

# Also handle Role Distribution Chart labels which are dynamic
# It uses: labels: [{% for r in role_distribution %}'{{ r.role_name_en }}',{% endfor %}]
# I'll change it to use role_name_ar if isArabic
content = content.replace(
    "labels: [{% for r in role_distribution %}'{{ r.role_name_en }}',{% endfor %}]",
    "labels: [{% for r in role_distribution %}isArabic ? '{{ r.role_name_ar }}' : '{{ r.role_name_en }}',{% endfor %}]"
)

# Fix table header strings that might be missing in PO or not picking up
content = content.replace('<th>Tenant Name</th>', '<th>{% translate "Tenant Name" %}</th>')
content = content.replace('<th>Grand Total</th>', '<th>{% translate "Grand Total" %}</th>')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied JS and table header fixes to dashboard.html")
