import io
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import PhoneVerification, Receipt, RefundApplication, Statement, TelegramLink
from .services.assistant import offline_reply
from .services.audit import DEMO_STATEMENT, scan_text
from .services.checkup import run_check
from .services.telegram import handle_update
from .templatetags.money import som
from .services.parsing import find_date, find_stir, find_total, parse_amount
from .services.tax import compare_providers, freelancer_savings, refund_for


class ParsingTests(TestCase):
    def test_amount_formats(self):
        self.assertEqual(parse_amount("1 200 000,00"), Decimal("1200000.00"))
        self.assertEqual(parse_amount("1,200,000.50"), Decimal("1200000.50"))
        self.assertEqual(parse_amount("1.200.000"), Decimal("1200000"))
        self.assertEqual(parse_amount("6500000"), Decimal("6500000"))

    def test_receipt_fields(self):
        text = "TDIU universiteti\nSTIR: 201122334\nSana: 03.02.2026\nJami: 12 000 000,00 so'm"
        self.assertEqual(find_total(text), Decimal("12000000.00"))
        self.assertEqual(find_stir(text), "201122334")
        self.assertEqual(find_date(text), date(2026, 2, 3))

    def test_demo_audit_finds_eligible_only(self):
        matches = scan_text(DEMO_STATEMENT)
        self.assertEqual(len(matches), 5)
        self.assertEqual(sum(m.amount for m in matches), Decimal("12000000"))
        self.assertEqual(refund_for(12_000_000), Decimal("1440000"))

    def test_audit_columns_split_across_lines(self):
        # Ko'p PDF'larda ustunlar alohida qatorlarga tushadi; "Jami" tranzaksiyaga qo'shilmasligi kerak
        text = (
            "Sana\nTavsif\nSumma\n"
            "03.02.2025 14:05\nToshkent davlat universiteti\nSTIR 201122334\n6 500 000,00\n"
            "11.03.2025 09:40\nKorzinka\n412 300,00\n"
            "20.04.2025 18:12\nМедицинский центр\n1 700 000,00\n"
            "Jami: 8 612 300,00"
        )
        matches = scan_text(text)
        self.assertEqual([m.amount for m in matches], [Decimal("6500000.00"), Decimal("1700000.00")])
        self.assertEqual(matches[0].stir, "201122334")
        self.assertEqual(matches[1].paid_at, date(2025, 4, 20))


class CalculatorTests(TestCase):
    def test_freelancer(self):
        s = freelancer_savings(10_000_000)
        self.assertEqual(s["savings"], Decimal("13200000"))
        self.assertTrue(s["eligible"])
        self.assertFalse(freelancer_savings(90_000_000)["eligible"])

    def test_providers_seeded_and_sorted(self):
        rows = compare_providers(12_000_000)
        self.assertEqual(len(rows), 5)
        self.assertTrue(rows[0].get("best"))
        self.assertEqual([r["net_cost"] for r in rows], sorted(r["net_cost"] for r in rows))


