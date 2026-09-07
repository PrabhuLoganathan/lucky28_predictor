import csv

from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.generics import RetrieveAPIView, ListAPIView
from .models import GameRound
from .serializers import GameRoundSerializer
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from .forms import AnalysisFilterForm, DateRangeForm, DeleteDayForm
from .services.history import completed_games, daily_summaries, day_context, filter_period


def dashboard_context(request):
    context = day_context(request.GET)
    day = context['selected_day']
    games = GameRound.objects.filter(Q(has_winner=False) | Q(winner_event_ts__isnull=False)).annotate(
        event_ts=Coalesce('winner_event_ts', 'pre_event_ts', 'created_at'),
    )
    games = filter_period(games, day, day, field='event_ts').order_by('-event_ts', '-id')
    if context['date_error']:
        games = games.none()
    page = Paginator(games, 50).get_page(request.GET.get('page'))
    context.update({
        'games': page,
        'page_obj': page,
        'day_summary': daily_summaries(filter_period(completed_games(), day, day)).first(),
    })
    return context

def game_dashboard(request):
    context = dashboard_context(request)
    return render(request, "games/dashboard.html", context, status=400 if context['date_error'] else 200)

def game_dashboard_rows(request):
    context = dashboard_context(request)
    return render(request, "games/dashboard_rows.html", context, status=400 if context['date_error'] else 200)


def daily_archive(request):
    form = DateRangeForm(request.GET)
    valid = form.is_valid()
    games = completed_games()
    if valid:
        games = filter_period(games, form.cleaned_data['start_date'], form.cleaned_data['end_date'])
    else:
        games = games.none()
    days = daily_summaries(games)
    page = Paginator(days, 30).get_page(request.GET.get('page'))
    return render(request, 'games/daily_archive.html', {
        'archive_form': form,
        'days': page,
        'page_obj': page,
        'saved_days': page.paginator.count,
        'saved_games': games.count(),
        'undated_games': GameRound.objects.filter(
            has_winner=True, winning_number__isnull=False, winner_event_ts__isnull=True,
        ).count(),
        'history_timezone': timezone.get_current_timezone_name(),
    }, status=200 if valid else 400)


def export_day(request):
    context = day_context(request.GET)
    if context['date_error']:
        return HttpResponse('Enter a valid date in YYYY-MM-DD format.', status=400)
    day = context['selected_day']
    games = filter_period(completed_games(), day, day).order_by('-winner_event_ts', '-id')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="lucky28-{day.isoformat()}.csv"'
    writer = csv.writer(response, lineterminator='\n')
    writer.writerow(['result', 'timestamp', 'winners_count', 'prize_amount', 'game_no'])
    for game in games.iterator():
        writer.writerow([
            game.winning_number,
            timezone.localtime(game.winner_event_ts).replace(tzinfo=None).isoformat(sep=' '),
            game.winner_count, game.win_total_energy, game.game_no,
        ])
    return response


@require_http_methods(['GET', 'POST'])
def delete_day(request):
    form = DeleteDayForm(request.POST if request.method == 'POST' else request.GET)
    valid = form.is_valid()
    day = form.cleaned_data.get('date')
    games = filter_period(completed_games(), day, day) if day else completed_games().none()

    if request.method == 'POST' and valid:
        if not form.cleaned_data['confirm']:
            form.add_error('confirm', 'Confirm deletion to remove this day.')
            valid = False
        else:
            # Django deletes the results and their related signal logs atomically.
            _, deleted = games.delete()
            count = deleted.get(GameRound._meta.label, 0)
            if count:
                messages.success(request, f'Deleted {count:,} saved results for {day.isoformat()} (UTC).')
            else:
                messages.info(request, f'No saved results remain for {day.isoformat()} (UTC).')
            return redirect('daily_archive')

    return render(request, 'games/delete_day.html', {
        'delete_form': form,
        'selected_date': day.isoformat() if day else '',
        'result_count': games.count(),
        'history_timezone': timezone.get_current_timezone_name(),
    }, status=200 if valid else 400)


