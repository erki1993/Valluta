from django.db.models.signals import post_save
from django.dispatch import receiver

from game.models import Battle


@receiver(post_save, sender=Battle)
def on_battle_saved(sender, instance, created, **kwargs):
    """Broadcast full game state to the group whenever a new battle begins."""
    if created:
        from host.views import broadcast_game_state

        broadcast_game_state(instance.game_id)
