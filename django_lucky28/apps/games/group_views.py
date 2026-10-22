from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .alert_management import management_access, paginated
from .group_config import GROUP_BY_ID, MAX_GROUP_THRESHOLD
from .group_forms import GroupAbsenceSettingsForm
from .models import GroupAbsenceStream, GroupAbsenceChange, GroupAbsenceEvent
from .services.group_absence import synchronize, save_settings, alert_state
from .services.alert_presentation import format_group_message


def selected_stream(request):
    key = request.GET.get('stream', 'lucky28')
    return key if GroupAbsenceStream.objects.filter(pk=key).exists() else 'lucky28'


@management_access
@require_http_methods(['GET'])
def dashboard(request):
    stream, states = synchronize(selected_stream(request))
    history = paginated(request, GroupAbsenceEvent.objects.filter(stream=stream).order_by('-pk'))
    for event in history['page_obj']:
        event.message = format_group_message(event.snapshot)
    return render(request, 'games/alerts/groups.html', dict(history, alert_tab='groups', stream=stream,
        streams=GroupAbsenceStream.objects.order_by('key'),
        rows=[dict(group=GROUP_BY_ID[state.group_id], state=state, status=alert_state(stream, state)) for state in states]))


@management_access
@require_http_methods(['GET', 'POST'])
def configuration(request):
    key = selected_stream(request)
    # A failed save must not evaluate unsaved inputs or change saved settings.
    stream, states = synchronize(key, evaluate_current=False)
    form = GroupAbsenceSettingsForm(request.POST if request.method == 'POST' else None, stream=stream, states=states)
    if request.method == 'POST' and form.is_valid():
        editor = request.user.get_username() if request.user.is_authenticated else 'Local operator'
        save_settings(key, form.cleaned_data['enabled'], form.group_values(), editor)
        messages.success(request, 'Group absence settings saved and applied immediately.')
        return redirect(f'{request.path}?{urlencode({"stream": key})}')
    return render(request, 'games/alerts/group_settings.html', dict(alert_tab='groups', form=form,
        group_rows=form.group_rows(), stream=stream, maximum=MAX_GROUP_THRESHOLD,
        changes=GroupAbsenceChange.objects.filter(stream=stream).order_by('-pk')[:50],
        display_timezone=timezone.get_current_timezone_name()), status=400 if request.method == 'POST' else 200)
