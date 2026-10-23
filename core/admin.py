from django.contrib import admin

from .models import PaymentProvider, Receipt, RefundApplication, Statement, StatementMatch


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "amount", "paid_at", "category", "status", "ocr_engine", "created_at")
    list_filter = ("status", "category", "ocr_engine")
    search_fields = ("organization", "stir", "user__username")


class StatementMatchInline(admin.TabularInline):
    model = StatementMatch
    extra = 0


@admin.register(Statement)
class StatementAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "source", "engine", "created_at")
    inlines = [StatementMatchInline]


@admin.register(PaymentProvider)
class PaymentProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "commission_percent", "commission_fixed", "cashback_percent", "cashback_cap", "is_active", "updated_at")
    list_editable = ("commission_percent", "commission_fixed", "cashback_percent", "cashback_cap", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(RefundApplication)
class RefundApplicationAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "year", "total_amount", "refund_amount", "status", "created_at")
    list_filter = ("status", "year")
