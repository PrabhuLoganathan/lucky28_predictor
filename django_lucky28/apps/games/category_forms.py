from django import forms
from django.core.exceptions import ValidationError
from .category_config import CATEGORIES, CATEGORY_FAMILIES, CATEGORY_MODES
from .group_config import parse_threshold


class CategorySettingsForm(forms.Form):
    enabled = forms.BooleanField(required=False, label='Enable row, column and category delivery',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    notify_changes = forms.BooleanField(required=False, label='Send a follow-up when an alerted absence or streak ends',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

    def __init__(self, *args, config, rules, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['enabled'] = config.enabled
        self.initial['notify_changes'] = config.notify_changes
        by_key = {(rule.group_id, rule.mode): rule for rule in rules}
        for group in CATEGORIES:
            for mode in CATEGORY_MODES:
                key = f'{group.id}_{mode}'
                rule = by_key[(group.id, mode)]
                self.fields[f'{key}_enabled'] = forms.BooleanField(required=False, label=f'Enable {group.name} {mode}',
                    widget=forms.CheckboxInput(attrs={'class': f'form-check-input {mode}-enabled'}))
                self.fields[f'{key}_threshold'] = forms.CharField(required=False, label=f'{group.name} {mode} threshold',
                    widget=forms.TextInput(attrs={'class': f'form-control category-threshold {mode}-threshold',
                        'inputmode': 'numeric', 'maxlength': 7, 'autocomplete': 'off'}))
                self.initial[f'{key}_enabled'] = rule.enabled
                self.initial[f'{key}_threshold'] = rule.threshold

    def clean(self):
        data = super().clean()
        for group in CATEGORIES:
            for mode in CATEGORY_MODES:
                key = f'{group.id}_{mode}'
                try:
                    data[f'{key}_threshold'] = parse_threshold(data.get(f'{key}_threshold'), data.get(f'{key}_enabled', False))
                except ValidationError as error:
                    self.add_error(f'{key}_threshold', error)
        return data

    def rule_values(self):
        return {(group.id, mode): dict(enabled=self.cleaned_data[f'{group.id}_{mode}_enabled'],
                                       threshold=self.cleaned_data[f'{group.id}_{mode}_threshold'])
                for group in CATEGORIES for mode in CATEGORY_MODES}

    def sections(self):
        sections = []
        for name, groups in CATEGORY_FAMILIES:
            rows = []
            for group in groups:
                row = {'group': group}
                for mode in CATEGORY_MODES:
                    row[f'{mode}_enabled'] = self[f'{group.id}_{mode}_enabled']
                    row[f'{mode}_threshold'] = self[f'{group.id}_{mode}_threshold']
                rows.append(row)
            sections.append({'name': name, 'rows': rows})
        return sections
