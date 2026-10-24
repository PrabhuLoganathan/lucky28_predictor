"""Read-only pages and exports for the independent Number Game case study."""

import json
import re

from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .services import case_study


def _stream(request):
    value = request.GET.get('stream', 'lucky28')
    return value if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value) else None


@never_cache
@require_GET
def dashboard(request):
    return render(request, 'games/case_study.html')


@never_cache
@require_GET
def live(request):
    stream = _stream(request)
    if stream is None:
        return JsonResponse({'error': 'Invalid stream.'}, status=400)
    return JsonResponse(case_study.dashboard(stream=stream))


@never_cache
@require_GET
def detail(request, case_id):
    record = case_study.case_detail(case_id)
    if record is None:
        return JsonResponse({'error': 'Case not found.'}, status=404)
    return JsonResponse(record)


@never_cache
@require_GET
def export(request):
    stream = _stream(request)
    if stream is None:
        return JsonResponse({'error': 'Invalid stream.'}, status=400)

    def lines():
        for record in case_study.export_records(stream=stream):
            yield json.dumps(record, cls=DjangoJSONEncoder, ensure_ascii=False) + '\n'

    response = StreamingHttpResponse(lines(), content_type='application/x-ndjson; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="number-case-study-{stream}.jsonl"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
