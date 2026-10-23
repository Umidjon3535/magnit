"""Matndan summa, sana, STIR va to'lov turini ajratib olish (OCR va PDF uchun umumiy)."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from core.models import Category

# Kalit so'zlar -> to'lov turi. Kichik harflarda, lotin va kirill yozuvida.
KEYWORDS: dict[str, list[str]] = {
    Category.EDUCATION: [
        "университет", "universitet", "university", "институт", "institut", "академия", "akademiya",
        "kontrakt", "контракт", "otm", "oliy ta'lim", "oliy talim", "talim", "ta'lim", "обучение",
    ],
    Category.KINDERGARTEN: [
        "bog'cha", "bogcha", "bog‘cha", "детский сад", "дет.сад", "детсад", "mtt", "maktabgacha",
        "kindergarten",
    ],
    Category.SCHOOL: ["maktab", "школа", "school", "litsey", "лицей"],
    Category.MEDICAL: [
        "медицинский", "медцентр", "medical", "klinika", "клиника", "shifoxona", "больница",
        "poliklinika", "поликлиника", "stomatolog", "стоматолог", "med center", "hospital",
    ],
}

_STIR_RE = re.compile(r"(?:STIR|ИНН|INN|СТИР)\s*[:№#]?\s*(\d{9})\b", re.IGNORECASE)
_BARE_STIR_RE = re.compile(r"(?<!\d)([2-6]\d{8})(?!\d)")
_DATE_RES = [
    (re.compile(r"\b(\d{2})[./-](\d{2})[./-](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[./-](\d{2})[./-](\d{2})\b"), "ymd"),
]
# 1 200 000,00 | 1,200,000.00 | 1200000 | 1.200.000
_AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d{1,2})?|\d{4,}(?:[.,]\d{1,2})?)(?![\d])")
_TOTAL_HINT_RE = re.compile(
    r"(jami|итого|всего|summa|сумма|to'lov|to‘lov|tolov|оплата|amount|total)", re.IGNORECASE
)


def parse_amount(token: str) -> Decimal | None:
    s = token.replace(" ", " ").strip()
    frac = "0"
    if not re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", s):
        # Oxirgi ajratkichdan keyin 1-2 raqam bo'lsa — bu tiyin qismi
        m = re.fullmatch(r"(.+)[.,](\d{1,2})", s)
        if m:
            s, frac = m.group(1), m.group(2)
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    try:
        return Decimal(f"{digits}.{frac}")
    except InvalidOperation:
        return None


def find_amounts(text: str) -> list[Decimal]:
    values = []
    for tok in _AMOUNT_RE.findall(text):
        val = parse_amount(tok)
        if val is not None and val >= 1000:
            values.append(val)
    return values


def find_total(text: str) -> Decimal | None:
    """Avval 'Jami/Итого/Summa' qatorlaridan, topilmasa — eng katta summani olamiz."""
    clean = _STIR_RE.sub(" ", text)
    clean = _strip_dates(clean)
    for line in clean.splitlines():
        if _TOTAL_HINT_RE.search(line):
            amounts = find_amounts(line)
            if amounts:
                return max(amounts)
    amounts = [a for a in find_amounts(clean) if not _looks_like_stir(a)]
    return max(amounts) if amounts else None


def _looks_like_stir(value: Decimal) -> bool:
    return value == value.to_integral() and 200_000_000 <= value < 700_000_000 and len(str(int(value))) == 9


def _strip_dates(text: str) -> str:
    for rx, _ in _DATE_RES:
        text = rx.sub(" ", text)
    return text


def find_date(text: str) -> date | None:
    for rx, order in _DATE_RES:
        for m in rx.finditer(text):
            a, b, c = (int(x) for x in m.groups())
            try:
                return date(c, b, a) if order == "dmy" else date(a, b, c)
            except ValueError:
                continue
    return None


def find_stir(text: str) -> str:
    m = _STIR_RE.search(text)
    if m:
        return m.group(1)
    m = _BARE_STIR_RE.search(text)
    return m.group(1) if m else ""


def detect_category(text: str) -> tuple[str, str]:
    """(to'lov turi, topilgan kalit so'z)."""
    low = text.lower()
    for category, words in KEYWORDS.items():
        for word in words:
            if word in low:
                return category, word
    return Category.OTHER, ""


def find_organization(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 4:
            continue
        cat, _ = detect_category(line)
        if cat != Category.OTHER or re.search(r'\b(MChJ|ООО|OOO|AJ|АО|DUK|ГУП|XK)\b', line):
            return line[:255]
    return ""


def parse_receipt_text(text: str) -> dict:
    category, _ = detect_category(text)
    return {
        "amount": find_total(text),
        "paid_at": find_date(text),
        "stir": find_stir(text),
        "organization": find_organization(text),
        "category": category if category != Category.OTHER else Category.EDUCATION,
    }


def parse_iso_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return find_date(str(value))
