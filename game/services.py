import random

from game.models import Game, GamePlayer


def start_game(game_id):
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
