"""
In-memory HTML → PDF rendering helpers for tenant print endpoints.
"""
import os
import re
import shutil
import subprocess

from django.conf import settings

# wkhtmltopdf (Qt WebKit) does not resolve CSS custom properties — inline tokens
# so branded print layouts match Printing-Templates/ reference designs.
_PRINT_CSS_VARIABLES = {
    '--brand-blue': '#3B82F6',
    '--brand-blue-dark': '#1E40AF',
    '--brand-orange': '#F59E0B',
    '--blue-soft': '#EFF6FF',
    '--blue-line': '#DBEAFE',
    '--navy': '#1E40AF',
    '--navy-soft': '#2C5BC9',
    '--navy-line': '#DBEAFE',
    '--navy-bg': '#EFF6FF',
    '--ink': '#1F2937',
    '--ink-2': '#374151',
    '--muted': '#6B7280',
    '--muted-2': '#9CA3AF',
    '--line': '#E5E7EB',
    '--line-soft': '#F3F4F6',
    '--paper': '#FFFFFF',
    '--bg': '#F9FAFB',
    '--font-ar': "'IBM Plex Sans Arabic', 'Segoe UI', 'Tahoma', sans-serif",
    '--font-en': "'IBM Plex Sans', 'Segoe UI', sans-serif",
    '--font-mono': "'IBM Plex Mono', 'Consolas', ui-monospace, monospace",
}

_CSS_VAR_PATTERN = re.compile(r'var\(\s*(--[\w-]+)\s*\)')

# Qt WebKit (wkhtmltopdf 0.12.x) lacks CSS Grid and logical properties — inject
# layout/color fallbacks so PDF output matches Printing-Templates/ reference HTML.
_WKHTMLTOPDF_COMPAT_STYLE = """
<style id="wkhtmltopdf-compat">
html, body {
    font-family: 'IBM Plex Sans Arabic', 'Segoe UI', Tahoma, sans-serif;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}
.doc-header {
    display: table !important;
    width: 100% !important;
    table-layout: fixed !important;
}
.doc-header > .org-block,
.doc-header > .doc-title-block {
    display: table-cell !important;
    vertical-align: middle !important;
}
.doc-title-block {
    text-align: left !important;
    border-right: 1px solid #E5E7EB !important;
    padding-right: 24px !important;
}
.org-block { display: table-cell !important; vertical-align: middle !important; }
.org-logo {
    display: table-cell !important;
    vertical-align: middle !important;
}
.iroute-wordmark {
    font-family: 'Segoe UI', Arial, Helvetica, sans-serif !important;
    font-size: 28pt !important;
    font-weight: 900 !important;
    letter-spacing: -2px !important;
    color: #3B82F6 !important;
    line-height: 1 !important;
}
.section-head,
.section-titles {
    display: block !important;
}
.field-grid {
    display: block !important;
    font-size: 0 !important;
    letter-spacing: 0 !important;
}
.field-grid > .field {
    display: inline-block !important;
    vertical-align: top !important;
    font-size: 10pt !important;
    box-sizing: border-box !important;
    padding-right: 8px !important;
    margin-bottom: 8px !important;
}
.field-grid.grid-1 > .field { width: 100% !important; }
.field-grid.grid-2 > .field { width: 49% !important; }
.field-grid.grid-3 > .field { width: 32% !important; }
.field-grid.grid-4 > .field { width: 24% !important; }
.field-grid.grid-5 > .field { width: 19% !important; }
.cargo-totals {
    display: block !important;
    font-size: 0 !important;
}
.cargo-totals > .field {
    display: inline-block !important;
    width: 49% !important;
    font-size: 10pt !important;
    vertical-align: top !important;
}
thead th {
    background: #1E40AF !important;
    color: #FFFFFF !important;
    border-right: 1px solid rgba(255, 255, 255, 0.18) !important;
}
thead th:last-child { border-right: none !important; }
tbody td {
    border-right: 1px solid #F3F4F6 !important;
}
tbody td:last-child { border-right: none !important; }
.address-block-head {
    background: #1E40AF !important;
    color: #FFFFFF !important;
}
.doc-number-tag {
    background: #3B82F6 !important;
    color: #FFFFFF !important;
}
.org-logo--white {
    background: #3B82F6 !important;
}
</style>
"""


WKHTMLTOPDF_INSTALL_HINT = (
    'wkhtmltopdf is not installed or not on PATH. '
    'Windows: download from https://wkhtmltopdf.org/downloads.html '
    '(install to "C:\\Program Files\\wkhtmltopdf") or set WKHTMLTOPDF_CMD in .env '
    'to the full path of wkhtmltopdf.exe, then restart the Django server.'
)


