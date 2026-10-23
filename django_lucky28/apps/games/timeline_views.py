import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse, HttpResponseNotModified
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .services.timeline import TRACKS, available_streams, build_timeline, recent_games, watermark


@never_cache
@ensure_csrf_cookie
@require_GET
def dashboard(request):
    return render(request, 'games/alerts/timeline.html', {'alert_tab': 'timeline'})


def stream(request):
    key = request.GET.get('stream', 'lucky28')
    return key if key in available_streams() else None


@never_cache
@require_GET
def live(request):
    key = stream(request)
    enabled = request.GET.get('tracks')
    enabled = list(TRACKS) if enabled is None else list(dict.fromkeys(filter(None, enabled.split(','))))
    if key is None or any(item not in TRACKS for item in enabled):
        return JsonResponse({'error': 'Unknown stream or tracker.'}, status=400)
    data = build_timeline(key, enabled, request.session.get('timeline_cutoffs', {}).get(key, {}))
    data['catalog'] = [dict(key=k, title=v[0]) for k, v in TRACKS.items()]
    data['streams'] = available_streams()
    # Hash actual snapshot contents so corrections, imports, evidence changes and
    # session-specific reset cutoffs invalidate the response without a stale cache.
    versioned = {name: value for name, value in data.items() if name != 'checked_at'}
    etag = '"' + hashlib.sha256(json.dumps(versioned, cls=DjangoJSONEncoder, separators=(',', ':')).encode()).hexdigest() + '"'
    response = HttpResponseNotModified() if request.headers.get('If-None-Match') == etag else JsonResponse(data)
    response['ETag'] = etag
    response['X-Timeline-Checked-At'] = data['checked_at']
    return response


@never_cache
@require_POST
def reset(request, tracker_key):
    key = stream(request)
    if key is None or tracker_key not in TRACKS:
        return JsonResponse({'error': 'Unknown stream or tracker.'}, status=400)
    action = request.POST.get('action', 'reset')
    if action not in ('reset', 'restore'):
        return JsonResponse({'error': 'Unknown action.'}, status=400)
    cutoffs = request.session.get('timeline_cutoffs', {})
    current = cutoffs.setdefault(key, {})
    if action == 'restore':
        current.pop(tracker_key, None)
    else:
        games = recent_games(key)
        current[tracker_key] = watermark(games[0]) if games else ['', 0]
    request.session['timeline_cutoffs'] = cutoffs
    return JsonResponse({'success': True, 'cutoff': current.get(tracker_key)})
