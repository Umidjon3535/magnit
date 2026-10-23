import json
import mimetypes
import secrets
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.utils import timezone, translation
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    ApplicationStatusForm,
    CheckupForm,
    FreelancerForm,
    PhoneLoginForm,
    PreferencesForm,
    ProfileForm,
    ReceiptConfirmForm,
    ReceiptUploadForm,
    RegisterForm,
    StatementUploadForm,
)
from .models import (
    ELIGIBLE_CATEGORIES,
    Category,
    PaymentProvider,
    PhoneVerification,
    Profile,
    Receipt,
    RefundApplication,
    Statement,
    StatementMatch,
    TelegramLink,
)
from .services import assistant, telegram
from .services.audit import DEMO_STATEMENT, audit_pdf, scan_text
from .services.checkup import FAMILY_QUESTION, QUESTIONS, SHORT_TITLES, run_check
from .services.ocr import scan_receipt
from .services.tax import FREELANCE_FIELDS, refund_for
from .templatetags.money import som

MONTHS = [_l("Yan"), _l("Fev"), _l("Mar"), _l("Apr"), _l("May"), _l("Iyun"), _l("Iyul"), _l("Avg"), _l("Sen"),
          _l("Okt"), _l("Noy"), _l("Dek")]


def _safe_next(request, value):
    return value if value and url_has_allowed_host_and_scheme(value, {request.get_host()}) else ""


def _next_step(pending, payments_count, app):
    """Bosh sahifadagi "Keyingi qadam": foydalanuvchi holatiga qarab bitta aniq harakat."""
    S = RefundApplication.Status
    if pending:
        return {"icon": "receipt", "kind": "warn", "url": reverse("dashboard") + "#receipts", "cta": _("Tasdiqlash"),
                "title": _("%(n)s ta chek tasdiqlashni kutmoqda") % {"n": pending},
                "text": _("Summa va STIR'ni tekshirib tasdiqlang — shundan keyin ular arizaga qo'shiladi.")}
    if not payments_count:
        return {"icon": "scan", "kind": "brand", "url": reverse("scan"), "cta": _("Yuklash"),
                "title": _("Birinchi chekingizni yuklang"),
                "text": _("Kontrakt, bog'cha yoki klinika cheki — 30 soniyada qancha qaytishini bilasiz.")}
    if not app:
        return {"icon": "file", "kind": "brand", "url": reverse("dashboard"), "cta": _("Shakllantirish"),
                "title": _("Arizani shakllantiring"),
                "text": _("To'lovlaringiz tayyor — reestrni bir bosishda yarating.")}
    if app.status == S.DRAFT:
        return {"icon": "arrow", "kind": "brand", "url": reverse("tracker"), "cta": _("Yuborish"),
                "title": _("Arizani my.soliq.uz orqali yuboring"),
                "text": _("Yuborgach, sanani belgilang — holatini biz kuzatib boramiz.")}
    if app.status == S.PAID:
        return {"icon": "check-circle", "kind": "good", "url": reverse("scan"), "cta": _("Yangi chek"),
                "title": _("Pul tushdi! 🎉"),
                "text": _("Yangi to'lovlaringizni qo'shib boring — keyingi yil uchun ham qaytaramiz.")}
    if app.status == S.REJECTED:
        return {"icon": "alert", "kind": "bad", "url": reverse("tracker"), "cta": _("Murojaat"),
                "title": _("Ariza rad etildi"),
                "text": _("Tayyor murojaat xati bilan sababini so'rang va qayta topshiring.")}
    days = app.days_waiting
    return {"icon": "chart", "kind": "brand", "url": reverse("tracker"), "cta": _("Kuzatish"),
            "title": app.get_status_display(),
            "text": _("Yuborilganiga %(n)s kun bo'ldi.") % {"n": days} if days is not None else _("Ariza holatini kuzatib boring.")}


def _home_summary(user):
    payments = _eligible_payments(user)
    years = sorted({p[0].year for p in payments if p[0]}, reverse=True)
    year = years[0] if years else timezone.now().year
    in_year = [p for p in payments if p[0] and p[0].year == year]
    total = sum((p[1] for p in in_year), Decimal("0"))
    pending = user.receipts.filter(status=Receipt.Status.PENDING).count()
    app = user.applications.first()
    return {
        "year": year, "total": total, "refund": refund_for(total), "count": len(in_year), "pending": pending,
        "app": app,
        "steps": [label for value, label in RefundApplication.Status.choices if value in RefundApplication.TRACK],
        "next": _next_step(pending, len(in_year), app),
        "initial": (user.first_name or user.username or "?")[:1].upper(),
    }


