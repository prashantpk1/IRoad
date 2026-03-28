import os
import re

def fix_translation_load(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if the file uses {% translate ... %}
    if '{% translate' in content:
        # Check if translation_tags is already loaded
        if '{% load translation_tags %}' not in content:
            # Case 1: Starts with {% extends ... %}
            extends_match = re.match(r'({%\s*extends\s+[^%]+\s*%})', content)
            if extends_match:
                # Add after extends
                new_content = content[:extends_match.end()] + '\n{% load translation_tags %}' + content[extends_match.end():]
            else:
                # Case 2: No extends, add at top
                new_content = '{% load translation_tags %}\n' + content
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Fixed translation load in: {filepath}")

root_dir = r"c:\Users\soham\Downloads\codes\iroad_main_new\iroad\templates"
for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        if filename.endswith(".html"):
            fix_translation_load(os.path.join(dirpath, filename))
print("Finished fixing translation load issues!")
