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
        help_text="Parent category. Root categories point to themselves."
    )
    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = 'pricing_product_category'
        verbose_name = 'Product Category'
        verbose_name_plural = 'Product Categories'
        indexes = [
            models.Index(fields=['parent_category', 'name']),
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
        db_column='product_id'
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
    variant_signature = models.CharField(
        max_length=500,
        db_index=True,
        help_text="Unique signature encoding attribute values (e.g., 'storage=1TB|edition=Digital')"
    )
    attribute_values = models.ManyToManyField(
        AttributeValue,
        through='VariantAttributeValue',
        related_name='variants'
    )

    class Meta:
        db_table = 'pricing_variant'
        unique_together = [['product', 'condition_grade', 'variant_signature']]
        indexes = [
            models.Index(fields=['product', 'condition_grade']),
            models.Index(fields=['cex_sku']),
            models.Index(fields=['current_price_gbp']),
        ]

    def __str__(self):
        return f"{self.product.name} ({self.condition_grade.code}) - {self.cex_sku}"


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