def home(request, reg_form=None, login_form=None, tab=None, login_error=""):
    """Bosh sahifa: o'ng tomonda ro'yxatdan o'tish va kirish. Xatolar ham shu sahifada ko'rsatiladi."""
    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next"))
    if request.user.is_authenticated:
        return render(request, "core/home.html", {"me": _home_summary(request.user)})
    return render(request, "core/home.html", {
        "reg_form": reg_form or RegisterForm(),
        "login_form": login_form or PhoneLoginForm(request),
        "tab": tab or ("login" if next_url else "register"),
        "login_error": login_error,
        "next": next_url,
    })


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method != "POST":
        return redirect("home")
    form = RegisterForm(request.POST)
    if not form.is_valid():
        return home(request, reg_form=form, tab="register")
    if not telegram.is_configured():
        form.add_error(None, "Ro'yxatdan o'tish vaqtincha ishlamayapti: Telegram-bot sozlanmagan.")
        return home(request, reg_form=form, tab="register")
    v = form.create_verification()
    request.session["verify_token"] = v.token
    return redirect("verify", token=v.token)


def login_password(request):
    """Telefon + parol bilan kirish. Xatolar bosh sahifadagi "Kirish" bo'limida ko'rsatiladi."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method != "POST":
        next_url = _safe_next(request, request.GET.get("next"))
        return redirect(f"{reverse('home')}?next={next_url}" if next_url else f"{reverse('home')}#login")
    form = PhoneLoginForm(request, data=request.POST)
    if not form.is_valid():
        return home(request, login_form=form, tab="login")
    login(request, form.get_user())
    return redirect(_safe_next(request, request.POST.get("next")) or "dashboard")


@require_POST
def login_code(request):
    """Telegram orqali kirish: bot havolasini beradi. Raqam saytda emas, botda kontakt orqali yuboriladi."""
    if not telegram.is_configured():
        return home(request, tab="login", login_error=_("Telegram orqali kirish vaqtincha ishlamayapti."))
    v = PhoneVerification.objects.create(token=secrets.token_urlsafe(24), purpose=PhoneVerification.Purpose.LOGIN)
    request.session["verify_token"] = v.token
    request.session["login_next"] = _safe_next(request, request.POST.get("next"))
    verify_url = reverse("verify", args=[v.token])
    # JS bilan: tugma botni yangi oynada ochadi, sahifa esa kod kiritishga o'tadi
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"bot_url": telegram.deep_link(v.token), "verify_url": verify_url})
    return redirect(verify_url)


def _verification_or_404(request, token):
    # Havola faqat jarayonni boshlagan brauzerda ishlaydi
    if request.session.get("verify_token") != token:
        raise Http404
    return get_object_or_404(telegram.pending(), token=token)


def verify(request, token):
    if request.user.is_authenticated:
        return redirect("dashboard")
    try:
        v = _verification_or_404(request, token)
    except Http404:
        messages.warning(request, _("Tasdiqlash muddati o'tgan. Qaytadan urinib ko'ring."))
        return redirect("home")

    is_login = v.purpose == PhoneVerification.Purpose.LOGIN
    error = ""
    if request.method == "POST":
        if v.attempts >= settings.VERIFY_MAX_ATTEMPTS:
            error = "Urinishlar soni tugadi. Botda raqamni qayta yuborib, yangi kod oling."
        elif telegram.code_is_valid(v, request.POST.get("code")):
            user = User.objects.filter(username=v.phone).first()
            if is_login and not user:
                # Raqam tasdiqlandi, lekin hisob yo'q — ism-familiya so'raymiz va hisob yaratamiz
                request.session["tg_signup"] = {"phone": v.phone, "chat_id": v.chat_id, "at": timezone.now().timestamp()}
                PhoneVerification.objects.filter(phone=v.phone).delete()
                request.session.pop("verify_token", None)
                return redirect("signup_complete")
            if not is_login and user:
                messages.error(request, _("Bu raqam allaqachon ro'yxatdan o'tgan. «Kirish» bo'limidan foydalaning."))
                return redirect(f"{reverse('home')}#login")
            if not is_login:
                user = User.objects.create(
                    username=v.phone, first_name=v.first_name, last_name=v.last_name, password=v.password_hash,
                )
            telegram.link_user(user, v.chat_id)
            PhoneVerification.objects.filter(phone=v.phone).delete()
            request.session.pop("verify_token", None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            if is_login:
                messages.success(request, _("Xush kelibsiz, %(name)s! 👋") % {"name": user.first_name} if user.first_name else _("Xush kelibsiz! 👋"))
                return redirect(request.session.pop("login_next", "") or "dashboard")
            messages.success(request, _("Xush kelibsiz, %(name)s! 🎉 Birinchi chekingizni yuklang.") % {"name": user.first_name})
            return redirect("scan")
        else:
            v.attempts += 1
            v.save(update_fields=["attempts"])
            left = settings.VERIFY_MAX_ATTEMPTS - v.attempts
            error = f"Kod noto'g'ri yoki eskirgan. Yana {left} ta urinish qoldi." if left else "Urinishlar soni tugadi. Botda raqamni qayta yuborib, yangi kod oling."
    return render(request, "registration/verify.html", {
        "v": v, "is_login": is_login, "link": telegram.deep_link(v.token), "bot": settings.TELEGRAM_BOT_USERNAME,
        "error": error, "ttl": settings.VERIFY_TTL_MINUTES,
    })


def signup_complete(request):
    """Telegram orqali tasdiqlangan yangi raqam: ism-familiya kiritilgach hisob yaratiladi."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    data = request.session.get("tg_signup")
    if not data or timezone.now().timestamp() - data["at"] > settings.VERIFY_TTL_MINUTES * 60:
        request.session.pop("tg_signup", None)
        messages.warning(request, _("Tasdiqlash muddati o'tgan. «Telegram orqali kirish»ni qaytadan bosing."))
        return redirect(f"{reverse('home')}#login")

    form = ProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if User.objects.filter(username=data["phone"]).exists():
            request.session.pop("tg_signup", None)
            messages.error(request, _("Bu raqam allaqachon ro'yxatdan o'tgan. «Telegram orqali kirish» orqali kiring."))
            return redirect(f"{reverse('home')}#login")
        user = User(username=data["phone"], first_name=form.cleaned_data["first_name"], last_name=form.cleaned_data["last_name"])
        user.set_unusable_password()  # kirish Telegram kodi orqali
        user.save()
        telegram.link_user(user, data["chat_id"])
        request.session.pop("tg_signup", None)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Xush kelibsiz, %(name)s! 🎉 Birinchi chekingizni yuklang.") % {"name": user.first_name})
        return redirect(request.session.pop("login_next", "") or "scan")
    return render(request, "registration/complete.html", {"form": form, "phone": data["phone"]})


