import os
import re

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content

    # 1. Action Buttons cleanup
    a_pattern = re.compile(r'(<a[^>]*class="[^"]*eal-row-btn[^"]*"[^>]*>)\s*(<i class="[^"]*"></i>)\s*([^<]+)\s*(</a>)')
    def a_repl(m):
        return f'{m.group(1).replace("eal-row-btn", "eal-row-btn icon-only-btn")}\n{m.group(2)}\n{m.group(4)}'
    content = a_pattern.sub(a_repl, content)

    btn_pattern = re.compile(r'(<button[^>]*class="[^"]*eal-row-btn[^"]*"[^>]*>)\s*(<i class="[^"]*"></i>)\s*([^<]+)\s*(</button>)')
    def btn_repl(m):
        return f'{m.group(1).replace("eal-row-btn", "eal-row-btn icon-only-btn")}\n{m.group(2)}\n{m.group(4)}'
    content = btn_pattern.sub(btn_repl, content)

    # 2. Pagination redesign
    # Find all pagination blocks
    pag_blocks = re.finditer(r'<div class="eal-pagination"[\s\S]*?</div>\s*</div>\s*(?:{% else %}|{% endif %})', content)
    # Actually safer approach: find eal-pagination and its wrapper manually
    pag_pattern = re.compile(r'<div class="eal-pagination"[^>]*>[\s\S]*?{% if (\w+)\.has_previous %}[\s\S]*?</div>\s*</div>')
    
    def pag_repl(match):
        var = match.group(1)
        return f'''<div class="table-pagination-wrapper">
  <div class="pagination-info">
    Showing {{{{ {var}.start_index }}}} to {{{{ {var}.end_index }}}} of {{{{ {var}.paginator.count }}}} entries
  </div>
  <div class="pagination-controls">
    {{% if {var}.has_previous %}}
      <a href="?search={{{{ search_query|urlencode }}}}&page={{{{ {var}.previous_page_number }}}}" class="page-link-btn"><i class="bi bi-chevron-left"></i></a>
    {{% else %}}
      <span class="page-link-btn disabled"><i class="bi bi-chevron-left"></i></span>
    {{% endif %}}
    <span class="page-link-btn active">{{{{ {var}.number }}}}</span>
    {{% if {var}.has_next %}}
      <a href="?search={{{{ search_query|urlencode }}}}&page={{{{ {var}.next_page_number }}}}" class="page-link-btn"><i class="bi bi-chevron-right"></i></a>
    {{% else %}}
      <span class="page-link-btn disabled"><i class="bi bi-chevron-right"></i></span>
    {{% endif %}}
  </div>
</div>'''
    content = pag_pattern.sub(pag_repl, content)

    # Ensure page-header lists structure
    header_pattern = re.compile(r'<div class="page-header">[\s\S]*?<div class="page-header-left">[\s\S]*?<h1 class="page-title">(.*?)</h1>([\s\S]*?)</div>\s*<div class="page-header-right">([\s\S]*?)</div>\s*</div>\s*</div>')
    def list_header_repl(match):
        title = match.group(1).strip()
        subtitle = match.group(2).strip()
        actions = match.group(3).strip()
        return f'''<div class="breadcrumb-container">
  <a href="#">System</a> 
  <span class="separator">/</span> 
  <span class="current">{{% translate "Manage" %}}</span>
</div>
<div class="list-page-header">
  <div class="list-page-title-area">
    <h1 class="page-title-main">{title}</h1>
    {subtitle}
  </div>
  <div class="list-page-actions">
    {actions}
  </div>
</div>'''
    content = header_pattern.sub(list_header_repl, content)

    # Basic layout scrub
    content = content.replace('style="margin-top: 16px"', 'class="list-filter-wrapper"')
    content = content.replace('class="page-subtitle"', 'class="page-subtitle text-muted font-weight-normal"')
    content = content.replace('class="eal-btn eal-btn-primary"', 'class="btn-solid-indigo"')
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated: {filepath}")

root_dir = r"c:\Users\soham\Downloads\codes\iroad_main_new\iroad\templates"
for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        if filename.endswith(".html"):
            process_file(os.path.join(dirpath, filename))
print("Done processing templates!")
