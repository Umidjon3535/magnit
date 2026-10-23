"""Chat-yordamchi: Claude orqali javob, kalit bo'lmasa — oflayn qoidalarga asoslangan javob."""

import re
from decimal import Decimal

from django.conf import settings
from django.utils.translation import get_language
from django.utils.translation import gettext as _

from . import ai
from .tax import freelancer_savings, refund_for

MAX_HISTORY = 20
LANGUAGE_NAMES = {"uz": "o'zbek (lotin)", "ru": "rus", "en": "ingliz"}


def _fmt(x: Decimal) -> str:
    return f"{int(x):,}".replace(",", " ")


def user_context(user) -> str:
    # Model foydalanuvchi tanlagan interfeys tilida javob berishi uchun
    lang = LANGUAGE_NAMES.get((get_language() or "uz")[:2], LANGUAGE_NAMES["uz"])
    lang_line = f"Interfeys tili: {lang}. Agar foydalanuvchi boshqa tilda yozmasa, shu tilda javob bering."
    if not user.is_authenticated:
        return f"Foydalanuvchi tizimga kirmagan (mehmon). {lang_line}"
    receipts = user.receipts.all()
    total = sum((r.amount or 0 for r in receipts), Decimal("0"))
    refund = sum((r.refund for r in receipts), Decimal("0"))
    return (
        f"Ism: {user.first_name or user.username}. Yuklangan cheklar: {receipts.count()} ta, "
        f"jami {_fmt(total)} so'm, qaytariladigan soliq {_fmt(refund)} so'm. "
        f"Avto-Audit hisobotlari: {user.statements.count()} ta. {lang_line}"
    )


def reply(session, user, message: str) -> tuple[str, bool]:
    """(javob matni, AI ishlatildimi). Tarix sessiyada saqlanadi."""
    history = session.get("chat_history", [])
    history.append({"role": "user", "content": message})
    history = history[-MAX_HISTORY:]
    if history[0]["role"] != "user":
        history = history[1:]

    used_ai = False
    try:
        text = ai.chat(history, user_context(user))
        used_ai = bool(text)
    except ai.AIUnavailable:
        text = ""
    if not text:
        text = offline_reply(message)

    history.append({"role": "assistant", "content": text})
    session["chat_history"] = history[-MAX_HISTORY:]
    return text, used_ai


_NUM_RE = re.compile(r"(\d[\d\s.,]*)\s*(mln|million|млн|ming|тыс|k)?", re.IGNORECASE)

# Kalit so'zlar uch tilda: o'zbek, rus, ingliz
FREELANCE_WORDS = ("frilans", "freelan", "ytt", "o'zini o'zi", "taksi", "repetitor", "1%", "dasturchi",
                   "фриланс", "самозанят", "такси", "репетитор", "программист", "self-employed", "taxi", "tutor")
AUDIT_WORDS = ("pdf", "hisobot", "audit", "выписка", "отчет", "отчёт", "statement", "report")
CASHBACK_WORDS = ("keshbek", "cashback", "кешбэк", "кэшбэк", "komissiya", "комиссия", "commission",
                  "click", "payme", "uzum", "anor", "zoomrad")
RECEIPT_WORDS = ("chek", "kvitansiya", "skan", "rasm", "чек", "квитанц", "ocr", "skrinshot", "receipt", "scan", "фото")
REFUND_WORDS = ("kontrakt", "контракт", "contract", "ta'lim", "talim", "bog'cha", "bogcha", "tibbiy", "soliq", "qaytar",
                "12%", "налог", "возврат", "обучен", "детсад", "школ", "медиц", "tax", "refund", "tuition",
                "kindergarten", "school", "medical")
PRIVACY_WORDS = ("maxfiy", "xavfsiz", "pasport", "karta", "безопас", "паспорт", "privacy", "secure", "passport")


def _extract_number(message: str) -> Decimal | None:
    best = None
    for m in _NUM_RE.finditer(message):
        digits = re.sub(r"[^\d]", "", m.group(1))
        if not digits:
            continue
        value = Decimal(digits)
        unit = (m.group(2) or "").lower()
        if unit in ("mln", "million", "млн"):
            value *= 1_000_000
        elif unit in ("ming", "тыс", "k"):
            value *= 1_000
        if best is None or value > best:
            best = value
    return best if best and best >= 10_000 else None


