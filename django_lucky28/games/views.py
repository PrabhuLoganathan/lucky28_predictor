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

    # WhatsApp Notification
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
