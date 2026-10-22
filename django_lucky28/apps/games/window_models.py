"""Independent settings and durable events for the latest ten completed results."""
from django.db import models
from django.utils import timezone


class WindowAlertState(models.Model):
    stream = models.OneToOneField('games.GroupAbsenceStream', on_delete=models.CASCADE, primary_key=True)
    drought_enabled = models.BooleanField(default=False)
    repeat_enabled = models.BooleanField(default=False)
    snapshot = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=timezone.now)


class WindowAlertEvent(models.Model):
    stream = models.ForeignKey('games.GroupAbsenceStream', on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=[('drought', 'Drought'), ('repeat', 'Repeat')])
    occurrence_key = models.CharField(max_length=64)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    invalidated_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['stream', 'kind', 'occurrence_key'], name='unique_window_alert_event')]
