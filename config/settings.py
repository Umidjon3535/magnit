"""
Magnit — moliyaviy va soliq platformasi uchun Django sozlamalari.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Vercel o'zi VERCEL=1 o'zgaruvchisini beradi
ON_VERCEL = bool(os.getenv("VERCEL"))

DEBUG = os.getenv("DJANGO_DEBUG", "0" if ON_VERCEL else "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY o'rnatilmagan (production).")
    SECRET_KEY = "django-insecure-faqat-lokal-ishlab-chiqish-uchun"

ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h]
if ON_VERCEL:
    ALLOWED_HOSTS.append(".vercel.app")
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if ON_VERCEL:
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
    for host in ALLOWED_HOSTS:
        if host not in ("127.0.0.1", "localhost", ".vercel.app"):
            CSRF_TRUSTED_ORIGINS.append("https://" + host.lstrip("."))


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.UserPreferencesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.platform",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Lokalda SQLite; serverda DATABASE_URL (Neon PostgreSQL)
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0 if ON_VERCEL else 600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uz"
# Interfeys tillari. Asosiy matnlar o'zbekcha yozilgan, ru/en tarjimalari locale/ papkasida.
# Tarjimalarni yangilagach: python manage.py build_locale
LANGUAGES = [
    ("uz", "O'zbekcha"),
    ("ru", "Русский"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Serverda statik fayllarni whitenoise beradi (collectstatic'siz ham)
WHITENOISE_USE_FINDERS = True

# Yuklangan fayllar: lokalda media/ papkasi, serverda Vercel Blob (BLOB_READ_WRITE_TOKEN)
BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN", "")
STORAGES = {
    "default": {
        "BACKEND": "core.storage.VercelBlobStorage" if BLOB_READ_WRITE_TOKEN else "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Yuklanadigan fayllar uchun cheklov (10 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "home"  # bosh sahifadagi "Kirish" bo'limi (?next= bilan)
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = True
    # Sayt hozircha xat yubormaydi
    SILENCED_SYSTEM_CHECKS = ["mail.E001"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}

# --- Platforma sozlamalari ---
# AI-yordamchi (Claude). Kalit bo'lmasa, yordamchi oflayn rejimda ishlaydi.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
AI_ENABLED = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

# Soliq stavkalari
JSHOD_RATE = 0.12          # Jismoniy shaxslar daromad solig'i
SELF_EMPLOYED_RATE = 0.01  # 2026-yilgi islohot: o'zini o'zi band qilganlar
SELF_EMPLOYED_LIMIT = 1_000_000_000  # yillik aylanma chegarasi, so'm

# Ariza holati: shu kundan ko'p javob bo'lmasa, murojaat xati taklif qilinadi (taxminiy, o'zgartiring)
REFUND_EXPECTED_DAYS = 30

# Brend va aloqa ma'lumotlari (sayt pastki qismi va "Biz haqimizda" sahifasida)
BRAND_NAME = "Magnit"
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "")
SUPPORT_TELEGRAM = os.getenv("SUPPORT_TELEGRAM", "")  # masalan: magnit_support (@ belgisisiz)
SUPPORT_PHONE = os.getenv("SUPPORT_PHONE", "")

# Telegram-bot orqali telefonni tasdiqlash (ro'yxatdan o'tish)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")
# Serverda bot webhook orqali ishlaydi: /telegram/webhook/ (Telegram shu maxfiy kalitni sarlavhada yuboradi)
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
VERIFY_TTL_MINUTES = 10
VERIFY_MAX_ATTEMPTS = 5
