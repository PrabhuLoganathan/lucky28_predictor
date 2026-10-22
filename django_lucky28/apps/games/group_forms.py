from django import forms
from games.group_config import COLOR_GROUPS, MAX_GROUP_THRESHOLD, parse_threshold


class GroupAbsenceSettingsForm(forms.Form):
    enabled = forms.BooleanField(required=False, label='Enable group absence delivery',
                                 widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

    def __init__(self, *args, stream, states, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['enabled'] = stream.enabled
        by_id = {state.group_id: state for state in states}
        for group in COLOR_GROUPS:
            self.fields[f'{group.id}_enabled'] = forms.BooleanField(required=False,
                label=f'Enable {group.name}', widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
            self.fields[f'{group.id}_threshold'] = forms.CharField(required=False, label=f'{group.name} threshold',
                widget=forms.TextInput(attrs={'class': 'form-control group-threshold', 'inputmode': 'numeric',
                                             'pattern': '[0-9]+', 'maxlength': 7,
                                             'data-max': MAX_GROUP_THRESHOLD, 'autocomplete': 'off'}))
            state = by_id[group.id]
            self.initial[f'{group.id}_enabled'] = state.enabled
            self.initial[f'{group.id}_threshold'] = state.threshold

    def clean(self):
        cleaned = super().clean()
        from django.core.exceptions import ValidationError
        for group in COLOR_GROUPS:
            field = f'{group.id}_threshold'
            try:
                cleaned[field] = parse_threshold(cleaned.get(field), cleaned.get(f'{group.id}_enabled', False))
            except ValidationError as error:
                self.add_error(field, error)
        return cleaned

    def group_values(self):
        return {group.id: {'enabled': self.cleaned_data[f'{group.id}_enabled'],
                           'threshold': self.cleaned_data[f'{group.id}_threshold']} for group in COLOR_GROUPS}

    def group_rows(self):
        return [{'group': group, 'enabled': self[f'{group.id}_enabled'],
                 'threshold': self[f'{group.id}_threshold']} for group in COLOR_GROUPS]
