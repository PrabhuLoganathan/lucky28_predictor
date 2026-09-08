import logging
from games.models import GameRound, SignalRule, SignalLog
from games.services.whatsapp import WhatsAppService
from django.db.models import Q

logger = logging.getLogger(__name__)

class SignalAnalyzer:
    def __init__(self, notify=True):
        self.notify = notify
        self.whatsapp = WhatsAppService() if notify else None

    def analyze_game(self, game_round):
        """
        Analyzes the latest game for signal triggers based on configured rules.
        """
        rules = SignalRule.objects.filter(is_active=True)
        if not rules.exists():
            return

        # Fetch recent history (enough to determine any reasonable streak)
        # 50 records should be enough for streaks, but for drought we might need more.
        # Let's fetch last 100 winners.
        history = GameRound.objects.filter(
            has_winner=True, 
            winning_number__isnull=False,
        ).filter(Q(game_type='lucky28') | Q(game_type__isnull=True) | Q(game_type=''))
        if game_round.winner_event_ts:
            history = history.filter(
                Q(winner_event_ts__lt=game_round.winner_event_ts)
                | Q(winner_event_ts=game_round.winner_event_ts, pk__lte=game_round.pk)
            )
        history = history.order_by('-winner_event_ts', '-id')[:100]

        if not history:
            return

        # Prepare stats
        stats = self._calculate_current_stats(history)

        for rule in rules:
            self._check_rule(rule, stats, game_round)

    def _calculate_current_stats(self, history):
        """
        Returns a dict of current streak/drought values.
        e.g. {'STREAK_BIG': 6, 'DROUGHT_RED': 20}
        """
        stats = {}
        
        # Dimensions
        # Big/Small
        stats.update(self._get_streak_drought(history, 'BIG_SMALL', lambda g: 'Big' if g.winning_number >= 14 else 'Small', ['Big', 'Small']))
        
        # Odd/Even
        stats.update(self._get_streak_drought(history, 'ODD_EVEN', lambda g: 'Odd' if g.winning_number % 2 != 0 else 'Even', ['Odd', 'Even']))
        
        # Color
        all_colors = ['Red', 'Yellow', 'Pink', 'Blue', 'Cyan', 'Green', 'Grey']
        stats.update(self._get_streak_drought(history, 'COLOR', lambda g: g.winner_color, all_colors))

        return stats

    def _get_streak_drought(self, history, dim_key, value_mapper, possible_values):
        """
        Generic calculator for streak and drought.
        """
        results = {}
        if not history:
            return results

        latest_val = value_mapper(history[0])
        
        # 1. Calculate Streak for the LATEST value only
        streak = 0
        for game in history:
            val = value_mapper(game)
            if val == latest_val:
                streak += 1
            else:
                break
        results[f'STREAK_{dim_key}_{latest_val}'] = streak

        # 2. Calculate Droughts for ALL possible values
        # Drought = How many games since we last saw this value?
        for target in possible_values:
            drought = 0
            found = False
            for game in history:
                val = value_mapper(game)
                if val == target:
                    found = True
                    break
                drought += 1
            
            # If never found in history limit, it's at least len(history)
            results[f'DROUGHT_{dim_key}_{target}'] = drought
        
        return results

    def _check_rule(self, rule, stats, game_round):
        key = f"{rule.rule_type}_{rule.dimension}_{rule.target_value}"
        current_value = stats.get(key, 0)

        # Trigger if current value meets or exceeds threshold
        # BUT we want to avoid spamming.
        # Strategy: Alert on the transitions? Or every time?
        # User requirement implies continuous monitoring "6B happened".
        # Let's log it. Use Triggered At to debounce if needed? 
        # For now, simplistic approach: If >= threshold, it's a signal.
        
        if current_value == rule.threshold:
            # Check if we already logged this specific signal for this specific game
            exists = SignalLog.objects.filter(game=game_round, rule=rule).exists()
            if not exists:
                # Create Log
                SignalLog.objects.create(
                    game=game_round,
                    rule=rule,
                    value=current_value
                )
                if not self.notify:
                    return
                
                # Count signals today
                from django.utils import timezone
                today = timezone.now().date()
                daily_count = SignalLog.objects.filter(triggered_at__date=today).count()
                
                # Compose Message
                msg_type = "🚨" if rule.severity == 'CRITICAL' else "⚠️"
                msg = (
                    f"{msg_type} *SIGNAL DETECTED* {msg_type}\n"
                    f"Rule: {rule.name}\n"
                    f"Current {rule.rule_type.title()}: *{current_value}*\n"
                    f"Game: {game_round.game_no}\n"
                    f"Signals Today: {daily_count}"
                )
                
                # Send Alert
                # Need a valid recipient. Currently pulling from logic inside views.
                # Ideally, SignalAnalyzer shouldn't know about requests.
                # We will pick up ADMIN_PHONE from env as default.
                import os
                recipient = os.environ.get("ADMIN_PHONE")
                if recipient:
                    self.whatsapp.send_message_raw(recipient, msg)
                else:
                    logger.warning("Signal detected but no ADMIN_PHONE Configured.")