def resolve_wkhtmltopdf_executable():
    """
    Resolve the wkhtmltopdf binary from settings, PATH, or common install locations.
    """
    configured = (getattr(settings, 'WKHTMLTOPDF_CMD', None) or '').strip()
    if configured:
        if os.path.isfile(configured):
            return configured
        raise RuntimeError(
            f'WKHTMLTOPDF_CMD is set to "{configured}" but that file does not exist. '
            f'{WKHTMLTOPDF_INSTALL_HINT}'
        )

    found = shutil.which('wkhtmltopdf')
    if found:
        return found

    if os.name == 'nt':
        for candidate in (
            r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
            r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
        ):
            if os.path.isfile(candidate):
                return candidate

    raise RuntimeError(WKHTMLTOPDF_INSTALL_HINT)


def _pdf_literal_string(value):
    return (
        value.replace('\\', '\\\\')
        .replace('(', '\\(')
        .replace(')', '\\)')
        .replace('\r', '\\r')
        .replace('\n', '\\n')
    )


def expand_print_css_variables(html_content: str) -> str:
    """Replace ``var(--token)`` with literal values for wkhtmltopdf rendering."""

    def _replace(match: re.Match) -> str:
        token = match.group(1)
        return _PRINT_CSS_VARIABLES.get(token, match.group(0))

    return _CSS_VAR_PATTERN.sub(_replace, html_content or '')


def inject_wkhtmltopdf_compat_styles(html_content: str) -> str:
    """Append layout/color overrides understood by wkhtmltopdf's legacy WebKit."""
    content = html_content or ''
    if 'id="wkhtmltopdf-compat"' in content:
        return content
    compat = expand_print_css_variables(_WKHTMLTOPDF_COMPAT_STYLE)
    if '</head>' in content:
        return content.replace('</head>', f'{compat}\n</head>', 1)
    return compat + content


def prepare_print_html_for_wkhtmltopdf(html_content: str, *, base_url: str = '') -> str:
    """
    Normalize designer HTML before PDF conversion.

    - Expands CSS variables (reference templates rely on them heavily).
    - Injects wkhtmltopdf layout fallbacks (grid/logical CSS are unsupported).
    - Strips external font requests (offline-safe fallbacks are in CSS).
    - Rewrites uploaded media URLs to local filesystem paths for wkhtmltopdf.
    """
    prepared = expand_print_css_variables(html_content or '')
    prepared = inject_wkhtmltopdf_compat_styles(prepared)
    prepared = rewrite_print_html_for_wkhtmltopdf(prepared)
    return prepared


def _local_file_uri(path: str) -> str:
    normalized = os.path.abspath(path).replace('\\', '/')
    if os.name == 'nt':
        return f'file:///{normalized}'
    return f'file://{normalized}'


def rewrite_print_html_for_wkhtmltopdf(html_content: str) -> str:
    """
    Make print HTML fully offline for wkhtmltopdf.

    External HTTP fetches (Google Fonts, SITE_URL static/media) cause
    ConnectionRefusedError when the dev server is unreachable from the subprocess.
    """
    content = html_content or ''

    content = re.sub(
        r'<link[^>]*fonts\.googleapis\.com[^>]*>\s*',
        '',
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r'<link[^>]*fonts\.gstatic\.com[^>]*>\s*',
        '',
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r'<link[^>]*rel=["\']preconnect["\'][^>]*>\s*',
        '',
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r'<base\s+[^>]*>\s*', '', content, flags=re.IGNORECASE)

    media_url = (getattr(settings, 'MEDIA_URL', '') or '/media/').rstrip('/')
    media_root = str(getattr(settings, 'MEDIA_ROOT', '') or '').replace('\\', '/')
    if media_url and media_root:
        if not media_root.endswith('/'):
            media_root += '/'

        site = (getattr(settings, 'SITE_URL', '') or '').strip().rstrip('/')
        prefixes = {media_url}
        if site:
            prefixes.add(f'{site}{media_url}')

        def _media_src_replacer(match: re.Match) -> str:
            raw_url = match.group(1)
            local_path = ''
            for prefix in prefixes:
                if raw_url.startswith(prefix + '/'):
                    rel = raw_url[len(prefix):].lstrip('/')
                    candidate = f'{media_root}{rel}'
                    if os.path.isfile(candidate):
                        local_path = candidate
                        break
            if not local_path:
                return match.group(0)
            return f'src="{_local_file_uri(local_path)}"'

        content = re.sub(r'src="([^"]+)"', _media_src_replacer, content)

    return content


