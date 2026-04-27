
import os

file_path = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\templates\dashboard\dashboard.html"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix header
content = content.replace(
    "{% extends 'base.html' %}\n{% load static %}\n{% block title %}Super Admin Dashboard{% endblock %}",
    "{% extends 'base.html' %}\n{% load static %}\n{% load i18n %}\n{% block title %}{% translate \"Super Admin Dashboard\" %}{% endblock %}"
)
content = content.replace(
    "{% block page_title %}Super Admin Dashboard{% endblock %}",
    "{% block page_title %}{% translate \"Super Admin Dashboard\" %}{% endblock %}"
)

# Fix toolbar title and subtitle
content = content.replace(
    '<h2 class="mb-1">Super Admin Dashboard</h2>',
    '<h2 class="mb-1">{% translate "Super Admin Dashboard" %}</h2>'
)
content = content.replace(
    'System overview — real-time platform insights',
    '{% translate "System overview — real-time platform insights" %}'
)

# Fix JS locale logic
old_js = """function updateDateTime() {
    const now = new Date();
    const dateEl = document.getElementById('dashDate');
    const timeEl = document.getElementById('dashTime');
    if (dateEl) {
        dateEl.textContent = now.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    }
    if (timeEl) {
        timeEl.textContent = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
}"""

new_js = """function updateDateTime() {
    const now = new Date();
    const dateEl = document.getElementById('dashDate');
    const timeEl = document.getElementById('dashTime');
    const docLang = (document.documentElement.lang || "en").toLowerCase();
    const locale = docLang.startsWith("ar") ? "ar-SA" : "en-US";
    
    if (dateEl) {
        dateEl.textContent = now.toLocaleDateString(locale, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    }
    if (timeEl) {
        timeEl.textContent = now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
}"""

# Try to find JS even if whitespace differs slightly
if old_js in content:
    content = content.replace(old_js, new_js)
else:
    # Manual surgical fix if exact match fails
    content = content.replace("'en-US'", "locale")
    if "const locale =" not in content and "updateDateTime()" in content:
        # Fallback: find updateDateTime and insert locale logic
        content = content.replace("const timeEl = document.getElementById('dashTime');", "const timeEl = document.getElementById('dashTime');\n    const docLang = (document.documentElement.lang || \"en\").toLowerCase();\n    const locale = docLang.startsWith(\"ar\") ? \"ar-SA\" : \"en-US\";")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied final fixes to dashboard.html")
