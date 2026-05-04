"""Remove ?tid= / &tid= / hidden tid from tenant HTML templates."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "iroad_tenants" / "templates"

patterns = [
    # request.GET.tid query suffix
    re.compile(r"\{%\s*if\s+request\.GET\.tid\s*%\}\?tid=\{\{\s*request\.GET\.tid\s*\|urlencode\s*\}\}\{%\s*endif\s*%\}"),
    re.compile(r"\{%\s*if\s+request\.GET\.tid\s*%\}\?tid=\{\{\s*request\.GET\.tid\s*\}\}\{%\s*endif\s*%\}"),
    re.compile(r"\{%\s*if\s+request\.GET\.tid\s*%\}&tid=\{\{\s*request\.GET\.tid\s*\|urlencode\s*\}\}\{%\s*endif\s*%\}"),
    re.compile(r"\{%\s*if\s+request\.GET\.tid\s*%\}&tid=\{\{\s*request\.GET\.tid\s*\}\}\{%\s*endif\s*%\}"),
    re.compile(r"\{%\s*if\s+portal_tid\s*%\}\?tid=\{\{\s*portal_tid\s*\|urlencode\s*\}\}\{%\s*endif\s*%\}"),
    re.compile(r"\{%\s*if\s+portal_tid\s*%\}\?tid=\{\{\s*portal_tid\s*\}\}\{%\s*endif\s*%\}"),
    # hidden form tid (single-line)
    re.compile(r"\s*\{%\s*if\s+portal_tid\s*%\}<input[^>]+name=\"tid\"[^>]*/>\{%\s*endif\s*%\}\s*\n"),
    re.compile(r"\{%\s*if\s+portal_tid\s*%\}<input[^>]+name='tid'[^>]*/>\{%\s*endif\s*%\}"),
    re.compile(r"\{%\s*if\s+request\.GET\.tid\s*%\}<input[^>]+name=\"tid\"[^>]*/>\{%\s*endif\s*%\}"),
    re.compile(
        r"\{%\s*if\s+request\.GET\.tid\s*%\}<input[^>]+name=\"tid\"[^>]*/>\{%\s*elif\s+request\.POST\.tid\s*%\}"
        r"<input[^>]+name=\"tid\"[^>]*/>\{%\s*endif\s*%\}"
    ),
    # multiline hidden tid
    re.compile(
        r"\{%\s*if\s+request\.GET\.tid\s*%\}\s*\n\s*<input[^>]+name=\"tid\"[^>]*/>\s*\n\s*\{%\s*endif\s*%\}",
        re.MULTILINE,
    ),
]

for path in ROOT.rglob("*.html"):
    text = path.read_text(encoding="utf-8")
    orig = text
    for p in patterns:
        text = p.sub("", text)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        print("updated", path.relative_to(ROOT.parent.parent))

print("done")