def game_detail(request, game_no):
    return render(request, "games/detail.html", {"game_no": game_no})

@api_view(["POST"])
def upsert_pre(request):
    game_no = request.data.get("game_no")
    if not game_no:
        return Response({"error": "game_no is required"}, status=400)

    obj, created = GameRound.objects.get_or_create(game_no=game_no)

    # update pre fields
    for f in ["game_type","latest_statistic","rate_big","rate_small","rate_even","rate_odd","pre_event_ts","pre_raw"]:
        if f in request.data:
            setattr(obj, f, request.data[f])

    obj.has_pre = True
    obj.save()

    return Response(GameRoundSerializer(obj).data, status=201 if created else 200)

def get_winning_color(number):
    if number is None:
        return None
    
    n = int(number)
    if n in [0, 1, 26, 27]: return "Red"
    if n in [2, 3, 24, 25]: return "Yellow"
    if n in [4, 5, 22, 23]: return "Pink"
    if n in [6, 7, 20, 21]: return "Blue"
    if n in [8, 9, 18, 19]: return "Cyan"
    if n in [10, 11, 16, 17]: return "Green"
    if n in [12, 13, 14, 15]: return "Grey"
    return "Unknown"

@api_view(["PATCH"])
def update_winner(request, game_no):
    try:
        obj = GameRound.objects.get(game_no=game_no)
    except GameRound.DoesNotExist:
        # Option: auto-create on winner update (your call)
        obj = GameRound(game_no=game_no)

    for f in [
        "winning_number","reward_numbers","reward_type",
        "winner_count","bet_users","bet_total_energy","win_total_energy","net_energy_system",
        "event_type","is_reward","status","winner_event_ts","winner_raw","game_type"
    ]:
        if f in request.data:
            setattr(obj, f, request.data[f])

    # Determine Color
    if obj.winning_number is not None:
        obj.winner_color = get_winning_color(obj.winning_number)

    obj.has_winner = True
    obj.save()

    # 1. Run Signal Detection (Metrics & Alerts)
    try:
        from .services.signals import SignalAnalyzer
        SignalAnalyzer().analyze_game(obj)
    except Exception as e:
        print(f"Signal Analyzer Error: {e}")

    # 2. WhatsApp Winner Notification
    # Trigger only if we have a winner and notification is enabled/valid
    if obj.has_winner:
        try:
            from .services.whatsapp import WhatsAppService
            import os
            
            # Determine Recipient: 
            # 1. 'customer_phone' in payload
            # 2. 'ADMIN_PHONE' env var
            recipient = request.data.get("customer_phone") or os.environ.get("ADMIN_PHONE")
            
            if recipient:
                service = WhatsAppService()
                service.send_winner_notification(recipient, obj)
            else:
                print("Skipping WhatsApp: No recipient number found (provide 'customer_phone' or set ADMIN_PHONE)")

        except Exception as e:
            print(f"Error triggering WhatsApp notification: {e}")

    return Response(GameRoundSerializer(obj).data, status=200)

class GameRoundRetrieve(RetrieveAPIView):
    serializer_class = GameRoundSerializer
    lookup_field = "game_no"
    queryset = GameRound.objects.all()

class GameRoundList(ListAPIView):
    serializer_class = GameRoundSerializer
    queryset = GameRound.objects.all().order_by("-created_at")