def verify_status(request, token):
    """Sahifa botdagi jarayonni kuzatishi uchun: bot ochildimi, kod yuborildimi."""
    try:
        v = _verification_or_404(request, token)
    except Http404:
        return JsonResponse({"expired": True})
    return JsonResponse({"expired": False, "bot_opened": bool(v.chat_id), "code_sent": bool(v.code)})



# --- Til va sozlamalar --------------------------------------------------------

def _apply_language(response, lang):
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=365 * 24 * 3600, samesite="Lax")
    return response


@require_POST
def set_language(request):
    """Menyudagi til tanlagichi: cookie'ga, kirgan foydalanuvchida esa profilga ham saqlanadi."""
    lang = request.POST.get("language")
    if lang not in dict(settings.LANGUAGES):
        lang = settings.LANGUAGE_CODE
    if request.user.is_authenticated:
        Profile.objects.filter(user=request.user).update(language=lang)
    next_url = _safe_next(request, request.POST.get("next")) or reverse("home")
    return _apply_language(redirect(next_url), lang)


@login_required
@require_POST
def save_theme(request):
    """Menyudagi kunduzgi/tungi tugmasi kirgan foydalanuvchi tanlovini profilga yozadi."""
    theme = request.POST.get("theme")
    if theme in Profile.Theme.values:
        Profile.objects.filter(user=request.user).update(theme=theme)
    return JsonResponse({"ok": True})


@login_required
def account_settings(request):
    """Kabinet → Sozlamalar: shaxsiy ma'lumotlar, parol, til va mavzu."""
    user, profile = request.user, request.profile
    section = request.POST.get("section")
    profile_form = ProfileForm(request.POST if section == "profile" else None,
                               initial={"first_name": user.first_name, "last_name": user.last_name})
    PasswordForm = PasswordChangeForm if user.has_usable_password() else SetPasswordForm
    password_form = PasswordForm(user, request.POST if section == "password" else None)
    prefs_form = PreferencesForm(request.POST if section == "prefs" else None, instance=profile)

    if request.method == "POST":
        if section == "profile" and profile_form.is_valid():
            user.first_name = profile_form.cleaned_data["first_name"].strip()
            user.last_name = profile_form.cleaned_data["last_name"].strip()
            user.save(update_fields=["first_name", "last_name"])
            messages.success(request, _("Ma'lumotlaringiz saqlandi."))
            return redirect("settings")
        if section == "password" and password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, user)  # parol o'zgargach tizimdan chiqarib yubormaslik uchun
            messages.success(request, _("Parol saqlandi."))
            return redirect("settings")
        if section == "prefs" and prefs_form.is_valid():
            profile = prefs_form.save()
            translation.activate(profile.language)
            messages.success(request, _("Sozlamalar saqlandi."))
            return _apply_language(redirect("settings"), profile.language)

    return render(request, "core/settings.html", {
        "profile_form": profile_form, "password_form": password_form, "prefs_form": prefs_form,
        "has_password": user.has_usable_password(),
        "telegram_linked": TelegramLink.objects.filter(user=user).exists(),
        "section": section,
    })


# --- Shaxsiy kabinet ---------------------------------------------------------

def _eligible_payments(user):
    """Tasdiqlangan cheklar + Avto-Audit topgan to'lovlar: (sana, summa, tur)."""
    rows = [
        (r.paid_at, r.amount, r.category)
        for r in user.receipts.filter(status=Receipt.Status.CONFIRMED)
        if r.amount and r.category in ELIGIBLE_CATEGORIES
    ]
    rows += [
        (m.paid_at, m.amount, m.category)
        for m in StatementMatch.objects.filter(statement__user=user, excluded=False)
        if m.category in ELIGIBLE_CATEGORIES
    ]
    return rows


