from ..models import Category, Subcategory, MarginRule

def get_effective_margin(category_id, subcategory_id=None, model_name=None):
    """
    Calculates effective margin for a given category/subcategory/model.
    Returns (effective_margin, category, subcategory, rule_matches)
    """
    try:
        # Find Category
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        raise ValueError("Invalid category")

    # Optional Subcategory
    subcategory = None
    if subcategory_id:
        try:
            subcategory = Subcategory.objects.get(id=subcategory_id)
        except Subcategory.DoesNotExist:
            subcategory = None

    # Base margin
    effective_margin = category.base_margin
    rule_matches = []

    # Find applicable rules
    rules = MarginRule.objects.filter(category=category, is_active=True)

    # Subcategory-based rule
    if subcategory:
        sub_rule = rules.filter(rule_type='subcategory', match_value__iexact=subcategory.name).first()
        if sub_rule:
            effective_margin += sub_rule.adjustment
            rule_matches.append({
                "type": "subcategory",
                "match": sub_rule.match_value,
                "adjustment": sub_rule.adjustment,
            })

    # Model-based rule
    if model_name:
        model_rule = rules.filter(rule_type='model', match_value__iexact=model_name).first()
        if model_rule:
            effective_margin += model_rule.adjustment
            rule_matches.append({
                "type": "model",
                "match": model_rule.match_value,
                "adjustment": model_rule.adjustment,
            })

    return effective_margin, category, subcategory, rule_matches
