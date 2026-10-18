from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import AlertEvaluation, AlertOccurrence, AlertDelivery, AlertRule, AlertRuntime
from .services.alert_settings import get_config
from .services.alert_worker import worker_running


def monitor(request):
    latest = AlertEvaluation.objects.order_by('-observed_at', '-pk').first()
    occurrences = AlertOccurrence.objects.select_related('evaluation').order_by('-evaluation__observed_at', '-pk')
    if request.GET.get('activations') == '1':
        occurrences = occurrences.filter(is_activation=True)
    runtime = AlertRuntime.objects.filter(pk=1).first()
    worker_live = worker_running(runtime)
    return render(request, 'games/alerts.html', {
        'latest': latest, 'page_obj': Paginator(occurrences, 30).get_page(request.GET.get('page')),
        'activations_only': request.GET.get('activations') == '1',
        'runtime': runtime, 'worker_live': worker_live,
        'telegram_enabled': get_config().telegram_enabled, 'alert_tab': 'overview',
        'rules_enabled': AlertRule.objects.filter(enabled=True).count(),
        'deliveries': AlertDelivery.objects.select_related('evaluation').order_by('-pk')[:20],
    })


def evidence(request, pk):
    evaluation = get_object_or_404(AlertEvaluation, pk=pk)
    return JsonResponse(evaluation.evidence, json_dumps_params={'indent': 2})


def latest_alerts(request):
    evaluation = AlertEvaluation.objects.order_by('-observed_at', '-pk').first()
    return JsonResponse({'evaluation_id': evaluation.pk if evaluation else None,
                         'evidence': evaluation.evidence if evaluation else None})
