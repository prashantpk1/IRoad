import os
import re

def process_form(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Page Header Block Replacement
    header_pattern = re.compile(r'<div class="page-header">[\s\S]*?<h1 class="page-title">(.*?)</h1>[\s\S]*?</div>\s*</div>\s*</div>')
    
    def header_repl(match):
        title = match.group(1).strip()
        return f'''<div class="breadcrumb-container">
  <a href="#">System</a> 
  <span class="separator">/</span> 
  <span class="current">{{% translate "Edit" %}}</span>
</div>
<h1 class="page-title-main">{title}</h1>'''
    content = header_pattern.sub(header_repl, content)

    # 2. Form Card Header Replacement
    card_pattern = re.compile(r'<div class="form-card"[^>]*>[\s\S]*?<div class="form-card-header">[\s\S]*?<h2 class="form-card-title">(.*?)</h2>[\s\S]*?<div class="form-card-body">')
    
    def card_repl(match):
        form_title = match.group(1).strip()
        return f'''<div class="form-card-master form-card-narrow">
    <h2 class="form-section-title">{form_title}</h2>
    <div class="form-card-body-inner">'''
    content = card_pattern.sub(card_repl, content)
    
    # 3. Field wraps
    content = content.replace('<div class="field">', '<div class="form-field-wrapper">')
    content = content.replace('<label class="form-label"', '<label class="form-field-label"')
    
    # Error fields
    err_pattern = re.compile(r'<div class="field-error" style="color: #ef4444; font-size: 12px; margin-top: 4px;">(.*?)</div>')
    content = err_pattern.sub(r'<div class="field-error form-error-msg">\1</div>', content)

    # 4. Form Actions bar
    footer_pattern = re.compile(r'<div class="form-actions-bar card shadow-sm"[^>]*>')
    content = footer_pattern.sub('<div class="form-footer-card">', content)

    btn_save_pattern = re.compile(r'<button type="submit" class="btn btn-primary"[^>]*>(.*?)</button>')
    content = btn_save_pattern.sub(r'<button type="submit" class="btn-solid-indigo">\1</button>', content)

    btn_cancel_pattern = re.compile(r'<button type="button" class="btn btn-secondary"[^>]*>(.*?)</button>')
    content = btn_cancel_pattern.sub(r'<button type="button" class="btn-outline-grey" onclick="history.back()">\1</button>', content)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


folder = r"c:\Users\soham\Downloads\codes\iroad_main_new\iroad\designerDesign\app"
print("Processing Forms...")
for fname in os.listdir(folder):
    if fname.endswith('form.html') and fname != 'city_form.html':
        print(f" - {fname}")
        process_form(os.path.join(folder, fname))
print("Form Processing Complete.")
