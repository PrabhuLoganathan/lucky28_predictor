from django.contrib import admin
from .models import GameRound

@admin.register(GameRound)
class GameRoundAdmin(admin.ModelAdmin):
    list_display = ("game_no","game_type","has_pre","has_winner","winning_number","bet_users","updated_at")
    search_fields = ("game_no",)
    list_filter = ("has_pre","has_winner","game_type")