@login_required
def dashboard(request):
    user = request.user
    payments = _eligible_payments(user)
    years = sorted({p[0].year for p in payments if p[0]}, reverse=True)
    # "2 026" kabi formatlangan yoki noto'g'ri qiymat sahifani yiqitmasin — faqat raqamlar olinadi
    requested = "".join(ch for ch in request.GET.get("year", "") if ch.isdigit())
    year = int(requested) if len(requested) == 4 else (years[0] if years else timezone.now().year)

    in_year = [p for p in payments if p[0] and p[0].year == year]
    total = sum((p[1] for p in in_year), Decimal("0"))

    monthly = [0] * 12
    by_cat = defaultdict(Decimal)
    for paid_at, amount, cat in in_year:
        monthly[paid_at.month - 1] += float(amount)
        by_cat[cat] += amount
    labels = dict(Category.choices)
    categories = sorted(
        ({"label": labels[c], "value": float(v), "refund": float(refund_for(v))} for c, v in by_cat.items()),
        key=lambda x: -x["value"],
    )

    chart = {"months": MONTHS, "monthly": monthly, "categories": categories}
    context = {
        "year": year,
        "years": years or [year],
        "total": total,
        "refund": refund_for(total),
        "payments_count": len(in_year),
        "receipts": user.receipts.all()[:8],
        "pending_count": user.receipts.filter(status=Receipt.Status.PENDING).count(),
        "statements": user.statements.prefetch_related("matches")[:5],
        "applications": user.applications.all()[:5],
        "year_app": user.applications.filter(year=year).first(),
        "chart": chart,
        "has_chart": bool(in_year),
    }
    return render(request, "core/dashboard.html", context)


# --- Chek skanerlash (OCR) ----------------------------------------------------

@login_required
def scan(request):
    return render(request, "core/scan.html", {"form": ReceiptConfirmForm(), "categories": Category.choices})


@login_required
@require_POST
def receipt_upload(request):
    form = ReceiptUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"ok": False, "message": form.errors["file"][0]}, status=400)

    upload = form.cleaned_data["file"]
    data = upload.read()
    mime = upload.content_type or mimetypes.guess_type(upload.name)[0] or ""
    if mime == "image/jpg":
        mime = "image/jpeg"
    result = scan_receipt(data, mime)
    upload.seek(0)

    receipt = Receipt(user=request.user, file=upload, ocr_engine=result.engine, raw_text=result.raw_text[:20000])
    for key, value in result.fields.items():
        if value:
            setattr(receipt, key, value)
    if not result.ok:
        receipt.status = Receipt.Status.UNREADABLE
    receipt.save()

    payload = {
        "ok": result.ok,
        "receipt_id": receipt.pk,
        "confirm_url": reverse("receipt_confirm", args=[receipt.pk]),
        "engine": result.engine,
        "file_url": receipt.file.url,
        "fields": {
            "amount": str(int(receipt.amount)) if receipt.amount else "",
            "paid_at": receipt.paid_at.isoformat() if receipt.paid_at else "",
            "stir": receipt.stir,
            "organization": receipt.organization,
            "category": receipt.category,
        },
        "refund": int(receipt.refund),
    }
    if not result.ok:
        payload["message"] = (
            _("Kechirasiz, chekni to'liq o'qib bo'lmadi 😔 Iltimos, yorug'roq va aniqroq rasm yuklang "
              "yoki ma'lumotlarni quyidagi formaga qo'lda kiriting.")
            if result.message != "no_engine"
            else _("OCR dvigateli sozlanmagan. Ma'lumotlarni formaga qo'lda kiriting — chek fayli saqlandi.")
        )
    return JsonResponse(payload)


@login_required
@require_POST
def receipt_confirm(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk, user=request.user)
    form = ReceiptConfirmForm(request.POST, instance=receipt)
    if form.is_valid():
        receipt = form.save(commit=False)
        receipt.status = Receipt.Status.CONFIRMED
        receipt.save()
        messages.success(
            request,
            _("✅ Chek tasdiqlandi! %(amount)s so'm to'lovdan %(refund)s so'm qaytariladi.") % {
                "amount": f"{receipt.amount:,.0f}".replace(",", " "), "refund": f"{receipt.refund:,.0f}".replace(",", " "),
            },
        )
        return redirect("dashboard")
    for errors in form.errors.values():
        messages.error(request, errors[0])
    return redirect("scan")


@login_required
@require_POST
def receipt_delete(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk, user=request.user)
    receipt.file.delete(save=False)
    receipt.delete()
    messages.info(request, _("Chek o'chirildi."))
    return redirect("dashboard")


# --- Avto-Audit ---------------------------------------------------------------

@login_required
def audit(request):
    form = StatementUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            source, engine, found = audit_pdf(upload.read())
        except Exception:  # noqa: BLE001 — buzilgan yoki shifrlangan PDF
            messages.error(request, _("PDF faylni o'qib bo'lmadi. Ilovadan hisobotni qayta yuklab oling."))
            return redirect("audit")
        upload.seek(0)
        statement = Statement.objects.create(user=request.user, file=upload, source=source, engine=engine)
        _save_matches(statement, found)
        return redirect("audit_result", pk=statement.pk)
    return render(request, "core/audit.html", {"form": form, "statements": request.user.statements.all()[:6]})


