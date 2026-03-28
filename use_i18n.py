import os
import re

def fix_translation_load(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Replace {% load translation_tags %} with {% load i18n %}
    new_content = content.replace('{% load translation_tags %}', '{% load i18n %}')
    
    # 2. Also ensure if {% translate %} is used, {% load i18n %} is present
    if '{% translate' in new_content and '{% load i18n %}' not in new_content:
        # Add after extends
        extends_match = re.match(r'({%\s*extends\s+[^%]+\s*%})', new_content)
        if extends_match:
            new_content = new_content[:extends_match.end()] + '\n{% load i18n %}' + new_content[extends_match.end():]
        else:
            new_content = '{% load i18n %}\n' + new_content
            
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed i18n load in: {filepath}")

root_dir = r"c:\Users\soham\Downloads\codes\iroad_main_new\iroad\templates"
for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        if filename.endswith(".html"):
            fix_translation_load(os.path.join(dirpath, filename))
print("Finished switching to i18n!")
