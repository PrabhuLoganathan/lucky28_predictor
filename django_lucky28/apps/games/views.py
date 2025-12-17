from django.shortcuts import render, get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.generics import RetrieveAPIView, ListAPIView
from .models import GameRound
from .serializers import GameRoundSerializer

def game_dashboard(request):
    games = GameRound.objects.all().order_by("-created_at")[:50]
    return render(request, "games/dashboard.html", {"games": games})

def game_dashboard_rows(request):
    games = GameRound.objects.all().order_by("-created_at")[:50]
    return render(request, "games/dashboard_rows.html", {"games": games})

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
    from django.utils.dateparse import parse_date

    # 1. Filter Logic
    qs = GameRound.objects.filter(has_winner=True, winning_number__isnull=False).order_by('winner_event_ts')
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        qs = qs.filter(winner_event_ts__date__gte=parse_date(start_date))
    if end_date:
        qs = qs.filter(winner_event_ts__date__lte=parse_date(end_date))
        
    # Limit if no filters to prevent generic overload (Streamlit used max 2000 usually)
    # But for Django we should perhaps be smarter. Let's just grab all if filtered, or last 2000 if not.
    if not (start_date or end_date):
        # We need them in ASC order for analysis, so slice from end? 
        # Django negative slicing is not supported on queryset.
        # So we order desc, take 2000, then reverse in python or subquery.
        # Let's effectively take last 2000.
        last_ids = GameRound.objects.filter(has_winner=True, winning_number__isnull=False).order_by('-id').values_list('id', flat=True)[:2000]
        qs = GameRound.objects.filter(id__in=list(last_ids)).order_by('id')

    # Convert to pandas Series for AnalysisService
    # We only need the winning number for most stats
    data = list(qs.values_list('winning_number', flat=True))
    if not data:
        return render(request, "games/pro_dashboard.html", {"no_data": True})

    series = pd.Series(data)
    
    # 2. Compute Stats
    # A. General & Recent
    total_len = len(series)
    # Recent Window (default 50)
    recent_n = int(request.GET.get('recent_n', 50))
    hotcold_n = int(request.GET.get('hotcold_n', 100))
    
    stats, freq, _ = AnalysisService.compute_stats(series)
    recent_series = series.tail(recent_n)
    recent_stats, _, recent_repeated = AnalysisService.compute_stats(recent_series)
    
    # B. Hot/Cold
    # Using window 'hotcold_n'
    window_series = series.tail(hotcold_n)
    window_freq = window_series.value_counts()
    hot_list, cold_list = AnalysisService.get_hot_cold(window_freq, top=5)
    
    # C. Streaks
    streaks = AnalysisService.get_streaks(series)
    
    # D. Empirical Probs (last 200)
    probs = AnalysisService.get_empirical_probs(series, window=200)
    
    # E. Repetition Analysis (Last 50 windows of size 10)
    # Just show last 50 rows of analysis
    repetition_rows = AnalysisService.analyze_window_repetition(series, window_size=10)
    if len(repetition_rows) > 50:
        repetition_rows = repetition_rows[:50]
        
    # F. Gap Analysis & Insights
    gap_data = AnalysisService.get_gap_analysis(series)
    insights = AnalysisService.get_predictions(gap_data, probs)
    
    # G. Chart Data (Serialize for Template)
    import json
    # 1. Trend (Last 50)
    # Convert numpy int64 to native python int list using tolist()
    trend_data = recent_series.tolist() 
    trend_labels = [f"#{i}" for i in range(1, len(trend_data)+1)]
    
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
            "start_date": start_date,
            "end_date": end_date,
            "total_games": total_len,
            "recent_n": recent_n,
            "hotcold_n": hotcold_n
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


# --- Import ---
from django.contrib import messages
from django.shortcuts import redirect
import csv
from io import TextIOWrapper
from datetime import datetime
from django.utils import timezone

def import_games(request):
    if request.method == "POST":
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, "No file uploaded.")
            return redirect('import_games')
        
        if not csv_file.name.endswith('.csv'):
            messages.error(request, "Please upload a CSV file.")
            return redirect('import_games')

        try:
            # Read CSV
            file_data = TextIOWrapper(csv_file.file, encoding='utf-8')
            reader = csv.DictReader(file_data)
            
            count = 0
            for row in reader:
                # Expected columns: issue, winning_number, time (optional)
                # Map various common names
                game_no = row.get('issue') or row.get('game_no') or row.get('Game No')
                winning_amt = row.get('result') or row.get('winning_number') or row.get('Number')
                
                # Metadata
                timestamp_str = row.get('timestamp') or row.get('time') or row.get('Time')
                winners_count = row.get('winners_count')
                prize_amount = row.get('prize_amount')

                if not winning_amt:
                    continue
                    
                # If game_no is missing but we have timestamp, generate one
                if not game_no and timestamp_str:
                    try:
                        # Attempt to parse timestamp
                        # Formats: 2025-12-14 21:37:00
                        ts = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        # Generate ID: YYYYMMDDHHMM
                        game_no = ts.strftime('%Y%m%d%H%M')
                    except ValueError:
                        pass # Keep game_no empty, will skip later

                if not game_no:
                    continue
                    
                winning_number = int(winning_amt)
                
                # Parse Timestamp
                winner_event_ts = timezone.now()
                if timestamp_str:
                    try:
                        naive_ts = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        if timezone.is_aware(timezone.now()):
                            winner_event_ts = timezone.make_aware(naive_ts)
                        else:
                            winner_event_ts = naive_ts
                    except:
                        pass

                # Create or Update
                defaults = {
                    'winning_number': winning_number,
                    'has_winner': True,
                    'winner_event_ts': winner_event_ts,
                }
                if winners_count: defaults['winner_count'] = int(winners_count)
                if prize_amount: defaults['win_total_energy'] = int(prize_amount)

                game, created = GameRound.objects.get_or_create(
                    game_no=game_no,
                    defaults=defaults
                )
                
                # If existing but incomplete
                if not created:
                    needs_save = False
                    if not game.has_winner:
                        game.winning_number = winning_number
                        game.has_winner = True
                        needs_save = True
                    
                    # Update fields if missing
                    if winners_count and not game.winner_count:
                        game.winner_count = int(winners_count)
                        needs_save = True
                    if prize_amount and not game.win_total_energy:
                        game.win_total_energy = int(prize_amount)
                        needs_save = True
                    if timestamp_str and not game.winner_event_ts:
                         game.winner_event_ts = winner_event_ts
                         needs_save = True
                         
                    if needs_save:
                        game.save()
                    
                # Calculate winner color
                if not game.winner_color:
                    game.winner_color = get_winning_color(winning_number)
                    game.save()
                
                # Also Trigger Signal Scanning for this imported game?
                # User said: "Once the signal is detected it should reset..."
                # If we import historical data, we might trigger OLD signals.
                # But that's probably okay for "Backfill".
                from .services.signals import SignalAnalyzer
                analyzer = SignalAnalyzer()
                analyzer.analyze_game(game)

                count += 1
                
            messages.success(request, f"Successfully imported {count} games.")
        except Exception as e:
            messages.error(request, f"Error processing file: {str(e)}")
            
        return redirect('import_games')
        
    return render(request, "games/import_games.html")
