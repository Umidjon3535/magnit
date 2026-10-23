# Magnit — moliyaviy va soliq platformasi (Django)

Kontrakt, bog'cha, maktab va tibbiyot to'lovlaridan **12% JShOD**ni qaytarishga yordam beruvchi veb-platforma va AI-yordamchi.

## Imkoniyatlar

| Bo'lim | URL | Nima qiladi |
|---|---|---|
| 📸 Chek skanerlash | `/scan/` | Chek (PNG/JPG/PDF) Drag & Drop → OCR → Summa, Sana, STIR formaga avtomatik tushadi → tasdiqlash |
| 🔍 Avto-Audit | `/audit/` | Click/Payme/Uzum/Anorbank yillik PDF-hisobotidan mos to'lovlarni topadi, 12% ni hisoblaydi |
| 💸 Keshbek optimizatori | `/cashback/` | 5 ta to'lov tizimining komissiya va keshbegini taqqoslaydi ("Ikki baravar foyda") |
| 🚀 Frilanser 1% | `/freelancer/` | 12% va 1% soliq rejimini taqqoslab, yillik tejamkorlikni ko'rsatadi |
| 📊 Shaxsiy kabinet | `/dashboard/` | KPI, oylik grafik, turlar bo'yicha taqsimot, ariza shakllantirish va chop etish |
| 🤖 AI-yordamchi | har sahifada | Claude asosidagi chat (kalit bo'lmasa — oflayn qoidalarga asoslangan javoblar) |
| 🛡️ Ariza tekshiruvi | `/check/` | Rad etilish xavfi, ushlangan JShOD bo'yicha **haqiqiy** qaytadigan summa, shaxsiy hujjatlar ro'yxati |
| 📍 Ariza holati | `/tracker/` | Arizani bosqichma-bosqich kuzatish; kechiksa (`REFUND_EXPECTED_DAYS`) yoki rad etilsa — tayyor murojaat xati |
| 💎 Nega Magnit? | `/why-magnit/` | Raqobat ustunliklari va muqobil yo'llar bilan taqqoslash jadvali |
| 🏷️ Narxlar | `/pricing/` | Bepul / Pro / Frilanser tariflari (`core/views.py` → `PLANS`) |
| ❓ Savol-javob | `/faq/` | Ko'p beriladigan savollar (`FAQ`) |
| 👥 Biz haqimizda | `/about/` | Missiya, yo'l xaritasi, aloqa (`SUPPORT_*` env o'zgaruvchilari) |
| ⚙️ Admin | `/admin/` | To'lov tizimlari tariflari, cheklar, arizalar |

## Ishga tushirish

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # ANTHROPIC_API_KEY ni kiriting (ixtiyoriy)
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver
# Alohida oynada — ro'yxatdan o'tish kodlarini yuboruvchi Telegram-bot:
.\.venv\Scripts\python manage.py telegram_bot
```

Ro'yxatdan o'tish: telefon Telegram-bot orqali tasdiqlanadi (bot kontakt so'raydi, raqam mos kelsa 6 xonali kod yuboradi). `.env` da `TELEGRAM_BOT_TOKEN` va `TELEGRAM_BOT_USERNAME` bo'lishi shart.

So'ng http://127.0.0.1:8000 ni oching.

## Tillar (uz / ru / en)

- Asosiy matnlar o'zbekcha yozilgan; rus va ingliz tarjimalari `locale/<til>/LC_MESSAGES/django.po` da.
- Til menyudagi **UZ/RU/EN** tanlagichidan yoki **Kabinet → Sozlamalar**dan almashtiriladi; kirgan foydalanuvchida tanlov profilga saqlanadi.
- Shablonga yangi matn qo'shsangiz (`{% translate %}` / `{% blocktranslate trimmed %}` / `_()`), so'ng:

```powershell
.\.venv\Scripts\python manage.py build_locale   # matnlarni yig'adi, .po ni yangilaydi va .mo ga kompilyatsiya qiladi
```

Yangi matnlar `.po` da `# TODO: tarjima qilinmagan` belgisi bilan qo'shiladi — `msgstr` ni to'ldirib, buyruqni qayta ishga tushiring. (GNU gettext talab qilinmaydi.)

## OCR qanday ishlaydi

Navbat bilan: **Claude Vision** (eng aniq, `ANTHROPIC_API_KEY` kerak) → **EasyOCR** → **Tesseract** → PDF matn qatlami.
Lokal dvigatellar ixtiyoriy: `pip install easyocr` yoki `pip install pytesseract` + Tesseract-OCR dasturi.
Hech biri bo'lmasa, fayl saqlanadi va foydalanuvchi ma'lumotlarni qo'lda kiritadi.

## AI-yordamchi

- Model: `claude-opus-5-5` (`CLAUDE_MODEL` orqali o'zgartiriladi).
- Tizim yo'riqnomasi: `core/services/prompts.py`.
- Server-side fallback yoqilgan: xavfsizlik klassifikatori so'rovni rad etsa, API avtomatik zaxira modelga o'tadi.
- Chat tarixi sessiyada saqlanadi (oxirgi 20 xabar).

## Serverga joylash (Vercel)

1. Vercel'da repozitoriyni import qiling (Framework: **Other**). `vercel.json` tayyor.
2. **Storage** bo'limidan ulang: **Neon Postgres** (`DATABASE_URL`) va **Blob** (`BLOB_READ_WRITE_TOKEN`).
3. **Environment Variables**: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` (o'z domeningiz),
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, ixtiyoriy `ANTHROPIC_API_KEY`.
4. Lokal kompyuterdan (`.env` ga `DATABASE_URL` va `BLOB_READ_WRITE_TOKEN` ni vaqtincha qo'yib):

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py loaddata backup\data.json   # lokal ma'lumotlarni ko'chirish
.\.venv\Scripts\python manage.py upload_media                  # cheklar va PDF'larni Blob'ga
.\.venv\Scripts\python manage.py telegram_webhook https://<sayt>.vercel.app
```

Webhook o'rnatilgach lokal `telegram_bot` ni ishga tushirmang (u webhook'ni o'chirib yuboradi).

## Muhim

- To'lov tizimlari tariflari **namuna**dir — `/admin/` → "To'lov tizimlari" bo'limida yangilang.
- Soliq stavkalari `config/settings.py` da: `JSHOD_RATE`, `SELF_EMPLOYED_RATE`, `SELF_EMPLOYED_LIMIT`.
- Hisob-kitoblar ma'lumot uchun; rasmiy ariza my.soliq.uz orqali yuboriladi.

## Testlar

```powershell
.\.venv\Scripts\python manage.py test core
```