# Signals UI
def signals_dashboard(request):
    from .models import SignalLog, SignalRule
    from .services.signals import SignalAnalyzer

    # Get recent logs
    recent_signals = SignalLog.objects.select_related('rule', 'game').order_by('-triggered_at')[:20]
    
    # Calculate Live Streaks for display (Re-using logic from Analyzer)
    # We'll just fetch brief history and run the calculator
    history = GameRound.objects.filter(
        has_winner=True, 
        winning_number__isnull=False
    ).order_by('-winner_event_ts')[:100]
    
    current_stats = SignalAnalyzer()._calculate_current_stats(history)
    
    # Format stats for template: Separating Streaks and Droughts
    streaks = {k:v for k,v in current_stats.items() if k.startswith('STREAK')}
    droughts = {k:v for k,v in current_stats.items() if k.startswith('DROUGHT')}

    return render(request, "games/signals_dashboard.html", {
        "recent_signals": recent_signals,
        "streaks": streaks,
        "droughts": droughts
    })

def signals_config(request):
    from .models import SignalRule
    rules = SignalRule.objects.all().order_by('dimension', 'name')
    return render(request, "games/signals_config.html", {
        "rules": rules,
        "dimensions": SignalRule.DIMENSIONS,
        "rule_types": SignalRule.RULE_TYPES,
        "severities": SignalRule.SEVERITY
    })

@api_view(["POST"])
def signals_config_action(request, action):
    from .models import SignalRule
    
    if action == "add":
        print(f"DEBUG: Adding Rule Payload: {request.data}")
        try:
            SignalRule.objects.create(
                name=request.data.get("name"),
                rule_type=request.data.get("rule_type"),
                dimension=request.data.get("dimension"),
                target_value=request.data.get("target_value"),
                threshold=int(request.data.get("threshold")),
                severity=request.data.get("severity")
            )
            return Response({"success": True})
        except Exception as e:
            print(f"ERROR Adding Rule: {e}")
            return Response({"error": str(e)}, status=400)

    elif action == "delete":
        rule_id = request.data.get("id")
        SignalRule.objects.filter(id=rule_id).delete()
        return Response({"success": True})

    elif action == "toggle":
        rule_id = request.data.get("id")
        try:
            rule = SignalRule.objects.get(id=rule_id)
            rule.is_active = not rule.is_active
            rule.save()
            return Response({"success": True, "is_active": rule.is_active})
        except SignalRule.DoesNotExist:
            return Response({"error": "Rule not found"}, status=404)

    return Response({"error": "Invalid action"}, status=400)