@override_settings(AI_ENABLED=False)
class FlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", password="Parol-12345", first_name="Ali")

    def test_public_pages(self):
        for name in ("home", "cashback", "freelancer", "pricing", "why", "faq", "about", "checkup"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def _bot(self, text=None, contact=None, chat_id=555, from_id=555, contact_owner=555):
        """Telegram-botga kelgan xabarni simulyatsiya qiladi; bot javoblarini qaytaradi."""
        sent = []
        msg = {"chat": {"id": chat_id}, "from": {"id": from_id}}
        if text:
            msg["text"] = text
        if contact:
            msg["contact"] = {"phone_number": contact, "user_id": contact_owner}
        handle_update({"message": msg}, send=lambda chat, t, **kw: sent.append(t))
        return sent

    @override_settings(TELEGRAM_BOT_TOKEN="x", TELEGRAM_BOT_USERNAME="test_bot")
    def test_register_with_phone_and_login(self):
        res = self.client.post(reverse("register"), {"phone": "90 123 45 67", "first_name": "Aziz", "last_name": "Karimov", "password": "Kuchli-parol7"})
        v = PhoneVerification.objects.get()
        self.assertRedirects(res, reverse("verify", args=[v.token]))
        self.assertFalse(User.objects.filter(username="998901234567").exists())
        self.assertContains(self.client.get(res.url), "t.me/test_bot?start=" + v.token)

        # Bot: /start <token> → kontakt so'raydi; boshqa raqam yuborilsa kod bermaydi
        self.assertIn("Raqamni yuborish", self._bot(f"/start {v.token}")[0])
        self.assertIn("+998911111111", self._bot(contact="+998911111111")[0])
        v.refresh_from_db()
        self.assertEqual(v.code, "")
        self._bot(contact="+998901234567")
        v.refresh_from_db()
        self.assertEqual(len(v.code), 6)

        # Noto'g'ri kod — hisob yaratilmaydi; to'g'ri kod — yaratiladi va kirgan bo'ladi
        wrong = "000000" if v.code != "000000" else "111111"
        self.assertContains(self.client.post(res.url, {"code": wrong}), "urinish qoldi")
        res = self.client.post(res.url, {"code": v.code})
        self.assertRedirects(res, reverse("scan"))
        user = User.objects.get(username="998901234567")
        self.assertEqual((user.first_name, user.last_name), ("Aziz", "Karimov"))
        self.assertTrue(user.check_password("Kuchli-parol7"))
        self.assertFalse(PhoneVerification.objects.exists())
        self.assertEqual(TelegramLink.objects.get(user=user).chat_id, 555)

        # Xuddi shu raqam bilan qayta ro'yxatdan o'tib bo'lmaydi
        self.client.logout()
        res = self.client.post(reverse("register"), {"phone": "+998901234567", "first_name": "X", "last_name": "Y", "password": "Kuchli-parol7"})
        self.assertTemplateUsed(res, "core/home.html")
        self.assertContains(res, "allaqachon")

    @override_settings(TELEGRAM_BOT_TOKEN="x", TELEGRAM_BOT_USERNAME="test_bot")
    def test_verify_link_is_bound_to_browser_and_rejects_foreign_contact(self):
        self.client.post(reverse("register"), {"phone": "901234567", "first_name": "Aziz", "last_name": "Karimov", "password": "Kuchli-parol7"})
        v = PhoneVerification.objects.get()
        other = self.client_class()
        self.assertRedirects(other.get(reverse("verify", args=[v.token])), reverse("home"))
        self._bot(f"/start {v.token}")
        # Birovning kontaktini yuborish (user_id boshqa) kod bermaydi
        self.assertIn("o'zingizning", self._bot(contact="+998901234567", contact_owner=999)[0])
        v.refresh_from_db()
        self.assertEqual(v.code, "")

    def test_register_errors_stay_on_home_page(self):
        res = self.client.post(reverse("register"), {"phone": "12345", "first_name": "", "last_name": "", "password": "12345678"})
        self.assertTemplateUsed(res, "core/home.html")
        form = res.context["reg_form"]
        self.assertEqual(set(form.errors), {"phone", "first_name", "last_name", "password"})
        self.assertContains(res, "Familiyangizni kiriting.")
        self.assertRedirects(self.client.get(reverse("register")), reverse("home"))

    def test_login_required_redirects_to_home_login_tab(self):
        res = self.client.get(reverse("dashboard"))
        self.assertRedirects(res, reverse("home") + "?next=/dashboard/")
        self.assertContains(self.client.get(res.url), 'name="next" value="/dashboard/"')

    def test_private_pages_require_login(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        self.assertEqual(self.client.get(reverse("tracker")).status_code, 302)

    def test_receipt_upload_confirm_and_application(self):
        self.client.force_login(self.user)
        buf = io.BytesIO()
        Image.new("RGB", (40, 40), "white").save(buf, "PNG")
        res = self.client.post(reverse("receipt_upload"), {"file": SimpleUploadedFile("chek.png", buf.getvalue(), "image/png")})
        data = res.json()
        self.assertIn("receipt_id", data)
        self.assertFalse(data["ok"])  # OCR dvigateli yo'q — qo'lda kiritish taklif qilinadi

        res = self.client.post(data["confirm_url"], {
            "amount": "12000000", "paid_at": "2026-02-03", "stir": "201122334",
            "organization": "TDIU", "category": "education",
        })
        self.assertRedirects(res, reverse("dashboard"))
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.status, Receipt.Status.CONFIRMED)
        self.assertEqual(receipt.refund, Decimal("1440000"))

        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "1 440 000")

        # Yil mingliklar ajratgichisiz chiqishi kerak, aks holda forma "2 026" yuboradi
        self.assertRegex(page.content.decode(), r'name="year" value="\d{4}"')

        res = self.client.post(reverse("application_create"), {"year": "2026"})
        app = RefundApplication.objects.get()
        self.assertRedirects(res, reverse("application_detail", args=[app.pk]))
        self.assertEqual(app.refund_amount, Decimal("1440000"))

    def test_audit_demo(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse("audit_demo"))
        st = Statement.objects.get()
        self.assertRedirects(res, reverse("audit_result", args=[st.pk]))
        self.assertContains(self.client.get(res.url), "1 440 000")

    def test_chat_offline(self):
        res = self.client.post(reverse("chat_api"), json.dumps({"message": "kontrakt 12 mln"}), content_type="application/json")
        self.assertIn("1 440 000", res.json()["reply"])
        self.assertFalse(res.json()["ai"])
        self.assertIn("tejaysiz", offline_reply("frilanserman, oyiga 15 mln"))


