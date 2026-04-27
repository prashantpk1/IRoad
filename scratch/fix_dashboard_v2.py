
import os

file_path = r"c:\Users\soham\Downloads\codes\iroad_worllog\iroad\templates\dashboard\dashboard.html"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the Date/Time JS to be very robust
new_js_logic = """
function updateDateTime() {
    const now = new Date();
    const dateEl = document.getElementById('dashDate');
    const timeEl = document.getElementById('dashTime');
    
    // Detect RTL/Arabic from body or html
    const isArabic = document.documentElement.lang.startsWith('ar') || document.body.dir === 'rtl';
    const locale = isArabic ? 'ar-SA' : 'en-US';
    
    if (dateEl) {
        try {
            dateEl.textContent = now.toLocaleDateString(locale, { 
                weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' 
            });
        } catch(e) {
            dateEl.textContent = now.toDateString();
        }
    }
    if (timeEl) {
        try {
            timeEl.textContent = now.toLocaleTimeString(locale, { 
                hour: '2-digit', minute: '2-digit', second: '2-digit' 
            });
        } catch(e) {
            timeEl.textContent = now.toTimeString().split(' ')[0];
        }
    }
}
"""

import re
content = re.sub(r'function updateDateTime\(\) \{.*?\}' , new_js_logic, content, flags=re.DOTALL)

# Ensure "MRR — This Month" and others are wrapped (Just in case they weren't)
# I'll do a few common strings
strings_to_wrap = [
    "MRR — This Month",
    "Awaiting Payment",
    "Needs Approval",
    "Support Inbox",
    "Over 48 Hours",
    "Live Sessions",
    "FAILED",
    "REJECTED",
    "ACTIVE",
    "LIVE DATA",
    "Total Active Staff",
    "Suspended Accounts",
    "Pending Activation",
    "2FA Adoption Rate"
]

for s in strings_to_wrap:
    # Avoid double wrapping
    if f'{{% translate "{s}" %}}' not in content:
        content = content.replace(f'>{s}<', f'>{{% translate "{s}" %}} <')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied final robust fixes to dashboard.html")
