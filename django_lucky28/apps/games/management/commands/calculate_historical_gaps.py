from django.core.management.base import BaseCommand
from games.models import GameRound, NumberGapStat

class Command(BaseCommand):
    help = "Calculates historical maximum and average gaps for all numbers"

    def handle(self, *args, **options):
        self.stdout.write("Initializing gap stats for numbers 0-27...")
        
        # Initialize the db table with all numbers (0-27)
        stats = {}
        for i in range(28):
            obj, _ = NumberGapStat.objects.get_or_create(number=i)
            # Reset values for a fresh run
            obj.current_gap = 0
            obj.max_gap = 0
            obj.total_gap_sum = 0
            obj.occurrence_count = 0
            obj.last_seen_game = None
            stats[i] = obj
            
        self.stdout.write("Fetching historical completed games...")
        # Get all games that have a winning number, ordered chronologically
        games = GameRound.objects.filter(has_winner=True, winning_number__isnull=False).order_by('winner_event_ts', 'id')
        
        total_games = games.count()
        self.stdout.write(f"Processing {total_games} games...")
        
        count = 0
        for game in games.iterator():
            winning_num = game.winning_number
            
            # Increment current_gap for ALL numbers
            for n in range(28):
                stats[n].current_gap += 1
                
            # Process the winning number
            winner_stat = stats[winning_num]
            
            # The gap for this number is whatever current_gap was right before it won, 
            # minus 1 (because we just added 1 above)
            actual_gap = winner_stat.current_gap - 1
            
            # Check for max gap
            if actual_gap > winner_stat.max_gap:
                winner_stat.max_gap = actual_gap
                
            winner_stat.total_gap_sum += actual_gap
            winner_stat.occurrence_count += 1
            winner_stat.last_seen_game = game
            
            # Reset current gap since it just appeared
            winner_stat.current_gap = 0
            
            count += 1
            if count % 5000 == 0:
                self.stdout.write(f"Processed {count}/{total_games} games...")
                
        self.stdout.write("Saving stats to database...")
        # Bulk save
        NumberGapStat.objects.bulk_update(
            list(stats.values()), 
            ['current_gap', 'max_gap', 'total_gap_sum', 'occurrence_count', 'last_seen_game']
        )
        
        self.stdout.write(self.style.SUCCESS("Successfully calculated historical gaps!"))
