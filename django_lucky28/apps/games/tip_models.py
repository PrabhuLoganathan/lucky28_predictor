"""Transactional tip state, settlement evidence, and retryable event outbox."""
from django.db import models
from django.utils import timezone


class TipStream(models.Model):
    key = models.CharField(max_length=80, primary_key=True)
    state = models.JSONField(default=dict)
    revision = models.PositiveBigIntegerField(default=0)
    delivery_destination = models.ForeignKey('games.AlertDestination', null=True, blank=True, on_delete=models.PROTECT)
    delivery_chat_id = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class TipRound(models.Model):
    stream = models.ForeignKey(TipStream, on_delete=models.CASCADE, related_name='rounds')
    game_id = models.CharField(max_length=80)
    sequence = models.PositiveBigIntegerField(null=True)
    status = models.CharField(max_length=16)
    source = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['stream', 'game_id'], name='unique_tip_round')]


class TipEvent(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    stream = models.ForeignKey(TipStream, on_delete=models.CASCADE, related_name='events')
    payload = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=240, blank=True)
