"""Persistent alert configuration, immutable evidence and delivery outbox."""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class AlertRule(models.Model):
    MODES = [(s, s.replace('_', ' ').title()) for s in (
        'every_game', 'streak', 'absence', 'density', 'density_low', 'breaker', 'alternating',
    )]
    SERIES = [(s, s.title()) for s in ('size', 'parity', 'color', 'number')]
    key = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=120)
    series = models.CharField(max_length=16, choices=SERIES)
    mode = models.CharField(max_length=20, choices=MODES)
    values = models.JSONField(default=list, blank=True, help_text='Exact values, e.g. ["Big"] or ["Odd", "Even"].')
    breaker_value = models.CharField(max_length=32, blank=True)
    threshold = models.PositiveIntegerField(default=4, validators=[MaxValueValidator(1000)])
    window = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(1000)])
    revision = models.PositiveIntegerField(default=1, editable=False)
    enabled = models.BooleanField(default=True)
    session_only = models.BooleanField(default=False)
    min_plan_rank = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])

    def clean(self):
        super().clean()
        allowed = {'size': {'Big', 'Small'}, 'parity': {'Odd', 'Even'},
                   'color': {'Red', 'Yellow', 'Pink', 'Blue', 'Cyan', 'Green', 'Grey'},
                   'number': {str(n) for n in range(28)}}
        if not isinstance(self.values, list) or any(not isinstance(v, str) or v not in allowed.get(self.series, set()) for v in self.values):
            raise ValidationError({'values': 'Use a list of exact values for the selected series.'})
        if self.mode != 'every_game' and not self.values:
            raise ValidationError({'values': 'At least one value is required.'})
        if self.mode in ('streak', 'absence', 'breaker') and len(self.values) != 1:
            raise ValidationError({'values': 'This mode requires exactly one value.'})
        if self.mode == 'alternating' and len(set(self.values)) != 2:
            raise ValidationError({'values': 'Alternating requires two distinct values.'})
        if self.threshold is None or self.window is None:
            return  # Required-field errors are supplied by field validation.
        if self.mode in ('density', 'density_low') and (not self.window or self.threshold > self.window):
            raise ValidationError({'window': 'Use a nonzero window at least as large as the threshold.'})
        if self.mode != 'density_low' and self.threshold < 1:
            raise ValidationError({'threshold': 'Use a positive threshold.'})
        if self.mode == 'breaker' and (self.breaker_value not in allowed.get(self.series, set()) or self.breaker_value in self.values):
            raise ValidationError({'breaker_value': 'Choose a different, valid value to break the streak.'})

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            fields = ('series', 'mode', 'values', 'breaker_value', 'threshold', 'window', 'session_only', 'enabled', 'min_plan_rank')
            self.revision = previous.revision + int(any(getattr(previous, f) != getattr(self, f) for f in fields))
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'revision'}
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class AlertDestination(models.Model):
    name = models.CharField(max_length=100)
    chat_id = models.CharField(max_length=80, unique=True)
    plan_rank = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])
    enabled = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    send_results = models.BooleanField(default=False)
    send_health = models.BooleanField(default=True)
    use_cards = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class AlertEvaluation(models.Model):
    game = models.OneToOneField('games.GameRound', null=True, on_delete=models.SET_NULL, related_name='alert_evaluation')
    game_no = models.CharField(max_length=32)
    observed_at = models.DateTimeField(db_index=True)
    captured_at = models.DateTimeField(default=timezone.now)
    session_started_at = models.DateTimeField()
    active_keys = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)


class AlertOccurrence(models.Model):
    evaluation = models.ForeignKey(AlertEvaluation, on_delete=models.CASCADE, related_name='occurrences')
    identity = models.CharField(max_length=160)
    rule_key = models.CharField(max_length=80)
    is_activation = models.BooleanField()
    snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['evaluation', 'identity'], name='unique_alert_occurrence')]


class AlertDelivery(models.Model):
    STATUSES = [(s, s.title()) for s in ('pending', 'sending', 'sent', 'uncertain', 'failed', 'cancelled')]
    dedup_key = models.CharField(max_length=180, unique=True)
    evaluation = models.ForeignKey(AlertEvaluation, null=True, blank=True, on_delete=models.SET_NULL, related_name='deliveries')
    destination = models.ForeignKey(AlertDestination, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[('alert', 'Alert'), ('result', 'Result'), ('health', 'Health'), ('test', 'Test')])
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=STATUSES, default='pending', db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    available_at = models.DateTimeField(default=timezone.now)
    claimed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    error = models.CharField(max_length=240, blank=True)
    artifact_path = models.CharField(max_length=500, blank=True)


class AlertRuntime(models.Model):
    """Single row also provides a write lock on SQLite for ingestion/evaluation."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.PositiveBigIntegerField(default=0)
    last_received_at = models.DateTimeField(null=True, blank=True)
    last_observed_at = models.DateTimeField(null=True, blank=True)
    monitoring_started_at = models.DateTimeField(null=True, blank=True)
    outage_active = models.BooleanField(default=False)
    outage_number = models.PositiveIntegerField(default=0)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    worker_status = models.CharField(max_length=32, default='stopped')
    stop_requested = models.BooleanField(default=False)


class AlertSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    telegram_enabled = models.BooleanField(default=False)
    collection_timeout_minutes = models.PositiveIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    max_event_age_seconds = models.PositiveIntegerField(default=120, validators=[MinValueValidator(10), MaxValueValidator(3600)])
