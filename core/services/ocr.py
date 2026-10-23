"""Chek/kvitansiyalarni OCR qilish.

Dvigatellar navbati: Claude (vision) -> EasyOCR -> Tesseract -> PDF matn qatlami.
EasyOCR va pytesseract ixtiyoriy — o'rnatilmagan bo'lsa o'tkazib yuboriladi.
"""

import io
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from . import ai
from .parsing import parse_iso_date, parse_receipt_text

log = logging.getLogger(__name__)


@dataclass
class OCRResult:
    ok: bool
    engine: str = ""
    raw_text: str = ""
    fields: dict = field(default_factory=dict)
    message: str = ""


def _easyocr(data: bytes) -> str:
    import easyocr  # noqa: PLC0415 — ixtiyoriy bog'liqlik

    reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return "\n".join(reader.readtext(data, detail=0, paragraph=False))


def _tesseract(data: bytes) -> str:
    import pytesseract  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    return pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang="rus+eng")


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _has_core_fields(fields: dict) -> bool:
    return bool(fields.get("amount"))


def scan_receipt(data: bytes, mime: str) -> OCRResult:
    # 1) Claude vision — eng aniq natija
    if mime in ai.IMAGE_TYPES or mime == "application/pdf":
        try:
            r = ai.extract_receipt(data, mime)
            fields = {
                "amount": Decimal(str(r["amount"])) if r.get("amount") else None,
                "paid_at": parse_iso_date(r.get("date")),
                "stir": (r.get("stir") or "")[:9],
                "organization": r.get("organization") or "",
                "category": r.get("category") if r.get("category") != "other" else "education",
            }
            if r.get("readable") and _has_core_fields(fields):
                return OCRResult(True, "Claude Vision", "", fields)
            if not r.get("readable"):
                return OCRResult(False, "Claude Vision", message="unreadable")
        except ai.AIUnavailable as e:
            log.info("AI OCR ishlatilmadi: %s", e)

    # 2) Lokal OCR dvigatellari / PDF matn qatlami
    engines = [("PDF matn", _pdf_text)] if mime == "application/pdf" else [("EasyOCR", _easyocr), ("Tesseract", _tesseract)]
    for name, fn in engines:
        try:
            text = fn(data)
        except ImportError:
            continue
        except Exception:  # noqa: BLE001 — buzilgan fayl, yo'q tesseract.exe va h.k.
            log.exception("%s xatosi", name)
            continue
        if text and text.strip():
            fields = parse_receipt_text(text)
            return OCRResult(_has_core_fields(fields), name, text, fields, "" if _has_core_fields(fields) else "unreadable")

    return OCRResult(False, "", message="no_engine")
