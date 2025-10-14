from django.db import models

# -------------------------------
# SCRAPED MARKET DATA
# -------------------------------

class MarketItem(models.Model):
    title = models.CharField(max_length=255)
    exclude_keywords = models.JSONField(blank=True, null=True, help_text="List of keywords to ignore when scraping/creating listings")

    def __str__(self):
        return self.title


class CompetitorListing(models.Model):
    COMPETITOR_CHOICES = [
        ("CeX", "CeX"),
        ("CashConverters", "CashConverters"),
        ("CashGenerator", "CashGenerator"),
        ("eBay", "eBay"),
    ]

    market_item = models.ForeignKey(MarketItem, on_delete=models.CASCADE, related_name="listings")
    competitor = models.CharField(max_length=50, choices=COMPETITOR_CHOICES)
    title = models.CharField(max_length=255)  # raw listing title
    price = models.FloatField()
    url = models.URLField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now=True)
    store_name = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.competitor} - {self.title} (£{self.price})"


# -------------------------------
# SHOP INVENTORY
# -------------------------------

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    base_margin = models.FloatField(default=0.0)  # store margin directly here
    description = models.TextField(blank=True)
    attributes = models.JSONField(blank=True, null=True)  # optional metadata

    def __str__(self):
        return f"{self.name} ({self.base_margin * 100:.0f}%)"


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
class ListingSnapshot(models.Model):
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
    
    # Competitor data (full raw table)
    competitors = models.JSONField(blank=True, default=list)

    # Store info
    branch = models.CharField(max_length=255, blank=True)
    listing_url = models.URLField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.item_name} ({self.branch or 'Unknown Branch'}) - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


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
        ('manufacturer', 'Manufacturer'),
        ('model', 'Model'),
        ('condition', 'Condition'),
        ('feature', 'Feature'),
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
