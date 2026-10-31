import re
from uuid import uuid4

from django import forms
from django.db import transaction
from django.utils.text import slugify

from .models import AlertRule, AlertDestination, AlertSettings
from .services.alert_settings import get_config

VALUES = {'size': ['Big', 'Small'], 'parity': ['Odd', 'Even'],
          'color': ['Red', 'Yellow', 'Pink', 'Blue', 'Cyan', 'Green', 'Grey'],
          'number': [str(n) for n in range(28)], 'tip': ['TIP', 'NO_TIP']}
RANKS = [(n, f'Level {n}' + (' (low)' if n == 1 else ' (high)' if n == 5 else '')) for n in range(1, 6)]


def recipient_choices():
    return [('levels', 'Level hierarchy')] + [(str(d.pk), d.name) for d in AlertDestination.objects.order_by('name')]


def initial_recipients(instance):
    return (['levels'] if instance.send_to_levels else []) + (
        [str(d.pk) for d in instance.destinations.all()] if instance.pk else [])


class RecipientField(forms.MultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget.attrs['class'] = 'form-check-input'


class StyledForm:
    def style(self):
        for field in self.fields.values():
            widget = field.widget
            widget.attrs['class'] = ('form-check-input' if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)) else
                                     'form-select' if isinstance(widget, forms.Select) else 'form-control')


class AlertRuleForm(StyledForm, forms.ModelForm):
    values = forms.MultipleChoiceField(label='Matching values', required=False,
                                      help_text='Choose one value, or two for an alternating pattern. Hold Ctrl / Command to select multiple values.')
    breaker_value = forms.ChoiceField(label='Value that ends the streak', required=False)
    min_plan_rank = forms.TypedChoiceField(label='Minimum destination level', choices=RANKS, coerce=int, required=False)
    recipients = RecipientField(label='Send to',
        help_text='Tick channels, Level hierarchy, or both. Selected channels ignore levels. Each channel receives the alert once.')

    class Meta:
        model = AlertRule
        fields = ['title', 'series', 'mode', 'values', 'threshold', 'window', 'breaker_value', 'recipients', 'min_plan_rank', 'session_only', 'enabled']
        labels = {'title': 'Rule name', 'series': 'Watch', 'mode': 'Pattern', 'threshold': 'Trigger count',
                  'window': 'Look back over this many rounds', 'session_only': 'Use only this server session', 'enabled': 'Rule enabled'}
        help_texts = {'threshold': 'Minimum count for most patterns; maximum count for low density.',
                      'window': 'Used for high or low density patterns.',
                      'session_only': 'Resets the rule’s history when the server restarts.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipients'].choices = recipient_choices()
        self.initial['recipients'] = initial_recipients(self.instance)
        series = self.data.get('series') if self.is_bound else self.instance.series or 'size'
        choices = [(v, v) for v in VALUES.get(series, [])]
        self.fields['values'].choices = choices
        self.fields['values'].widget.attrs['size'] = min(7, max(2, len(choices)))
        self.fields['breaker_value'].choices = [('', 'Choose a value')] + choices
        self.fields['series'].initial = series
        self.fields['series'].choices = [('size', 'Big / Small'), ('parity', 'Odd / Even'), ('color', 'Color'), ('number', 'Number'), ('tip', 'Tip settlement')]
        self.fields['mode'].choices = [('streak', 'Consecutive results'), ('absence', 'Drought / absence'),
            ('density', 'High frequency in a window'), ('density_low', 'Low frequency in a window'),
            ('breaker', 'Streak ended'), ('alternating', 'Alternating results'), ('every_game', 'Every new round')]
        self.fields['window'].required = False
        self.fields['threshold'].required = False
        self.style()

    def clean(self):
        data = super().clean()
        if not data.get('min_plan_rank'):
            if 'levels' in data.get('recipients', []):
                self.add_error('min_plan_rank', 'Choose a minimum destination level.')
            data['min_plan_rank'] = self.instance.min_plan_rank or 1
        mode = data.get('mode')
        if mode != 'breaker':
            data['breaker_value'] = ''
        if mode not in ('density', 'density_low'):
            data['window'] = 0
        if mode == 'every_game':
            data['values'], data['threshold'] = [], 1
        elif data.get('threshold') is None:
            self.add_error('threshold', 'Enter a trigger count.')
        if mode in ('density', 'density_low') and not data.get('window'):
            self.add_error('window', 'Enter a window size.')
        if not self.instance.key:
            self.instance.key = f'{slugify(data.get("title", "rule"))[:60] or "rule"}-{uuid4().hex[:10]}'
        return data

    @transaction.atomic
    def save(self, commit=True):
        self.instance.send_to_levels = 'levels' in self.cleaned_data['recipients']
        return super().save(commit=commit)

    def _save_m2m(self):
        super()._save_m2m()
        self.instance.destinations.set([int(value) for value in self.cleaned_data['recipients'] if value != 'levels'])


