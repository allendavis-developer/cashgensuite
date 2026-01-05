def extract_checkbox_options(entries):
    options = []

    for entry in entries:
        if entry.get("_type") != "TextualSelection":
            continue

        value = entry.get("paramValue")
        label = extract_label(entry)

        if not value or not label:
            continue

        options.append({
            "value": value,
            "label": label,
            "count": extract_count(entry)
        })

    return options

import re

def extract_count(entry):
    # ebay count is stored in secondaryLabel like " (3,542)"
    secondary = entry.get("secondaryLabel", {})
    spans = secondary.get("textSpans", [])

    if spans:
        text = spans[0].get("text", "")
        match = re.search(r"\(([\d,]+)\)", text)
        if match:
            return int(match.group(1).replace(",", ""))

    return None


def contains_range(entries):
    return any(e.get("_type") == "RangeValueSelection" for e in entries)


def extract_range_filter(group, label):
    min_value = group.get("minValue")
    max_value = group.get("maxValue")

    if min_value is None or max_value is None:
        return None

    return {
        "name": label,
        "id": normalize_id(group.get("fieldId") or label),
        "type": "range",
        "min": min_value,
        "max": max_value
    }


def normalize_id(value):
    return (
        value
        .lower()
        .replace(" ", "_")
        .replace("&", "")
    )


def extract_label(group):
    label = group.get("label", {})
    spans = label.get("textSpans", [])
    if spans:
        return spans[0].get("text")
    return None


def extract_group_as_filter(group):
    field_id = group.get("fieldId")
    param_key = group.get("paramKey")

    # skip category
    if field_id == "category" or param_key == "_sacat":
        return None

    label = extract_label(group)
    entries = group.get("entries", [])

    if not label or not entries:
        return None

    # range?
    if contains_range(entries):
        return extract_range_filter(group, label)

    # checkbox?
    options = extract_checkbox_options(entries)
    if options:
        return {
            "name": label,
            "id": normalize_id(label),
            "type": "checkbox",
            "options": options
        }

    return None


def extract_filters(ebay_raw):
    filters = []

    for group in ebay_raw.get("group", []):

        # 🚪 aspect drawer
        if group.get("fieldId") == "aspectlist":
            for aspect_group in group.get("entries", []):
                extracted = extract_group_as_filter(aspect_group)
                if extracted:
                    filters.append(extracted)
            continue

        # normal top-level filter
        extracted = extract_group_as_filter(group)
        if extracted:
            filters.append(extracted)

    return filters
