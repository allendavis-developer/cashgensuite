from django import forms
from .models import Category, MarginRule, GlobalMarginRule, MarketItemAttributeValue


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

class MarketItemAttributeValueForm(forms.ModelForm):
    class Meta:
        model = MarketItemAttributeValue
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attribute = getattr(self.instance, 'attribute', None)

        # Hide all value fields by default
        for field_name in ['value_text', 'value_number', 'value_boolean']:
            self.fields[field_name].widget = forms.HiddenInput()

        if attribute:
            if attribute.field_type == 'text':
                self.fields['value_text'].widget = forms.TextInput()
            elif attribute.field_type == 'number':
                self.fields['value_number'].widget = forms.NumberInput()
            elif attribute.field_type == 'boolean':
                self.fields['value_boolean'].widget = forms.CheckboxInput()
            elif attribute.field_type == 'select':
                # Make sure value_text is a ChoiceField with proper options
                choices = [(opt, opt) for opt in (attribute.options or [])]
                self.fields['value_text'] = forms.ChoiceField(
                    choices=choices,
                    widget=forms.Select(),
                    label=self.fields['value_text'].label,
                    required=self.fields['value_text'].required
                )
