from django.contrib import admin
from .models import MarketItem, CompetitorListing, Category, InventoryItem, PriceAnalysis, PawnShopAgreement, MarginRule, Category

# -------------------------------
# Scraped Market Data Admin
# -------------------------------

class CompetitorListingInline(admin.TabularInline):
    model = CompetitorListing
    extra = 0
    readonly_fields = ("competitor", "title", "price", "url", "timestamp", "store_name", "description")
    can_delete = False


@admin.register(MarketItem)
class MarketItemAdmin(admin.ModelAdmin):
    list_display = ("title",)
    search_fields = ("title",)
    readonly_fields = ("title",)
    inlines = [CompetitorListingInline]

    def has_add_permission(self, request):
        return False  # disable adding

    def has_change_permission(self, request, obj=None):
        return False  # disable editing


# -------------------------------
# Shop Inventory Admin
# -------------------------------


class InventoryItemInline(admin.TabularInline):
    model = InventoryItem
    extra = 0
    readonly_fields = (
        "title",
        "serial_number",
        "buyback_price",
        "suggested_price",
        "final_listing_price",
        "status",
        "created_at",
        "updated_at",
    )

    can_delete = False


@admin.register(PawnShopAgreement)
class PawnShopAgreementAdmin(admin.ModelAdmin):
    list_display = ("agreement_number", "customer", "created_date", "expiry_date", "created_by")
    search_fields = ("agreement_number", "customer", "created_by")
    inlines = [InventoryItemInline]

@admin.register(PriceAnalysis)
class PriceAnalysisAdmin(admin.ModelAdmin):
    list_display = ('item', 'suggested_price', 'confidence', 'created_at')
    list_filter = ('confidence', 'created_at')
    search_fields = ('item__title', 'reasoning')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)

class PriceAnalysisInline(admin.TabularInline):
    model = PriceAnalysis
    extra = 0
    readonly_fields = ("reasoning", "suggested_price", "confidence", "created_at")
    can_delete = False

@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "category", "buyback_price", "suggested_price", "final_listing_price", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("title", "serial_number")
    inlines = [PriceAnalysisInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "base_margin", "description")
    search_fields = ("name",)
    ordering = ("name",)

@admin.register(MarginRule)
class MarginRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "rule_type", "match_value", "adjustment", "is_active")
    list_filter = ("rule_type", "is_active", "category")
    search_fields = ("match_value", "description")
    ordering = ("category", "order")

