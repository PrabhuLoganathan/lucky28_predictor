"""Invalidate counters for imports, admin corrections and deletions as well as live writes."""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from games.models import GameRound, GroupAbsenceStream


@receiver(post_save, sender=GameRound)
@receiver(post_delete, sender=GameRound)
def history_changed(sender, instance, **kwargs):
    key = instance.game_type or 'lucky28'
    GroupAbsenceStream.objects.get_or_create(key=key)
    # Also invalidate a former stream if an administrator moved this result.
    GroupAbsenceStream.objects.all().update(dirty=True)
