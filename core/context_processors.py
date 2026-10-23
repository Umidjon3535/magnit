from django.conf import settings

ASSETS = [settings.BASE_DIR / "static" / "css" / "app.css", settings.BASE_DIR / "static" / "js" / "app.js"]


def _asset_version():
    # Fayl o'zgarganda havola ham o'zgaradi — brauzer eski CSS/JS'ni keshdan olmaydi
    try:
        return str(int(max(f.stat().st_mtime for f in ASSETS)))
    except OSError:
        return "0"


def platform(request):
    return {
        "AI_ENABLED": settings.AI_ENABLED,
        "JSHOD_PERCENT": int(settings.JSHOD_RATE * 100),
        "BRAND": settings.BRAND_NAME,
        "LANG_CHOICES": settings.LANGUAGES,  # nomlar tarjimasiz — har bir til o'z nomi bilan
        "THEME": getattr(getattr(request, "profile", None), "theme", ""),
        "TELEGRAM_BOT": settings.TELEGRAM_BOT_USERNAME,
        "ASSET_VERSION": _asset_version(),
        "SUPPORT": {
            "email": settings.SUPPORT_EMAIL,
            "telegram": settings.SUPPORT_TELEGRAM,
            "phone": settings.SUPPORT_PHONE,
        },
    }
