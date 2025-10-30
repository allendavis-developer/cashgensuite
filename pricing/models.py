from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from multiselectfield import MultiSelectField

# -------------------------------
# SCRAPED MARKET DATA
# -------------------------------

class Subcategory(models.Model):
    name = models.CharField(max_length=100, unique=True)

    category = models.ForeignKey(
        'Category',
        on_delete=models.CASCADE,
        related_name='subcategories'
    )


    def __str__(self):
        return self.name


class Category(models.Model):
    SCRAPE_SOURCES = [
        ("CEX", "CEX"),
        ("eBay", "eBay"),
        ("CashConverters", "CashConverters"),
        ("CashGenerator", "CashGenerator"),
    ]

    scrape_sources = MultiSelectField(
        choices=SCRAPE_SOURCES,
        blank=True,
        max_length=200,
        help_text="Select which competitor sites to scrape for this category."
    )

    name = models.CharField(max_length=100, unique=True)
    base_margin = models.FloatField(default=0.0)
    description = models.TextField(blank=True)
    metadata = models.JSONField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.base_margin * 100:.0f}%)"


class CategoryAttribute(models.Model):
    """Defines what extra attributes a category has (storage, color, etc.)"""
    FIELD_TYPES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('select', 'Select'),
        ('boolean', 'Boolean'),
    ]

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='attributes')
    name = models.CharField(max_length=100, help_text="e.g. 'storage'")
    label = models.CharField(max_length=255, help_text="e.g. 'Storage Capacity'")
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    required = models.BooleanField(default=True)
    options = models.JSONField(blank=True, null=True, help_text="For 'select' type: ['64GB','128GB']")
    order = models.IntegerField(default=0)

    class Meta:
        unique_together = ('category', 'name')
        ordering = ['order']

    def __str__(self):
        return f"{self.category.name} - {self.label}"

class ItemModel(models.Model):
    """e.g. Apple iPhone 15 (in Smartphones category)"""
    subcategory = models.ForeignKey(Subcategory, on_delete=models.CASCADE, related_name='models')
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ('subcategory', 'name')

    @property
    def category(self):
        return self.subcategory.category

    def __str__(self):
        return f"{self.subcategory.name} {self.name}"

class ItemModelAttributeValue(models.Model):
    """Stores the canonical attribute values for each ItemModel."""
    item_model = models.ForeignKey(ItemModel, on_delete=models.CASCADE, related_name='attribute_values')
    attribute = models.ForeignKey(CategoryAttribute, on_delete=models.CASCADE)
    value_text = models.CharField(max_length=255, blank=True, null=True)
    value_number = models.FloatField(blank=True, null=True)
    value_boolean = models.BooleanField(default=False)

    class Meta:
        unique_together = ('item_model', 'attribute')

    def __str__(self):
        return f"{self.item_model} - {self.attribute.label}"

    def get_display_value(self):
        if self.attribute.field_type in ['text', 'select']:
            return self.value_text or ''
        elif self.attribute.field_type == 'number':
            return str(self.value_number) if self.value_number is not None else ''
        elif self.attribute.field_type == 'boolean':
            return 'Yes' if self.value_boolean else 'No'
        return ''


class MarketItem(models.Model):
    """The main item"""
    title = models.CharField(max_length=255)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="market_items"
    )
    last_scraped = models.DateTimeField(blank=True, null=True)
    exclude_keywords = models.JSONField(blank=True, null=True)
    item_model = models.ForeignKey(ItemModel, on_delete=models.SET_NULL, null=True, blank=True, related_name='market_items')


    # Optional helper property for convenience
    @property
    def model(self):
        """Return the first ItemModel in the category if exists"""
        return getattr(self, "_cached_model", None)

    def __str__(self):
        return self.title



