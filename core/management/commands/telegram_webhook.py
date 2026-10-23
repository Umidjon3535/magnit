from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import telegram


class Command(BaseCommand):
    help = "Serverdagi bot uchun Telegram webhook'ni o'rnatadi: manage.py telegram_webhook https://sayt.vercel.app"

    def add_arguments(self, parser):
        parser.add_argument("site_url", help="Sayt manzili, masalan https://magnit.vercel.app")
        parser.add_argument("--delete", action="store_true", help="Webhook'ni o'chirish (lokal polling uchun)")

    def handle(self, *args, site_url, delete, **options):
        if not telegram.is_configured():
            raise CommandError("TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_USERNAME ni kiriting.")
        if delete:
            telegram.api("deleteWebhook")
            self.stdout.write(self.style.SUCCESS("Webhook o'chirildi."))
            return
        if not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError("TELEGRAM_WEBHOOK_SECRET ni kiriting (Vercel'dagi qiymat bilan bir xil).")
        url = site_url.rstrip("/") + "/telegram/webhook/"
        telegram.api("setWebhook", url=url, secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                     allowed_updates=["message"], drop_pending_updates=False)
        self.stdout.write(self.style.SUCCESS(f"Webhook o'rnatildi: {url}"))