ALL_YES = {"official_income": True, "own_payment": True, "contract": True, "receipt": True, "licensed": True}


class CheckupTests(TestCase):
    def test_refund_capped_by_withheld_tax(self):
        # 2 mln oylik → yiliga 2 880 000 JShOD; 30 mln kontraktning 12% i = 3 600 000
        r = run_check(monthly_salary=2_000_000, payment=30_000_000, for_family=False, answers=ALL_YES)
        self.assertEqual(r.expected_refund, Decimal("3600000"))
        self.assertEqual(r.real_refund, Decimal("2880000"))
        self.assertTrue(r.capped)
        self.assertEqual(r.level, "low")

    def test_no_official_income_means_no_refund(self):
        r = run_check(monthly_salary=5_000_000, payment=12_000_000, for_family=True, answers={**ALL_YES, "official_income": False})
        self.assertEqual(r.real_refund, 0)
        self.assertEqual(r.level, "high")
        self.assertIn("Qarindoshlikni tasdiqlovchi hujjat nusxasi", r.documents)

    def test_checkup_page_parses_spaced_amounts(self):
        data = {"monthly_salary": "6 000 000", "payment": "12 000 000", **{k: "on" for k in ALL_YES}}
        res = self.client.post(reverse("checkup"), data)
        self.assertContains(res, "Rad etilish xavfi past")
        self.assertContains(res, som(1440000))


class TrackerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("998901112233", password="Parol-12345", first_name="Ali")
        self.app = RefundApplication.objects.create(user=self.user, year=2026, total_amount=12_000_000, refund_amount=1_440_000)
        self.client.force_login(self.user)

    def test_status_requires_submission_date(self):
        url = reverse("application_status", args=[self.app.pk])
        self.client.post(url, {f"a{self.app.pk}-status": "submitted"})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "draft")

    def test_overdue_application_gets_appeal_letter(self):
        url = reverse("application_status", args=[self.app.pk])
        self.client.post(url, {f"a{self.app.pk}-status": "in_review", f"a{self.app.pk}-submitted_at": "2026-01-10"})
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "in_review")
        page = self.client.get(reverse("tracker"))
        self.assertContains(page, "Tayyor murojaat xati")
        self.assertContains(page, "+998901112233")

    def test_other_users_application_is_hidden(self):
        other = User.objects.create_user("998909998877", password="Parol-12345")
        self.client.force_login(other)
        res = self.client.post(reverse("application_status", args=[self.app.pk]), {})
        self.assertEqual(res.status_code, 404)


