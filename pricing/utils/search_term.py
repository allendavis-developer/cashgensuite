CATEGORY_SEARCH_FORMAT = {
    "smartphones and mobile": ["item_name", "storage"],  
    "games (discs/cartridges)": ["subcategory", "item_name"],
    "gaming consoles": ["item_name", "storage", "condition"],
    "laptops": ["item_name", "ram", "storage",],
    "tablets": ["item_name", "storage",]

    # Add more categories here
}

from pricing.models import MarketItem

def build_search_term(item_name, category, subcategory=None, attributes=None):
    """
    Build a search term string based on category mapping, subcategory, and attributes.
    """
    attributes = attributes or {}
    format_fields = CATEGORY_SEARCH_FORMAT.get(category.lower(), ["item_name"])

    print(f"Looking up: '{category.lower()}' in format mapping")
    print(f"Found fields: {format_fields}")
    print(f"Subcategory: {subcategory}")
    print(f"Attributes received: {attributes}")

    parts = []

    for field in format_fields:
        if field == "item_name":
            parts.append(str(item_name))
        elif field == "subcategory" and subcategory:
            parts.append(str(subcategory))
        elif field in attributes and attributes[field]:
            parts.append(str(attributes[field]))
            print(f"Added '{field}': {attributes[field]}")
    
    search_term = " ".join(p for p in parts if p and p != "—").strip()
    return search_term

def get_model_variants(item_model):
    """
    For a given ItemModel, parse MarketItem titles to extract distinct attribute
    variants based purely on CATEGORY_SEARCH_FORMAT order (no hardcoding).
    """
    category_name = item_model.category.name.lower() if item_model.category else ""
    format_fields = CATEGORY_SEARCH_FORMAT.get(category_name, ["item_name"])
    relevant_attrs = [f for f in format_fields if f not in ("item_name", "subcategory")]

    print(f"➡️ Building variants for model: {item_model}")
    print(f"Category: {category_name}")
    print(f"Relevant attributes: {relevant_attrs}")

    variants = {attr: set() for attr in relevant_attrs}

    market_items = MarketItem.objects.filter(item_model=item_model)
    base_name = item_model.name.lower().strip()

    for mi in market_items:
        title = mi.title.lower().strip()

        # Remove the base model name from the beginning of the title if present
        if title.startswith(base_name):
            remainder = title[len(base_name):].strip()
        else:
            # try to remove partial overlap (fallback)
            remainder = title.replace(base_name, "").strip()

        # Split by spaces to get attribute chunks
        parts = remainder.split()
        # Match them to the expected attributes in order
        for i, attr in enumerate(relevant_attrs):
            if i < len(parts):
                value = parts[i].strip()
                if value and value != "—":
                    variants[attr].add(value)

    # Convert sets to sorted lists
    variants = {k: sorted(v, key=str.lower) for k, v in variants.items() if v}

    print(f"✅ Found variants for {item_model.name}: {variants}")
    return variants
