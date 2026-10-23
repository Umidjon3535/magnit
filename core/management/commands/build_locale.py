"""Tarjimalarni yig'ish va kompilyatsiya qilish (GNU gettext o'rnatilmagan muhit uchun).

1. templates/ va core/ dan {% translate %}, {% blocktranslate trimmed %} va _()/gettext() matnlarini yig'adi;
2. locale/<til>/LC_MESSAGES/django.po ni yangilaydi (mavjud tarjimalar saqlanadi, yangilari bo'sh qo'shiladi);
3. .po → .mo kompilyatsiya qiladi.

Asosiy til — o'zbekcha: msgid o'zbekcha matnning o'zi, shuning uchun uz uchun tarjima fayli kerak emas.
"""
import ast
import re
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

TRANSLATE_RE = re.compile(r"""\{%\s*(?:translate|trans)\s+(?P<q>["'])(?P<s>.*?)(?P=q)(?:\s+[^%]*)?%\}""", re.S)
BLOCK_RE = re.compile(r"\{%\s*blocktranslate\b(?P<args>[^%]*)%\}(?P<body>.*?)\{%\s*endblocktranslate\s*%\}", re.S)
VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
GETTEXT_FUNCS = {"_", "gettext", "gettext_lazy", "_l"}


def block_msgid(args, body):
    """Django BlockTranslateNode bilan bir xil msgid: oddiy % → %%, {{ x }} → %(x)s, trimmed bo'lsa qatorlar birlashadi."""
    if "trimmed" in args.split():
        body = re.sub(r"\s*\n\s*", " ", body.strip())
    parts = VAR_RE.split(body)  # [matn, o'zgaruvchi, matn, ...]
    return "".join(f"%({p})s" if i % 2 else p.replace("%", "%%") for i, p in enumerate(parts))


def from_templates(root):
    for path in sorted(root.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for m in TRANSLATE_RE.finditer(text):
            # Django {% translate %} ham % ni %% ga aylantirib qidiradi (keyin qaytaradi)
            yield m.group("s").replace("%", "%%"), path
        for m in BLOCK_RE.finditer(text):
            yield block_msgid(m.group("args"), m.group("body")), path


def from_python(root):
    for path in sorted(root.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in GETTEXT_FUNCS
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                yield node.args[0].value, path


def po_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def po_unescape(s):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def read_po(path):
    entries, msgid, msgstr, field = {}, None, None, None
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = line.strip()
        if line.startswith("msgid "):
            if msgid is not None:
                entries[msgid] = msgstr
            msgid, msgstr, field = po_unescape(line[7:-1]), "", "id"
        elif line.startswith("msgstr "):
            msgstr, field = po_unescape(line[8:-1]), "str"
        elif line.startswith('"') and field:
            if field == "id":
                msgid += po_unescape(line[1:-1])
            else:
                msgstr += po_unescape(line[1:-1])
        elif not line and msgid is not None:
            entries[msgid] = msgstr
            msgid, field = None, None
    entries.pop("", None)
    return entries


def write_po(path, lang, msgids, existing):
    out = [
        f"# Magnit — {lang} tarjimasi. Yangilash: python manage.py build_locale",
        'msgid ""', 'msgstr ""',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        f'"Language: {lang}\\n"', "",
    ]
    for msgid, sources in msgids.items():
        out.append("#: " + " ".join(sorted(sources)))
        if not existing.get(msgid):
            out.append("# TODO: tarjima qilinmagan")
        out += [f'msgid "{po_escape(msgid)}"', f'msgstr "{po_escape(existing.get(msgid, ""))}"', ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")


def write_mo(path, catalog):
    """GNU .mo formati: sarlavha + kalitlar jadvali + qiymatlar jadvali."""
    catalog = {"": "Content-Type: text/plain; charset=UTF-8\n", **{k: v for k, v in catalog.items() if v}}
    keys = sorted(catalog)
    ids = b"".join(k.encode() + b"\0" for k in keys)
    strs = b"".join(catalog[k].encode() + b"\0" for k in keys)
    n = len(keys)
    key_start = 7 * 4 + 16 * n
    value_start = key_start + len(ids)
    offsets, ko, vo = [], 0, 0
    for k in keys:
        kb, vb = k.encode(), catalog[k].encode()
        offsets.append((len(kb), key_start + ko, len(vb), value_start + vo))
        ko += len(kb) + 1
        vo += len(vb) + 1
    data = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    data += b"".join(struct.pack("ii", ln, off) for ln, off, _, _ in offsets)
    data += b"".join(struct.pack("ii", ln, off) for _, _, ln, off in offsets)
    path.write_bytes(data + ids + strs)


class Command(BaseCommand):
    help = "Tarjima matnlarini yig'adi, .po fayllarni yangilaydi va .mo ga kompilyatsiya qiladi."

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        found = {}
        sources = list(from_templates(base / "templates")) + list(from_python(base / "core"))
        for msgid, path in sources:
            found.setdefault(msgid, set()).add(path.relative_to(base).as_posix())
        for lang, _name in settings.LANGUAGES:
            if lang == settings.LANGUAGE_CODE:
                continue
            po = base / "locale" / lang / "LC_MESSAGES" / "django.po"
            existing = read_po(po)
            write_po(po, lang, found, existing)
            catalog = {k: existing.get(k, "") for k in found}
            write_mo(po.with_suffix(".mo"), catalog)
            missing = sum(1 for v in catalog.values() if not v)
            self.stdout.write(f"{lang}: {len(found)} ta matn, tarjima qilinmagan: {missing}")