@override_settings(TELEGRAM_BOT_TOKEN="x", TELEGRAM_BOT_USERNAME="test_bot")
class TelegramLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("998901234567", password="Kuchli-parol7", first_name="Aziz")

    def _bot(self, text=None, contact=None, chat_id=777):
        sent = []
        msg = {"chat": {"id": chat_id}, "from": {"id": chat_id}}
        if text:
            msg["text"] = text
        if contact:
            msg["contact"] = {"phone_number": contact, "user_id": chat_id}
        handle_update({"message": msg}, send=lambda chat, t, **kw: sent.append(t))
        return sent

    def test_login_button_opens_bot_and_contact_brings_code(self):
        # JS tugmasi: JSON bilan bot havolasi va kod sahifasi qaytadi, raqam saytda so'ralmaydi
        res = self.client.post(reverse("login_code"), HTTP_ACCEPT="application/json")
        v = PhoneVerification.objects.get()
        self.assertEqual(res.json(), {"bot_url": f"https://t.me/test_bot?start={v.token}",
                                      "verify_url": reverse("verify", args=[v.token])})
        self.assertIn("Raqamni yuborish", self._bot(f"/start {v.token}")[0])
        self._bot(contact="+998 90 123 45 67")
        v.refresh_from_db()
        self.assertEqual((v.phone, len(v.code)), ("998901234567", 6))

        res = self.client.post(reverse("verify", args=[v.token]), {"code": v.code})
        self.assertRedirects(res, reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertEqual(TelegramLink.objects.get(user=self.user).chat_id, 777)

    def test_new_number_signs_up_with_name_after_telegram_code(self):
        res = self.client.post(reverse("login_code"))
        v = PhoneVerification.objects.get()
        self.assertRedirects(res, reverse("verify", args=[v.token]))
        self._bot(f"/start {v.token}")
        reply = self._bot(contact="998909999999")[0]
        self.assertIn("Ro'yxatdan o'tish kodi", reply)
        v.refresh_from_db()

        # Kod to'g'ri, hisob yo'q → ism-familiya sahifasi
        res = self.client.post(reverse("verify", args=[v.token]), {"code": v.code})
        self.assertRedirects(res, reverse("signup_complete"))
        self.assertFalse(User.objects.filter(username="998909999999").exists())
        self.assertContains(self.client.get(res.url), "+998909999999")

        res = self.client.post(res.url, {"first_name": "", "last_name": ""})
        self.assertContains(res, "Ismingizni kiriting.")
        res = self.client.post(reverse("signup_complete"), {"first_name": "Vali", "last_name": "Aliyev"})
        self.assertRedirects(res, reverse("scan"))
        user = User.objects.get(username="998909999999")
        self.assertEqual((user.first_name, user.last_name), ("Vali", "Aliyev"))
        self.assertFalse(user.has_usable_password())
        self.assertEqual(TelegramLink.objects.get(user=user).chat_id, 777)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_complete_requires_verified_phone(self):
        res = self.client.get(reverse("signup_complete"))
        self.assertRedirects(res, reverse("home") + "#login", fetch_redirect_response=False)

    def test_next_is_kept_after_login(self):
        self.client.post(reverse("login_code"), {"next": "/tracker/"})
        v = PhoneVerification.objects.get()
        self._bot(f"/start {v.token}")
        self._bot(contact="998901234567")
        v.refresh_from_db()
        res = self.client.post(reverse("verify", args=[v.token]), {"code": v.code})
        self.assertRedirects(res, reverse("tracker"))

    def test_password_login_on_home_page(self):
        res = self.client.post(reverse("login"), {"username": "90 123 45 67", "password": "noto'g'ri"})
        self.assertTemplateUsed(res, "core/home.html")
        self.assertEqual(res.context["tab"], "login")
        self.assertIn("parol noto", res.context["login_form"].non_field_errors()[0])
        res = self.client.post(reverse("login"), {"username": "901234567", "password": "Kuchli-parol7", "next": "/tracker/"})
        self.assertRedirects(res, reverse("tracker"))
        self.assertRedirects(self.client.get(reverse("login")), reverse("dashboard"), fetch_redirect_response=False)


class SettingsAndLanguageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("998901112244", password="Eski-parol-77", first_name="Ali", last_name="Valiyev")
        self.client.force_login(self.user)

    def test_edit_profile(self):
        res = self.client.post(reverse("settings"), {"section": "profile", "first_name": "Vali", "last_name": "Aliyev"})
        self.assertRedirects(res, reverse("settings"))
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Vali", "Aliyev"))

    def test_change_password_keeps_session(self):
        res = self.client.post(reverse("settings"), {
            "section": "password", "old_password": "Eski-parol-77",
            "new_password1": "Yangi-parol-88", "new_password2": "Yangi-parol-88",
        })
        self.assertRedirects(res, reverse("settings"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Yangi-parol-88"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_telegram_only_user_can_set_password(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("settings")), 'name="new_password1"')
        self.assertNotContains(self.client.get(reverse("settings")), 'name="old_password"')
        self.client.post(reverse("settings"), {"section": "password", "new_password1": "Yangi-parol-88", "new_password2": "Yangi-parol-88"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Yangi-parol-88"))

    def test_preferences_switch_language_and_theme(self):
        res = self.client.post(reverse("settings"), {"section": "prefs", "language": "ru", "theme": "dark"})
        self.assertRedirects(res, reverse("settings"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assertEqual((self.user.profile.language, self.user.profile.theme), ("ru", "dark"))
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, '<html lang="ru" data-theme="dark">')
        self.assertContains(page, "Личный кабинет")
        # Til nomlari doim o'z tilida (Django ularni tarjima qilmasin)
        self.assertContains(page, ">English<")
        self.assertContains(page, ">O&#x27;zbekcha<")

    def test_nav_theme_toggle_saves_to_profile(self):
        self.client.get(reverse("dashboard"))  # profil yaratiladi
        self.client.post(reverse("save_theme"), {"theme": "light"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme, "light")

    def test_language_switcher_for_guests_and_users(self):
        self.client.logout()
        res = self.client.post(reverse("set_language"), {"language": "en", "next": "/pricing/"})
        self.assertRedirects(res, "/pricing/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/pricing/"), "Transparent pricing")
        # Kirgan foydalanuvchining tanlovi profilga yoziladi va boshqa qurilmada ham amal qiladi
        self.client.force_login(self.user)
        self.client.get(reverse("dashboard"))
        self.client.post(reverse("set_language"), {"language": "ru", "next": "/"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.language, "ru")
        other = self.client_class()
        other.force_login(self.user)
        self.assertContains(other.get(reverse("dashboard")), "Личный кабинет")

    def test_translations_keep_placeholders(self):
        from django.utils import translation
        for lang in ("ru", "en"):
            with translation.override(lang):
                self.assertIn("1 440 000", offline_reply("kontrakt 12 mln"))
                self.assertIn("21 600 000", offline_reply("frilanserman, oyiga 15 mln"))

    def test_percent_strings_are_translated(self):
        # {% translate %} dagi % li matnlar (Django ularni %% bilan qidiradi)
        self.client.logout()
        self.client.cookies["django_language"] = "ru"
        page = self.client.get(reverse("cashback"))
        self.assertContains(page, "Фрилансер 1%")
        self.assertNotContains(page, "Frilanser 1%")

    def test_logout_lives_in_settings_not_header(self):
        page = self.client.get(reverse("dashboard")).content.decode()
        header = page[page.index("<header"):page.index("</header>")]
        self.assertNotIn('action="/logout/"', header)
        self.assertNotIn('href="/dashboard/settings/" class="icon-btn', header)
        self.assertContains(self.client.get(reverse("settings")), 'action="/logout/"')
        res = self.client.post(reverse("logout"))
        self.assertRedirects(res, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)


class HomeSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("998901113355", password="Parol-12345", first_name="Umid")
        self.client.force_login(self.user)

    def _next(self):
        return self.client.get(reverse("home")).context["me"]["next"]

    def test_next_step_follows_user_progress(self):
        self.assertEqual(self._next()["url"], reverse("scan"))  # hali chek yo'q
        r = Receipt.objects.create(user=self.user, file="receipts/t.png", amount=12_000_000, paid_at=date(2026, 2, 3),
                                   category="education", status="pending")
        self.assertIn("#receipts", self._next()["url"])  # tasdiq kutmoqda
        r.status = "confirmed"
        r.save()
        self.assertEqual(self._next()["url"], reverse("dashboard"))  # ariza shakllantirish
        app = RefundApplication.objects.create(user=self.user, year=2026, total_amount=12_000_000, refund_amount=1_440_000)
        self.assertEqual(self._next()["url"], reverse("tracker"))  # yuborish
        app.status, app.submitted_at = "in_review", date(2026, 6, 1)
        app.save()
        page = self.client.get(reverse("home"))
        self.assertEqual(page.context["me"]["refund"], Decimal("1440000"))
        self.assertContains(page, "mini-steps")


class AuditExcludeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("998901114466", password="Parol-12345")
        self.client.force_login(self.user)
        self.client.post(reverse("audit_demo"))
        self.statement = Statement.objects.get()

    def test_excluding_match_updates_totals_and_application(self):
        page = self.client.get(reverse("audit_result", args=[self.statement.pk]))
        self.assertEqual(page.context["summary"]["refund"], Decimal("1440000"))
        uni = self.statement.matches.filter(stir="201122334").first()
        res = self.client.post(reverse("audit_toggle", args=[uni.pk]), {"include": "0"})
        self.assertTrue(res.json()["excluded"])
        self.assertEqual(res.json()["refund"], som(1440000 - uni.refund))
        # Chiqarilgan to'lov arizaga kirmaydi
        self.client.post(reverse("application_create"), {"year": res.json()["year"]})
        app = RefundApplication.objects.get()
        self.assertEqual(app.refund_amount, Decimal("1440000") - uni.refund)
        # Qayta yoqish mumkin
        self.assertFalse(self.client.post(reverse("audit_toggle", args=[uni.pk]), {"include": "1"}).json()["excluded"])

    def test_cannot_toggle_other_users_match(self):
        match = self.statement.matches.first()
        self.client.force_login(User.objects.create_user("998901114477", password="Parol-12345"))
        self.assertEqual(self.client.post(reverse("audit_toggle", args=[match.pk]), {"include": "0"}).status_code, 404)

    def test_payment_title_strips_noise(self):
        from .templatetags.money import payment_title
        self.assertEqual(payment_title("03.02.2025 14:05 Toshkent davlat iqtisodiyot universiteti STIR 201122334 6 500 000,00"),
                         "Toshkent davlat iqtisodiyot universiteti")
        self.assertEqual(payment_title("14-son davlat bog'cha (MTT)"), "14-son davlat bog'cha (MTT)")


class DashboardYearTests(TestCase):
    def test_formatted_or_bad_year_does_not_crash(self):
        user = User.objects.create_user("998901115577", password="Parol-12345")
        self.client.force_login(user)
        for value in ("2\u00a0026", "2 026", "abc", "20261"):
            self.assertEqual(self.client.get(reverse("dashboard"), {"year": value}).status_code, 200, value)
        self.assertEqual(self.client.get(reverse("dashboard"), {"year": "2\u00a0025"}).context["year"], 2025)

    def test_year_links_are_not_localized(self):
        user = User.objects.create_user("998901115588", password="Parol-12345")
        self.client.force_login(user)
        for y in (2025, 2026):
            Receipt.objects.create(user=user, file="r.png", amount=1_000_000, paid_at=date(y, 3, 1), category="education", status="confirmed")
        page = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('href="?year=2025"', page)
        self.assertNotIn("2\u00a0025", page)


class CheckupLiveTests(TestCase):
    def test_json_mode_returns_rendered_result(self):
        data = {"monthly_salary": "2 000 000", "payment": "30 000 000", "official_income": "on", "own_payment": "", "for_family": ""}
        res = self.client.post(reverse("checkup"), data, HTTP_ACCEPT="application/json")
        body = res.json()
        self.assertTrue(body["valid"])
        self.assertIn(som(2880000), body["html"])  # haqiqiy summa ushlangan soliq bilan cheklanadi
        self.assertIn("ck-ring", body["html"])

    def test_page_shows_yes_no_questions(self):
        page = self.client.get(reverse("checkup"))
        self.assertContains(page, 'name="official_income" value="on"')
        self.assertContains(page, 'name="official_income" value=""')
        self.assertContains(page, "Natija shu yerda chiqadi")

    def test_unanswered_questions_do_not_penalize(self):
        data = {"monthly_salary": "6 000 000", "payment": "12 000 000", "official_income": "on"}
        res = self.client.post(reverse("checkup"), data)
        result = res.context["result"]
        self.assertEqual(result.score, 100)
        self.assertEqual(result.unanswered, 4)
        self.assertContains(res, "natija taxminiy")
        # Aniq "Yo'q" javobi esa jarimaga kiradi
        res = self.client.post(reverse("checkup"), {**data, "own_payment": ""})
        self.assertEqual(res.context["result"].score, 70)


@override_settings(TELEGRAM_WEBHOOK_SECRET="maxfiy-kalit")
class TelegramWebhookTests(TestCase):
    def test_rejects_wrong_secret(self):
        res = self.client.post(reverse("telegram_webhook"), "{}", content_type="application/json",
                               HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="boshqa")
        self.assertEqual(res.status_code, 404)

    def test_passes_update_to_bot(self):
        from unittest import mock
        update = {"update_id": 1, "message": {"chat": {"id": 5}, "text": "/start"}}
        with mock.patch("core.views.telegram.handle_update") as handle:
            res = self.client.post(reverse("telegram_webhook"), json.dumps(update), content_type="application/json",
                                   HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="maxfiy-kalit")
        self.assertEqual(res.status_code, 200)
        handle.assert_called_once_with(update)


class BlobStorageTests(TestCase):
    def test_url_and_unique_names(self):
        from .storage import VercelBlobStorage
        st = VercelBlobStorage(token="vercel_blob_rw_AbC123_secretpart")
        name = st.get_available_name("receipts/2026/10/chek.jpg")
        self.assertRegex(name, r"^receipts/2026/10/chek-[\w-]{16}\.jpg$")
        self.assertEqual(st.url("receipts/a b.jpg"), "https://abc123.public.blob.vercel-storage.com/receipts/a%20b.jpg")
