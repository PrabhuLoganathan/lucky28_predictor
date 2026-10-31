"""First-party alert screens for the local dashboard and authenticated staff."""
from functools import wraps
from html import unescape
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST, require_http_methods

from .alert_forms import AlertRuleForm, AlertDestinationForm, AlertSettingsForm, VALUES
from .models import AlertRule, AlertDestination, AlertDelivery, AlertEvaluation, AlertRuntime, AlertSettings
from .services.alert_engine import default_rules
from .services.alert_presentation import render_card, format_message
from .services.alert_album import render_album, PAGE_TITLES
from .services.alert_settings import get_config, save_token
from .services.alert_worker import start_worker, stop_worker, worker_running
from .services.alerts import queue_delivery


def management_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        # Ignore forwarded headers: local control is limited to actual loopback clients.
        local = (request.META.get('REMOTE_ADDR') in ('127.0.0.1', '::1')
                 and urlsplit('http://' + request.get_host()).hostname in ('127.0.0.1', 'localhost', '::1'))
        if not local and not (request.user.is_authenticated and request.user.is_staff):
            return HttpResponseForbidden('Open this dashboard on localhost to manage alerts, or sign in with a staff account.')
        return view(request, *args, **kwargs)
    return never_cache(wrapped)


def paginated(request, queryset):
    query = request.GET.copy()
    query.pop('page', None)
    return {'page_obj': Paginator(queryset, 25).get_page(request.GET.get('page')), 'filter_query': query.urlencode()}


@management_access
def rules(request):
    queryset = AlertRule.objects.prefetch_related('destinations').order_by('series', 'title')
    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(Q(title__icontains=search) | Q(key__icontains=search))
    if request.GET.get('series') in VALUES:
        queryset = queryset.filter(series=request.GET['series'])
    if request.GET.get('enabled') in ('1', '0'):
        queryset = queryset.filter(enabled=request.GET['enabled'] == '1')
    return render(request, 'games/alerts/rules.html', dict(paginated(request, queryset),
        alert_tab='rules', series_choices=AlertRule.SERIES, total=AlertRule.objects.count(), enabled=AlertRule.objects.filter(enabled=True).count()))