@login_required
@require_POST
def audit_demo(request):
    statement = Statement.objects.create(user=request.user, source="Payme (namuna)", engine="Kalit so'zlar")
    _save_matches(statement, scan_text(DEMO_STATEMENT))
    return redirect("audit_result", pk=statement.pk)


def _save_matches(statement, found):
    StatementMatch.objects.bulk_create(
        StatementMatch(
            statement=statement,
            description=m.description,
            amount=m.amount,
            paid_at=m.paid_at,
            stir=m.stir,
            category=m.category,
            keyword=m.keyword,
        )
        for m in found
    )


def _audit_summary(statement):
    """Natija sahifasi va jonli yangilanish uchun: jami, qaytadigan summa va turlar bo'yicha taqsimot."""
    included = [m for m in statement.matches.all() if not m.excluded]
    labels = dict(Category.choices)
    by_cat = defaultdict(Decimal)
    for m in included:
        by_cat[m.category] += m.amount
    years = [m.paid_at.year for m in included if m.paid_at]
    return {
        "count": len(included),
        "total": statement.total,
        "refund": statement.refund,
        "categories": [{"label": str(labels.get(c, c)), "total": v, "refund": refund_for(v)}
                       for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        # Ariza eng ko'p to'lov qilingan yil uchun shakllantiriladi
        "year": max(set(years), key=years.count) if years else timezone.now().year,
    }


@login_required
def audit_result(request, pk):
    statement = get_object_or_404(Statement.objects.prefetch_related("matches"), pk=pk, user=request.user)
    return render(request, "core/audit_result.html", {
        "statement": statement, "matches": statement.matches.all(), "summary": _audit_summary(statement),
    })


@login_required
@require_POST
def audit_toggle(request, pk):
    """Topilgan to'lovni hisobga olish / chiqarib tashlash — natija darhol qayta hisoblanadi."""
    match = get_object_or_404(StatementMatch, pk=pk, statement__user=request.user)
    match.excluded = request.POST.get("include") != "1"
    match.save(update_fields=["excluded"])
    statement = Statement.objects.prefetch_related("matches").get(pk=match.statement_id)
    s = _audit_summary(statement)
    return JsonResponse({
        "excluded": match.excluded, "count": s["count"], "total": som(s["total"]), "refund": som(s["refund"]),
        "categories": [{"label": c["label"], "total": som(c["total"]), "refund": som(c["refund"])} for c in s["categories"]],
        "year": s["year"],
    })


# --- Ariza ---------------------------------------------------------------------

@login_required
@require_POST
def application_create(request):
    year = int(request.POST.get("year") or timezone.now().year)
    used_receipts = RefundApplication.objects.filter(user=request.user).values_list("receipts", flat=True)
    used_matches = RefundApplication.objects.filter(user=request.user).values_list("statement_matches", flat=True)

    receipts = [
        r
        for r in request.user.receipts.filter(status=Receipt.Status.CONFIRMED, paid_at__year=year).exclude(pk__in=used_receipts)
        if r.category in ELIGIBLE_CATEGORIES
    ]
    matches = [
        m
        for m in StatementMatch.objects.filter(statement__user=request.user, paid_at__year=year, excluded=False).exclude(pk__in=used_matches)
        if m.category in ELIGIBLE_CATEGORIES
    ]
    if not receipts and not matches:
        messages.warning(request, _("%(year)s-yil uchun arizaga kiritilmagan yangi to'lovlar topilmadi.") % {"year": year})
        return redirect("dashboard")

    total = sum((r.amount for r in receipts), Decimal("0")) + sum((m.amount for m in matches), Decimal("0"))
    app = RefundApplication.objects.create(
        user=request.user, year=year, total_amount=total, refund_amount=refund_for(total)
    )
    app.receipts.set(receipts)
    app.statement_matches.set(matches)
    messages.success(request, _("📝 Ariza shakllantirildi! Uni chop eting yoki my.soliq.uz orqali yuboring."))
    return redirect("application_detail", pk=app.pk)


@login_required
def application_detail(request, pk):
    app = get_object_or_404(RefundApplication, pk=pk, user=request.user)
    return render(
        request,
        "core/application.html",
        {"app": app, "receipts": app.receipts.all(), "matches": app.statement_matches.all()},
    )


# --- Kalkulyatorlar --------------------------------------------------------------

def cashback(request):
    providers = [
        {
            "name": p.name,
            "slug": p.slug,
            "commission_percent": float(p.commission_percent),
            "commission_fixed": float(p.commission_fixed),
            "cashback_percent": float(p.cashback_percent),
            "cashback_cap": float(p.cashback_cap) if p.cashback_cap is not None else None,
            "note": p.note,
            "color": p.color,
        }
        for p in PaymentProvider.objects.filter(is_active=True)
    ]
    updated = PaymentProvider.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()
    return render(request, "core/cashback.html", {"providers": providers, "updated": updated, "rate": settings.JSHOD_RATE})


def freelancer(request):
    return render(
        request,
        "core/freelancer.html",
        {
            "form": FreelancerForm(),
            "fields": FREELANCE_FIELDS,
            "rates": {
                "general": settings.JSHOD_RATE,
                "reduced": settings.SELF_EMPLOYED_RATE,
                "limit": settings.SELF_EMPLOYED_LIMIT,
            },
        },
    )


# --- Ariza tekshiruvi va holati ---------------------------------------------------

def checkup(request):
    """Ariza tekshiruvi. JS har javobdan keyin shu sahifaga yuboradi va natija qismini jonli yangilaydi."""
    form = CheckupForm(request.POST or None)
    result = None
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        # Faqat haqiqatan javob berilgan savollar; javobsizlari jarimaga kirmaydi (natija "taxminiy" deb belgilanadi)
        answers = {k: v for k, v in form.answers().items() if k in request.POST}
        result = run_check(monthly_salary=d["monthly_salary"], payment=d["payment"], for_family=d["for_family"],
                           answers=answers, unknown_as_no=False)
    if request.headers.get("Accept") == "application/json":
        html = render_to_string("core/_checkup_result.html", {"result": result, "form": form}, request=request)
        return JsonResponse({"html": html, "valid": form.is_valid()})
    answered = set(request.POST) if request.method == "POST" else set()
    questions = [
        {"key": key, "title": SHORT_TITLES[key], "text": text, "answer": request.POST.get(key) if key in answered else None}
        for key, text, *_ in QUESTIONS + [FAMILY_QUESTION]
    ]
    return render(request, "core/checkup.html", {"form": form, "questions": questions, "result": result})


def _appeal_letter(app, user):
    name = user.get_full_name() or user.first_name or user.username
    submitted = app.submitted_at.strftime("%d.%m.%Y") if app.submitted_at else "____"
    refund = f"{app.refund_amount:,.0f}".replace(",", " ")
    if app.status == RefundApplication.Status.REJECTED:
        ask = _("Arizam rad etilgani haqida xabar oldim. Rad etish asoslarini yozma ravishda tushuntirib berishingizni "
                "va kamchiliklarni bartaraf etib qayta topshirishim uchun qaysi hujjatlar yetishmasligini ko'rsatishingizni so'rayman.")
    else:
        ask = _("Ariza topshirilganiga %(days)s kun bo'ldi, biroq hozirgacha javob olmadim. "
                "Arizam qaysi bosqichda ekani va pul qachon qaytarilishi haqida yozma ma'lumot berishingizni so'rayman.") % {
            "days": app.days_waiting,
        }
    return _(
        "____________ tumani (shahri) Davlat soliq inspeksiyasi boshlig'iga\n"
        "Fuqaro %(name)sdan\n"
        "Tel.: +%(phone)s\n\n"
        "MUROJAAT\n\n"
        "Men %(submitted)s sanada %(year)s-yil uchun ta'lim/tibbiyot to'lovlari bo'yicha %(refund)s so'm "
        "jismoniy shaxslardan olinadigan daromad solig'ini qaytarish to'g'risida ariza topshirganman.\n\n"
        "%(ask)s\n\n"
        "Ilova: to'lov hujjatlari reestri.\n\n"
        "Sana: %(today)s            Imzo: __________"
    ) % {
        "name": name, "phone": user.username, "submitted": submitted, "year": app.year, "refund": refund,
        "ask": ask, "today": f"{timezone.localdate():%d.%m.%Y}",
    }


@login_required
def tracker(request):
    apps = list(request.user.applications.all())
    for app in apps:
        app.form = ApplicationStatusForm(instance=app, prefix=f"a{app.pk}")
        app.steps = [label for value, label in RefundApplication.Status.choices if value in RefundApplication.TRACK]
        overdue = app.days_waiting is not None and app.days_waiting > settings.REFUND_EXPECTED_DAYS
        app.overdue = overdue
        app.letter = _appeal_letter(app, request.user) if overdue or app.status == RefundApplication.Status.REJECTED else ""
    return render(request, "core/tracker.html", {"apps": apps, "expected_days": settings.REFUND_EXPECTED_DAYS})


@login_required
@require_POST
def application_status(request, pk):
    app = get_object_or_404(RefundApplication, pk=pk, user=request.user)
    form = ApplicationStatusForm(request.POST, instance=app, prefix=f"a{app.pk}")
    if form.is_valid():
        form.save()
        messages.success(request, _("%(year)s-yil arizasi holati yangilandi: %(status)s.") % {"year": app.year, "status": app.get_status_display()})
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, _("Holat saqlanmadi: %(errors)s") % {"errors": errors})
    return redirect(f"{reverse('tracker')}#app-{app.pk}")


