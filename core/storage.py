"""
Vercel Blob uchun Django fayl ombori.

Vercel serverining diski vaqtinchalik — yuklangan cheklar va PDF'lar u yerda
saqlanmaydi. Shuning uchun serverda fayllar Vercel Blob'ga yoziladi
(settings.BLOB_READ_WRITE_TOKEN bo'lsa). Lokalda oddiy media/ papkasi ishlatiladi.
"""

import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

API = "https://blob.vercel-storage.com"
API_VERSION = "7"


@deconstructible
class VercelBlobStorage(Storage):
    def __init__(self, token=None):
        self.token = token or settings.BLOB_READ_WRITE_TOKEN
        # Token ko'rinishi: vercel_blob_rw_<storeId>_<maxfiy qism>
        self.store_id = self.token.split("_")[3].lower()
        self.base_url = f"https://{self.store_id}.public.blob.vercel-storage.com/"

    def _request(self, url, method="GET", data=None, headers=None):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "authorization": f"Bearer {self.token}",
            "x-api-version": API_VERSION,
            **(headers or {}),
        })
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
        return json.loads(body) if body else {}

    def get_available_name(self, name, max_length=None):
        # Har bir faylga tasodifiy qo'shimcha: nomlar to'qnashmaydi va URL'ni taxmin qilib bo'lmaydi
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        name = f"{stem}-{secrets.token_urlsafe(12)}{dot}{ext}"
        if max_length and len(name) > max_length:
            raise ValueError("Fayl nomi juda uzun.")
        return name

    def _save(self, name, content):
        content.seek(0)
        data = content.read()
        ctype = getattr(content, "content_type", None) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._request(f"{API}/{urllib.parse.quote(name)}", method="PUT", data=data, headers={
            "x-content-type": ctype,
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
        })
        return name

    def _open(self, name, mode="rb"):
        with urllib.request.urlopen(self.url(name), timeout=60) as res:
            return ContentFile(res.read(), name=name)

    def delete(self, name):
        if name:
            self._request(f"{API}/delete", method="POST", data=json.dumps({"urls": [self.url(name)]}).encode(),
                          headers={"content-type": "application/json"})

    def exists(self, name):
        try:
            urllib.request.urlopen(urllib.request.Request(self.url(name), method="HEAD"), timeout=30).close()
            return True
        except urllib.error.HTTPError:
            return False

    def size(self, name):
        with urllib.request.urlopen(urllib.request.Request(self.url(name), method="HEAD"), timeout=30) as res:
            return int(res.headers.get("content-length", 0))

    def url(self, name):
        return self.base_url + urllib.parse.quote(name)