def inject_pdf_auto_print_action(pdf_content):
    """
    Add a PDF OpenAction that asks compatible PDF viewers to open the print dialog.
    """
    root_matches = list(re.finditer(br'/Root\s+(\d+)\s+(\d+)\s+R', pdf_content))
    size_matches = list(re.finditer(br'/Size\s+(\d+)', pdf_content))
    startxref_match = re.search(
        br'startxref\s+(\d+)',
        pdf_content[pdf_content.rfind(b'startxref'):],
    )
    if not root_matches or not size_matches or not startxref_match:
        raise RuntimeError('Unable to locate PDF catalog for auto-print action')

    root_obj = int(root_matches[-1].group(1))
    root_gen = int(root_matches[-1].group(2))
    trailer_size = int(size_matches[-1].group(1))
    previous_xref = int(startxref_match.group(1))

    catalog_pattern = re.compile(
        rb'%d\s+%d\s+obj\s*(.*?)\s*endobj' % (root_obj, root_gen),
        re.DOTALL,
    )
    catalog_matches = list(catalog_pattern.finditer(pdf_content))
    if not catalog_matches:
        raise RuntimeError('Unable to locate PDF catalog object for auto-print action')

    catalog_body = catalog_matches[-1].group(1).strip()
    if not catalog_body.startswith(b'<<') or not catalog_body.endswith(b'>>'):
        raise RuntimeError('Unsupported PDF catalog format for auto-print action')

    print_js = 'this.print({bUI: true, bSilent: false, bShrinkToFit: true});'
    open_action = (
        b'\n/OpenAction << /S /JavaScript /JS ('
        + _pdf_literal_string(print_js).encode('ascii')
        + b') >>\n'
    )
    insert_at = catalog_body.rfind(b'>>')
    updated_catalog = catalog_body[:insert_at] + open_action + catalog_body[insert_at:]

    prefix = b'' if pdf_content.endswith(b'\n') else b'\n'
    new_object_offset = len(pdf_content) + len(prefix)
    new_object = (
        b'%d %d obj\n' % (root_obj, root_gen)
        + updated_catalog
        + b'\nendobj\n'
    )
    xref_offset = new_object_offset + len(new_object)
    incremental_update = (
        prefix
        + new_object
        + b'xref\n'
        + b'%d 1\n' % root_obj
        + b'%010d %05d n \n' % (new_object_offset, root_gen)
        + b'trailer\n'
        + b'<< /Size %d /Root %d %d R /Prev %d >>\n'
        % (trailer_size, root_obj, root_gen, previous_xref)
        + b'startxref\n'
        + str(xref_offset).encode('ascii')
        + b'\n%%EOF\n'
    )
    return pdf_content + incremental_update


def render_pdf_from_html_bytes(
    html_content,
    *,
    page_size='A4',
    margin_cm='0.2',
):
    """
    Render HTML to PDF bytes entirely in-memory (no disk persistence).
    """
    wkhtmltopdf_bin = resolve_wkhtmltopdf_executable()
    html_content = prepare_print_html_for_wkhtmltopdf(html_content)
    command = [
        wkhtmltopdf_bin,
        '--quiet',
        '--enable-local-file-access',
        '--encoding',
        'utf-8',
        '--print-media-type',
        '--disable-smart-shrinking',
        '--javascript-delay',
        '800',
        '--load-error-handling',
        'ignore',
        '--load-media-error-handling',
        'ignore',
        '--enable-external-links',
        '--enable-plugins',
        '--no-stop-slow-scripts',
        '--page-size',
        page_size,
        '--margin-top',
        f'{margin_cm}cm',
        '--margin-right',
        f'{margin_cm}cm',
        '--margin-bottom',
        f'{margin_cm}cm',
        '--margin-left',
        f'{margin_cm}cm',
        '--footer-right',
        'Page [page] of [toPage]',
        '--footer-font-size',
        '9',
        '--footer-spacing',
        '3',
        '-',
        '-',
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pdf_content, error = process.communicate(input=html_content.encode('utf-8'))
    if process.returncode != 0:
        err = (error or b'').decode('utf-8', errors='ignore').strip()
        raise RuntimeError(err or 'wkhtmltopdf failed')
    return inject_pdf_auto_print_action(pdf_content)
