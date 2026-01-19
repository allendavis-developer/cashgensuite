import logging
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from pricing.models_v2 import Product, Variant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Repair models_v2 links: for Variants with no product, attach the Product whose name "
        "matches Variant.title exactly (skips ambiguous matches)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Batch size for bulk_update.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional cap on number of orphan variants to process (0 = no limit).",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        batch_size = int(options["batch_size"])
        limit = int(options["limit"])

        if batch_size <= 0:
            raise ValueError("--batch-size must be > 0")
        if limit < 0:
            raise ValueError("--limit must be >= 0")

        self.stdout.write("Building Product name → product_id map...")

        # Build name->ids map to detect ambiguous product names.
        name_to_product_ids = defaultdict(list)
        for name, product_id in Product.objects.values_list("name", "product_id").iterator(chunk_size=10000):
            if not name:
                continue
            name_to_product_ids[name].append(product_id)

        ambiguous_names = {name for name, ids in name_to_product_ids.items() if len(ids) > 1}
        self.stdout.write(f"Products loaded: {sum(len(v) for v in name_to_product_ids.values())}")
        self.stdout.write(f"Ambiguous product names (skipped): {len(ambiguous_names)}")

        orphan_qs = Variant.objects.filter(product__isnull=True).exclude(title__isnull=True).exclude(title__exact="")
        orphan_count = orphan_qs.count()
        self.stdout.write(f"Orphan variants (product is NULL) with non-empty title: {orphan_count}")

        if orphan_count == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        if limit:
            orphan_qs = orphan_qs.order_by("variant_id")[:limit]
            self.stdout.write(f"Applying --limit={limit}")

        to_update = []
        linked = 0
        skipped_ambiguous = 0
        skipped_no_match = 0

        # Iterate through orphans and link by exact title match to Product.name
        for variant in orphan_qs.only("variant_id", "title", "product_id").iterator(chunk_size=10000):
            title = variant.title
            if title in ambiguous_names:
                skipped_ambiguous += 1
                continue

            product_ids = name_to_product_ids.get(title)
            if not product_ids:
                skipped_no_match += 1
                continue

            variant.product_id = product_ids[0]
            to_update.append(variant)
            linked += 1

            if len(to_update) >= batch_size:
                self._flush_updates(to_update, dry_run=dry_run)
                to_update.clear()

        if to_update:
            self._flush_updates(to_update, dry_run=dry_run)

        self.stdout.write("-" * 80)
        self.stdout.write(self.style.SUCCESS(f"Linked variants: {linked}{' (dry-run)' if dry_run else ''}"))
        self.stdout.write(f"Skipped (ambiguous Product.name): {skipped_ambiguous}")
        self.stdout.write(f"Skipped (no Product.name match): {skipped_no_match}")

        logger.info(
            "Variant↔Product relink finished: linked=%s dry_run=%s skipped_ambiguous=%s skipped_no_match=%s",
            linked,
            dry_run,
            skipped_ambiguous,
            skipped_no_match,
        )

    def _flush_updates(self, variants, *, dry_run: bool):
        if dry_run:
            return

        with transaction.atomic():
            Variant.objects.bulk_update(variants, ["product_id"], batch_size=len(variants))

