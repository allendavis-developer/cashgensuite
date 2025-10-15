from django.contrib import admin
from .models import (
    Listing,
    ListingSnapshot,
    InventoryItem,
    Category,
    PawnShopAgreement,
    MarketItem,
    CompetitorListing,
    PriceAnalysis,
    MarginCategory,
    MarginRule,
    GlobalMarginRule,
)

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


class ListingSnapshotInline(admin.TabularInline):
    model = ListingSnapshot
    extra = 0
    readonly_fields = (
        "created_at",
        "market_average",
        "user_margin",
        "cex_avg",
        "cc_avg",
        "cg_avg",
        "reasoning",
    )
    fields = (
        "created_at",
        "market_average",
        "user_margin",
        "cex_avg",
        "cc_avg",
        "cg_avg",
        "reasoning",
    )
    show_change_link = True


# -----------------------------
# LISTING ADMIN
# -----------------------------
@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "item",
        "price",
        "platform",
        "branch",
        "is_active",
        "created_at",
    )
    list_filter = ("platform", "branch", "is_active", "created_at")
    search_fields = ("item__title", "title", "description", "platform", "branch")
    readonly_fields = ("created_at", "updated_at")
    inlines = [ListingSnapshotInline]
    ordering = ("-created_at",)

    fieldsets = (
        ("Item Info", {
            "fields": ("item", "title", "description", "price", "platform", "url")
        }),
        ("Status & Location", {
            "fields": ("branch", "is_active")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )


# -----------------------------
# SNAPSHOT ADMIN
# -----------------------------
@admin.register(ListingSnapshot)
class ListingSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "created_at",
        "market_average",
        "user_margin",
        "cex_avg",
        "cc_avg",
        "cg_avg",
    )
    list_filter = ("created_at",)
    search_fields = (
        "listing__item__title",
        "item_name",
        "reasoning",
        "listing__platform",
    )
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
