from rest_framework import serializers
from .models import GameRound

class GameRoundSerializer(serializers.ModelSerializer):
    class Meta:
        model = GameRound
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")
