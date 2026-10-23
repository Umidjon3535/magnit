from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class Category(models.TextChoices):
    EDUCATION = "education", _("Ta'lim (OTM, kontrakt)")
    KINDERGARTEN = "kindergarten", _("Bog'cha")
    SCHOOL = "school", _("Maktab")
    MEDICAL = "medical", _("Tibbiyot")
    CONTRACT = "contract", _("Boshqa shartnoma")
    OTHER = "other", _("Boshqa")


ELIGIBLE_CATEGORIES = {
    Category.EDUCATION,
    Category.KINDERGARTEN,
    Category.SCHOOL,
    Category.MEDICAL,
    Category.CONTRACT,
}


class Receipt(models.Model):
    """OCR orqali skanerlangan to'lov cheki yoki kvitansiya."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Tasdiqlanmagan")
        CONFIRMED = "confirmed", _("Tasdiqlangan")
        UNREADABLE = "unreadable", _("O'qib bo'lmadi")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="receipts")
    file = models.FileField(upload_to="receipts/%Y/%m/", max_length=255)
    organization = models.CharField("Tashkilot", max_length=255, blank=True)
    stir = models.CharField("STIR (INN)", max_length=9, blank=True)
    amount = models.DecimalField("Summa (so'm)", max_digits=14, decimal_places=2, null=True, blank=True)
    paid_at = models.DateField("To'lov sanasi", null=True, blank=True)
    category = models.CharField("Turi", max_length=20, choices=Category.choices, default=Category.EDUCATION)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    ocr_engine = models.CharField(max_length=40, blank=True)
    raw_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Chek"
        verbose_name_plural = "Cheklar"

    def __str__(self):
        return f"{self.organization or 'Chek'} — {self.amount or 0:,.0f} so'm"

    @property
    def refund(self) -> Decimal:
        if not self.amount or self.category not in ELIGIBLE_CATEGORIES:
            return Decimal("0")
        return (self.amount * Decimal(str(settings.JSHOD_RATE))).quantize(Decimal("1"))


class Statement(models.Model):
    """Click, Payme, Uzum, Anorbank va h.k. ilovalaridan olingan PDF-hisobot."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="statements")
    file = models.FileField(upload_to="statements/%Y/%m/", blank=True, max_length=255)
    source = models.CharField("Manba", max_length=40, blank=True)
    engine = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "PDF-hisobot"
        verbose_name_plural = "PDF-hisobotlar"

    def __str__(self):
        return f"{self.source or 'Hisobot'} #{self.pk}"

    @property
    def total(self) -> Decimal:
        """Foydalanuvchi chiqarib tashlamagan to'lovlar yig'indisi."""
        return sum((m.amount for m in self.matches.all() if not m.excluded), Decimal("0"))

    @property
    def included_count(self) -> int:
        return sum(1 for m in self.matches.all() if not m.excluded)

    @property
    def refund(self) -> Decimal:
        return (self.total * Decimal(str(settings.JSHOD_RATE))).quantize(Decimal("1"))


