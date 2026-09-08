"""Authenticated Lucky Number ingestion and signal feedback for the local logger."""

import json
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import GameRound, SignalLog
from .serializers import GameRoundSerializer
from .services.analysis import AnalysisService
from .services.signals import SignalAnalyzer


class LoggerPermission(BasePermission):
    message = 'A valid X-Lucky28-Token header is required.'

    def has_permission(self, request, view):
        expected = settings.LOGGER_API_TOKEN
        if not expected:
            try:
                expected = settings.LOGGER_TOKEN_FILE.read_text().strip()
            except OSError:
                return False
        return bool(expected) and secrets.compare_digest(expected, request.headers.get('X-Lucky28-Token', ''))


class PreDataSerializer(serializers.Serializer):
    latest_statistic = serializers.CharField(max_length=32, required=False, allow_blank=True)
    rate_big = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), required=False)
    rate_small = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), required=False)
    rate_even = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), required=False)
    rate_odd = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'), max_value=Decimal('100'), required=False)
    bet_users = serializers.IntegerField(min_value=0, required=False)
    bet_total_energy = serializers.IntegerField(min_value=0, required=False)
    surplus_seconds = serializers.IntegerField(min_value=0, required=False)


class WinnerDataSerializer(serializers.Serializer):
    winning_number = serializers.IntegerField(min_value=0, max_value=27)
    reward_numbers = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=9), min_length=3, max_length=3, required=False)
    winner_count = serializers.IntegerField(min_value=0, required=False)
    win_total_energy = serializers.IntegerField(min_value=0, required=False)
    bet_users = serializers.IntegerField(min_value=0, required=False)
    bet_total_energy = serializers.IntegerField(min_value=0, required=False)
    status = serializers.ChoiceField(choices=[3, 4])

    def validate(self, data):
        if 'reward_numbers' in data and sum(data['reward_numbers']) != data['winning_number']:
            raise serializers.ValidationError('Reward numbers must add up to the winning number.')
        return data


class LoggerEventSerializer(serializers.Serializer):
    schema_version = serializers.ChoiceField(choices=[1])
    game_type = serializers.ChoiceField(choices=['lucky28'])
    game_no = serializers.CharField(max_length=32)
    phase = serializers.ChoiceField(choices=['pre', 'winner'])
    observed_at = serializers.DateTimeField()
    data = serializers.DictField()

    def validate(self, data):
        nested = (PreDataSerializer if data['phase'] == 'pre' else WinnerDataSerializer)(data=data['data'])
        nested.is_valid(raise_exception=True)
        data['data'] = nested.validated_data
        return data


class EventConflict(APIException):
    status_code = 409
    default_detail = 'This event conflicts with a saved game.'


@api_view(['GET'])
@authentication_classes([])
@permission_classes([LoggerPermission])
def health(request):
    return Response({'service': 'lucky28', 'schema_version': 1, 'game_type': 'lucky28'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([LoggerPermission])
def events(request):
    serializer = LoggerEventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    event = serializer.validated_data
    data = event['data']
    observed = event['observed_at']
    with transaction.atomic():
        game, _ = GameRound.objects.select_for_update().get_or_create(game_no=event['game_no'])
        if game.game_type not in (None, '', 'lucky28'):
            raise EventConflict('This game ID belongs to a different game type.')
        game.game_type = 'lucky28'
        duplicate = False
        raw = json.loads(json.dumps(data, cls=DjangoJSONEncoder))
        if event['phase'] == 'pre':
            if game.pre_event_ts and observed <= game.pre_event_ts:
                duplicate = True
            else:
                for field, value in data.items():
                    if field != 'surplus_seconds' and not (game.has_winner and field in ('bet_users', 'bet_total_energy')):
                        setattr(game, field, value)
                game.has_pre = True
                game.pre_event_ts = observed
                game.pre_raw = raw
                game.save()
        else:
            duplicate = game.has_winner
            if duplicate and game.winning_number != data['winning_number']:
                raise EventConflict('A different winner is already saved for this game.')
            if not duplicate:
                for field, value in data.items():
                    setattr(game, field, value)
                game.has_winner = True
                game.winner_event_ts = observed
                game.winner_raw = raw
                game.winner_color = AnalysisService.get_color(game.winning_number)
                game.reward_type = f'{game.size_label}/{game.parity_label}'
                game.save()
                SignalAnalyzer(notify=False).analyze_game(game)
        signals = list(SignalLog.objects.filter(game=game).order_by('id').values(
            'id', 'rule__name', 'rule__dimension', 'rule__target_value', 'rule__severity', 'value',
        )) if event['phase'] == 'winner' else []
    return Response({'accepted': True, 'duplicate': duplicate, 'game': GameRoundSerializer(game).data, 'signals': signals})
