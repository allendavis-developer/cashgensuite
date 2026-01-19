"""
New database models for the pricing app.

This module contains new models that will coexist with the existing models
in models.py. Both sets of models will be available and Django will generate
migrations for both.

Schema Overview:
- ProductCategory: Strict hierarchy, no orphans (every category has a parent)
- Product: The model/family name
- Attribute: Dimensions that can vary (scoped to category)
- AttributeValue: Allowed values for attributes
- ConditionGrade: CeX-specific condition grades (global)
- Variant: The sellable SKU type
- VariantAttributeValue: Bridge table linking variants to attribute values
- VariantPriceHistory: Append-only price history
- VariantStatus: Status tracking for variants
"""

from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal


class ProductCategory(models.Model):
    """
    Category hierarchy. Every category must have a parent.
    Even the top level points to a synthetic root (self-referential root).
    """
    category_id = models.AutoField(primary_key=True)
    parent_category = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='children',
        db_column='parent_category_id',
        help_text="Parent category. Root categories point to themselves.",
        null=True,
        blank=True
    )
    name = models.CharField(max_length=255, db_index=True)
    cex_category_id = models.IntegerField(
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="CeX API category ID (e.g., 810, 1063, 1143)"
    )

    class Meta:
        db_table = 'pricing_product_category'
        verbose_name = 'Product Category'
        verbose_name_plural = 'Product Categories'
        indexes = [
            models.Index(fields=['parent_category', 'name']),
            models.Index(fields=['cex_category_id']),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    A product is a model name, not a sellable thing.
    Represents the family/model (e.g., "PlayStation 5 Slim").
    """
    product_id = models.AutoField(primary_key=True)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='products',
        db_column='category_id'
    )
    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = 'pricing_product'
        indexes = [
            models.Index(fields=['category', 'name']),
        ]

    def __str__(self):
        return self.name


class Attribute(models.Model):
    """
    Attributes define what kinds of variation exist for products in this category.
    Examples: storage_tb, edition, console_colour
    Attributes are scoped to a category and reusable across products.
    """
    attribute_id = models.AutoField(primary_key=True)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='attributes',
        db_column='category_id'
    )
    code = models.CharField(max_length=100, db_index=True, help_text="Attribute code (e.g., 'storage_tb', 'edition')")

    class Meta:
        db_table = 'pricing_attribute'
        unique_together = [['category', 'code']]
        indexes = [
            models.Index(fields=['category', 'code']),
        ]

    def __str__(self):
        return f"{self.category.name} - {self.code}"


class AttributeValue(models.Model):
    """
    Canonical value table for attributes.
    Each value exists once. No free-text chaos. No duplication.
    """
    attribute_value_id = models.AutoField(primary_key=True)
    attribute = models.ForeignKey(
        Attribute,
        on_delete=models.CASCADE,
        related_name='values',
        db_column='attribute_id'
    )
    value = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = 'pricing_attribute_value'
        unique_together = [['attribute', 'value']]
        indexes = [
            models.Index(fields=['attribute', 'value']),
        ]

    def __str__(self):
        return f"{self.attribute.code} = {self.value}"


class ConditionGrade(models.Model):
    """
    CeX-specific condition grades.
    Condition is not an attribute - it's a core axis of sellability.
    This table is global (not scoped to category).
    """
    condition_grade_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=50, unique=True, db_index=True, help_text="Condition code (e.g., 'BOXED', 'UNBOXED', 'DISCOUNTED')")

    class Meta:
        db_table = 'pricing_condition_grade'
        verbose_name = 'Condition Grade'
        verbose_name_plural = 'Condition Grades'

    def __str__(self):
        return self.code


class Variant(models.Model):
    """
    The sellable SKU type.
    A variant is one unique combination of:
    - product
    - condition
    - attribute values
    
    Also owns the CeX SKU and current price.
    """
    variant_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
        db_column='product_id',
        null=True,
        blank=True,
        help_text="Product (nullable for raw scraped data)"
    )
    condition_grade = models.ForeignKey(
        ConditionGrade,
        on_delete=models.CASCADE,
        related_name='variants',
        db_column='condition_grade_id'
    )
    cex_sku = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="CeX SKU - stable identity"
    )
    current_price_gbp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Current price in GBP (denormalized for fast reads)"
    )
    title = models.CharField(
        max_length=500,
        db_index=True,
        blank=True,
        help_text="Title from the listing (e.g., 'Xbox Console, Black, Unboxed')"
    )
    variant_signature = models.CharField(
        max_length=500,
        db_index=True,
        null=True,
        blank=True,
        help_text="Unique signature encoding attribute values (e.g., 'storage=1TB|edition=Digital')"
    )
    attribute_values = models.ManyToManyField(
        AttributeValue,
        through='VariantAttributeValue',
        related_name='variants'
    )

    class Meta:
        db_table = 'pricing_variant'
        # Note: unique_together removed since product and variant_signature can be null
        indexes = [
            models.Index(fields=['product', 'condition_grade']),
            models.Index(fields=['cex_sku']),
            models.Index(fields=['current_price_gbp']),
        ]

    def __str__(self):
        # Imported / raw variants often have no Product attached yet.
        # Prefer showing the scraped listing title, then fall back to SKU.
        label = None
        if self.product_id:
            label = self.product.name
        else:
            title = (self.title or "").strip()
            label = title if title else self.cex_sku
        return f"{label} ({self.condition_grade.code}) - {self.cex_sku}"


class VariantAttributeValue(models.Model):
    """
    Bridge table that applies attribute values to variants.
    This is where storage, edition, colour, etc. actually attach.
    """
    variant = models.ForeignKey(
        Variant,
        on_delete=models.CASCADE,
        related_name='variant_attribute_values',
        db_column='variant_id'
    )
    attribute_value = models.ForeignKey(
        AttributeValue,
        on_delete=models.CASCADE,
        related_name='variant_attribute_values',
        db_column='attribute_value_id'
    )

    class Meta:
        db_table = 'pricing_variant_attribute_value'
        unique_together = [['variant', 'attribute_value']]
        indexes = [
            models.Index(fields=['variant', 'attribute_value']),
        ]

    def __str__(self):
        return f"{self.variant.cex_sku} - {self.attribute_value}"


class VariantPriceHistory(models.Model):
    """
    Append-only price history table.
    Preserves every observed price change.
    Never updated, only appended.
    variant.current_price_gbp mirrors the latest row.
    """
    price_history_id = models.AutoField(primary_key=True)
    variant = models.ForeignKey(
        Variant,
        on_delete=models.CASCADE,
        related_name='price_history',
        db_column='variant_id'
    )
    price_gbp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Price in GBP at this point in time"
    )
    recorded_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When this price was recorded"
    )

    class Meta:
        db_table = 'pricing_variant_price_history'
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['variant', '-recorded_at']),
            models.Index(fields=['recorded_at']),
        ]

    def __str__(self):
        return f"{self.variant.cex_sku} - £{self.price_gbp} @ {self.recorded_at}"


class VariantStatus(models.Model):
    """
    Status tracking for variants.
    Avoids deleting history when CeX delists items.
    Keeps variants stable even when unavailable.
    """
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('DELISTED', 'Delisted'),
        ('DISCONTINUED', 'Discontinued'),
    ]

    variant = models.ForeignKey(
        Variant,
        on_delete=models.CASCADE,
        related_name='status_history',
        db_column='variant_id'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        db_index=True
    )
    effective_from = models.DateTimeField(
        db_index=True,
        help_text="When this status became effective"
    )

    class Meta:
        db_table = 'pricing_variant_status'
        ordering = ['-effective_from']
        indexes = [
            models.Index(fields=['variant', '-effective_from']),
            models.Index(fields=['status', 'effective_from']),
        ]

    def __str__(self):
        return f"{self.variant.cex_sku} - {self.status} from {self.effective_from}"


# =============================================================================
# Rule-Based Attribute Matching Models
# =============================================================================

class MatchRule(models.Model):
    """
    Stores learned match rules for attribute extraction from SKU titles.
    
    A match rule maps a pattern in the title to an attribute value.
    For example: match_rule="playstation 5 pro" → attribute_value="PlayStation 5 Pro"
    
    Rules are GLOBAL (not per-category) so a "boxed" rule learned from
    one category works across all categories.
    """
    match_rule_id = models.AutoField(primary_key=True)
    attribute_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Attribute name (e.g., 'model_name', 'consoles_condition')"
    )
    attribute_value = models.CharField(
        max_length=255,
        db_index=True,
        help_text="The value this rule matches to (e.g., 'PlayStation 5 Pro', 'Boxed')"
    )
    match_pattern = models.JSONField(
        help_text="Match pattern - string for single match, list for multi-word match (all must appear)"
    )
    source_sku = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="SKU this rule was learned from (or 'preloaded' for filter-based rules)"
    )
    source_title = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Title this rule was learned from"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pricing_match_rule'
        verbose_name = 'Match Rule'
        verbose_name_plural = 'Match Rules'
        unique_together = [['attribute_name', 'attribute_value', 'match_pattern']]
        indexes = [
            models.Index(fields=['attribute_name']),
            models.Index(fields=['attribute_name', 'attribute_value']),
        ]

    def __str__(self):
        pattern = self.match_pattern
        if isinstance(pattern, list):
            pattern_str = f"{pattern} (ALL)"
        else:
            pattern_str = f'"{pattern}"'
        return f"{self.attribute_name}={self.attribute_value} via {pattern_str}"


class CategorySkuPrefix(models.Model):
    """
    Maps SKU prefixes to categories for quick category detection without HTTP.
    
    Prefixes are dynamically computed from observed SKUs.
    For example: prefix="SPS5" → category="PlayStation 5 Consoles"
    """
    prefix_id = models.AutoField(primary_key=True)
    prefix = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="SKU prefix (e.g., 'SPS5', 'SXB1')"
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='sku_prefixes',
        db_column='category_id'
    )
    sku_count = models.IntegerField(
        default=1,
        help_text="Number of SKUs used to compute this prefix"
    )

    class Meta:
        db_table = 'pricing_category_sku_prefix'
        verbose_name = 'Category SKU Prefix'
        verbose_name_plural = 'Category SKU Prefixes'
        indexes = [
            models.Index(fields=['prefix']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f"{self.prefix}* → {self.category.name}"


class CategoryRequirement(models.Model):
    """
    Stores which attributes are required for each category.
    
    This is user-defined when a category is first encountered.
    For example: PlayStation 5 Consoles requires ['model_name', 'storage_GB', 'edition']
    """
    requirement_id = models.AutoField(primary_key=True)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='requirements',
        db_column='category_id'
    )
    attribute_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Required attribute name"
    )
    is_skipped = models.BooleanField(
        default=False,
        help_text="True if user chose to skip this attribute (unlearnable)"
    )
    always_fetch = models.BooleanField(
        default=False,
        help_text="True if this attribute is un-teachable and should always be fetched from the API for this category"
    )

    class Meta:
        db_table = 'pricing_category_requirement'
        verbose_name = 'Category Requirement'
        verbose_name_plural = 'Category Requirements'
        unique_together = [['category', 'attribute_name']]
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['category', 'attribute_name']),
        ]

    def __str__(self):
        status_parts = []
        if self.is_skipped:
            status_parts.append("skipped")
        if self.always_fetch and not self.is_skipped:
            status_parts.append("always_fetch")
        status = f" ({', '.join(status_parts)})" if status_parts else ""
        return f"{self.category.name} requires {self.attribute_name}{status}"
