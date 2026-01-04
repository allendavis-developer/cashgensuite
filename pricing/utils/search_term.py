# this is the search that will be done on the database
CATEGORY_SEARCH_FORMAT = {
    "smartphones and mobile": ["item_name", "storage"],  
    "games (discs/cartridges)": ["subcategory", "item_name"],
    "gaming consoles": ["item_name", "storage", "condition"],
    "laptops": ["item_name", "ram", "storage",],
    "tablets": ["item_name", "storage",],
    "televisions": ["item_name", "size",],
    "smartwatches": ["item_name", "size",],
    "cameras": ["item_name",],
    "music tech": ["item_name",],
    "headphones": ["item_name",],
    "media player accessories": ["item_name",],
    "console accessories": ["item_name",],
    "drone": ["item_name", "condition"]
    # Add more categories here
}

# this is the search on the cc and cg website
CATEGORY_SEARCH_FORMAT_ONLINE = {
    "smartphones and mobile": ["item_name", "storage"],  
    "games (discs/cartridges)": ["item_name"],
    "gaming consoles": ["item_name", "storage",],
    "laptops": ["item_name", "ram", "storage",],
    "tablets": ["item_name", "storage",],
    "televisions": ["item_name", "size",],
    "smartwatches": ["item_name", "size",],
    "cameras": ["item_name",],
    "music tech": ["item_name",],
    "headphones": ["item_name",],
    "media player accessories": ["item_name",],
    "console accessories": ["item_name",]
    # Add more categories here
}

from pricing.models import MarketItem

def build_search_term(item_name, category, subcategory=None, attributes=None, is_online=False):
    """
    Build a search term string based on category mapping, subcategory, and attributes.
    """
    attributes = attributes or {}
    if is_online:
        format_fields = CATEGORY_SEARCH_FORMAT_ONLINE.get(category.lower(), ["item_name"])
    else:
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
    category_name = item_model.category.name.lower() if item_model.category else ""
    format_fields = CATEGORY_SEARCH_FORMAT.get(category_name, ["item_name"])
    relevant_attrs = [f for f in format_fields if f not in ("item_name", "subcategory")]

    variants = {attr: set() for attr in relevant_attrs}
    combinations = []  # <--- NEW: store attribute combinations

    market_items = MarketItem.objects.filter(item_model=item_model)
    base_name = item_model.name.lower().strip()

    for mi in market_items:
        title = mi.title.lower().strip()
        remainder = title[len(base_name):].strip() if title.startswith(base_name) else title
        parts = remainder.split()

        combo = {}
        for i, attr in enumerate(relevant_attrs):
            if i < len(parts):
                value = parts[i].strip()
                if value and value != "—":
                    variants[attr].add(value)
                    combo[attr] = value
        if combo:
            combinations.append(combo)

    variants = {k: sorted(v) for k, v in variants.items() if v}

    return {
        "variants": variants,
        "combinations": combinations  # list of dicts like [{"storage": "128GB", "color": "Black"}, ...]
    }
