from django.contrib import admin
from django import forms
from django.utils.html import format_html

from .models import (
    Listing,
    ListingSnapshot,
    InventoryItem,
    Category,
    PawnShopAgreement,
    MarketItem,
    CompetitorListing,
    CompetitorListingHistory,  # NEW
    PriceAnalysis,
    MarginCategory,
    MarginRule,
    GlobalMarginRule,
    ItemModelAttributeValue
)

# -------------------------------
# SCRAPED MARKET DATA ADMIN
# -------------------------------

class CompetitorListingHistoryInline(admin.TabularInline):
    model = CompetitorListingHistory
    extra = 0
    readonly_fields = ("price", "title", "condition", "timestamp")
    ordering = ("-timestamp",)
    can_delete = False


class CompetitorListingInline(admin.TabularInline):
    model = CompetitorListing
    extra = 0
    readonly_fields = (
        "competitor",
        "store_name",
        "stable_id",
        "title",
        "price",
        "url",
        "condition",
        "description",
        "is_active",
        "last_seen",
    )
    fields = (
        "competitor",
        "store_name",
        "stable_id",
        "title",
        "price",
        "url",
        "condition",
        "is_active",
        "last_seen",
    )
    show_change_link = True
    can_delete = False


@admin.register(CompetitorListing)
class CompetitorListingAdmin(admin.ModelAdmin):
    list_display = (
        "competitor",
        "market_item",
        "title",
        "price",
        "store_name",
        "is_active",
        "last_seen",
    )
    list_filter = ("competitor", "is_active", "store_name")
    search_fields = ("title", "market_item__title", "store_name", "stable_id")
    readonly_fields = (
        "competitor",
        "market_item",
        "stable_id",
        "store_name",
        "title",
        "price",
        "url",
        "condition",
        "description",
        "is_active",
        "last_seen",
    )
    ordering = ("-last_seen",)
    inlines = [CompetitorListingHistoryInline]

    def has_add_permission(self, request):
        return False  # scraped only

    def has_change_permission(self, request, obj=None):
        return False  # read-only


from .models import (
    MarketItem, Category, CategoryAttribute, Manufacturer, ItemModel
)

class MarketItemForm(forms.ModelForm):
    class Meta:
        model = MarketItem
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # If category is set, filter models to only that category
        if 'category' in self.data:
            try:
                category_id = int(self.data.get('category'))
                self.fields['model'].queryset = ItemModel.objects.filter(category_id=category_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.category:
            self.fields['model'].queryset = ItemModel.objects.filter(category=self.instance.category)
        else:
            self.fields['model'].queryset = ItemModel.objects.none()
        
        # If manufacturer is also set, filter further
        if 'manufacturer' in self.data:
            try:
                manufacturer_id = int(self.data.get('manufacturer'))
                self.fields['model'].queryset = self.fields['model'].queryset.filter(
                    manufacturer_id=manufacturer_id
                )
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.manufacturer:
            self.fields['model'].queryset = self.fields['model'].queryset.filter(
                manufacturer=self.instance.manufacturer
            )

class ItemModelAttributeValueInlineFromMarketItem(admin.StackedInline):
    model = ItemModelAttributeValue
    extra = 0
    can_delete = False
    verbose_name = "Model Attribute"
    verbose_name_plural = "Model Attributes"

    # Only allow editing if there is a parent object with a model
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if hasattr(self, 'parent_object') and self.parent_object.item_model:
            return qs.filter(item_model=self.parent_object.item_model).order_by('attribute__order')
        return qs.none()

    def has_add_permission(self, request, obj=None):
        # No adding from MarketItemAdmin
        return False

    def has_delete_permission(self, request, obj=None):
        # No deletion from MarketItemAdmin
        return False

    def has_change_permission(self, request, obj=None):
        # Optional: allow editing values from MarketItemAdmin
        return obj and obj.model is not None



@admin.register(MarketItem)
class MarketItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'model_name', 'model_attributes', 'last_scraped')
    list_filter = ('category',)
    search_fields = ('title',)
    readonly_fields = ('model_attributes',)
    inlines = [CompetitorListingInline]  

    def model_name(self, obj):
        if obj.item_model:
            return str(obj.item_model)
        return "-"
    model_name.short_description = "Item Model"

    def model_attributes(self, obj):
        if not obj.item_model:
            return "-"
        lines = [f"<strong>{av.attribute.label}:</strong> {av.get_display_value()}" 
                for av in obj.item_model.attribute_values.all()]
        return format_html("<br>".join(lines))
    model_attributes.short_description = "Model Attributes"

    model_attributes.short_description = "Model Attributes"

