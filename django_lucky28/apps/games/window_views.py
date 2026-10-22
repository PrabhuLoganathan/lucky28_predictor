from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .alert_management import management_access, paginated
from .group_views import selected_stream
from .models import GroupAbsenceStream, WindowAlertEvent
from .services.window_alerts import synchronize, save_settings


class WindowAlertForm(forms.Form):
    drought_enabled = forms.BooleanField(required=False, label='Enable drought alerts',
        help_text='Alert once when the latest 10 results are all different. Re-arm after a window contains a repeat.',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    repeat_enabled = forms.BooleanField(required=False, label='Enable repeat alerts',
        help_text='Alert when the newest result matches any of the previous 9. An old pair remaining in the window does not send another alert.',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))


@management_access
@require_http_methods(['GET', 'POST'])
def dashboard(request):
    key = selected_stream(request)
    state = synchronize(key, evaluate_current=request.method == 'GET')
    form = WindowAlertForm(request.POST if request.method == 'POST' else None,
        initial={'drought_enabled': state.drought_enabled, 'repeat_enabled': state.repeat_enabled})
    if request.method == 'POST' and form.is_valid():
        save_settings(key, **form.cleaned_data)
        messages.success(request, '10-game alert settings saved and applied immediately.')
        return redirect(f'{request.path}?{urlencode({"stream": key})}')
    return render(request, 'games/alerts/windows.html', dict(
        paginated(request, WindowAlertEvent.objects.filter(stream_id=key).order_by('-pk')),
        alert_tab='windows', state=state, window=state.snapshot, form=form,
        streams=GroupAbsenceStream.objects.order_by('key')), status=400 if request.method == 'POST' else 200)