# --- Ma'lumot sahifalari (startup: narxlar, raqobat ustunligi, savol-javob) ------

# Tariflar — taklif qilinayotgan biznes-model; to'lov integratsiyasi ulanganda shu yerdan yangilanadi.
PLANS = [
    {
        "key": "free",
        "name": _l("Bepul"),
        "icon": "i-receipt",
        "audience": _l("Bitta kontrakt yoki chekni sinab ko'rish uchun"),
        "monthly": 0,
        "yearly": 0,
        "highlights": [
            _l("Yiliga 5 tagacha chek"),
            _l("1 marta Avto-Audit"),
            _l("Ariza tekshiruvi va reestr"),
        ],
        "cta": _l("Bepul boshlash"),
        "featured": False,
    },
    {
        "key": "family",
        "name": _l("Oila"),
        "icon": "i-users",
        "audience": _l("Kontrakt, bog'cha va davolanishni to'laydigan oilalar uchun"),
        "monthly": 4_900,
        "yearly": 49_000,
        "highlights": [
            _l("Cheksiz chek — AI o'zi o'qiydi"),
            _l("Cheksiz Avto-Audit"),
            _l("4 kishigacha oila a'zolari"),
            _l("Telegram'da muddat eslatmalari"),
        ],
        "cta": _l("Oila tarifini tanlash"),
        "featured": True,
    },
    {
        "key": "freelancer",
        "name": _l("Frilanser"),
        "icon": "i-rocket",
        "audience": _l("O'zini o'zi band qilganlar va YTTlar uchun"),
        "monthly": 9_900,
        "yearly": 99_000,
        "highlights": [
            _l("Oila tarifidagi hammasi"),
            _l("1% rejim bo'yicha daromad hisobi"),
            _l("Choraklik soliq kalendari"),
            _l("Ustuvor yordam"),
        ],
        "cta": _l("Frilanser tarifini tanlash"),
        "featured": False,
    },
]

