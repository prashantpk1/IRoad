"""Remove commented-out page subtitles and designer marker comments from tenant templates."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'iroad_tenants' / 'templates'

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r'<!--\s*<p class="page-subtitle">[\s\S]*?-->\s*\n?', re.MULTILINE),
        '',
    ),
    (re.compile(r'^\s*<!-- Top Header -->\s*\n', re.MULTILINE), ''),
    (
        re.compile(r'^\s*<!-- ========== END TABLE UI DESIGN ========== -->\s*\n', re.MULTILINE),
        '',
    ),
    (
        re.compile(r'^\s*<!-- ========== END NEW TABLE UI DESIGN ========== -->\s*\n', re.MULTILINE),
        '',
    ),
    (
        re.compile(r'<!--\s*<p class="sub-page-subtitle">[\s\S]*?-->\s*\n?', re.MULTILINE),
        '',
    ),
    (
        re.compile(r'^\s*<!-- Section .*designerDesign.* -->\s*\n', re.MULTILINE | re.IGNORECASE),
        '',
    ),
    (
        re.compile(r'^\s*\{# Structure from designer[^\n]*#\}\s*\n', re.MULTILINE | re.IGNORECASE),
        '',
    ),
]


def clean_text(text: str) -> str:
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    return re.sub(r'\n{4,}', '\n\n\n', text)


def main() -> None:
    changed: list[str] = []
    for path in ROOT.rglob('*.html'):
        original = path.read_text(encoding='utf-8')
        updated = clean_text(original)
        if updated != original:
            path.write_text(updated, encoding='utf-8', newline='\n')
            changed.append(str(path.relative_to(ROOT)))
    print(f'Updated {len(changed)} files')
    for rel in sorted(changed):
        print(f'  {rel}')


if __name__ == '__main__':
    main()
