"""One-off: remove URL tid / portal_tid propagation from iroad_tenants/views.py."""
import re
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "iroad_tenants" / "views.py"
text = path.read_text(encoding="utf-8")

text = re.sub(r"\n\s*'portal_tid':[^\n]+", "", text)

text = re.sub(
    r"\n\s*tid = \(request\.POST\.get\('tid'\) or request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"\s*if tid:\n"
    r"\s*q\['tid'\] = tid",
    "",
    text,
)

text = re.sub(
    r"def _redirect_client_contract_list\(request\):\n"
    r"    url = reverse\('iroad_tenants:tenant_client_contract_list'\)\n"
    r"    tid = \(request\.POST\.get\('tid'\) or request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"    if tid:\n"
    r"        url = f'\{url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"    return redirect\(url\)",
    "def _redirect_client_contract_list(request):\n"
    "    url = reverse('iroad_tenants:tenant_client_contract_list')\n"
    "    return redirect(url)",
    text,
)

text = re.sub(
    r"def _tenant_redirect\(request, route_name\):\n"
    r"    tid = str\(request\.GET\.get\('tid'\) or request\.POST\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"    base = reverse\(route_name\)\n"
    r"    if tid:\n"
    r"        return redirect\(f'\{base\}\?tid=\{tid\}'\)\n"
    r"    return redirect\(base\)",
    "def _tenant_redirect(request, route_name):\n"
    "    base = reverse(route_name)\n"
    "    return redirect(base)",
    text,
)

# GET tid + list_url + edit_url (contiguous if tid blocks)
text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    edit_url = f'\{edit_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.POST\.get\('tid'\) or request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.POST\.get\('tid'\) or request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    url = f'\{url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"(?P=i)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    edit_url = f'\{edit_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)[^\n]+\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    detail_u = f'\{detail_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = self\._tid_for_redirect\(request\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n    def _tid_for_redirect\(self, request\):\n"
    r"        return \(request\.GET\.get\('tid'\) or request\.POST\.get\('tid'\) or ''\)\.strip\(\)\n",
    "\n",
    text,
)

text = re.sub(
    r"\n    def _tid\(self, request\):\n"
    r"        return \(request\.GET\.get\('tid'\) or request\.POST\.get\('tid'\) or ''\)\.strip\(\)\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    edit_url = f'\{edit_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    edit_u = f'\{edit_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    detail_u = f'\{detail_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or request\.POST\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    list_url = f'\{list_url\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid_addr = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)[^\n]+\n"
    r"(?P=i)if tid_addr:\n"
    r"(?P=i)    edit_u = f'\{edit_u\}\?\{urlencode\(\{\"tid\": tid_addr\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid_cargo = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)[^\n]+\n"
    r"(?P=i)if tid_cargo:\n"
    r"(?P=i)    edit_u = f'\{edit_u\}\?\{urlencode\(\{\"tid\": tid_cargo\}\)\}'\n"
    r"(?P=i)if tid_cargo:\n"
    r"(?P=i)    detail_u = f'\{detail_u\}\?\{urlencode\(\{\"tid\": tid_cargo\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)[^\n]+\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    detail_u = f'\{detail_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    edit_u = f'\{edit_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

text = re.sub(
    r"\n(?P<i>\s*)tid = \(request\.GET\.get\('tid'\) or ''\)\.strip\(\)\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    detail_u = f'\{detail_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n"
    r"(?P=i)if tid:\n"
    r"(?P=i)    edit_u = f'\{edit_u\}\?\{urlencode\(\{\"tid\": tid\}\)\}'\n",
    "\n",
    text,
)

path.write_text(text, encoding="utf-8")
print("wrote", path)
