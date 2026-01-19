import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

import ijson
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pricing.models_v2 import (
    Attribute,
    AttributeValue,
    ConditionGrade,
    ProductCategory,
    Variant,
    VariantAttributeValue,
)

logger = logging.getLogger(__name__)


def _looks_like_condition_attribute(attr_name: str) -> bool:
    n = (attr_name or "").strip().lower()
    return ("condition" in n) or ("grade" in n)


def _safe_attribute_code(raw: str) -> str:
    """
    `Attribute.code` is max_length=100. Keep original key if possible; otherwise truncate.
    """
    raw = str(raw or "").strip()
    if len(raw) <= 100:
        return raw
    return raw[:100]


def _chunked(it: Iterable[Any], size: int) -> Iterator[list[Any]]:
    buf: list[Any] = []
    for x in it:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


class Command(BaseCommand):
    help = (
        "Populate v2 models (ProductCategory, Attribute, AttributeValue, VariantAttributeValue) "
        "from process_data_results.json (streams results to handle large files)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="process_data_results.json",
            help="Path to the JSON file containing a top-level `results` array.",
        )
        parser.add_argument(
            "--root-category-name",
            default="ROOT",
            help="Name of the synthetic root category. All imported categories become children of this.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Commit every N items (keeps transactions bounded for large imports).",
        )
        parser.add_argument(
            "--default-price",
            default="0.01",
            help="Default Variant.current_price_gbp to use when not present in input.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and count but do not write to the database.",
        )

    def handle(self, *args, **options):
        json_path = Path(options["path"])
        if not json_path.exists():
            raise CommandError(f"File not found: {json_path}")

        try:
            default_price = Decimal(str(options["default_price"]))
        except Exception as e:
            raise CommandError(f"Invalid --default-price: {options['default_price']} ({e})")

        if default_price <= 0:
            raise CommandError("--default-price must be > 0")

        dry_run = bool(options["dry_run"])
        batch_size = int(options["batch_size"])
        root_name = str(options["root_category_name"]).strip() or "ROOT"

        self.stdout.write(
            f"Importing v2 attributes/values + variant links from `{json_path}` "
            f"(dry_run={dry_run}, batch_size={batch_size})"
        )

        # Caches to reduce DB round-trips.
        # In dry-run, these are in-memory sentinels used for "would create" counts.
        # In real runs, these store actual ORM instances for reuse across batches.
        category_cache: Dict[str, ProductCategory] = {}
        attribute_cache: Dict[Tuple[int, str], Attribute] = {}
        value_cache: Dict[Tuple[int, str], AttributeValue] = {}
        condition_cache: Dict[str, ConditionGrade] = {}
        variant_cache: Dict[str, Variant] = {}
        # For dry-run link counting (VariantAttributeValue through table)
        link_cache: set[Tuple[str, str, str]] = set()

        root_category, root_created = self._get_or_create_root(root_name, dry_run=dry_run)
        if root_created:
            self.stdout.write(f"Created synthetic root category: {root_category.name}")

        # Counters
        cats_created = 0
        attrs_created = 0
        vals_created = 0
        vars_created = 0
        links_created = 0

        processed = 0

        def iter_results_items() -> Iterable[Dict[str, Any]]:
            """
            Stream `results.item` so we never load the whole file.
            Also tries a couple common alternate roots.
            """
            prefixes = ("results.item", "data.results.item", "payload.results.item")
            last_exc: Optional[BaseException] = None
            for prefix in prefixes:
                try:
                    with open(json_path, "rb") as f:
                        yield from ijson.items(f, prefix)
                    return
                except BaseException as e:
                    last_exc = e
            raise CommandError(
                "Could not locate a `results` array to stream. "
                "Expected JSON like `{\"results\": [...]}`."
            ) from last_exc

        def process_item_dry_run(item: Dict[str, Any]) -> None:
            nonlocal processed, cats_created, attrs_created, vals_created, vars_created, links_created

            processed += 1

            sku = str(item.get("sku") or "").strip()
            if not sku:
                return

            category_name = str(item.get("category") or "").strip() or "Unknown"
            attrs = item.get("attributes") or {}
            if not isinstance(attrs, dict):
                # Some feeds might serialize attributes as list-of-pairs
                try:
                    attrs = dict(attrs)  # type: ignore[arg-type]
                except Exception:
                    attrs = {}

            category_obj, created = self._get_or_create_category(
                root_category=root_category,
                category_name=category_name,
                cache=category_cache,
                dry_run=dry_run,
            )
            if created:
                cats_created += 1

            # Condition/grade handling: map to ConditionGrade if present
            condition_code = None
            for k, v in attrs.items():
                if _looks_like_condition_attribute(str(k)):
                    condition_code = str(v).strip().upper()
                    break
            condition_grade, _ = self._get_or_create_condition(
                condition_code or "UNKNOWN",
                cache=condition_cache,
                dry_run=dry_run,
            )

            # Variant (unique by cex_sku)
            variant, v_created = self._get_or_create_variant(
                sku=sku,
                condition_grade=condition_grade,
                title=str(item.get("title") or "").strip(),
                default_price=default_price,
                cache=variant_cache,
                dry_run=dry_run,
            )
            if v_created:
                vars_created += 1

            # For each attribute key/value, ensure Attribute + AttributeValue and link.
            for raw_attr_name, raw_attr_value in attrs.items():
                attr_name = _safe_attribute_code(raw_attr_name)
                attr_value = str(raw_attr_value or "").strip()
                if not attr_name or not attr_value:
                    continue
                if _looks_like_condition_attribute(attr_name):
                    # Condition is modeled in ConditionGrade, not Attribute/AttributeValue.
                    continue

                attr_obj, a_created = self._get_or_create_attribute(
                    category=category_obj,
                    code=attr_name,
                    cache=attribute_cache,
                    dry_run=dry_run,
                )
                if a_created:
                    attrs_created += 1

                val_obj, val_created = self._get_or_create_value(
                    attribute=attr_obj,
                    value=attr_value,
                    cache=value_cache,
                    dry_run=dry_run,
                )
                if val_created:
                    vals_created += 1

                link_created = self._get_or_create_variant_attr_link(
                    variant=variant,
                    attribute=attr_obj,
                    value=attr_value,
                    attribute_value=val_obj,
                    dry_run=dry_run,
                    link_cache=link_cache,
                )
                if link_created:
                    links_created += 1

        if dry_run:
            for item in iter_results_items():
                process_item_dry_run(item)
                if (processed % batch_size) == 0:
                    self.stdout.write(f"Processed {processed} items (dry-run; no DB writes).")
        else:
            batch: list[Dict[str, Any]] = []
            for item in iter_results_items():
                batch.append(item)
                if len(batch) >= batch_size:
                    with transaction.atomic():
                        self._process_batch_bulk(
                            batch=batch,
                            root_category=root_category,
                            default_price=default_price,
                            category_cache=category_cache,
                            condition_cache=condition_cache,
                            variant_cache=variant_cache,
                            attribute_cache=attribute_cache,
                            value_cache=value_cache,
                        )
                    processed += len(batch)
                    self.stdout.write(f"Committed bulk batch at {processed} items...")
                    batch.clear()
            if batch:
                with transaction.atomic():
                    self._process_batch_bulk(
                        batch=batch,
                        root_category=root_category,
                        default_price=default_price,
                        category_cache=category_cache,
                        condition_cache=condition_cache,
                        variant_cache=variant_cache,
                        attribute_cache=attribute_cache,
                        value_cache=value_cache,
                    )
                processed += len(batch)

        self.stdout.write(
            "Done.\n"
            f"- Processed items: {processed}\n"
            f"- Categories created: {cats_created}\n"
            f"- Attributes created: {attrs_created}\n"
            f"- AttributeValues created: {vals_created}\n"
            f"- Variants created: {vars_created}\n"
            f"- VariantAttributeValue links created: {links_created}\n"
            f"- Dry run: {dry_run}"
        )

    def _process_batch_bulk(
        self,
        *,
        batch: list[Dict[str, Any]],
        root_category: ProductCategory,
        default_price: Decimal,
        category_cache: Dict[str, ProductCategory],
        condition_cache: Dict[str, ConditionGrade],
        variant_cache: Dict[str, Variant],
        attribute_cache: Dict[Tuple[int, str], Attribute],
        value_cache: Dict[Tuple[int, str], AttributeValue],
    ) -> None:
        """
        Bulk import a batch with minimal round-trips:
        - bulk_create(ignore_conflicts=True) for missing rows
        - re-fetch what we need to build FK mappings
        """

        # 1) Parse batch into normalized needs (deduped).
        category_names: set[str] = set()
        condition_codes: set[str] = set()
        sku_to_title: Dict[str, str] = {}
        sku_to_category: Dict[str, str] = {}
        sku_to_condition_code: Dict[str, str] = {}
        # category -> attribute_codes
        category_to_attr_codes: Dict[str, set[str]] = {}
        # (category, attr_code) -> values
        cat_attr_to_values: Dict[Tuple[str, str], set[str]] = {}
        # link tuples: (sku, category, attr_code, value)
        link_tuples: set[Tuple[str, str, str, str]] = set()

        for item in batch:
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue

            category_name = str(item.get("category") or "").strip() or "Unknown"
            attrs = item.get("attributes") or {}
            if not isinstance(attrs, dict):
                try:
                    attrs = dict(attrs)  # type: ignore[arg-type]
                except Exception:
                    attrs = {}

            category_names.add(category_name)
            sku_to_title.setdefault(sku, str(item.get("title") or "").strip())
            sku_to_category.setdefault(sku, category_name)

            condition_code = "UNKNOWN"
            for k, v in attrs.items():
                if _looks_like_condition_attribute(str(k)):
                    condition_code = str(v).strip().upper() or "UNKNOWN"
                    break
            condition_codes.add(condition_code)
            sku_to_condition_code.setdefault(sku, condition_code)

            for raw_attr_name, raw_attr_value in attrs.items():
                attr_code = _safe_attribute_code(raw_attr_name)
                attr_value = str(raw_attr_value or "").strip()
                if not attr_code or not attr_value:
                    continue
                if _looks_like_condition_attribute(attr_code):
                    continue

                category_to_attr_codes.setdefault(category_name, set()).add(attr_code)
                cat_attr_to_values.setdefault((category_name, attr_code), set()).add(attr_value)
                link_tuples.add((sku, category_name, attr_code, attr_value))

        if not sku_to_category:
            return

        # 2) Ensure categories exist
        uncached_category_names = [n for n in category_names if n not in category_cache]
        if uncached_category_names:
            existing = list(ProductCategory.objects.filter(name__in=uncached_category_names))
            seen: Dict[str, ProductCategory] = {}
            for c in existing:
                if c.name in seen:
                    logger.warning(
                        "Multiple ProductCategory rows found for name=%r. Using category_id=%s",
                        c.name,
                        seen[c.name].category_id,
                    )
                    continue
                seen[c.name] = c
            missing_names = [n for n in uncached_category_names if n not in seen]
            if missing_names:
                ProductCategory.objects.bulk_create(
                    [ProductCategory(name=n, parent_category=root_category) for n in missing_names],
                    ignore_conflicts=True,
                    batch_size=1000,
                )
                # Re-fetch missing (created by us or raced)
                for c in ProductCategory.objects.filter(name__in=missing_names):
                    if c.name not in seen:
                        seen[c.name] = c
            category_cache.update(seen)

        # 3) Ensure conditions exist
        uncached_conditions = [c for c in condition_codes if c not in condition_cache]
        if uncached_conditions:
            existing = {c.code: c for c in ConditionGrade.objects.filter(code__in=uncached_conditions)}
            missing = [c for c in uncached_conditions if c not in existing]
            if missing:
                ConditionGrade.objects.bulk_create(
                    [ConditionGrade(code=c) for c in missing],
                    ignore_conflicts=True,
                    batch_size=1000,
                )
                for c in ConditionGrade.objects.filter(code__in=missing):
                    existing.setdefault(c.code, c)
            condition_cache.update(existing)

        # 4) Ensure variants exist (by cex_sku)
        skus = list(sku_to_category.keys())
        uncached_skus = [s for s in skus if s not in variant_cache]
        if uncached_skus:
            existing_variants = {v.cex_sku: v for v in Variant.objects.filter(cex_sku__in=uncached_skus)}
            missing_skus = [s for s in uncached_skus if s not in existing_variants]
            if missing_skus:
                Variant.objects.bulk_create(
                    [
                        Variant(
                            product=None,
                            condition_grade=condition_cache[sku_to_condition_code.get(s, "UNKNOWN") or "UNKNOWN"],
                            cex_sku=s,
                            current_price_gbp=default_price,
                            title=sku_to_title.get(s, "")[:500],
                            variant_signature=None,
                        )
                        for s in missing_skus
                    ],
                    ignore_conflicts=True,
                    batch_size=1000,
                )
                for v in Variant.objects.filter(cex_sku__in=missing_skus):
                    existing_variants.setdefault(v.cex_sku, v)
            variant_cache.update(existing_variants)

        # 5) Ensure attributes exist (scoped to category)
        desired_attr_keys: set[Tuple[int, str]] = set()
        desired_codes: set[str] = set()
        desired_cat_ids: set[int] = set()
        for cat_name, codes in category_to_attr_codes.items():
            cat = category_cache.get(cat_name)
            if not cat:
                continue
            desired_cat_ids.add(cat.category_id)
            for code in codes:
                desired_attr_keys.add((cat.category_id, code))
                desired_codes.add(code)

        missing_attr_keys: set[Tuple[int, str]] = set()
        if desired_attr_keys:
            # Load existing attributes for these categories/codes
            existing_attrs = {}
            for a in Attribute.objects.filter(category_id__in=list(desired_cat_ids), code__in=list(desired_codes)):
                existing_attrs[(a.category_id, a.code)] = a
            # Add any already cached
            existing_attrs.update({k: v for k, v in attribute_cache.items() if k in desired_attr_keys})

            missing_attr_keys = desired_attr_keys - set(existing_attrs.keys())
            if missing_attr_keys:
                Attribute.objects.bulk_create(
                    [Attribute(category_id=cat_id, code=code) for (cat_id, code) in missing_attr_keys],
                    ignore_conflicts=True,
                    batch_size=2000,
                )
                # Re-fetch missing
                for a in Attribute.objects.filter(category_id__in=list(desired_cat_ids), code__in=list(desired_codes)):
                    existing_attrs[(a.category_id, a.code)] = a

            attribute_cache.update({k: v for k, v in existing_attrs.items() if k in desired_attr_keys})

        # 6) Ensure attribute values exist
        # Build desired (attribute_id, value) keys from cat_attr_to_values
        desired_value_keys: set[Tuple[int, str]] = set()
        all_values: set[str] = set()
        for (cat_name, code), values in cat_attr_to_values.items():
            cat = category_cache.get(cat_name)
            if not cat:
                continue
            attr = attribute_cache.get((cat.category_id, code))
            if not attr:
                continue
            for v in values:
                desired_value_keys.add((attr.attribute_id, v))
                all_values.add(v)

        if desired_value_keys:
            attr_ids = list({aid for (aid, _) in desired_value_keys})
            # Fetch existing values only for values present in this batch
            existing_vals = {}
            for av in AttributeValue.objects.filter(attribute_id__in=attr_ids, value__in=list(all_values)):
                existing_vals[(av.attribute_id, av.value)] = av
            # Add any already cached
            existing_vals.update({k: v for k, v in value_cache.items() if k in desired_value_keys})

            missing_value_keys = desired_value_keys - set(existing_vals.keys())
            if missing_value_keys:
                for chunk in _chunked(
                    (AttributeValue(attribute_id=aid, value=val) for (aid, val) in missing_value_keys),
                    5000,
                ):
                    AttributeValue.objects.bulk_create(
                        chunk,
                        ignore_conflicts=True,
                        batch_size=2000,
                    )
                # Re-fetch all needed again (bounded to this batch's values)
                existing_vals = {}
                for av in AttributeValue.objects.filter(attribute_id__in=attr_ids, value__in=list(all_values)):
                    existing_vals[(av.attribute_id, av.value)] = av

            value_cache.update(existing_vals)

        # 7) Ensure variant-attribute-value links (through table)
        through_objs: list[VariantAttributeValue] = []
        for sku, cat_name, code, val in link_tuples:
            var = variant_cache.get(sku)
            cat = category_cache.get(cat_name)
            if not var or not cat:
                continue
            attr = attribute_cache.get((cat.category_id, code))
            if not attr:
                continue
            av = value_cache.get((attr.attribute_id, val))
            if not av:
                continue
            through_objs.append(VariantAttributeValue(variant_id=var.variant_id, attribute_value_id=av.attribute_value_id))

        if through_objs:
            for chunk in _chunked(through_objs, 5000):
                VariantAttributeValue.objects.bulk_create(
                    chunk,
                    ignore_conflicts=True,
                    batch_size=2000,
                )

    def _get_or_create_root(self, name: str, dry_run: bool) -> Tuple[ProductCategory, bool]:
        if dry_run:
            root = ProductCategory(category_id=-1, name=name, parent_category=None)
            return root, False

        root, created = ProductCategory.objects.get_or_create(
            name=name,
            defaults={"parent_category": None},
        )
        # Make root self-referential (docstring convention) once it exists.
        if root.parent_category_id is None:
            root.parent_category = root
            root.save(update_fields=["parent_category"])
        return root, created

    def _get_or_create_category(
        self,
        *,
        root_category: ProductCategory,
        category_name: str,
        cache: Dict[str, ProductCategory],
        dry_run: bool,
    ) -> Tuple[ProductCategory, bool]:
        if category_name in cache:
            return cache[category_name], False

        if dry_run:
            cat = ProductCategory(category_id=-1, name=category_name, parent_category=root_category)
            cache[category_name] = cat
            return cat, True

        # Avoid creating duplicate categories when one already exists by name.
        existing = list(ProductCategory.objects.filter(name=category_name)[:2])
        if len(existing) == 1:
            cat = existing[0]
            created = False
            # If it's orphaned, attach to root to keep hierarchy consistent.
            if cat.parent_category_id is None:
                cat.parent_category = root_category
                cat.save(update_fields=["parent_category"])
        elif len(existing) > 1:
            cat = existing[0]
            created = False
            logger.warning(
                "Multiple ProductCategory rows found for name=%r. Using category_id=%s",
                category_name,
                cat.category_id,
            )
        else:
            cat = ProductCategory.objects.create(name=category_name, parent_category=root_category)
            created = True

        cache[category_name] = cat
        return cat, created

    def _get_or_create_attribute(
        self,
        *,
        category: ProductCategory,
        code: str,
        cache: Dict[Tuple[int, str], Attribute],
        dry_run: bool,
    ) -> Tuple[Attribute, bool]:
        key = (getattr(category, "category_id", -1), code)
        if key in cache:
            return cache[key], False

        if dry_run:
            attr = Attribute(attribute_id=-1, category=category, code=code)
            cache[key] = attr
            return attr, True

        obj, created = Attribute.objects.get_or_create(category=category, code=code)
        cache[key] = obj
        return obj, created

    def _get_or_create_value(
        self,
        *,
        attribute: Attribute,
        value: str,
        cache: Dict[Tuple[int, str], AttributeValue],
        dry_run: bool,
    ) -> Tuple[AttributeValue, bool]:
        key = (getattr(attribute, "attribute_id", -1), value)
        if key in cache:
            return cache[key], False

        if dry_run:
            obj = AttributeValue(attribute_value_id=-1, attribute=attribute, value=value)
            cache[key] = obj
            return obj, True

        obj, created = AttributeValue.objects.get_or_create(attribute=attribute, value=value)
        cache[key] = obj
        return obj, created

    def _get_or_create_condition(
        self,
        code: str,
        *,
        cache: Dict[str, ConditionGrade],
        dry_run: bool,
    ) -> Tuple[ConditionGrade, bool]:
        code = str(code or "UNKNOWN").strip().upper() or "UNKNOWN"
        if code in cache:
            return cache[code], False

        if dry_run:
            obj = ConditionGrade(condition_grade_id=-1, code=code)
            cache[code] = obj
            return obj, True

        obj, created = ConditionGrade.objects.get_or_create(code=code)
        cache[code] = obj
        return obj, created

    def _get_or_create_variant(
        self,
        *,
        sku: str,
        condition_grade: ConditionGrade,
        title: str,
        default_price: Decimal,
        cache: Dict[str, Variant],
        dry_run: bool,
    ) -> Tuple[Variant, bool]:
        if sku in cache:
            return cache[sku], False

        if dry_run:
            obj = Variant(
                variant_id=-1,
                product=None,
                condition_grade=condition_grade,
                cex_sku=sku,
                current_price_gbp=default_price,
                title=title,
                variant_signature=None,
            )
            cache[sku] = obj
            return obj, True

        obj, created = Variant.objects.get_or_create(
            cex_sku=sku,
            defaults={
                "product": None,
                "condition_grade": condition_grade,
                "current_price_gbp": default_price,
                "title": title,
                "variant_signature": None,
            },
        )
        # If the variant exists but lacks a condition, we keep it; don't overwrite existing.
        cache[sku] = obj
        return obj, created

    def _get_or_create_variant_attr_link(
        self,
        *,
        variant: Variant,
        attribute: Attribute,
        value: str,
        attribute_value: AttributeValue,
        dry_run: bool,
        link_cache: set[Tuple[str, str, str]],
    ) -> bool:
        if dry_run:
            # attribute_value_id is a sentinel (-1) in dry-run, so use a stable composite key.
            key = (variant.cex_sku, attribute.code, value)
            if key in link_cache:
                return False
            link_cache.add(key)
            return True
        _, created = VariantAttributeValue.objects.get_or_create(
            variant=variant,
            attribute_value=attribute_value,
        )
        return created


class _noop_context:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False