class CompetitorListing(models.Model):
    COMPETITOR_CHOICES = [
        ("CeX", "CeX"),
        ("CashConverters", "CashConverters"),
        ("CashGenerator", "CashGenerator"),
        ("eBay", "eBay"),
    ]

    market_item = models.ForeignKey("MarketItem", on_delete=models.CASCADE, related_name="listings")
    competitor = models.CharField(max_length=50, choices=COMPETITOR_CHOICES)
    stable_id = models.CharField(max_length=100, db_index=True)  # competitor-specific unique identifier
    store_name = models.CharField(max_length=255, blank=True, null=True)
    url = models.URLField(blank=True, null=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    condition = models.CharField(max_length=255, blank=True, null=True)
    price = models.FloatField()
    is_active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("market_item", "competitor", "stable_id")

    def __str__(self):
        return f"{self.competitor} - {self.title} (£{self.price})"


class CompetitorListingHistory(models.Model):
    listing = models.ForeignKey(CompetitorListing, on_delete=models.CASCADE, related_name="history")
    price = models.FloatField()
    title = models.CharField(max_length=255)
    condition = models.CharField(max_length=255, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.listing.competitor} ({self.timestamp:%Y-%m-%d %H:%M})"


# -------------------------------
# SHOP INVENTORY
# -------------------------------

class PawnShopAgreement(models.Model):
    agreement_number = models.CharField(max_length=50, unique=True)
    created_date = models.DateField()
    expiry_date = models.DateField()
    previous_agreements = models.TextField(blank=True, null=True)#
    description = models.TextField(blank=True, null=True)
    created_by = models.CharField(max_length=100)
    customer = models.CharField(max_length=255)
    days_gone_past_expiry = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Agreement {self.agreement_number} - {self.customer}"


class InventoryItem(models.Model):
    STATUS_CHOICES = [
        ("buyback_storage", "Buyback Storage"),
        ("free_stock", "Free Stock"),
        ("sold", "Sold"),
        ("reserved", "Reserved"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_items")
    serial_number = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="buyback_storage")
    buyback_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    suggested_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    final_listing_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    agreement = models.ForeignKey(
        PawnShopAgreement,
        on_delete=models.CASCADE,
        related_name="inventory_items",
        blank=True,
        null=True
    )

    market_item = models.ForeignKey(
        MarketItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_items"
    )


    def __str__(self):
        return f"{self.title} ({self.status})"


class PriceAnalysis(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name="price_analyses")
    reasoning = models.TextField()
    suggested_price = models.DecimalField(max_digits=10, decimal_places=2)#
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  # <-- new field
    confidence = models.PositiveIntegerField(default=0)  # 0-100%
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Analysis for {self.item.title} - £{self.suggested_price}"


# -- Web listing
class Listing(models.Model):
    item = models.OneToOneField(
        'InventoryItem',
        on_delete=models.CASCADE,
        related_name='listing',
        help_text="The inventory item currently listed for sale"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    platform = models.CharField(max_length=100, blank=True, help_text="Where this item is listed, e.g. eBay, Website, etc.")
    url = models.URLField(blank=True, null=True)
    branch = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Listing for {self.item.title} - £{self.price}"


class ListingSnapshot(models.Model):
    listing = models.ForeignKey(
        'Listing',
        on_delete=models.CASCADE,
        related_name='snapshots',
        help_text="The listing this snapshot belongs to"
    )

    item_name = models.CharField(max_length=255)
    description = models.TextField()
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    user_margin = models.DecimalField(max_digits=5, decimal_places=2, default=37.5)
    market_range = models.CharField(max_length=50, blank=True)
    market_average = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    cex_avg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cex_discounted = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rrp_with_margin = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    cc_lowest = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cc_avg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cg_lowest = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cg_avg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    cc_recommended_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cg_recommended_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    reasoning = models.TextField(blank=True)
    competitors = models.JSONField(blank=True, default=list)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Snapshot for {self.listing.item.title} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


# BUYING MARGINS
class MarginCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)  # e.g., "Smartphones", "DIY/Drills"
    base_margin = models.FloatField()  # 0.30 for 30%
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.base_margin*100:.1f}%)"

class MarginRule(models.Model):
    RULE_TYPES = [
        ('subcategory', 'Subcategory'),
        ('model', 'Model'),
    ]

    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='rules')
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)
    match_value = models.CharField(max_length=100)

    adjustment = models.FloatField()
    description = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'order', 'rule_type']

    def __str__(self):
        sign = '+' if self.adjustment >= 0 else ''
        return f"{self.category.name} - {self.rule_type}: {self.match_value} ({sign}{self.adjustment * 100:.1f}%)"


class GlobalMarginRule(models.Model):
    RULE_TYPES = [
        ('condition', 'Condition'),
        ('demand', 'Demand'),
    ]

    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)
    match_value = models.CharField(max_length=100)
    adjustment = models.FloatField(help_text="e.g. 0.10 for +10%, -0.05 for -5%")
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def __str__(self):
        sign = '+' if self.adjustment >= 0 else ''
        return f"Global {self.rule_type}: {self.match_value} ({sign}{self.adjustment * 100:.1f}%)"
