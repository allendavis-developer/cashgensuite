from django import forms
from .models import Category, MarginRule, GlobalMarginRule, Subcategory, ItemModel


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
    match_value = forms.ChoiceField(choices=[], required=False)

    class Meta:
        model = MarginRule
        fields = ["rule_type", "match_value", "adjustment", "is_active"]
        widgets = {
            "adjustment": forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.30"}),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Figure out which rule type is being used
        rule_type = None
        if self.is_bound:
            rule_type = self.data.get("rule_type")
        elif self.instance and self.instance.pk:
            rule_type = self.instance.rule_type

        # Dynamically populate match_value dropdown
        if rule_type == "subcategory":
            choices = [(m.name, m.name) for m in Subcategory.objects.all().order_by("name")]
        elif rule_type == "model":
            choices = [(m.name, m.name) for m in ItemModel.objects.all().order_by("name")]
        else:
            choices = []

        self.fields["match_value"].choices = [("", "Select a value")] + choices

    def clean(self):
        cleaned_data = super().clean()
        rule_type = cleaned_data.get("rule_type")
        match_value = cleaned_data.get("match_value")

        if not match_value:
            self.add_error("match_value", "Please select a value for this rule type.")

        return cleaned_data



class GlobalMarginRuleForm(forms.ModelForm):
    class Meta:
        model = GlobalMarginRule
        fields = ["rule_type", "match_value", "adjustment", "description", "is_active"]