def offline_reply(message: str) -> str:
    low = message.lower()
    number = _extract_number(message)

    if any(w in low for w in FREELANCE_WORDS):
        if number:
            s = freelancer_savings(number)
            note = "" if s["eligible"] else "\n\n" + _("⚠️ Yillik aylanma 1 mlrd so'mdan oshadi — 1% rejim qo'llanilmaydi.")
            return _(
                "🚀 Oylik daromad **%(monthly)s so'm** bo'lsa:\n"
                "- 12%% JShOD: **%(general)s so'm/yil**\n"
                "- 1%% (o'zini o'zi band): **%(reduced)s so'm/yil**\n\n"
                "Siz yiliga **%(savings)s so'm** tejaysiz!%(note)s\n\n"
                "Batafsil hisob uchun [Frilanser 1%%](/freelancer/) bo'limiga o'ting."
            ) % {
                "monthly": _fmt(s["monthly"]), "general": _fmt(s["tax_general"]), "reduced": _fmt(s["tax_reduced"]),
                "savings": _fmt(s["savings"]), "note": note,
            }
        return _(
            "🚀 2026-yilgi islohot bo'yicha yillik aylanmasi **1 mlrd so'mgacha** bo'lgan "
            "o'zini o'zi band qilganlar **1%** soliq to'laydi (12% o'rniga).\n\n"
            "Oylik daromadingiz va sohangizni yozing — tejamkorlikni hisoblab beraman. "
            "Yoki [Frilanser 1%](/freelancer/) kalkulyatoridan foydalaning."
        )

    if any(w in low for w in AUDIT_WORDS):
        return _(
            "🔍 **Avto-Audit** uchun Click, Payme, Uzum yoki Anorbank ilovasidan 1 yillik "
            "xarajatlar hisobotini PDF ko'rinishida yuklab oling va [Avto-Audit](/audit/) "
            "sahifasidagi **'Fayl yuklash'** maydoniga tashlang. Tizim universitet, bog'cha, maktab "
            "va tibbiyot to'lovlarini o'zi topib, qaytariladigan 12% ni hisoblaydi."
        )

    if any(w in low for w in CASHBACK_WORDS):
        return _(
            "💸 **Ikki baravar foyda** formulasi:\n\n"
            "Umumiy foyda = **12% soliq qaytarilishi** + **ilova keshbegi** − **komissiya**\n\n"
            "[Keshbek optimizatori](/cashback/) bo'limiga shartnoma summasini kiriting — "
            "Click, Payme, Anorbank, Uzum va Zoomrad bir jadvalda taqqoslanadi."
        )

    if any(w in low for w in RECEIPT_WORDS):
        return _(
            "📸 [Chek skanerlash](/scan/) sahifasida chek skrinshoti (PNG, JPG) yoki PDF kvitansiyani "
            "**'Fayl yuklash'** maydoniga tashlang.\n\n"
            "Tizim **To'lov summasi**, **Sana** va **STIR** raqamini avtomatik ajratib, kalkulyator "
            "formasiga joylashtiradi — siz faqat tekshirib **'Tasdiqlash'** tugmasini bosasiz.\n\n"
            "💡 Rasm aniq, yorug' va to'liq kadrda bo'lsin."
        )

    if number or any(w in low for w in REFUND_WORDS):
        if number:
            return _(
                "🎓 **%(amount)s so'm** to'lovdan **%(refund)s so'm** (12%% JShOD) qaytarib olishingiz mumkin!\n\n"
                "Buning uchun to'lov chekini [Chek skanerlash](/scan/) sahifasiga yuklang, so'ng "
                "[Shaxsiy kabinet](/dashboard/)da **'Ariza shakllantirish'** tugmasini bosing."
            ) % {"amount": _fmt(number), "refund": _fmt(refund_for(number))}
        return _(
            "🎓 Ta'lim (kontrakt), bog'cha, maktab va tibbiyot to'lovlaridan **12% JShOD** qaytariladi.\n\n"
            "1. [Chek skanerlash](/scan/) — chekni yuklang\n"
            "2. Ma'lumotlarni tasdiqlang\n"
            "3. [Shaxsiy kabinet](/dashboard/)da arizani shakllantiring\n\n"
            "To'lov summasini yozsangiz, qancha qaytishini hozir hisoblab beraman."
        )

    if any(w in low for w in PRIVACY_WORDS):
        return _(
            "🔒 Shaxsiy ma'lumotlaringiz (pasport, STIR, karta) Maxfiylik siyosatiga muvofiq "
            "himoyalangan holda saqlanadi. Biz hech qachon karta CVV kodi yoki SMS-kodni so'ramaymiz."
        )

    return _(
        "Salom! 👋 Men **Magnit** AI-yordamchisiman. Quyidagilarda yordam beraman:\n\n"
        "- 🎓 Kontrakt, bog'cha, tibbiyot to'lovlaridan **12% soliqni qaytarish**\n"
        "- 📸 Cheklarni **OCR** orqali skanerlash\n"
        "- 🔍 PDF-hisobotni **Avto-Audit** qilish\n"
        "- 💸 Eng foydali **keshbek** va kam komissiyali to'lov usuli\n"
        "- 🚀 Frilanserlar uchun **12% → 1%** soliq optimizatsiyasi\n\n"
        "Savolingizni yozing yoki summani kiriting (masalan: *kontrakt 12 mln*)."
    ) + ("" if settings.AI_ENABLED else "\n\n" + _("_Oflayn rejim: to'liq AI javoblar uchun administrator API kalitni sozlashi kerak._"))
