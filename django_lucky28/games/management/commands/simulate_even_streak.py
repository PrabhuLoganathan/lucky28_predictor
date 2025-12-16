from django.core.management.base import BaseCommand
from games.models import GameRound, SignalLog
from games.services.signals import SignalAnalyzer
from django.utils import timezone
import time

class Command(BaseCommand):
    help = 'Simulates a streak of Even numbers to test signals'

    def handle(self, *args, **options):
        self.stdout.write("Simulating 6 Consecutive EVEN games...")
        
        # Base Game ID
        start_id = int(time.time())
        analyzer = SignalAnalyzer()

        for i in range(1, 7):
            game_no = str(start_id + i)
            # Even numbers: 2, 4, 6, 8, 10, 12
            winning_number = i * 2 
            
            # Create Game
            game = GameRound.objects.create(
                game_no=game_no,
                winning_number=winning_number,
                winner_color="Blue", # Arbitrary
                has_winner=True,
                winner_event_ts=timezone.now()
            )
            
            self.stdout.write(f"Created Game {game_no}: Winner {winning_number} (Even)")
            
            # Trigger Analyzer
            analyzer.analyze_game(game)
            time.sleep(0.1) # Brief pause

        # Verification
        logs = SignalLog.objects.filter(rule__name="6 Even Streak").order_by('-triggered_at')
        if logs.exists():
            last_log = logs.first()
            self.stdout.write(self.style.SUCCESS(f"✅ SIGNAL TRIGGERED! \nRule: {last_log.rule.name}\nValue: {last_log.value}\nGame: {last_log.game.game_no}"))
        else:
            self.stdout.write(self.style.ERROR("❌ NO SIGNAL TRIGGERED. Check rules or analyzer."))
