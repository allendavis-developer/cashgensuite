"""
Django admin configuration for the new models in models_v2.py.

This module registers all the new pricing models with the Django admin interface,
separate from the existing admin.py to maintain clear separation.
"""

from django.contrib import admin
from django.utils.html import format_html
from .models_v2 import (
    ProductCategory,
    Product,
    Attribute,
    AttributeValue,
    ConditionGrade,
    Variant,
    VariantAttributeValue,
    VariantPriceHistory,
    VariantStatus,
)


# -------------------------------
# PRODUCT CATEGORY ADMIN
# -------------------------------

@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent_category', 'product_count', 'attribute_count')
    list_filter = ('parent_category',)
    search_fields = ('name',)
    autocomplete_fields = ['parent_category']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('parent_category').prefetch_related('products', 'attributes')
    
    def product_count(self, obj):
        """Show how many products are in this category."""
        return obj.products.count()
    product_count.short_description = 'Products'
    
    def attribute_count(self, obj):
        """Show how many attributes are defined for this category."""
        return obj.attributes.count()
    attribute_count.short_description = 'Attributes'


# -------------------------------
# PRODUCT ADMIN
# -------------------------------

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'variant_count')
    list_filter = ('category',)
    search_fields = ('name', 'category__name')
    autocomplete_fields = ['category']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('category').prefetch_related('variants')
    
    def variant_count(self, obj):
        """Show how many variants exist for this product."""
        return obj.variants.count()
    variant_count.short_description = 'Variants'


# -------------------------------
# ATTRIBUTE ADMIN
# -------------------------------

@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = ('code', 'category', 'value_count')
    list_filter = ('category',)
    search_fields = ('code', 'category__name')
    autocomplete_fields = ['category']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('category').prefetch_related('values')
    
    def value_count(self, obj):
        """Show how many values are defined for this attribute."""
        return obj.values.count()
    value_count.short_description = 'Values'


# -------------------------------
# ATTRIBUTE VALUE ADMIN
# -------------------------------

@admin.register(AttributeValue)
class AttributeValueAdmin(admin.ModelAdmin):
    list_display = ('value', 'attribute', 'variant_count')
    list_filter = ('attribute__category', 'attribute')
    search_fields = ('value', 'attribute__code', 'attribute__category__name')
    autocomplete_fields = ['attribute']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('attribute__category').prefetch_related('variants')
    
    def variant_count(self, obj):
        """Show how many variants use this attribute value."""
        return obj.variants.count()
    variant_count.short_description = 'Variants'


# -------------------------------
# CONDITION GRADE ADMIN
# -------------------------------

