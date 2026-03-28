import os
import re

def process_list(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove old breadcrumb block entirely so it doesn't conflict
    content = re.sub(r'{%\s*block breadcrumb_items\s*%}[\s\S]*?{%\s*endblock\s*%}', '', content)

    # 2. Refactor list headers
    header_pattern = re.compile(
        r'<div class="page-header">[\s\S]*?<div class="page-header-left">[\s\S]*?<h1 class="page-title">(.*?)</h1>([\s\S]*?)</div>\s*<div class="page-header-right">([\s\S]*?)</div>\s*</div>\s*</div>'
    )
    
    def list_header_repl(match):
        title = match.group(1).strip()
        subtitle_area = match.group(2).strip()
        right_actions = match.group(3).strip()
        
        # Wrapping in utility classes to avoid inline styles
        return f'''<div class="breadcrumb-container">
  <a href="#">System</a> 
  <span class="separator">/</span> 
  <span class="current">{{% translate "Manage" %}}</span>
</div>
<div class="list-page-header">
  <div class="list-page-title-area">
    <h1 class="page-title-main">{title}</h1>
    {subtitle_area}
  </div>
  <div class="list-page-actions">
    {right_actions}
  </div>
</div>'''
    
    content = header_pattern.sub(list_header_repl, content)

    # Convert commonly hardcoded list inline layouts to classes
    content = content.replace('style="margin-bottom: 20px;"', 'class="list-filter-wrapper"')
    content = content.replace('style="padding: 16px 20px;"', '')
    content = content.replace('style="opacity: 0.7;"', 'class="row-inactive"')
    content = content.replace('style="display: flex; align-items: center; gap: 0.75rem;"', 'class="table-cell-flex"')
    
    # Save button standardize on lists
    content = content.replace('class="eal-btn eal-btn-primary"', 'class="btn-solid-indigo"')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

folder = r"c:\Users\soham\Downloads\codes\iroad_main_new\iroad\designerDesign\app"
print("Processing Lists...")
for fname in os.listdir(folder):
    if fname.endswith('_list.html'):
        print(f" - {fname}")
        process_list(os.path.join(folder, fname))
print("List Processing Complete.")