# Tariflar taqqoslovi: True — bor, False — yo'q, matn — limit
PLAN_MATRIX = [
    (_l("Chek skanerlash"), [_l("5 ta / yil"), _l("Cheksiz"), _l("Cheksiz")]),
    (_l("AI chekni o'zi o'qiydi (Claude Vision)"), [False, True, True]),
    (_l("Avto-Audit (bank hisoboti)"), [_l("1 marta"), _l("Cheksiz"), _l("Cheksiz")]),
    (_l("Ariza tekshiruvi va reestr"), [True, True, True]),
    (_l("Ariza holati va murojaat xati"), [True, True, True]),
    (_l("Oila a'zolari"), [False, _l("4 kishigacha"), _l("4 kishigacha")]),
    (_l("Telegram'da muddat eslatmalari"), [False, True, True]),
    (_l("AI-yordamchi"), [_l("Asosiy"), _l("To'liq"), _l("To'liq")]),
    (_l("1% rejim bo'yicha daromad hisobi"), [False, False, True]),
    (_l("Choraklik soliq kalendari"), [False, False, True]),
    (_l("Ustuvor yordam"), [False, False, True]),
]

# Raqobat taqqoslovi: True — bor, False — yo'q, "part" — qisman
COMPARISON = {
    "columns": [_l("Magnit"), _l("Qo'lda (my.soliq.uz)"), _l("Buxgalter xizmati"), _l("Oddiy kalkulyator")],
    "rows": [
        (_l("Chekni rasmdan avtomatik o'qish (OCR)"), [True, False, False, False]),
        (_l("Bank/ilova hisobotidan to'lovlarni o'zi topish"), [True, False, "part", False]),
        (_l("12% qaytarishni darhol hisoblash"), [True, False, True, True]),
        (_l("Keshbek va komissiyani taqqoslash"), [True, False, False, False]),
        (_l("Frilanser 1% rejim kalkulyatori"), [True, False, True, "part"]),
        (_l("Tayyor ariza reestri"), [True, "part", True, False]),
        (_l("Ariza rad etilish xavfini oldindan tekshirish"), [True, False, "part", False]),
        (_l("Ushlangan soliq bo'yicha haqiqiy summani hisoblash"), [True, False, True, False]),
        (_l("Ariza holatini kuzatish va tayyor murojaat xati"), [True, "part", "part", False]),
        (_l("24/7 AI-maslahatchi o'zbek tilida"), [True, False, False, False]),
        (_l("Qaytgan puldan foiz olinmaydi"), [True, True, False, True]),
        (_l("Vaqt sarfi"), [_l("5 daqiqa"), _l("2–3 soat"), _l("1–2 kun"), _l("30 daqiqa")]),
    ],
}

ADVANTAGES = [
    ("i-scan", _l("Hammasi bitta joyda"), _l("Chek, bank hisoboti, keshbek va frilanser soliqlari — boshqa servislar ularni alohida-alohida taklif qiladi.")),
    ("i-zap", _l("5 daqiqada ariza"), _l("OCR va Avto-Audit qo'lda kiritishni yo'q qiladi: yuklang, tasdiqlang, chop eting.")),
    ("i-tag", _l("Shaffof narx"), _l("Qaytgan pulingizdan foiz olmaymiz. Bepul tarif doimo bepul qoladi.")),
    ("i-wallet", _l("Ikki baravar foyda"), _l("Faqat soliqni qaytarmaymiz — to'lovni qaysi ilovada qilsangiz ko'proq keshbek olishingizni ham ko'rsatamiz.")),
    ("i-shield", _l("Rad etilmaydigan ariza"), _l("Yuborishdan oldin tekshiruv: yetishmayotgan hujjatlar va haqiqatda qaytadigan summa — boshqalar faqat 12% ni ko'paytiradi.")),
    ("i-chart", _l("Pulingiz qayerdaligini bilasiz"), _l("Ariza holatini bosqichma-bosqich kuzating; kechiksa — tayyor murojaat xati bir bosishda.")),
    ("i-bot", _l("O'zbek tilidagi AI"), _l("Soliq savollariga kechayu kunduz oddiy tilda javob beradigan yordamchi.")),
]

