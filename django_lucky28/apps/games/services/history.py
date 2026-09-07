from datetime import datetime, time, timedelta

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from games.forms import DayFilterForm
from games.models import GameRound


def completed_games():
    return GameRound.objects.filter(
        has_winner=True, winning_number__isnull=False, winner_event_ts__isnull=False,
    )


def day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def filter_period(queryset, start=None, end=None, field='winner_event_ts'):
    if start:
        queryset = queryset.filter(**{f'{field}__gte': day_start(start)})
    if end:
        queryset = queryset.filter(**{f'{field}__lt': day_start(end + timedelta(days=1))})
    return queryset


def daily_summaries(queryset=None):
    if queryset is None:
        queryset = completed_games()
    return queryset.order_by().annotate(day=TruncDate('winner_event_ts')).values('day').annotate(
        total=Count('id'),
        big=Count('id', filter=Q(winning_number__range=(14, 27))),
        small=Count('id', filter=Q(winning_number__range=(0, 13))),
        even=Count('id', filter=Q(winning_number__in=list(range(0, 28, 2)))),
        odd=Count('id', filter=Q(winning_number__in=list(range(1, 28, 2)))),
        winners=Sum('winner_count', default=0),
        prizes=Sum('win_total_energy', default=0),
        winner_records=Count('winner_count'),
        prize_records=Count('win_total_energy'),
        first_result=Min('winner_event_ts'),
        last_result=Max('winner_event_ts'),
    ).order_by('-day')


def day_context(params):
    days = list(completed_games().datetimes('winner_event_ts', 'day', order='DESC'))
    dates = [value.date() for value in days]
    form = DayFilterForm(params)
    valid = form.is_valid()
    selected = form.cleaned_data.get('date') if valid else None
    selected = selected or (dates[0] if dates else timezone.localdate())
    return {
        'selected_date': selected.isoformat(),
        'selected_day': selected,
        'previous_day': next((day.isoformat() for day in dates if day < selected), None),
        'next_day': next((day.isoformat() for day in reversed(dates) if day > selected), None),
        'day_form': form,
        'date_error': not valid,
        'history_timezone': timezone.get_current_timezone_name(),
    }