class StatementMatch(models.Model):
    """Avto-Audit topgan, soliq qaytarishga mos to'lov."""

    statement = models.ForeignKey(Statement, on_delete=models.CASCADE, related_name="matches")
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_at = models.DateField(null=True, blank=True)
    stir = models.CharField(max_length=9, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    keyword = models.CharField(max_length=60, blank=True)
    # Foydalanuvchi "bu mos emas" deb belgilagan to'lov: summalarga va arizaga kirmaydi
    excluded = models.BooleanField(default=False)

    class Meta:
        ordering = ["paid_at"]

    @property
    def refund(self) -> Decimal:
        return (self.amount * Decimal(str(settings.JSHOD_RATE))).quantize(Decimal("1"))


class PaymentProvider(models.Model):
    """To'lov tizimi tariflari — admin paneldan yangilanadi."""

    name = models.CharField(max_length=60)
    slug = models.SlugField(unique=True)
    commission_percent = models.DecimalField("Komissiya, %", max_digits=5, decimal_places=2, default=0)
    commission_fixed = models.DecimalField("Qat'iy komissiya, so'm", max_digits=10, decimal_places=0, default=0)
    cashback_percent = models.DecimalField("Keshbek, %", max_digits=5, decimal_places=2, default=0)
    cashback_cap = models.DecimalField(
        "Keshbek limiti, so'm", max_digits=12, decimal_places=0, null=True, blank=True,
        help_text="Bo'sh qoldirilsa — cheklovsiz",
    )
    note = models.CharField("Izoh", max_length=200, blank=True)
    color = models.CharField(max_length=7, default="#2a78d6")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "To'lov tizimi"
        verbose_name_plural = "To'lov tizimlari"

    def __str__(self):
        return self.name


class RefundApplication(models.Model):
    """Shaxsiy kabinetda shakllantirilgan soliq qaytarish arizasi."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Qoralama")
        SUBMITTED = "submitted", _("Yuborildi")
        IN_REVIEW = "in_review", _("Ko'rib chiqilmoqda")
        APPROVED = "approved", _("Tasdiqlandi")
        PAID = "paid", _("Pul tushdi")
        REJECTED = "rejected", _("Rad etildi")

    # Kuzatuv bosqichlari (rad etish alohida holat)
    TRACK = [Status.DRAFT, Status.SUBMITTED, Status.IN_REVIEW, Status.APPROVED, Status.PAID]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="applications")
    year = models.PositiveIntegerField()
    receipts = models.ManyToManyField(Receipt, blank=True)
    statement_matches = models.ManyToManyField(StatementMatch, blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    refund_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateField("Yuborilgan sana", null=True, blank=True)
    resolved_at = models.DateField("Yakunlangan sana", null=True, blank=True)
    note = models.TextField("Izoh", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Ariza"
        verbose_name_plural = "Arizalar"

    def __str__(self):
        return f"Ariza {self.year} — {self.refund_amount:,.0f} so'm"

    @property
    def step(self):
        """Kuzatuv chizig'idagi joriy bosqich raqami (rad etilgan ariza "Ko'rib chiqilmoqda"da to'xtaydi)."""
        if self.status == self.Status.REJECTED:
            return self.TRACK.index(self.Status.IN_REVIEW)
        return self.TRACK.index(self.status)

    @property
    def days_waiting(self):
        if not self.submitted_at or self.status in (self.Status.PAID, self.Status.REJECTED):
            return None
        from django.utils import timezone
        return (timezone.localdate() - self.submitted_at).days


def current_language():
    """Yozuv yaratilgan paytdagi interfeys tili (bot xabarlari shu tilda yuboriladi)."""
    return (get_language() or settings.LANGUAGE_CODE)[:2]


class PhoneVerification(models.Model):
    """Telefonni Telegram-bot orqali tasdiqlash: ro'yxatdan o'tish yoki kirish uchun bir martalik kod."""

    class Purpose(models.TextChoices):
        REGISTER = "register", "Ro'yxatdan o'tish"
        LOGIN = "login", "Kirish"

    token = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.REGISTER)
    phone = models.CharField(max_length=12)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)
    language = models.CharField(max_length=5, default=current_language)
    chat_id = models.BigIntegerField(null=True, blank=True)
    code = models.CharField(max_length=6, blank=True)
    code_sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Telefon tasdiqlash"
        verbose_name_plural = "Telefon tasdiqlashlar"

    def __str__(self):
        return f"+{self.phone} ({'kod yuborilgan' if self.code else 'kutilmoqda'})"


class TelegramLink(models.Model):
    """Foydalanuvchining tasdiqlangan Telegram chati: kirish kodi shu yerga to'g'ridan-to'g'ri yuboriladi."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram")
    chat_id = models.BigIntegerField()
    linked_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram bog'lanishi"
        verbose_name_plural = "Telegram bog'lanishlari"

    def __str__(self):
        return f"{self.user} → {self.chat_id}"


class Profile(models.Model):
    """Foydalanuvchi sozlamalari: interfeys tili va mavzu (kunduzgi/tungi)."""

    class Language(models.TextChoices):
        UZ = "uz", "O'zbekcha"
        RU = "ru", "Русский"
        EN = "en", "English"

    class Theme(models.TextChoices):
        LIGHT = "light", _("Kunduzgi")
        DARK = "dark", _("Tungi")
        SYSTEM = "system", _("Qurilma bo'yicha")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    language = models.CharField(max_length=5, choices=Language.choices, default=Language.UZ)
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profillar"

    def __str__(self):
        return f"{self.user} ({self.language}, {self.theme})"

    @classmethod
    def for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]
