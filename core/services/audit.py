"""Avto-Audit: PDF-hisobotdan soliq qaytarishga mos to'lovlarni topish."""

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.models import Category

from . import ai
from .ocr import _pdf_text
from .parsing import _STIR_RE, detect_category, find_amounts, find_date, find_stir, parse_iso_date

log = logging.getLogger(__name__)

SOURCES = ["Click", "Payme", "Uzum", "Anorbank", "Zoomrad", "Humo", "Uzcard"]


@dataclass
class Match:
    description: str
    amount: Decimal
    paid_at: date | None
    stir: str
    category: str
    keyword: str = ""


def detect_source(text: str) -> str:
    low = text.lower()
    for name in SOURCES:
        if name.lower() in low:
            return name
    return ""


_RECORD_START_RE = re.compile(r"^\s*(\d{2}[./-]\d{2}[./-]\d{4}|\d{4}[./-]\d{2}[./-]\d{2})\b")
_FOOTER_RE = re.compile(r"\b(jami|итого|всего|total)\b", re.IGNORECASE)


def _records(text: str) -> list[str]:
    """Hisobot matnini tranzaksiyalarga bo'lish.

    Ko'p PDF'larda ustunlar (sana, tavsif, STIR, summa) alohida qatorlarga tushadi, shuning uchun
    sana bilan boshlanadigan qatordan keyingi shunday qatorgacha bo'lgan hamma narsa bitta yozuv.
    Sanali qatorlar bo'lmasa — har bir qator alohida yozuv.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not any(_RECORD_START_RE.match(ln) for ln in lines):
        return lines
    records, current = [], []
    for ln in lines:
        if not _RECORD_START_RE.match(ln) and _FOOTER_RE.search(ln):
            # "Jami / Итого" — hisobot yakuni, tranzaksiyaga qo'shilmaydi
            if current:
                records.append(" ".join(current))
            current = []
            continue
        if _RECORD_START_RE.match(ln) and current:
            records.append(" ".join(current))
            current = []
        if current or _RECORD_START_RE.match(ln):
            current.append(ln)
    if current:
        records.append(" ".join(current))
    return records


def scan_text(text: str) -> list[Match]:
    """Kalit so'zlar bo'yicha tranzaksiyalarni qidirish."""
    matches: list[Match] = []
    for record in _records(text):
        category, keyword = detect_category(record)
        if category == Category.OTHER:
            continue
        stir = find_stir(record)
        clean = _STIR_RE.sub(" ", record)
        if stir:
            clean = clean.replace(stir, " ")
        amounts = find_amounts(_drop_dates(clean))
        if amounts:
            # Oxirgi summa — odatda "Summa" ustuni (oldingi raqamlar tavsif ichida bo'lishi mumkin)
            matches.append(Match(record[:500], amounts[-1], find_date(record), stir, category, keyword))
    return matches


def _drop_dates(text: str) -> str:
    return re.sub(r"\b\d{2}[./-]\d{2}[./-]\d{4}\b|\b\d{4}[./-]\d{2}[./-]\d{2}\b|\b\d{2}:\d{2}(:\d{2})?\b", " ", text)


def audit_pdf(data: bytes) -> tuple[str, str, list[Match]]:
    """(manba, dvigatel, topilgan to'lovlar)."""
    try:
        r = ai.extract_statement(data)
        matches = [
            Match(
                p["description"][:500],
                Decimal(str(p["amount"])),
                parse_iso_date(p.get("date")),
                (p.get("stir") or "")[:9],
                p.get("category") or Category.OTHER,
                "AI",
            )
            for p in r.get("payments", [])
            if p.get("amount")
        ]
        source = r.get("source") or ""
        return ("" if source.lower().startswith("noma") else source), "Claude", matches
    except ai.AIUnavailable as e:
        log.info("AI audit ishlatilmadi: %s", e)

    text = _pdf_text(data)
    return detect_source(text), "Kalit so'zlar", scan_text(text)


DEMO_STATEMENT = """\
Payme — Xarajatlar hisoboti 01.01.2025 – 31.12.2025
15.01.2025 10:22  Mobil aloqa Beeline                       50 000,00
03.02.2025 14:05  Toshkent davlat iqtisodiyot universiteti   STIR 201122334   6 500 000,00
11.03.2025 09:40  Korzinka supermarket                       412 300,00
20.04.2025 18:12  "Shifo-Med" Медицинский центр MChJ   STIR 305566778   1 700 000,00
02.05.2025 08:30  14-son davlat bog'cha (MTT)                 STIR 202233445   950 000,00
05.06.2025 08:31  14-son davlat bog'cha (MTT)                 STIR 202233445   950 000,00
12.07.2025 12:00  P2P o'tkazma                               300 000,00
01.09.2025 11:15  Toshkent davlat iqtisodiyot universiteti   STIR 201122334   1 900 000,00
"""
