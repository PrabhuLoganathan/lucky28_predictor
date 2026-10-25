"""Durable stream counters, manual settings, audit trail and alert events."""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from .group_config import MAX_GROUP_THRESHOLD
from django.utils import timezone


class GroupAbsenceStream(models.Model):
    key = models.CharField(max_length=32, primary_key=True)
    enabled = models.BooleanField(default=False)
    consecutive_ids = models.BooleanField(default=True)
    dirty = models.BooleanField(default=True)
    version = models.PositiveBigIntegerField(default=0)
    complete = models.BooleanField(default=False)
    incomplete_reason = models.TextField(blank=True)
    last_round = models.CharField(max_length=32, blank=True)
    last_timestamp = models.DateTimeField(null=True)
    observed_rounds = models.PositiveBigIntegerField(default=0)


class GroupAbsenceState(models.Model):
    stream = models.ForeignKey(GroupAbsenceStream, on_delete=models.CASCADE, related_name='groups')
    group_id = models.CharField(max_length=3)
    enabled = models.BooleanField(default=False)
    threshold = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(MAX_GROUP_THRESHOLD)])
    absence = models.PositiveBigIntegerField(default=0)
    last_number = models.PositiveSmallIntegerField(null=True)
    last_round = models.CharField(max_length=32, blank=True)
    last_timestamp = models.DateTimeField(null=True)
    period_key = models.CharField(max_length=64, blank=True)
    notified = models.BooleanField(default=False)
    complete = models.BooleanField(default=False)
    ending_enabled = models.BooleanField(default=False)
    ending_threshold = models.PositiveIntegerField(null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_GROUP_THRESHOLD)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['stream', 'group_id'], name='unique_group_stream'),
            models.CheckConstraint(condition=models.Q(threshold__isnull=True) | models.Q(threshold__gte=1, threshold__lte=MAX_GROUP_THRESHOLD), name='valid_group_threshold'),
            models.CheckConstraint(condition=models.Q(enabled=False) | models.Q(threshold__isnull=False), name='enabled_group_threshold_required'),
            models.CheckConstraint(condition=models.Q(ending_threshold__isnull=True) | models.Q(ending_threshold__gte=1, ending_threshold__lte=MAX_GROUP_THRESHOLD), name='valid_group_ending_threshold'),
            models.CheckConstraint(condition=models.Q(ending_enabled=False) | models.Q(ending_threshold__isnull=False), name='enabled_group_ending_threshold'),
        ]


class GroupAbsenceChange(models.Model):
    stream = models.ForeignKey(GroupAbsenceStream, on_delete=models.CASCADE)
    group_id = models.CharField(max_length=16)
    old_value = models.JSONField()
    new_value = models.JSONField()
    editor = models.CharField(max_length=150)
    saved_at = models.DateTimeField(default=timezone.now)


class GroupAbsenceEvent(models.Model):
    stream = models.ForeignKey(GroupAbsenceStream, on_delete=models.PROTECT)
    group_id = models.CharField(max_length=3)
    period_key = models.CharField(max_length=64)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['stream', 'group_id', 'period_key'], name='unique_group_absence_event')]


class GroupDataIssue(models.Model):
    stream = models.ForeignKey(GroupAbsenceStream, on_delete=models.CASCADE)
    round_id = models.CharField(max_length=32)
    reason = models.CharField(max_length=240)
    observed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['stream', 'round_id'], name='unique_group_data_issue')]


class GroupAbsenceEnding(models.Model):
    stream = models.ForeignKey(GroupAbsenceStream, on_delete=models.PROTECT)
    group_id = models.CharField(max_length=3)
    ending_round = models.CharField(max_length=32)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    invalidated = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['stream', 'group_id', 'ending_round'],
                                               name='unique_group_absence_ending')]
