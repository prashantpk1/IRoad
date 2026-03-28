import os
import re

def apply_standard(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. Ensure {% load i18n %} is present after extends
    if '{% load i18n %}' not in content:
        extends_match = re.match(r'({%\s*extends\s+[^%]+\s*%})', content)
        if extends_match:
            content = content[:extends_match.end()] + '\n{% load i18n %}' + content[extends_match.end():]
    
    # 2. Extract title if possible
    title_match = re.search(r'{%\s*block\s+(?:page_)?title\s*%}(.*?){%\s*endblock\s*%}', content)
    title = title_match.group(1).strip() if title_match else "Page Title"
    
    # 3. Update breadcrumbs and blocks
    content = re.sub(r'<div class="breadcrumb-container">[\s\S]*?</div>', '', content)
    content = re.sub(r'<nav class="page-breadcrumb">[\s\S]*?</nav>', '', content)
    content = re.sub(r'<div class="list-page-header">[\s\S]*?</div>\s*</div>\s*</div>', '', content) # Clean legacy
    
    # Ensure breadcrumb_items block
    if '{% block breadcrumb_items %}' not in content:
        content_block_match = re.search(r'{%\s*block\s+content\s*%}', content)
        if content_block_match:
            breadcrumb_html = f'\n{{% block breadcrumb_items %}}\n<li class="breadcrumb-item active" aria-current="page">{{% translate "{title}" %}}</li>\n{{% endblock %}}\n\n'
            content = content[:content_block_match.start()] + breadcrumb_html + content[content_block_match.start():]

    # 4. Standardize Page Header
    header_pattern = re.compile(r'<(div|header) class="(?:list-page-header|page-header)">[\s\S]*?</\1>', re.IGNORECASE)
    
    # Try to find actions before we delete the old header
    actions = ""
    actions_match = re.search(r'<div class="eal-header-actions">([\s\S]*?)</div>', content)
    if actions_match:
        actions = actions_match.group(1).strip()
    
    # Clean up any leftover list-page-header artifacts
    content = re.sub(r'<div class="list-page-header">[\s\S]*?<div class="eal-header-actions">[\s\S]*?</div>\s*</div>\s*</div>', '', content)

    standard_header = f'''<div class="page-header">
  <div class="page-header-row">
    <div class="page-header-left">
      <h1 class="page-title">{{% translate "{title}" %}}</h1>
      <p class="page-subtitle">{{% translate "Manage your records here" %}}</p>
    </div>
    <div class="page-header-right">
      <div class="eal-header-actions">
        {actions}
      </div>
    </div>
  </div>
</div>'''
    
    if '{% block content %}' in content:
        # Remove any existing headers inside content
        content = header_pattern.sub('', content)
        # Clean up double headers or artifacts
        content = re.sub(r'<div class="page-header">[\s\S]*?</div>\s*</div>', '', content, count=1) 
        # Insert fresh standard header
        content = content.replace('{% block content %}', '{% block content %}\n' + standard_header + '\n')

    # 5. List Specifics & Pagination
    if '_list.html' in filepath:
        # Detect page_obj name
        page_obj_name = "page_obj"
        for_match = re.search(r'{%\s*for\s+\w+\s+in\s+([\w\.]+)\s*%}', content)
        if for_match:
            page_obj_name = for_match.group(1).split('.')[0]
        
        # Replace custom pagination blocks
        content = re.sub(r'<div class="eal-pagination mt-3">[\s\S]*?</div>\s*</div>\s*{% endif %}', '', content)
        content = re.sub(r'<div class="table-pagination-wrapper">[\s\S]*?</div>\s*</div>', '', content)
        
        # Append standardized pagination include before endblock content
        if "{% include 'partials/pagination.html'" not in content:
            content = content.replace('{% endblock %}', f"{{% include 'partials/pagination.html' with page_obj={page_obj_name} %}}\n{{% endblock %}}")

        # Force eal-table-card structure
        if '<div class="eal-table-card">' not in content:
            content = re.sub(r'(<table[\s\S]*?</table>)', r'<div class="eal-table-card">\n  <div class="eal-table-wrap">\n\1\n  </div>\n</div>', content)
        
        content = re.sub(r'<table\s+(?!class="eal-table")', '<table class="eal-table" ', content)
        
        # Update empty states
        content = re.sub(r'<tr>\s*<td colspan="\d+"\s+class="text-center[^"]*">([\s\S]*?)</td>\s*</tr>', 
                        r'<tr class="eal-table-empty">\n  <td colspan="20">\n    <div class="eal-empty-icon"><i class="bi bi-inbox"></i></div>\n    <div class="eal-empty-title">{% translate "No Data Found" %}</div>\n    <div class="eal-empty-text">\1</div>\n  </td>\n</tr>', content)

    # 6. Form Specifics
    if '_form.html' in filepath:
        # Ensure form-card
        if 'class="form-card"' not in content:
            content = re.sub(r'(<form[\s\S]*?</form>)', r'<div class="form-card">\n  <div class="form-card-body">\n\1\n  </div>\n</div>', content)
        
        # Footer standardize
        content = re.sub(r'<(div|footer) class="(?:form-footer-bar|form-footer-card)[^"]*">([\s\S]*?)</\1>',
                        r'<div class="form-actions-bar">\n  <div class="eal-header-actions">\n\2\n  </div>\n</div>', content)

    # 7. Button Standardize
    content = content.replace('btn-solid-indigo', 'eal-btn eal-btn-primary')
    content = content.replace('btn btn-primary', 'eal-btn eal-btn-primary')
    content = content.replace('btn btn-outline-secondary', 'eal-btn eal-btn-outline')
    content = content.replace('class="eal-row-btn"', 'class="eal-row-btn"') # No change but safe

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Standardized: {filepath}")

if __name__ == "__main__":
    templates_dir = r"c:\Users\soham\Downloads\codes\iroad_main_new\iroad\templates"
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('_list.html') or file.endswith('_form.html'):
                apply_standard(os.path.join(root, file))
