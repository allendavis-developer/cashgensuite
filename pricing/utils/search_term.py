CATEGORY_SEARCH_FORMAT = {
    "smartphones and mobile": ["item_name", "storage"],  
    "games (discs & cartridges)": ["subcategory", "item_name"]
    # Add more categories here
}


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
