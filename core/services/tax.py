"""Kalkulyatorlar: JShOD qaytarish, keshbek taqqoslash, frilanser 1%."""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.utils.translation import gettext_lazy as _l

from core.models import PaymentProvider


def _d(x) -> Decimal:
    return Decimal(str(x))


def _round(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def refund_for(amount) -> Decimal:
    return _round(_d(amount) * _d(settings.JSHOD_RATE))


def compare_providers(amount) -> list[dict]:
    """Har bir to'lov tizimi uchun: komissiya, keshbek, sof xarajat va umumiy foyda."""
    amount = _d(amount)
    refund = refund_for(amount)
    rows = []
    for p in PaymentProvider.objects.filter(is_active=True):
        commission = _round(amount * p.commission_percent / 100 + p.commission_fixed)
        cashback = _round(amount * p.cashback_percent / 100)
        if p.cashback_cap is not None:
            cashback = min(cashback, p.cashback_cap)
        rows.append(
            {
                "provider": p,
                "commission": commission,
                "cashback": cashback,
                "net_cost": amount + commission - cashback,
                "total_benefit": refund + cashback - commission,
            }
        )
    rows.sort(key=lambda r: r["net_cost"])
    if rows:
        rows[0]["best"] = True
    return rows


def freelancer_savings(monthly_income) -> dict:
    monthly = _d(monthly_income)
    annual = monthly * 12
    general = _round(annual * _d(settings.JSHOD_RATE))
    reduced = _round(annual * _d(settings.SELF_EMPLOYED_RATE))
    return {
        "monthly": monthly,
        "annual": annual,
        "tax_general": general,
        "tax_reduced": reduced,
        "savings": general - reduced,
        "monthly_savings": _round((general - reduced) / 12),
        "eligible": annual <= settings.SELF_EMPLOYED_LIMIT,
        "limit": settings.SELF_EMPLOYED_LIMIT,
    }


FREELANCE_FIELDS = [
    ("it", _l("IT-mutaxassis / dasturchi")),
    ("design", _l("Dizayner / kontent")),
    ("tutor", _l("Repetitor / o'qituvchi")),
    ("taxi", _l("Taksi haydovchisi")),
    ("courier", _l("Kuryer / yetkazib berish")),
    ("crafts", _l("Hunarmand / usta")),
    ("other", _l("Boshqa xizmatlar")),
]
