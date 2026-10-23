"""Ariza tekshiruvi: rad etilish xavfi, haqiqiy qaytadigan summa va hujjatlar ro'yxati.

Qoidalar amaliyotda eng ko'p uchraydigan rad etilish sabablariga asoslangan va ma'lumot uchun.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.utils.translation import gettext_lazy as _l

# (savol kaliti, savol matni, "yo'q" bo'lsa og'irligi, muammo, yechim)
QUESTIONS = [
    (
        "official_income",
        _l("Rasmiy ish joyingiz bor va maoshingizdan 12% JShOD ushlab qolinadimi?"),
        60,
        _l("Rasmiy daromad va ushlangan JShOD bo'lmasa, qaytariladigan soliqning o'zi yo'q."),
        _l("Ish beruvchidan daromad va ushlangan soliq haqida ma'lumotnoma oling yoki my.soliq.uz'dagi daromadlaringiz bo'limini tekshiring."),
    ),
    (
        "own_payment",
        _l("To'lov o'z nomingizdan (o'z kartangiz yoki hisobingizdan) qilinganmi?"),
        30,
        _l("Boshqa shaxs kartasidan to'langan bo'lsa, to'lov sizniki ekanini isbotlash qiyinlashadi."),
        _l("Keyingi to'lovlarni o'z kartangizdan qiling; bu to'lov uchun to'lovchi nomi ko'rsatilgan kvitansiyani oling."),
    ),
    (
        "contract",
        _l("Muassasa bilan tuzilgan shartnoma (kontrakt) nusxasi bormi?"),
        25,
        _l("Shartnomasiz to'lov maqsadini tasdiqlab bo'lmaydi."),
        _l("O'quv yoki tibbiyot muassasasining buxgalteriyasidan shartnoma nusxasini so'rang."),
    ),
    (
        "receipt",
        _l("Har bir to'lov uchun chek yoki kvitansiya bor va unda summa, sana va tashkilot STIR'i ko'rinadimi?"),
        25,
        _l("Chekda STIR yoki sana bo'lmasa, to'lov tashkilotga bog'lanmaydi."),
        _l("Ilova (Click, Payme va h.k.) tarixidan elektron chekni qayta yuklab oling yoki bankdan ko'chirma oling."),
    ),
    (
        "licensed",
        _l("Muassasa davlat litsenziyasi yoki akkreditatsiyasiga egami?"),
        20,
        _l("Litsenziyasiz o'quv markazlari va xususiy kurslar uchun to'lovlar odatda inobatga olinmaydi."),
        _l("Muassasa litsenziyasini rasmiy reyestrdan tekshiring yoki to'g'ridan-to'g'ri muassasadan so'rang."),
    ),
]

FAMILY_QUESTION = (
    "family_docs",
    _l("Qarindoshlikni tasdiqlovchi hujjat (tug'ilganlik guvohnomasi, nikoh guvohnomasi) bormi?"),
    25,
    _l("Farzand yoki oila a'zosi uchun to'lovda qarindoshlik isbotlanmasa, ariza qaytariladi."),
    _l("Hujjat nusxasini oldindan tayyorlang (elektron nusxasi my.gov.uz orqali olinishi mumkin)."),
)

# Savollarning qisqa sarlavhalari — sahifada katta harf bilan, to'liq savol esa ostida
SHORT_TITLES = {
    "official_income": _l("Rasmiy ish joyi"),
    "own_payment": _l("To'lov o'z nomingizdan"),
    "contract": _l("Shartnoma nusxasi"),
    "receipt": _l("Chek yoki kvitansiya"),
    "licensed": _l("Muassasa litsenziyasi"),
    "family_docs": _l("Qarindoshlik hujjati"),
}

BASE_DOCUMENTS = [
    _l("Pasport yoki ID-karta"),
    _l("Ish beruvchidan daromad va ushlangan JShOD haqida ma'lumotnoma"),
    _l("Muassasa bilan shartnoma (kontrakt) nusxasi"),
    _l("Har bir to'lov cheki yoki kvitansiyasi"),
    _l("Bank kartasi yoki hisob raqami rekvizitlari (pul qaytarilishi uchun)"),
]


@dataclass
class CheckResult:
    payment: Decimal
    expected_refund: Decimal
    tax_withheld: Decimal
    real_refund: Decimal
    capped: bool
    score: int
    level: str
    issues: list = field(default_factory=list)
    documents: list = field(default_factory=list)
    unanswered: int = 0


def questions_for(for_family: bool):
    return QUESTIONS + ([FAMILY_QUESTION] if for_family else [])


def run_check(*, monthly_salary, payment, for_family, answers, unknown_as_no=True):
    """answers: {savol_kaliti: True/False}.

    unknown_as_no=True — javob berilmagan savol "yo'q" deb hisoblanadi (yakuniy tekshiruv).
    unknown_as_no=False — jonli rejim: javobsiz savol jarimaga kirmaydi, faqat sanaladi.
    """
    rate = Decimal(str(settings.JSHOD_RATE))
    payment = Decimal(payment or 0)
    expected = (payment * rate).quantize(Decimal("1"))
    withheld = (Decimal(monthly_salary or 0) * 12 * rate).quantize(Decimal("1"))
    # Qaytarish yil davomida haqiqatda ushlangan JShOD'dan oshmaydi
    has_income = answers.get("official_income", not unknown_as_no)
    real = min(expected, withheld) if has_income else Decimal("0")

    penalty, issues, unanswered = 0, [], 0
    for key, _q, weight, problem, fix in questions_for(for_family):
        if key not in answers and not unknown_as_no:
            unanswered += 1
            continue
        if not answers.get(key):
            penalty += weight
            issues.append({"problem": problem, "fix": fix, "critical": weight >= 30})
    if has_income and expected > withheld:
        issues.append({
            "problem": _l("To'lovning 12% i yil davomida ushlangan soliqdan ko'p — farqi qaytarilmaydi."),
            "fix": _l("Qolgan qismni oila a'zosi (masalan, turmush o'rtog'i) nomidan rasmiylashtirish mumkinligini soliq inspeksiyasidan so'rang."),
            "critical": False,
        })

    score = max(0, 100 - penalty)
    level = "low" if score >= 80 else "medium" if score >= 50 else "high"
    documents = BASE_DOCUMENTS + ([_l("Qarindoshlikni tasdiqlovchi hujjat nusxasi")] if for_family else [])
    return CheckResult(payment, expected, withheld, real, real < expected, score, level, issues, documents, unanswered)