@admin.register(ConditionGrade)
class ConditionGradeAdmin(admin.ModelAdmin):
    list_display = ('code', 'variant_count')
    search_fields = ('code',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('variants')
    
    def variant_count(self, obj):
        """Show how many variants use this condition grade."""
        return obj.variants.count()
    variant_count.short_description = 'Variants'


# -------------------------------
# VARIANT ATTRIBUTE VALUE INLINE
# -------------------------------

class VariantAttributeValueInline(admin.TabularInline):
    """Inline for managing attribute values on a variant."""
    model = VariantAttributeValue
    extra = 1
    autocomplete_fields = ['attribute_value']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('attribute_value__attribute')


# -------------------------------
# VARIANT PRICE HISTORY INLINE
# -------------------------------

class VariantPriceHistoryInline(admin.TabularInline):
    """Inline for viewing price history (read-only, append-only)."""
    model = VariantPriceHistory
    extra = 0
    readonly_fields = ('price_gbp', 'recorded_at')
    fields = ('price_gbp', 'recorded_at')
    ordering = ('-recorded_at',)
    can_delete = False
    max_num = 20  # Limit to most recent 20 entries
    
    def has_add_permission(self, request, obj=None):
        # Price history should be managed programmatically, not through admin
        return False


# -------------------------------
# VARIANT STATUS INLINE
# -------------------------------

class VariantStatusInline(admin.TabularInline):
    """Inline for viewing status history."""
    model = VariantStatus
    extra = 0
    readonly_fields = ('status', 'effective_from')
    fields = ('status', 'effective_from')
    ordering = ('-effective_from',)
    can_delete = False
    max_num = 10  # Limit to most recent 10 entries


# -------------------------------
# VARIANT ADMIN
# -------------------------------

@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = (
        'cex_sku',
        'title',
        'product',
        'condition_grade',
        'current_price_gbp',
        'variant_signature',
        'attribute_summary',
    )
    list_filter = ('condition_grade', 'product__category')
    search_fields = ('cex_sku', 'title', 'product__name', 'variant_signature')
    readonly_fields = ('variant_signature',)
    autocomplete_fields = ['product', 'condition_grade']
    inlines = [
        VariantAttributeValueInline,
        VariantPriceHistoryInline,
        VariantStatusInline,
    ]
    
    fieldsets = (
        ('Identity', {
            'fields': ('cex_sku', 'product', 'condition_grade', 'variant_signature')
        }),
        ('Listing Info', {
            'fields': ('title',)
        }),
        ('Pricing', {
            'fields': ('current_price_gbp',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            'product__category',
            'condition_grade'
        ).prefetch_related('variant_attribute_values__attribute_value__attribute')
    
    def attribute_summary(self, obj):
        """Display a summary of attribute values for this variant."""
        attr_values = obj.variant_attribute_values.select_related(
            'attribute_value__attribute'
        ).all()
        if not attr_values:
            return "-"
        parts = []
        for vav in attr_values:
            attr = vav.attribute_value.attribute
            value = vav.attribute_value.value
            parts.append(f"{attr.code}={value}")
        return ", ".join(parts)
    attribute_summary.short_description = 'Attributes'


# -------------------------------
# VARIANT ATTRIBUTE VALUE ADMIN (standalone)
# -------------------------------

@admin.register(VariantAttributeValue)
class VariantAttributeValueAdmin(admin.ModelAdmin):
    list_display = ('variant', 'attribute_value', 'get_attribute', 'get_category')
    list_filter = ('attribute_value__attribute__category', 'attribute_value__attribute')
    search_fields = (
        'variant__cex_sku',
        'variant__product__name',
        'attribute_value__value',
        'attribute_value__attribute__code'
    )
    autocomplete_fields = ['variant', 'attribute_value']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            'variant__product',
            'attribute_value__attribute__category'
        )
    
    def get_attribute(self, obj):
        """Display the attribute code."""
        return obj.attribute_value.attribute.code
    get_attribute.short_description = 'Attribute'
    get_attribute.admin_order_field = 'attribute_value__attribute__code'
    
    def get_category(self, obj):
        """Display the category this attribute belongs to."""
        return obj.attribute_value.attribute.category.name
    get_category.short_description = 'Category'
    get_category.admin_order_field = 'attribute_value__attribute__category__name'


# -------------------------------
# VARIANT PRICE HISTORY ADMIN (standalone)
# -------------------------------

@admin.register(VariantPriceHistory)
class VariantPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('variant', 'price_gbp', 'recorded_at', 'price_change')
    list_filter = ('recorded_at',)
    search_fields = ('variant__cex_sku', 'variant__product__name')
    readonly_fields = ('variant', 'price_gbp', 'recorded_at')
    autocomplete_fields = ['variant']
    ordering = ('-recorded_at',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('variant__product', 'variant__condition_grade')
    
    def price_change(self, obj):
        """Show price change from previous entry."""
        previous = VariantPriceHistory.objects.filter(
            variant=obj.variant,
            recorded_at__lt=obj.recorded_at
        ).order_by('-recorded_at').first()
        
        if previous:
            change = obj.price_gbp - previous.price_gbp
            if change > 0:
                return format_html(
                    '<span style="color: green;">+£{:.2f}</span>',
                    change
                )
            elif change < 0:
                return format_html(
                    '<span style="color: red;">£{:.2f}</span>',
                    change
                )
            else:
                return "No change"
        return "-"
    price_change.short_description = 'Change'
    
    def has_add_permission(self, request):
        # Price history should be managed programmatically
        return False
    
    def has_change_permission(self, request, obj=None):
        # Price history is append-only
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Price history should not be deleted
        return False


# -------------------------------
# VARIANT STATUS ADMIN (standalone)
# -------------------------------

@admin.register(VariantStatus)
class VariantStatusAdmin(admin.ModelAdmin):
    list_display = ('variant', 'status', 'effective_from')
    list_filter = ('status', 'effective_from')
    search_fields = ('variant__cex_sku', 'variant__product__name')
    autocomplete_fields = ['variant']
    ordering = ('-effective_from',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('variant__product', 'variant__condition_grade')
    
    def get_readonly_fields(self, request, obj=None):
        if obj:
            # Don't allow editing existing status records
            return ['variant', 'status', 'effective_from']
        return ['effective_from']
    
    def has_delete_permission(self, request, obj=None):
        # Status history should generally not be deleted
        return False


# -------------------------------
# UNREGISTER OLD MODELS
# -------------------------------
# Hide old models from admin to avoid confusion with new v2 models

try:
    from .models import (
        Listing,
        ListingSnapshot,
        InventoryItem,
        Category,
        MarketItem,
        CompetitorListing,
        CompetitorListingHistory,
        MarginCategory,
        MarginRule,
        GlobalMarginRule,
        ItemModelAttributeValue,
        CEXPricingRule,
        CategoryAttribute,
        Subcategory,
        ItemModel,
    )
    
    # Unregister all old models
    if admin.site.is_registered(Listing):
        admin.site.unregister(Listing)
    if admin.site.is_registered(ListingSnapshot):
        admin.site.unregister(ListingSnapshot)
    if admin.site.is_registered(InventoryItem):
        admin.site.unregister(InventoryItem)
    if admin.site.is_registered(Category):
        admin.site.unregister(Category)
    if admin.site.is_registered(MarketItem):
        admin.site.unregister(MarketItem)
    if admin.site.is_registered(CompetitorListing):
        admin.site.unregister(CompetitorListing)
    if admin.site.is_registered(CompetitorListingHistory):
        admin.site.unregister(CompetitorListingHistory)
    if admin.site.is_registered(MarginCategory):
        admin.site.unregister(MarginCategory)
    if admin.site.is_registered(MarginRule):
        admin.site.unregister(MarginRule)
    if admin.site.is_registered(GlobalMarginRule):
        admin.site.unregister(GlobalMarginRule)
    if admin.site.is_registered(ItemModelAttributeValue):
        admin.site.unregister(ItemModelAttributeValue)
    if admin.site.is_registered(CEXPricingRule):
        admin.site.unregister(CEXPricingRule)
    if admin.site.is_registered(Subcategory):
        admin.site.unregister(Subcategory)
    if admin.site.is_registered(ItemModel):
        admin.site.unregister(ItemModel)
except ImportError:
    # If old models don't exist, that's fine
    pass
except Exception:
    # If unregistering fails for any reason, continue anyway
    pass