class AlertDestinationForm(StyledForm, forms.ModelForm):
    plan_rank = forms.TypedChoiceField(label='Destination level', choices=RANKS, coerce=int, required=False)
    routing_type = forms.ChoiceField(label='Destination type', choices=AlertDestination.ROUTING_TYPES,
        required=False, help_text='Direct only receives alerts explicitly assigned to this channel, outside Levels 1–5.')

    class Meta:
        model = AlertDestination
        fields = ['name', 'chat_id', 'routing_type', 'plan_rank', 'expires_at', 'enabled', 'send_results', 'send_health', 'use_cards']
        labels = {'name': 'Destination name', 'chat_id': 'Telegram chat ID or channel username',
                  'expires_at': 'Subscription expires (UTC)', 'enabled': 'Enable this destination',
                  'send_results': 'Send confirmed result follow-ups', 'send_health': 'Send collection outage warnings',
                  'use_cards': 'Send image cards when available'}
        widgets = {'expires_at': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})}
        help_texts = {'chat_id': 'For example, -1001234567890 or @my_channel. Add your bot to the destination first.',
                      'expires_at': 'Leave blank for no expiry.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()

    def clean_chat_id(self):
        value = self.cleaned_data['chat_id'].strip()
        if not re.fullmatch(r'-?\d+|@[A-Za-z][A-Za-z0-9_]{4,}', value):
            raise forms.ValidationError('Enter a numeric chat ID or a channel username beginning with @.')
        return value

    def clean(self):
        data = super().clean()
        data['routing_type'] = data.get('routing_type') or 'level'
        if not data.get('plan_rank'):
            if data['routing_type'] == 'level':
                self.add_error('plan_rank', 'Choose a destination level.')
            # Preserve the dormant level so switching back does not lose it.
            data['plan_rank'] = self.instance.plan_rank or 1
        if data['routing_type'] == 'direct':
            data['send_health'] = False
        return data


class AlertSettingsForm(StyledForm, forms.ModelForm):
    bot_token = forms.CharField(required=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                               label='Telegram bot token', help_text='Leave blank to keep the saved token. The saved token is never displayed.')
    clear_token = forms.BooleanField(required=False, label='Remove the saved bot token')

    class Meta:
        model = AlertSettings
        fields = ['telegram_enabled', 'collection_timeout_minutes', 'max_event_age_seconds']
        labels = {'telegram_enabled': 'Enable Telegram delivery', 'collection_timeout_minutes': 'Warn after no fresh events (minutes)',
                  'max_event_age_seconds': 'Ignore events and queued round alerts older than (seconds)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['bot_token', 'telegram_enabled', 'collection_timeout_minutes', 'max_event_age_seconds', 'clear_token'])
        self.style()

    def clean_bot_token(self):
        token = self.cleaned_data['bot_token'].strip()
        if token and not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{20,}', token):
            raise forms.ValidationError('Enter a valid token supplied by BotFather.')
        return token

    def clean(self):
        data = super().clean()
        if data.get('clear_token') and data.get('bot_token'):
            self.add_error('clear_token', 'Choose either a replacement token or removal.')
        token = '' if data.get('clear_token') else data.get('bot_token') or get_config().bot_token
        if data.get('telegram_enabled') and not token:
            self.add_error('telegram_enabled', 'Add a bot token before enabling Telegram delivery.')
        return data
