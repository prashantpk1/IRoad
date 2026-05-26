#!/usr/bin/env python3
"""Remove orphaned mobile dashboard/job/timeline translation entries from django.po files."""
from __future__ import annotations

import re
from pathlib import Path

KEEP_MSGIDS = frozenset(
    {
        'mobile.jobs.execute.execution_context_required',
        'mobile.jobs.execute.execution_context_driver_mismatch',
    }
)

REMOVE_EXACT = frozenset(
    {
        'mobile.auth.dashboard_denied',
        'mobile.auth.dashboard_method_not_allowed',
        'mobile.auth.jobs_denied',
        'mobile.auth.jobs_method_not_allowed',
        'mobile.validation.invalid_entity_type',
    }
)

ADD_ENTRIES = {
    'mobile.jobs.execute.execution_context_required': (
        'Secure execution context is required for this action.',
        'مطلوب سياق تنفيذ آمن لهذا الإجراء.',
    ),
    'mobile.jobs.execute.execution_context_driver_mismatch': (
        'Driver session does not match the execution context.',
        'جلسة السائق لا تطابق سياق التنفيذ.',
    ),
}


def should_remove(msgid: str) -> bool:
    if msgid in KEEP_MSGIDS:
        return False
    if msgid in REMOVE_EXACT:
        return True
    if msgid.startswith('mobile.dashboard.'):
        return True
    if msgid.startswith('mobile.jobs.'):
        return True
    return False


def parse_blocks(content: str) -> list[tuple[str, str]]:
    """Return list of (msgid, full_block_text)."""
    blocks: list[tuple[str, str]] = []
    parts = re.split(r'\n(?=msgid )', content)
    header = parts[0]
    if not header.endswith('\n'):
        header += '\n'
    blocks.append(('__header__', header))
    for part in parts[1:]:
        if not part.strip():
            continue
        m = re.match(r'msgid "(.*)"', part)
        if not m:
            blocks.append(('__raw__', part if part.endswith('\n') else part + '\n'))
            continue
        msgid = m.group(1)
        block = part if part.endswith('\n') else part + '\n'
        blocks.append((msgid, block))
    return blocks


def clean_po(path: Path, *, locale: str) -> tuple[int, int]:
    content = path.read_text(encoding='utf-8')
    blocks = parse_blocks(content)
    kept: list[str] = []
    removed = 0
    present_msgids: set[str] = set()
    for msgid, block in blocks:
        if msgid == '__header__':
            kept.append(block)
            continue
        if msgid == '__raw__':
            kept.append(block)
            continue
        present_msgids.add(msgid)
        if should_remove(msgid):
            removed += 1
            continue
        kept.append(block)

    added = 0
    insert_anchor = 'msgid "mobile.validation.failed"'
    insert_text = ''
    for msgid, (en, ar) in ADD_ENTRIES.items():
        if msgid in present_msgids:
            continue
        msgstr = ar if locale == 'ar' else en
        insert_text += f'\nmsgid "{msgid}"\nmsgstr "{msgstr}"\n'
        added += 1

    out = ''.join(kept)
    if insert_text:
        if insert_anchor in out:
            out = out.replace(insert_anchor, insert_text + insert_anchor, 1)
        else:
            out += insert_text

    path.write_text(out, encoding='utf-8')
    return removed, added


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for locale in ('en', 'ar'):
        po = root / 'locale' / locale / 'LC_MESSAGES' / 'django.po'
        removed, added = clean_po(po, locale=locale)
        print(f'{po}: removed={removed} added={added}')


if __name__ == '__main__':
    main()
