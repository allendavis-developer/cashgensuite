from django.contrib import admin
from django import forms
from django.utils.html import format_html

from .models import (
    Listing,
    ListingSnapshot,
    InventoryItem,
    Category,
    MarketItem,
    CompetitorListing,
    CompetitorListingHistory,  # NEW
    MarginCategory,
    MarginRule,
    GlobalMarginRule,
    ItemModelAttributeValue,
    CEXPricingRule
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
    MarketItem, Category, CategoryAttribute, Subcategory, ItemModel
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
        
        # If subcategory is also set, filter further
        if 'subcategory' in self.data:
            try:
                subcategory_id = int(self.data.get('subcategory'))
                self.fields['model'].queryset = self.fields['model'].queryset.filter(
                    subcategory_id=subcategory_id
                )
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.subcategory:
            self.fields['model'].queryset = self.fields['model'].queryset.filter(
                subcategory=self.instance.subcategory
            )


@admin.register(MarketItem)
class MarketItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'model_name', 'last_scraped')
    list_filter = ('category',)
    search_fields = ('title',)
    inlines = [CompetitorListingInline]  

    def model_name(self, obj):
        if obj.item_model:
            return str(obj.item_model)
        return "-"
    model_name.short_description = "Item Model"


class CategoryAttributeInline(admin.TabularInline):
    model = CategoryAttribute
    extra = 1
    fields = ('name', 'label', 'field_type', 'required', 'options', 'order')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'base_margin', 'attribute_count', 'get_scrape_sources')
    inlines = [CategoryAttributeInline]
    search_fields = ('name',)
    list_filter = ('scrape_sources',)

    def get_scrape_sources(self, obj):
        """Display selected scrape sources as a comma-separated string."""
        return ", ".join(obj.scrape_sources) if obj.scrape_sources else "-"
    get_scrape_sources.short_description = "Scrape Sources"

    def attribute_count(self, obj):
        """Show how many custom attributes the category has."""
        return obj.attributes.count()
    attribute_count.short_description = 'Attributes'


class ItemModelInline(admin.TabularInline):
    model = ItemModel
    extra = 0
    readonly_fields = ("get_category", "get_subcategory")
    fields = ("name", "get_category", "get_subcategory")

    def get_category(self, obj):
        """Display the parent category (through subcategory)."""
        return obj.subcategory.category.name if obj.subcategory and obj.subcategory.category else "-"
    get_category.short_description = "Category"

    def get_subcategory(self, obj):
        """Display the subcategory name."""
        return obj.subcategory.name if obj.subcategory else "-"
    get_subcategory.short_description = "Subcategory"



@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
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
    list_display = ('name', 'get_category', 'subcategory')
    list_filter = ('subcategory__category', 'subcategory')
    search_fields = ('name', 'subcategory__name')
    inlines = [ItemModelAttributeValueInline]

    def get_category(self, obj):
        return obj.category
    get_category.admin_order_field = 'subcategory__category'  # allows column sorting
    get_category.short_description = 'Category'



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


from dal import autocomplete

class CEXPricingRuleForm(forms.ModelForm):
    class Meta:
        model = CEXPricingRule
        fields = '__all__'
        widgets = {
            'category': autocomplete.ModelSelect2(url='category-autocomplete'),
            'subcategory': autocomplete.ModelSelect2(url='subcategory-autocomplete', forward=['category']),
            'item_model': autocomplete.ModelSelect2(url='itemmodel-autocomplete', forward=['subcategory']),
        }


@admin.register(CEXPricingRule)
class CEXPricingRuleAdmin(admin.ModelAdmin):
    form = CEXPricingRuleForm
    list_display = ('__str__', 'category', 'subcategory', 'item_model', 'cex_pct', 'is_active')
    list_filter = ('is_active', 'category')
    search_fields = ('category__name', 'subcategory__name', 'item_model__name', 'description')
    ordering = ('category', 'subcategory', 'item_model',)

class CategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Category.objects.all()
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs

class SubcategoryAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Subcategory.objects.all()
        category_id = self.forwarded.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs

class ItemModelAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = ItemModel.objects.all()
        subcat_id = self.forwarded.get('subcategory', None)
        if subcat_id:
            qs = qs.filter(subcategory_id=subcat_id)
        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs
