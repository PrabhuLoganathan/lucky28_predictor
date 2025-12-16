from django.core.management.base import BaseCommand
from games.models import SignalRule

class Command(BaseCommand):
    help = 'Seeds default signal rules (Streaks/Droughts)'

    def handle(self, *args, **options):
        rules = [
            # STREAKS
            {"name": "6 Big Streak", "type": "STREAK", "dim": "BIG_SMALL", "val": "Big", "th": 6, "sev": "WARNING"},
            {"name": "6 Small Streak", "type": "STREAK", "dim": "BIG_SMALL", "val": "Small", "th": 6, "sev": "WARNING"},
            {"name": "6 Odd Streak", "type": "STREAK", "dim": "ODD_EVEN", "val": "Odd", "th": 6, "sev": "WARNING"},
            {"name": "6 Even Streak", "type": "STREAK", "dim": "ODD_EVEN", "val": "Even", "th": 6, "sev": "WARNING"},
            # COLOR STREAKS (Rare but possible)
            {"name": "4 Red Streak", "type": "STREAK", "dim": "COLOR", "val": "Red", "th": 4, "sev": "CRITICAL"},
            
            # DROUGHTS (Missing for N games)
            {"name": "Gray Drought (15)", "type": "DROUGHT", "dim": "COLOR", "val": "Grey", "th": 15, "sev": "WARNING"},
            {"name": "Gray Drought (20)", "type": "DROUGHT", "dim": "COLOR", "val": "Grey", "th": 20, "sev": "CRITICAL"},
            {"name": "Red Drought (20)", "type": "DROUGHT", "dim": "COLOR", "val": "Red", "th": 20, "sev": "WARNING"},
        ]

        for r in rules:
            obj, created = SignalRule.objects.get_or_create(
                name=r["name"],
                defaults={
                    "rule_type": r["type"],
                    "dimension": r["dim"],
                    "target_value": r["val"],
                    "threshold": r["th"],
                    "severity": r["sev"]
                }
            )
            if created:
                self.stdout.write(f"Created Rule: {r['name']}")
            else:
                self.stdout.write(f"Rule already exists: {r['name']}")
