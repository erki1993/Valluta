import random

from game.models import Game, GamePlayer


def start_game(game_id: int) -> GamePlayer | None:
    """
    Activate the game and return a random active GamePlayer.

    Raises Game.DoesNotExist when the given game does not exist.
    Returns None when the game has no non-eliminated players with active Player records.
    """
    game = Game.objects.get(pk=game_id)
    game.status = Game.Status.ACTIVE
    game.save(update_fields=["status"])

    active_game_players = list(
        GamePlayer.objects.filter(
            game=game,
            is_eliminated=False,
            player__is_active=True,
        ).select_related("player", "topic")
    )
    if not active_game_players:
        return None

    return random.choice(active_game_players)
