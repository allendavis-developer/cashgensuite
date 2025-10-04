from django import forms
from .models import Category, MarginRule, GlobalMarginRule

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "base_margin", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Category name"}),
            "base_margin": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.30"}),
            "description": forms.Textarea(attrs={"placeholder": "Optional description", "rows": 2}),
        }

class MarginRuleForm(forms.ModelForm):
    class Meta:
        model = MarginRule
        fields = ["rule_type", "match_value", "adjustment", "is_active"]
        widgets = {
            "rule_type": forms.Select(),
            "match_value": forms.TextInput(attrs={"placeholder": "e.g., Apple"}),
            "adjustment": forms.NumberInput(attrs={"step": "0.01"}),
            "is_active": forms.CheckboxInput(),
        }

class GlobalMarginRuleForm(forms.ModelForm):
    class Meta:
        model = GlobalMarginRule
        fields = ["rule_type", "match_value", "adjustment", "description", "is_active"]
