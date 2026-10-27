from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from .group_config import MAX_GROUP_THRESHOLD


class CategoryAlertSettings(models.Model):
    stream = models.OneToOneField('games.GroupAbsenceStream', on_delete=models.PROTECT, primary_key=True)
    enabled = models.BooleanField(default=False)
    notify_changes = models.BooleanField(default=True)
    snapshot = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=timezone.now)


class CategoryAlertRule(models.Model):
    settings = models.ForeignKey(CategoryAlertSettings, on_delete=models.CASCADE, related_name='rules')
    group_id = models.CharField(max_length=16)
    mode = models.CharField(max_length=7, choices=[('absence', 'Absence'), ('streak', 'Consecutive streak')])
    enabled = models.BooleanField(default=False)
    threshold = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(MAX_GROUP_THRESHOLD)])
    count = models.PositiveBigIntegerField(default=0)
    complete = models.BooleanField(default=False)
    lower_bound = models.BooleanField(default=False)
    last_number = models.PositiveSmallIntegerField(null=True)
    last_round = models.CharField(max_length=32, blank=True)
    last_timestamp = models.DateTimeField(null=True)
    period_start = models.CharField(max_length=32, blank=True)
    period_key = models.CharField(max_length=64, blank=True)
    notified = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['settings', 'group_id', 'mode'], name='unique_category_alert_rule'),
            models.CheckConstraint(condition=models.Q(threshold__isnull=True) | models.Q(threshold__gte=1, threshold__lte=MAX_GROUP_THRESHOLD), name='valid_category_threshold'),
            models.CheckConstraint(condition=models.Q(enabled=False) | models.Q(threshold__isnull=False), name='enabled_category_threshold'),
        ]


class CategoryAlertEvent(models.Model):
    rule = models.ForeignKey(CategoryAlertRule, on_delete=models.PROTECT, related_name='events')
    period_key = models.CharField(max_length=64)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True)
    resolution_snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['rule', 'period_key'], name='unique_category_alert_event')]


class CategoryAlertChange(models.Model):
    settings = models.ForeignKey(CategoryAlertSettings, on_delete=models.CASCADE)
    group_id = models.CharField(max_length=16)
    mode = models.CharField(max_length=7, blank=True)
    old_value = models.JSONField()
    new_value = models.JSONField()
    editor = models.CharField(max_length=150)
    saved_at = models.DateTimeField(default=timezone.now)
