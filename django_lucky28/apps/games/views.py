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
