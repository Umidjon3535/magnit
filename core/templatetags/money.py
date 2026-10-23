import re

from django import template

register = template.Library()


@register.filter
def som(value):
    """1440000 -> '1 440 000' (bo'linmaydigan bo'shliq bilan — summa qatorga bo'linmaydi)."""
    try:
        return f"{round(float(value)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return value


_TITLE_NOISE = [
    re.compile(r"\b\d{2}[./-]\d{2}[./-]\d{2,4}\b"),                     # sana
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),                         # vaqt
    re.compile(r"\b(?:STIR|INN|ИНН|СТИР)\s*:?\s*\d{9}\b", re.IGNORECASE),  # STIR
    re.compile(r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{2})?|\d{4,}(?:[.,]\d{2})"),  # summa
]


@register.filter
def payment_title(text):
    """Hisobot qatoridan sana, vaqt, STIR va summani olib tashlaydi — faqat to'lov nomi qoladi.

    "03.02.2025 14:05 TDIU STIR 201122334 6 500 000,00" -> "TDIU"
    """
    if not text:
        return text
    cleaned = text
    for rx in _TITLE_NOISE:
        cleaned = rx.sub(" ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ·-—,;:")
    return cleaned or text
