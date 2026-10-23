"""Telegram-bot: ro'yxatdan o'tish va kirish uchun bir martalik kod.

Oqim: sayt t.me/<bot>?start=<token> havolasini beradi → bot kontakt so'raydi →
yuborilgan raqam saytdagi raqamga mos kelsa, 6 xonali kod yuboriladi.
"""
import json
import logging
import re
import secrets
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from ..models import PhoneVerification, TelegramLink

log = logging.getLogger(__name__)


def is_configured():
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_USERNAME)


def api(method, **params):
    """Telegram Bot API chaqiruvi; javobning "result" qismini qaytaradi."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    timeout = params.get("timeout", 0) + 15
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read())
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description')}")
    return data["result"]


def deep_link(token):
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"


def ttl():
    return timedelta(minutes=settings.VERIFY_TTL_MINUTES)


def pending():
    """Muddati o'tmagan tasdiqlash arizalari."""
    return PhoneVerification.objects.filter(created_at__gte=timezone.now() - ttl())


def code_is_valid(v, code):
    if not v.code or not v.code_sent_at or timezone.now() - v.code_sent_at > ttl():
        return False
    return secrets.compare_digest(v.code, re.sub(r"\D", "", code or ""))


def contact_keyboard():
    return {
        "keyboard": [[{"text": _("📱 Raqamni yuborish"), "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


REMOVE_KEYBOARD = {"remove_keyboard": True}

# Token bo'lmagan /start: foydalanuvchi tili noma'lum — uch tilda qisqa yo'riqnoma
WELCOME = (
    "Assalomu alaykum! 👋 Bu Magnit platformasining rasmiy boti. "
    "Kirish yoki ro'yxatdan o'tish uchun saytdagi Telegram tugmasini bosing.\n\n"
    "Здравствуйте! 👋 Это официальный бот платформы Magnit. "
    "Чтобы войти или зарегистрироваться, нажмите кнопку Telegram на сайте.\n\n"
    "Hello! 👋 This is the official Magnit bot. To sign in or sign up, tap the Telegram button on the website."
)


def send_message(chat_id, text, **extra):
    return api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", **extra)


def issue_code(v, chat_id, send=None):
    """Yangi kod yaratib, uni Telegram chatiga foydalanuvchi tilida yuboradi."""
    send = send or send_message
    v.chat_id = chat_id
    v.code = f"{secrets.randbelow(10 ** 6):06d}"
    v.code_sent_at = timezone.now()
    v.attempts = 0
    v.save(update_fields=["chat_id", "code", "code_sent_at", "attempts"])
    is_new = v.purpose == PhoneVerification.Purpose.LOGIN and not User.objects.filter(username=v.phone).exists()
    with translation.override(v.language):
        if v.purpose == PhoneVerification.Purpose.REGISTER or is_new:
            action = _("Ro'yxatdan o'tish kodi")
        else:
            action = _("Magnit'ga kirish kodi")
        hint = _("Kodni saytga kiriting, so'ng ism-familiyangizni yozing — hisobingiz yaratiladi.") + "\n\n" if is_new else ""
        text = _(
            "🔐 %(action)s: <code>%(code)s</code>\n\n%(hint)s"
            "Kod %(minutes)s daqiqa amal qiladi. Uni hech kimga bermang — Magnit xodimlari kodni hech qachon so'ramaydi.\n\n"
            "Bu so'rovni siz yubormagan bo'lsangiz, xabarni e'tiborsiz qoldiring."
        ) % {"action": action, "code": v.code, "hint": hint, "minutes": settings.VERIFY_TTL_MINUTES}
        send(chat_id, text, reply_markup=REMOVE_KEYBOARD)


def link_user(user, chat_id):
    TelegramLink.objects.update_or_create(user=user, defaults={"chat_id": chat_id})


def handle_update(update, send=None):
    """Bitta Telegram yangilanishini qayta ishlaydi. send(chat_id, text, **extra) — testlar uchun almashtiriladi."""
    send = send or send_message
    msg = update.get("message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = msg.get("text") or ""

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        v = pending().filter(token=parts[1]).first() if len(parts) > 1 else None
        if not v:
            send(chat_id, WELCOME)
            return
        v.chat_id = chat_id
        v.save(update_fields=["chat_id"])
        with translation.override(v.language):
            if v.purpose == PhoneVerification.Purpose.LOGIN:
                text = _("Assalomu alaykum! 👋\n\nMagnit'ga kirish uchun pastdagi <b>«📱 Raqamni yuborish»</b> "
                         "tugmasini bosing — kirish kodi shu yerga keladi.")
            else:
                text = _("Assalomu alaykum, %(name)s! 👋\n\nRo'yxatdan o'tish uchun saytda <b>+%(phone)s</b> raqami "
                         "kiritildi. Tasdiqlash uchun pastdagi <b>«📱 Raqamni yuborish»</b> tugmasini bosing.") % {
                    "name": v.first_name, "phone": v.phone,
                }
            send(chat_id, text, reply_markup=contact_keyboard())
        return

    contact = msg.get("contact")
    v = pending().filter(chat_id=chat_id).first()
    with translation.override(v.language if v else settings.LANGUAGE_CODE):
        if contact:
            if contact.get("user_id") != msg.get("from", {}).get("id"):
                send(chat_id, _("Faqat o'zingizning raqamingizni yuboring — pastdagi tugmadan foydalaning."),
                     reply_markup=contact_keyboard())
                return
            if not v:
                send(chat_id, _("Ariza topilmadi yoki muddati o'tgan. Saytda Telegram tugmasini qaytadan bosing."),
                     reply_markup=REMOVE_KEYBOARD)
                return
            phone = re.sub(r"\D", "", contact.get("phone_number", ""))
            if v.purpose == PhoneVerification.Purpose.LOGIN:
                # Kirishda raqam saytda kiritilmaydi — hisob shu kontakt bo'yicha topiladi.
                # Hisob bo'lmasa ham kod beriladi: saytda ism-familiya kiritilgach hisob yaratiladi.
                v.phone = phone
                v.save(update_fields=["phone"])
            elif phone != v.phone:
                send(chat_id, _("Bu Telegram hisobi <b>+%(tg)s</b> raqamiga bog'langan, saytda esa <b>+%(site)s</b> kiritilgan.\n\n"
                                "Saytda Telegram'ingizdagi raqamni kiriting.") % {"tg": phone, "site": v.phone},
                     reply_markup=REMOVE_KEYBOARD)
                return
            issue_code(v, chat_id, send)
            return

        send(chat_id, _("Kirish yoki ro'yxatdan o'tish uchun saytdagi Telegram tugmasini bosing."))
