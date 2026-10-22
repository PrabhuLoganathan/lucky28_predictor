from urllib.parse import urlencode
from django.contrib import messages
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from .alert_management import management_access, paginated
from .group_views import selected_stream
from .category_config import CATEGORY_FAMILIES, CATEGORY_BY_ID
from .category_forms import CategorySettingsForm
from .group_config import MAX_GROUP_THRESHOLD
from .models import GroupAbsenceStream, CategoryAlertEvent, CategoryAlertChange
from .services.category_alerts import synchronize, save_settings, rule_status
from .services.alert_presentation import format_category_message


@management_access
@require_http_methods(['GET'])
def dashboard(request):
    config, rules = synchronize(selected_stream(request))
    indexed = {(rule.group_id, rule.mode): rule for rule in rules}
    sections = []
    for name, groups in CATEGORY_FAMILIES:
        rows = []
        for group in groups:
            absence, streak = indexed[(group.id, 'absence')], indexed[(group.id, 'streak')]
            rows.append(dict(group=group, absence=absence, streak=streak,
                absence_status=rule_status(config, absence), streak_status=rule_status(config, streak)))
        sections.append(dict(name=name, rows=rows))
    history = paginated(request, CategoryAlertEvent.objects.filter(rule__settings=config).order_by('-pk'))
    for event in history['page_obj']:
        event.message = format_category_message(event.snapshot)
        event.resolution_message = (format_category_message(event.resolution_snapshot)
            if event.resolution_snapshot.get('change_type') == 'ended' else '')
    return render(request, 'games/alerts/categories.html', dict(history, alert_tab='categories', config=config,
        sections=sections, streams=GroupAbsenceStream.objects.order_by('key'),
        memberships=[CATEGORY_BY_ID[key] for key in config.snapshot.get('memberships', [])]))


@management_access
@require_http_methods(['GET', 'POST'])
def configuration(request):
    config, rules = synchronize(selected_stream(request), evaluate_current=False)
    form = CategorySettingsForm(request.POST if request.method == 'POST' else None, config=config, rules=rules)
    if request.method == 'POST' and form.is_valid():
        editor = request.user.get_username() if request.user.is_authenticated else 'Local operator'
        save_settings(config.stream_id, form.cleaned_data['enabled'], form.rule_values(), editor,
                      notify_changes=form.cleaned_data['notify_changes'])
        messages.success(request, 'Row, column and category settings saved and applied immediately.')
        return redirect(f'{request.path}?{urlencode({"stream": config.stream_id})}')
    return render(request, 'games/alerts/category_settings.html', dict(alert_tab='categories', config=config,
        form=form, sections=form.sections(), maximum=MAX_GROUP_THRESHOLD,
        changes=CategoryAlertChange.objects.filter(settings=config).order_by('-pk')[:50]),
        status=400 if request.method == 'POST' else 200)
