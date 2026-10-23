from django.db import migrations

# Namuna tariflar. Haqiqiy tariflar tez-tez o'zgaradi — admin paneldan yangilang.
PROVIDERS = [
    ("Click", "click", 0, 0, 0.5, 50_000, "Ta'lim to'lovlari komissiyasiz (namuna tarif)", "#2a78d6"),
    ("Payme", "payme", 0, 0, 1.0, 100_000, "Keshbek oylik limit bilan (namuna tarif)", "#1baf7a"),
    ("Uzum Bank", "uzum", 0, 0, 1.5, 150_000, "Uzum kartasi bilan to'lovda (namuna tarif)", "#6250d6"),
    ("Anorbank", "anorbank", 0.5, 0, 2.0, 200_000, "Premium karta egalariga (namuna tarif)", "#e34948"),
    ("Zoomrad", "zoomrad", 0.3, 0, 1.0, None, "Limit yo'q (namuna tarif)", "#eb6834"),
]


def seed(apps, schema_editor):
    PaymentProvider = apps.get_model("core", "PaymentProvider")
    for name, slug, cp, cf, cb, cap, note, color in PROVIDERS:
        PaymentProvider.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "commission_percent": cp,
                "commission_fixed": cf,
                "cashback_percent": cb,
                "cashback_cap": cap,
                "note": note,
                "color": color,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("core", "PaymentProvider").objects.filter(slug__in=[p[1] for p in PROVIDERS]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