FAQ = [
    (_l("Umumiy"), [
        (_l("Magnit nima?"), _l("Magnit — ta'lim, bog'cha, maktab va tibbiyot to'lovlaridan 12% JShOD (daromad solig'i)ni qaytarib olishga yordam beruvchi platforma. Cheklarni o'qiydi, mos to'lovlarni topadi va ariza reestrini tayyorlaydi.")),
        (_l("Kimlar soliqni qaytarib olishi mumkin?"), _l("Rasmiy ish joyidan maosh olib, 12% daromad solig'i to'layotgan har bir fuqaro o'zi, farzandi yoki yaqinlari uchun qilingan mos to'lovlar bo'yicha soliqni qaytarishi mumkin.")),
        (_l("Qaysi to'lovlar mos keladi?"), _l("Oliy ta'lim kontrakti, bog'cha, maktab, tibbiyot muassasalari va shartnomaviy to'lovlar. Aniq ro'yxat Soliq kodeksiga muvofiq yangilanib boriladi.")),
    ]),
    (_l("Foydalanish"), [
        (_l("Chekni qanday yuklayman?"), _l("\"Chek skanerlash\" bo'limida PNG, JPG yoki PDF faylni tashlang. Summa, sana va STIR avtomatik to'ldiriladi — siz faqat tekshirib tasdiqlaysiz.")),
        (_l("Avto-Audit qanday ishlaydi?"), _l("Click, Payme, Uzum yoki Anorbank ilovasidan yillik PDF-hisobotni yuklaysiz. Tizim universitet, bog'cha, maktab va klinikalarga qilingan to'lovlarni o'zi ajratib beradi.")),
        (_l("Ariza qayerga topshiriladi?"), _l("Magnit ariza reestrini tayyorlaydi. Rasmiy ariza my.soliq.uz orqali yoki soliq inspeksiyasiga topshiriladi.")),
    ]),
    (_l("Narx va xavfsizlik"), [
        (_l("Xizmat pullikmi?"), _l("Bepul tarif doimo bepul. Oila va Frilanser tariflari qo'shimcha imkoniyatlar beradi. Biz qaytgan pulingizdan foiz olmaymiz.")),
        (_l("Ma'lumotlarim xavfsizmi?"), _l("Hujjatlaringiz faqat sizning kabinetingizda saqlanadi va uchinchi shaxslarga berilmaydi. Istalgan chekni o'zingiz o'chirishingiz mumkin.")),
        (_l("Hisob-kitoblar rasmiymi?"), _l("Hisob-kitoblar ma'lumot uchun. Yakuniy summa soliq organi tomonidan tasdiqlanadi.")),
    ]),
]

ROADMAP = [
    (_l("Ishga tushirildi"), _l("OCR, Avto-Audit, keshbek va 1% kalkulyatorlari, AI-yordamchi"), True),
    (_l("Keyingi bosqich"), _l("Telegram-bot, oila kabineti, muddatlar haqida eslatmalar"), False),
    (_l("Kelajakda"), _l("my.soliq.uz bilan integratsiya, bank API orqali avtomatik import, mobil ilova"), False),
]


def pricing(request):
    return render(request, "core/pricing.html", {"plans": PLANS, "matrix": PLAN_MATRIX})


def why(request):
    return render(request, "core/why.html", {"comparison": COMPARISON, "advantages": ADVANTAGES})


def faq(request):
    return render(request, "core/faq.html", {"faq": FAQ})


def about(request):
    return render(request, "core/about.html", {"roadmap": ROADMAP})


# --- AI chat ------------------------------------------------------------------------

@require_POST
def chat_api(request):
    try:
        message = (json.loads(request.body).get("message") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": _("Noto'g'ri so'rov")}, status=400)
    if not message:
        return JsonResponse({"error": _("Xabar bo'sh")}, status=400)
    text, used_ai = assistant.reply(request.session, request.user, message[:2000])
    return JsonResponse({"reply": text, "ai": used_ai})


@require_POST
def chat_reset(request):
    request.session.pop("chat_history", None)
    return JsonResponse({"ok": True})


# --- Telegram webhook (serverda; lokalda `manage.py telegram_bot` ishlatiladi) -------

@csrf_exempt
@require_POST
def telegram_webhook(request):
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not secrets.compare_digest(given, secret):
        raise Http404
    try:
        update = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)
    try:
        telegram.handle_update(update)
    except Exception:
        # Telegram xatoda qayta-qayta yuboraveradi — logga yozib, 200 qaytaramiz
        telegram.log.exception("Webhook yangilanishini qayta ishlashda xato: %s", update.get("update_id"))
    return HttpResponse("ok")

# views finesh