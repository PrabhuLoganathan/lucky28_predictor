from django.core.paginator import Paginator
from django.shortcuts import render

from games.services.history import completed_games, daily_summaries, day_context, filter_period


def homepage(request):
    context = day_context(request.GET)
    day = context['selected_day']
    results = filter_period(completed_games(), day, day).order_by('-winner_event_ts', '-id')
    if context['date_error']:
        results = results.none()
    page = Paginator(results, 100).get_page(request.GET.get('page'))
    context.update({
        'results': page,
        'page_obj': page,
        'day_summary': daily_summaries(results).first(),
    })
    return render(request, 'gameapp/homepage.html', context, status=400 if context['date_error'] else 200)
