from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from core.storage import VercelBlobStorage


class Command(BaseCommand):
    help = "Lokal media/ papkasidagi fayllarni Vercel Blob'ga xuddi shu nom bilan yuklaydi (bazadagi yo'llar o'zgarmaydi)."

    def handle(self, *args, **options):
        if not settings.BLOB_READ_WRITE_TOKEN:
            raise CommandError("BLOB_READ_WRITE_TOKEN ni kiriting (Vercel → Storage → Blob).")
        storage = VercelBlobStorage()
        files = [p for p in settings.MEDIA_ROOT.rglob("*") if p.is_file()]
        for path in files:
            name = path.relative_to(settings.MEDIA_ROOT).as_posix()
            with path.open("rb") as fh:
                storage._save(name, File(fh, name=name))
            self.stdout.write(f"  {name}")
        self.stdout.write(self.style.SUCCESS(f"{len(files)} ta fayl yuklandi."))