@management_access
@require_http_methods(['GET', 'POST'])
def rule_edit(request, pk=None):
    instance = get_object_or_404(AlertRule, pk=pk) if pk else AlertRule(series='size', mode='streak')
    form = AlertRuleForm(request.POST if request.method == 'POST' else None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Rule saved. Changes apply to future rounds; queued alerts are checked against the current routing before sending.')
        return redirect('alert_rules')
    return render(request, 'games/alerts/form.html', dict(form=form, title='Edit rule' if pk else 'Create rule',
        subtitle='Choose the results and pattern to watch. Existing evidence stays unchanged.',
        alert_tab='rules', back_url='alert_rules', values_map=VALUES, rule_form=True),
        status=400 if request.method == 'POST' else 200)


@management_access
@require_POST
def rule_toggle(request, pk):
    rule = get_object_or_404(AlertRule, pk=pk)
    rule.enabled = request.POST.get('enabled') == '1'
    rule.save()
    messages.success(request, f'{rule.title}: {"enabled" if rule.enabled else "disabled"}.')
    return redirect('alert_rules')


@management_access
@require_http_methods(['GET', 'POST'])
def rule_delete(request, pk):
    rule = get_object_or_404(AlertRule, pk=pk)
    if request.method == 'POST':
        rule.delete()
        messages.success(request, 'Rule deleted. Saved evidence has been retained.')
        return redirect('alert_rules')
    return render(request, 'games/alerts/confirm.html', dict(alert_tab='rules', title='Delete rule',
        object_name=rule.title, explanation='This removes the rule from future evaluations. Past alert evidence remains available.', back_url='alert_rules'))


@management_access
@require_POST
def rule_defaults(request):
    count = 0
    for definition in default_rules():
        definition = dict(definition)
        _, created = AlertRule.objects.get_or_create(key=definition.pop('key'), defaults=definition)
        count += created
    messages.success(request, f'Added {count} missing default rules. Existing rules were kept.')
    return redirect('alert_rules')


@management_access
def destinations(request):
    return render(request, 'games/alerts/destinations.html', dict(
        paginated(request, AlertDestination.objects.order_by('name')), alert_tab='destinations', now=timezone.now()))


@management_access
@require_http_methods(['GET', 'POST'])
def destination_edit(request, pk=None):
    instance = get_object_or_404(AlertDestination, pk=pk) if pk else AlertDestination()
    form = AlertDestinationForm(request.POST if request.method == 'POST' else None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Destination saved.')
        return redirect('alert_destinations')
    return render(request, 'games/alerts/form.html', dict(form=form, title='Edit destination' if pk else 'Add destination',
        subtitle='Choose a Telegram chat, channel, or subscriber and the alerts it should receive.',
        alert_tab='destinations', back_url='alert_destinations'), status=400 if request.method == 'POST' else 200)


@management_access
@require_POST
def destination_toggle(request, pk):
    destination = get_object_or_404(AlertDestination, pk=pk)
    destination.enabled = request.POST.get('enabled') == '1'
    destination.save(update_fields=['enabled'])
    messages.success(request, f'{destination.name}: {"enabled" if destination.enabled else "disabled"}.')
    return redirect('alert_destinations')


@management_access
@require_http_methods(['GET', 'POST'])
def destination_delete(request, pk):
    destination = get_object_or_404(AlertDestination, pk=pk)
    if request.method == 'POST':
        try:
            destination.delete()
            messages.success(request, 'Destination deleted.')
        except ProtectedError:
            destination.enabled = False
            destination.save(update_fields=['enabled'])
            messages.info(request, 'Destination disabled. It is retained because it has delivery history or assigned alerts.')
        return redirect('alert_destinations')
    return render(request, 'games/alerts/confirm.html', dict(alert_tab='destinations', title='Remove destination',
        object_name=destination.name, explanation='Destinations with delivery history or assigned alerts will be disabled instead of deleted.', back_url='alert_destinations'))


@management_access
@sensitive_post_parameters('bot_token')
@require_http_methods(['GET', 'POST'])
def configuration(request):
    config = get_config()
    instance = AlertSettings.objects.filter(pk=1).first() or AlertSettings(pk=1,
        telegram_enabled=config.telegram_enabled, collection_timeout_minutes=config.collection_timeout_minutes,
        max_event_age_seconds=config.max_event_age_seconds)
    form = AlertSettingsForm(request.POST if request.method == 'POST' else None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            if form.cleaned_data['clear_token'] or form.cleaned_data['bot_token']:
                save_token('' if form.cleaned_data['clear_token'] else form.cleaned_data['bot_token'])
            form.save()
        except OSError:
            form.add_error(None, 'The token could not be saved. Check that the application can write its local state folder.')
        else:
            messages.success(request, 'Settings saved. The app and worker use them immediately.')
            return redirect('alert_settings')
    runtime = AlertRuntime.objects.filter(pk=1).first()
    return render(request, 'games/alerts/settings.html', dict(form=form, alert_tab='settings', token_saved=bool(config.bot_token),
        runtime=runtime, worker_live=worker_running(runtime)), status=400 if request.method == 'POST' else 200)


@management_access
@require_POST
def worker_action(request, action):
    if action == 'start':
        config = get_config()
        if config.telegram_enabled and not config.bot_token:
            messages.error(request, 'Save a bot token before starting Telegram delivery.')
        else:
            try:
                started = start_worker()
                messages.success(request, 'Worker is starting.' if started else 'Worker is already running or starting.')
            except (OSError, ImportError):
                messages.error(request, 'The worker could not start. Check local folder permissions and use macOS or Linux.')
    elif action == 'stop':
        stop_worker()
        messages.success(request, 'Stop requested. Any message already being sent will finish first.')
    else:
        return HttpResponse('Unknown worker action.', status=400)
    return redirect('alert_settings')


@management_access
@require_POST
def destination_test(request, pk):
    destination = get_object_or_404(AlertDestination, pk=pk)
    config = get_config()
    if not config.telegram_enabled or not config.bot_token:
        messages.error(request, 'Save a bot token and enable Telegram in Telegram & worker first.')
    elif not destination.enabled or (destination.expires_at and destination.expires_at <= timezone.now()):
        messages.error(request, 'Enable this destination and check its expiry before sending a test.')
    else:
        queue_delivery(f'test:{uuid4().hex}', destination, 'test', dict(game_no='Test message',
            captured_at=timezone.now().isoformat(), matches=[], detail='Your Lucky28 Telegram destination is configured.'))
        messages.success(request, 'Test message queued. Start the delivery worker to send it.' if not worker_running() else 'Test message queued for delivery.')
    return redirect('alert_destinations')


@management_access
def deliveries(request):
    queryset = AlertDelivery.objects.select_related('destination', 'evaluation').order_by('-pk')
    status = request.GET.get('status', '')
    if status in dict(AlertDelivery.STATUSES):
        queryset = queryset.filter(status=status)
    return render(request, 'games/alerts/deliveries.html', dict(paginated(request, queryset),
        alert_tab='deliveries', status_choices=AlertDelivery.STATUSES))


@management_access
def delivery_detail(request, pk):
    delivery = get_object_or_404(AlertDelivery.objects.select_related('destination', 'evaluation'), pk=pk)
    directory = Path(settings.ALERT_STATE_DIR) / 'artifacts'
    text = format_message(delivery.payload, delivery.kind)
    count = int((directory / f'{pk}.jpg').is_file())
    try:
        artifact = json.loads((directory / f'{pk}.json').read_text())
        count = artifact.get('image_count', count)
        data = artifact['data']
        text = json.loads(data['media'])[0]['caption'] if artifact['method'] == 'sendMediaGroup' else data.get('caption', data.get('text', text))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    return render(request, 'games/alerts/delivery_detail.html', dict(alert_tab='deliveries', delivery=delivery,
        formatted_text=unescape(text.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')),
        images=[dict(number=index, title=PAGE_TITLES[index-1] if count == 3 else 'Archived alert card')
                for index in range(1, min(count, 3)+1)]))


@management_access
@require_POST
def delivery_action(request, pk, action):
    delivery = get_object_or_404(AlertDelivery, pk=pk)
    if action == 'cancel':
        changed = AlertDelivery.objects.filter(pk=pk, status='pending').update(status='cancelled', error='Cancelled from the dashboard.')
    elif action == 'retry':
        changed = AlertDelivery.objects.filter(pk=pk, status='failed').update(status='pending', error='', available_at=timezone.now())
    else:
        return HttpResponse('Unknown delivery action.', status=400)
    if changed:
        messages.success(request, 'Delivery cancelled.' if action == 'cancel' else 'Delivery queued for retry; destination and round eligibility will be checked again.')
    else:
        messages.error(request, 'The delivery changed state or is not eligible for this action. Uncertain deliveries cannot be retried.')
    return redirect('alert_delivery_detail', pk=delivery.pk)


@management_access
def delivery_image(request, pk):
    get_object_or_404(AlertDelivery, pk=pk)
    page = request.GET.get('page', '1')
    if page not in ('1', '2', '3'):
        return HttpResponse('Unknown album page.', status=404)
    suffix = '' if page == '1' else f'-{page}'
    path = Path(settings.ALERT_STATE_DIR) / 'artifacts' / f'{pk}{suffix}.jpg'
    if not path.is_file():
        return HttpResponse('No image was archived for this delivery.', status=404)
    return FileResponse(path.open('rb'), content_type='image/jpeg')


@management_access
def evidence_detail(request, pk):
    evaluation = get_object_or_404(AlertEvaluation, pk=pk)
    return render(request, 'games/alerts/evidence.html', {'alert_tab': 'overview', 'evaluation': evaluation,
        'album_pages': [dict(number=i, title=title) for i, title in enumerate(PAGE_TITLES, 1)]})


@management_access
def evidence_card(request, pk):
    evaluation = get_object_or_404(AlertEvaluation, pk=pk)
    page = request.GET.get('page')
    if page is not None and page not in ('1', '2', '3'):
        return HttpResponse('Unknown album page.', status=404)
    try:
        content = render_album(evaluation.evidence)[int(page)-1] if page else render_card(evaluation.evidence)
        return HttpResponse(content, content_type='image/jpeg')
    except Exception:
        return HttpResponse('Image preview is unavailable. All evidence is available on the details page.', status=503)
