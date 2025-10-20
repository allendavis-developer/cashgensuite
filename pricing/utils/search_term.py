CATEGORY_SEARCH_FORMAT = {
    "smartphones and mobile": ["item_name", "storage"],  # ← lowercase key
    # Add more categories here
}


def build_search_term(item_name, category, attributes):
    """
    Build a search term string based on category mapping and attributes.
    """
    # Use category name as key (lowercase for matching)
    format_fields = CATEGORY_SEARCH_FORMAT.get(category.lower(), ["item_name"])
    
    print(f"Looking up: '{category.lower()}' in format mapping")
    print(f"Found fields: {format_fields}")
    print(f"Attributes received: {attributes}")
    
    parts = []
    for field in format_fields:
        if field == "item_name":
            parts.append(item_name)
        elif field in attributes and attributes[field]:
            parts.append(attributes[field])
            print(f"Added '{field}': {attributes[field]}")
    
    return " ".join(parts)