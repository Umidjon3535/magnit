"""Avto-Audit'ni sinash uchun NAMUNA PDF-hisobot yaratadi (haqiqiy hujjat emas).

Ishga tushirish:  .\\.venv\\Scripts\\python samples\\make_sample_statement.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).with_name("namuna_hisobot_2025.pdf")
FONTS = Path("C:/Windows/Fonts")
pdfmetrics.registerFont(TTFont("Arial", str(FONTS / "arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", str(FONTS / "arialbd.ttf")))

# (sana, vaqt, tavsif, STIR, summa) — mos va mos bo'lmagan to'lovlar aralash
ROWS = [
    ("05.01.2025", "09:14", "Beeline mobil aloqa", "", "50 000,00"),
    ("18.01.2025", "19:40", "Korzinka supermarket", "", "386 200,00"),
    ("03.02.2025", "14:05", "Toshkent davlat iqtisodiyot universiteti kontrakt", "201122334", "6 500 000,00"),
    ("14.02.2025", "12:30", "P2P o'tkazma 8600 **** 1234", "", "300 000,00"),
    ("02.03.2025", "08:30", "14-son davlat bog'cha (MTT)", "202233445", "950 000,00"),
    ("21.03.2025", "17:22", "Uzum Market buyurtma", "", "740 000,00"),
    ("02.04.2025", "08:31", "14-son davlat bog'cha (MTT)", "202233445", "950 000,00"),
    ("20.04.2025", "18:12", "Shifo-Med Медицинский центр MChJ", "305566778", "1 700 000,00"),
    ("11.05.2025", "10:03", "Hududgaz kommunal to'lov", "", "210 500,00"),
    ("02.06.2025", "08:29", "14-son davlat bog'cha (MTT)", "202233445", "950 000,00"),
    ("15.07.2025", "13:47", "Stomatologiya klinikasi Dental Plus", "306677889", "1 250 000,00"),
    ("28.08.2025", "20:10", "Evos restoran", "", "164 000,00"),
    ("01.09.2025", "11:15", "Toshkent davlat iqtisodiyot universiteti kontrakt", "201122334", "6 500 000,00"),
    ("05.09.2025", "07:55", "52-maktab to'garak to'lovi", "203344556", "400 000,00"),
    ("19.10.2025", "16:20", "Humans mobil aloqa", "", "60 000,00"),
    ("12.11.2025", "09:00", "Детская поликлиника №3 платные услуги", "307788990", "480 000,00"),
    ("24.12.2025", "15:35", "Texnomart xarid", "", "2 900 000,00"),
]


def main():
    c = canvas.Canvas(str(OUT), pagesize=A4)
    w, h = A4
    c.setTitle("NAMUNA - Xarajatlar hisoboti 2025 (test uchun)")

    # Suv belgisi
    c.saveState()
    c.setFont("Arial-Bold", 70)
    c.setFillColor(colors.Color(0.9, 0.2, 0.2, alpha=0.08))
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "NAMUNA · TEST")
    c.restoreState()

    c.setFillColor(colors.HexColor("#0fb37f"))
    c.rect(0, h - 80, w, 80, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Arial-Bold", 18)
    c.drawString(40, h - 45, "Payme — Xarajatlar hisoboti (NAMUNA)")
    c.setFont("Arial", 10)
    c.drawString(40, h - 63, "Davr: 01.01.2025 – 31.12.2025 · Test uchun yaratilgan soxta hujjat, haqiqiy emas")

    y = h - 115
    c.setFillColor(colors.black)
    c.setFont("Arial", 10)
    c.drawString(40, y, "Mijoz: Test Foydalanuvchi    Karta: 8600 **** **** 0000")
    y -= 30

    c.setFont("Arial-Bold", 9)
    for x, title in ((40, "Sana"), (120, "Tavsif"), (400, "STIR"), (555, "Summa, so'm")):
        if x == 555:
            c.drawRightString(x, y, title)
        else:
            c.drawString(x, y, title)
    y -= 6
    c.line(40, y, 555, y)
    y -= 16

    c.setFont("Arial", 9)
    total = 0
    for i, (d, t, desc, stir, amount) in enumerate(ROWS):
        if i % 2:
            c.setFillColor(colors.HexColor("#f2f4f8"))
            c.rect(36, y - 5, 523, 17, stroke=0, fill=1)
            c.setFillColor(colors.black)
        # Har bir qator bitta matn satri: PDF matn qatlami to'g'ri o'qilishi uchun
        c.drawString(40, y, f"{d} {t}")
        c.drawString(120, y, desc[:52])
        c.drawString(400, y, f"STIR {stir}" if stir else "")
        c.drawRightString(555, y, amount)
        total += int(amount.split(",")[0].replace(" ", ""))
        y -= 20

    y -= 6
    c.line(40, y, 555, y)
    y -= 18
    c.setFont("Arial-Bold", 10)
    c.drawString(40, y, "Davr bo'yicha jami xarajatlar:")
    c.drawRightString(555, y, f"{total:,}".replace(",", " ") + ",00")

    c.setFont("Arial", 8)
    c.setFillColor(colors.grey)
    c.drawString(40, 40, "Ushbu hujjat Magnit platformasining Avto-Audit funksiyasini sinash uchun yaratilgan. Haqiqiy bank hujjati emas.")
    c.save()
    print(OUT)


if __name__ == "__main__":
    main()