# --- Pro Analysis Dashboard ---
def pro_dashboard(request):
    """
    Main view for the advanced Lucky 28 stats dashboard.
    Ported from Streamlit.
    """
    from .services.analysis import AnalysisService
    import pandas as pd
    form = AnalysisFilterForm(request.GET)
    base_context = {
        'analysis_form': form,
        'history_timezone': timezone.get_current_timezone_name(),
    }
    if not form.is_valid():
        return render(request, 'games/pro_dashboard.html', {
            **base_context, 'no_data': True,
        }, status=400)

    start_date = form.cleaned_data['start_date']
    end_date = form.cleaned_data['end_date']
    selected_date = form.cleaned_data['date']
    if selected_date or not (start_date or end_date):
        selection = day_context({'date': selected_date.isoformat()} if selected_date else {})
        base_context.update(selection)
        start_date = end_date = selection['selected_day']

    qs = filter_period(completed_games(), start_date, end_date).order_by('winner_event_ts', 'id')
    recent_n = form.cleaned_data['recent_n'] or 50
    hotcold_n = form.cleaned_data['hotcold_n'] or 500
    base_context['filters'] = {
        'start_date': start_date.isoformat() if start_date else '',
        'end_date': end_date.isoformat() if end_date else '',
        'recent_n': recent_n,
        'hotcold_n': hotcold_n,
        'total_games': 0,
    }

    # Convert to pandas DataFrame for AnalysisService
    # We need winning_number and game_no/id for advanced analysis
    df = pd.DataFrame(list(qs.values('id', 'game_no', 'winning_number', 'winner_event_ts', 'winner_count', 'win_total_energy')))
    if df.empty:
        return render(request, "games/pro_dashboard.html", {**base_context, "no_data": True})

    series = df['winning_number']
    
    # Instantiate Service
    service = AnalysisService(df)
    
    # 2. Compute Stats
    # A. General & Recent
    total_len = len(series)
    # Recent Window (default 50)
    recent_series = series.tail(recent_n)
    
    stats, _, _ = AnalysisService.compute_stats(series)
    recent_stats, _, recent_repeated = AnalysisService.compute_stats(recent_series)
    
    # B. Hot/Cold
    hotcold_series = series.tail(hotcold_n)
    hot_list, cold_list = AnalysisService.get_hot_cold(hotcold_series.value_counts(), top=5)
    
    # C. Streaks (Longest/Current)
    streaks = AnalysisService.get_streaks(series)
    
    # D. Empirical Probs
    probs = AnalysisService.get_empirical_probs(series, window=500)
    
    # E. Repetition Analysis (Last 50 windows of size 10)
    # Using new instance method
    repetition_rows = service.get_repetition_analysis(window=10, limit=50)
        
    # F. Gap Analysis & Insights
    gap_data = AnalysisService.get_gap_analysis(series)
    insights = AnalysisService.get_predictions(gap_data, probs)
    
    # G. Chart Data (Serialize for Template)
    import json
    # 1. Trend (Last 50)
    # Convert numpy int64 to native python int list using tolist()
    trend_data = recent_series.tolist() 
    trend_labels = [timezone.localtime(value).strftime('%m-%d %H:%M')
                    for value in df['winner_event_ts'].tail(recent_n)]
    
    # 2. Number Freq (Full Series)
    # 0-27
    full_freq = series.value_counts().sort_index()
    freq_data = []
    freq_labels = [str(i) for i in range(28)]
    for i in range(28):
        freq_data.append(int(full_freq.get(i, 0)))

    chart_payload = {
        "trend": {
            "labels": trend_labels,
            "data": trend_data
        },
        "freq": {
            "labels": freq_labels,
            "data": freq_data
        },
        "dist": {
            "big": stats['big'], "small": stats['small'],
            "odd": stats['odd'], "even": stats['even']
        }
    }

    context = {
        **base_context,
        "stats": stats,
        "recent_stats": recent_stats,
        "hot_list": hot_list,
        "cold_list": cold_list,
        "streaks": streaks,
        "probs": probs,
        "repetition_rows": repetition_rows,
        "recent_repeated": recent_repeated.to_dict('records') if not recent_repeated.empty else [],
        "gap_data": gap_data,
        "insights": insights,
        "charts_json": json.dumps(chart_payload),
        "filters": {
            **base_context['filters'],
            "total_games": total_len,
        }
    }
    
    return render(request, "games/pro_dashboard.html", context)


@api_view(["POST"])
def api_analysis_simulate(request):
    from .services.analysis import AnalysisService
    
    # Expects: target_prob, current_len, sims, max_extra
    try:
        p = float(request.data.get("prob", 0.5))
        c = int(request.data.get("current_len", 1))
        sims = int(request.data.get("sims", 1000))
        extra = int(request.data.get("max_extra", 20))
        
        results = AnalysisService.simulate_streak(p, c, sims, extra)
        return Response(results)
    except Exception as e:
        return Response({"error": str(e)}, status=400)


def import_games(request):
    if request.method == "POST":
        from .services.imports import import_history

        files = request.FILES.getlist('csv_file')
        if not files:
            messages.error(request, 'Please select at least one CSV file.')
            return redirect('import_games')
        try:
            summary = import_history(files)
            dates = ', '.join(day.isoformat() for day in sorted(summary['dates']))
            messages.success(request, (
                f"Added {summary['created']} results, updated {summary['updated']}, "
                f"already saved {summary['unchanged']}. Dates: {dates}."
            ))
        except (ValueError, UnicodeError, csv.Error) as error:
            messages.error(request, f'Import cancelled; no changes saved. {error}')
        return redirect('import_games')

    return render(request, 'games/import_games.html', {
        'history_timezone': timezone.get_current_timezone_name(),
    })
