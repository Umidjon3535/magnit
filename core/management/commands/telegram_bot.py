import time

from django.core.management.base import BaseCommand, CommandError

from core.services import telegram


class Command(BaseCommand):
    help = "Telegram-botni ishga tushiradi (long polling): ro'yxatdan o'tishda tasdiqlash kodlarini yuboradi."

    def handle(self, *args, **options):
        if not telegram.is_configured():
            raise CommandError(".env faylida TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_USERNAME ni kiriting.")
        me = telegram.api("getMe")
        # Webhook o'rnatilgan bo'lsa, getUpdates ishlamaydi
        telegram.api("deleteWebhook")
        self.stdout.write(self.style.SUCCESS(f"@{me['username']} ishga tushdi. To'xtatish: Ctrl+C"))
        offset = None
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset
                for update in telegram.api("getUpdates", **params):
                    offset = update["update_id"] + 1
                    try:
                        telegram.handle_update(update)
                    except Exception:
                        telegram.log.exception("Yangilanishni qayta ishlashda xato: %s", update.get("update_id"))
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.stderr.write(f"Telegram bilan aloqa xatosi: {e}. 5 soniyadan so'ng qayta urinamiz.")
                time.sleep(5)
