from django.db import models

class GameRound(models.Model):
    game_no = models.CharField(max_length=32, unique=True, db_index=True)
    game_type = models.CharField(max_length=32, blank=True, null=True)

    # Pre-winner stats
    latest_statistic = models.CharField(max_length=32, blank=True, null=True)
    rate_big = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    rate_small = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    rate_even = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    rate_odd = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    pre_event_ts = models.DateTimeField(blank=True, null=True)
    pre_raw = models.JSONField(blank=True, null=True)

    # Winner details
    winning_number = models.IntegerField(blank=True, null=True)
    reward_numbers = models.JSONField(blank=True, null=True)  # [5,4,9]
    reward_type = models.CharField(max_length=32, blank=True, null=True)
    winner_color = models.CharField(max_length=32, blank=True, null=True)
    winner_count = models.IntegerField(blank=True, null=True)
    bet_users = models.IntegerField(blank=True, null=True)
    bet_total_energy = models.BigIntegerField(blank=True, null=True)
    win_total_energy = models.BigIntegerField(blank=True, null=True)
    net_energy_system = models.BigIntegerField(blank=True, null=True)

    event_type = models.CharField(max_length=32, blank=True, null=True)
    is_reward = models.IntegerField(blank=True, null=True)
    status = models.IntegerField(blank=True, null=True)
    winner_event_ts = models.DateTimeField(blank=True, null=True)
    winner_raw = models.JSONField(blank=True, null=True)

    # Flags
    has_pre = models.BooleanField(default=False)
    has_winner = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.game_no} ({'winner' if self.has_winner else 'pending'})"

    @property
    def size_label(self):
        if self.winning_number is None: return ""
        return "Big" if 14 <= self.winning_number <= 27 else "Small"

    @property
    def parity_label(self):
        if self.winning_number is None: return ""
        return "Even" if self.winning_number % 2 == 0 else "Odd"

class SignalRule(models.Model):
    RULE_TYPES = [('STREAK', 'Streak'), ('DROUGHT', 'Drought')]
    DIMENSIONS = [('BIG_SMALL', 'Big/Small'), ('ODD_EVEN', 'Odd/Even'), ('COLOR', 'Color')]
    SEVERITY = [('INFO', 'Info'), ('WARNING', 'Warning'), ('CRITICAL', 'Critical')]

    name = models.CharField(max_length=100) # e.g. "6 Big Streak"
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)
    dimension = models.CharField(max_length=20, choices=DIMENSIONS)
    target_value = models.CharField(max_length=50) # "Big", "Red", "Odd"
    threshold = models.IntegerField() # e.g. 6, 15
    severity = models.CharField(max_length=20, choices=SEVERITY, default='INFO')
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.threshold})"

class SignalLog(models.Model):
    game = models.ForeignKey(GameRound, on_delete=models.CASCADE, related_name='signals')
    rule = models.ForeignKey(SignalRule, on_delete=models.CASCADE)
    value = models.IntegerField() # The actual streak/drought length triggering this
    triggered_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.rule.name} @ Game {self.game.game_no}"

