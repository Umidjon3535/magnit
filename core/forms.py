import re
import secrets
from decimal import Decimal

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import make_password
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _l

from .models import PhoneVerification, Profile, Receipt, RefundApplication
from .services.checkup import FAMILY_QUESTION, QUESTIONS
from .services.tax import FREELANCE_FIELDS

MAX_UPLOAD = 10 * 1024 * 1024


def _check_size(f):
    if f.size > MAX_UPLOAD:
        raise forms.ValidationError(_l("Fayl hajmi 10 MB dan oshmasligi kerak."))
    return f


def normalize_phone(value: str) -> str:
    """'+998 90 123-45-67', '901234567', '998901234567' -> '998901234567'."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 9:
        digits = "998" + digits
    if not re.fullmatch(r"998\d{9}", digits):
        raise forms.ValidationError(_l("Telefon raqamini to'liq kiriting: +998 XX XXX XX XX"))
    return digits


class RegisterForm(forms.Form):
    """Ro'yxatdan o'tish: telefon raqam (login sifatida), ism, familiya va parol. Telefon Telegram-bot orqali tasdiqlanadi."""

    phone = forms.CharField(label=_l("Telefon raqam"), error_messages={"required": _l("Telefon raqamini kiriting.")})
    first_name = forms.CharField(label=_l("Ism"), max_length=150, error_messages={"required": _l("Ismingizni kiriting.")})
    last_name = forms.CharField(label=_l("Familiya"), max_length=150, error_messages={"required": _l("Familiyangizni kiriting.")})
    password = forms.CharField(label=_l("Parol"), strip=False, widget=forms.PasswordInput, error_messages={"required": _l("Parol o'ylab toping.")})

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if User.objects.filter(username=phone).exists():
            raise forms.ValidationError(_l("Bu raqam allaqachon ro'yxatdan o'tgan — «Kirish» bo'limidan foydalaning."))
        return phone

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            user = User(username=cleaned.get("phone", ""), first_name=cleaned.get("first_name", ""))
            try:
                password_validation.validate_password(password, user)
            except forms.ValidationError as e:
                self.add_error("password", e)
        return cleaned

    def create_verification(self):
        """Hisob darhol yaratilmaydi: avval telefon Telegram-bot orqali tasdiqlanadi."""
        d = self.cleaned_data
        return PhoneVerification.objects.create(
            token=secrets.token_urlsafe(24),
            phone=d["phone"],
            first_name=d["first_name"].strip(),
            last_name=d["last_name"].strip(),
            password_hash=make_password(d["password"]),
        )


class ProfileForm(forms.Form):
    """Telegram orqali tasdiqlangan yangi foydalanuvchi uchun: ism va familiya."""

    first_name = forms.CharField(label=_l("Ism"), max_length=150, error_messages={"required": _l("Ismingizni kiriting.")})
    last_name = forms.CharField(label=_l("Familiya"), max_length=150, error_messages={"required": _l("Familiyangizni kiriting.")})


class PreferencesForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["language", "theme"]
        widgets = {"language": forms.RadioSelect, "theme": forms.RadioSelect}


class PhoneLoginForm(AuthenticationForm):
    """Kirish: telefon raqam + parol."""

    error_messages = {
        "invalid_login": _l("Telefon raqam yoki parol noto'g'ri."),
        "inactive": _l("Bu hisob faol emas."),
    }

    def clean_username(self):
        value = self.cleaned_data.get("username", "")
        try:
            return normalize_phone(value)
        except forms.ValidationError:
            return value  # noto'g'ri raqam -> autentifikatsiya "invalid_login" bilan rad etadi


class ReceiptUploadForm(forms.Form):
    file = forms.FileField(
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp", "pdf"])],
    )

    def clean_file(self):
        return _check_size(self.cleaned_data["file"])


class ReceiptConfirmForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = ("amount", "paid_at", "stir", "organization", "category")
        widgets = {
            "paid_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "1", "min": "0", "inputmode": "numeric"}),
            "stir": forms.TextInput(attrs={"inputmode": "numeric", "pattern": r"\d{9}", "maxlength": 9}),
        }

    def clean_stir(self):
        stir = self.cleaned_data.get("stir", "").strip()
        if stir and (len(stir) != 9 or not stir.isdigit()):
            raise forms.ValidationError(_l("STIR 9 ta raqamdan iborat bo'lishi kerak."))
        return stir

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if not amount or amount <= 0:
            raise forms.ValidationError(_l("To'lov summasini kiriting."))
        return amount


class StatementUploadForm(forms.Form):
    file = forms.FileField(validators=[FileExtensionValidator(["pdf"])])

    def clean_file(self):
        return _check_size(self.cleaned_data["file"])


class FreelancerForm(forms.Form):
    monthly_income = forms.DecimalField(label=_l("Oylik daromad (so'm)"), min_value=0, max_digits=14, decimal_places=0)
    field = forms.ChoiceField(label=_l("Soha"), choices=FREELANCE_FIELDS)


class MoneyField(forms.Field):
    """"12 000 000" kabi bo'shliqli summani butun songa aylantiradi."""

    def to_python(self, value):
        digits = re.sub(r"[^\d]", "", super().to_python(value) or "")
        if not digits:
            if self.required:
                raise forms.ValidationError(_l("Summani kiriting."))
            return Decimal("0")
        return Decimal(digits)


class CheckupForm(forms.Form):
    monthly_salary = MoneyField(label=_l("Oylik rasmiy ish haqingiz (soliqdan oldin)"))
    payment = MoneyField(label=_l("Yillik to'lov summasi (kontrakt, bog'cha, davolanish)"))
    for_family = forms.BooleanField(label=_l("To'lov farzandim yoki oila a'zom uchun"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, question, *_ in QUESTIONS + [FAMILY_QUESTION]:
            self.fields[key] = forms.BooleanField(label=question, required=False)

    def answers(self):
        return {k: v for k, v in self.cleaned_data.items() if isinstance(v, bool)}


class ApplicationStatusForm(forms.ModelForm):
    class Meta:
        model = RefundApplication
        fields = ["status", "submitted_at", "resolved_at", "note"]
        widgets = {
            "submitted_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "resolved_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 2, "placeholder": _l("Masalan: ariza raqami, inspektor javobi")}),
        }

    def clean(self):
        data = super().clean()
        status = data.get("status")
        if status != RefundApplication.Status.DRAFT and not data.get("submitted_at"):
            self.add_error("submitted_at", _l("Ariza yuborilgan sanani kiriting."))
        return data
