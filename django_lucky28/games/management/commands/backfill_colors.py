from django.core.management.base import BaseCommand
from games.models import GameRound

class Command(BaseCommand):
    help = 'Backfills winner_color for existing games'

    def handle(self, *args, **options):
        games = GameRound.objects.exclude(winning_number__isnull=True)
        count = 0
        
        for game in games:
            n = game.winning_number
            color = "Unknown"
            
            if n in [0, 1, 26, 27]: color = "Red"
            elif n in [2, 3, 24, 25]: color = "Yellow"
            elif n in [4, 5, 22, 23]: color = "Pink"
            elif n in [6, 7, 20, 21]: color = "Blue"
            elif n in [8, 9, 18, 19]: color = "Cyan"
            elif n in [10, 11, 16, 17]: color = "Green"
            elif n in [12, 13, 14, 15]: color = "Grey"
            
            if game.winner_color != color:
                game.winner_color = color
                game.save()
                count += 1
                self.stdout.write(f"Updated Game {game.game_no}: {n} -> {color}")

        self.stdout.write(self.style.SUCCESS(f'Successfully backfilled colors for {count} games'))
