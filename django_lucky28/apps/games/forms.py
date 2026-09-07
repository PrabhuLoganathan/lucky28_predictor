from django import forms


class DayFilterForm(forms.Form):
    date = forms.DateField(required=False, input_formats=['%Y-%m-%d'])


class DeleteDayForm(forms.Form):
    date = forms.DateField(input_formats=['%Y-%m-%d'])
    confirm = forms.BooleanField(required=False)


class DateRangeForm(forms.Form):
    start_date = forms.DateField(required=False, input_formats=['%Y-%m-%d'])
    end_date = forms.DateField(required=False, input_formats=['%Y-%m-%d'])

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and start > end:
            raise forms.ValidationError('The start date must be on or before the end date.')
        return cleaned


class AnalysisFilterForm(DateRangeForm, DayFilterForm):
    recent_n = forms.IntegerField(required=False, min_value=1, max_value=5000)
    hotcold_n = forms.IntegerField(required=False, min_value=1, max_value=5000)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('date') and (cleaned.get('start_date') or cleaned.get('end_date')):
            raise forms.ValidationError('Choose a single date or a date range.')
        return cleaned