class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 1
    fields = ('name', 'label', 'field_type', 'required', 'options', 'order')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_margin', 'attribute_count')
    inlines = [CategoryAttributeInline]
    
    def attribute_count(self, obj):
        return obj.attributes.count()
    attribute_count.short_description = 'Attributes'


class ItemModelInline(admin.TabularInline):
    model = ItemModel
    extra = 1
    fields = ('category', 'name')


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name', 'model_count')
    search_fields = ('name',)
    inlines = [ItemModelInline]
    
    def model_count(self, obj):
        return obj.models.count()
    model_count.short_description = 'Models'

class ItemModelAttributeValueForm(forms.ModelForm):
    class Meta:
        model = ItemModelAttributeValue
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        attribute = getattr(self.instance, 'attribute', None)
        if attribute:
            field_type = attribute.field_type
            options = getattr(attribute, 'options', []) or []

            # Hide all value fields first
            for field_name in ['value_text', 'value_number', 'value_boolean']:
                if field_name in self.fields:
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.fields[field_name].required = False

            # Show only the relevant field based on attribute type
            if field_type == 'select' and options:
                if 'value_text' in self.fields:
                    self.fields['value_text'].widget = forms.Select(
                        choices=[('', '---')] + [(opt, opt) for opt in options]
                    )
                    self.fields['value_text'].required = attribute.required
            elif field_type == 'number':
                if 'value_number' in self.fields:
                    self.fields['value_number'].widget = forms.NumberInput()
                    self.fields['value_number'].required = attribute.required
            elif field_type == 'boolean':
                if 'value_boolean' in self.fields:
                    self.fields['value_boolean'].widget = forms.CheckboxInput()
                    self.fields['value_boolean'].required = False  # Checkboxes are never "required"
            else:  # text, default
                if 'value_text' in self.fields:
                    self.fields['value_text'].widget = forms.TextInput()
                    self.fields['value_text'].required = attribute.required


class ItemModelAttributeValueInline(admin.StackedInline):
    model = ItemModelAttributeValue
    extra = 0
    form = ItemModelAttributeValueForm
    
    def get_fields(self, request, obj=None):
        # Dynamically show only relevant value field based on attribute type
        base_fields = ['item_model', 'attribute']
        
        if obj and hasattr(obj, 'attribute') and obj.attribute:
            field_type = obj.attribute.field_type
            if field_type == 'select' or field_type == 'text':
                return base_fields + ['value_text']
            elif field_type == 'number':
                return base_fields + ['value_number']
            elif field_type == 'boolean':
                return base_fields + ['value_boolean']
        
        # Default: show all fields (for new items without attribute selected yet)
        return base_fields + ['value_text', 'value_number', 'value_boolean']

@admin.register(ItemModel)
class ItemModelAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'category', 'manufacturer')
    list_filter = ('category', 'manufacturer')
    search_fields = ('name', 'manufacturer__name')
    inlines = [ItemModelAttributeValueInline]


# -------------------------------
# SHOP INVENTORY ADMIN
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
    list_display = ("item", "suggested_price", "confidence", "created_at")
    list_filter = ("confidence", "created_at")
    search_fields = ("item__title", "reasoning")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


class PriceAnalysisInline(admin.TabularInline):
    model = PriceAnalysis
    extra = 0
    readonly_fields = ("reasoning", "suggested_price", "confidence", "created_at")
    can_delete = False


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status",
        "category",
        "buyback_price",
        "suggested_price",
        "final_listing_price",
        "updated_at",
    )
    list_filter = ("status", "category")
    search_fields = ("title", "serial_number")
    inlines = [PriceAnalysisInline]


@admin.register(MarginRule)
class MarginRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "rule_type", "match_value", "adjustment", "is_active")
    list_filter = ("rule_type", "is_active", "category")
    search_fields = ("match_value", "description")
    ordering = ("category", "order")


# -----------------------------
# LISTING ADMIN
# -----------------------------

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
