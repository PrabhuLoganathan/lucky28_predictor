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

    obj.has_winner = True
    obj.save()

    return Response(GameRoundSerializer(obj).data, status=200)

class GameRoundRetrieve(RetrieveAPIView):
    serializer_class = GameRoundSerializer
    lookup_field = "game_no"
    queryset = GameRound.objects.all()

class GameRoundList(ListAPIView):
    serializer_class = GameRoundSerializer
    queryset = GameRound.objects.all().order_by("-created_at")
