import re
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .services import tips


@never_cache
@require_GET
def dashboard(request):
    return render(request, 'games/tips.html')


@never_cache
@require_GET
def live(request):
    stream = request.GET.get('monitor', settings.TIP_MONITOR_ID)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', stream):
        return JsonResponse({'error': 'Invalid monitor ID.'}, status=400)
    return JsonResponse(tips.dashboard(stream))
