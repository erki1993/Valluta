import random

from django.core.management.base import BaseCommand

from game.models import Game, GamePlayer, Player, Question, Square, Topic


class Command(BaseCommand):
    help = "Seed demo game data."

    topic_names = ("Science", "History", "Sports")
    player_specs = (
        ("Alice", "#FF5733"),
        ("Bob", "#33A1FF"),
        ("Charlie", "#7D3C98"),
        ("Diana", "#27AE60"),
    )

    def handle(self, *args, **options):
        game = Game.objects.create(status=Game.Status.LOBBY)
        topics = [Topic.objects.create(name=name) for name in self.topic_names]

        for topic in topics:
            Question.objects.bulk_create(
                [
                    Question(
                        topic=topic,
                        text=f"{topic.name} Question {index}",
                        answer=f"{topic.name} Answer {index}",
                    )
                    for index in range(1, 6)
                ]
            )

        game_players = []
        for name, color in self.player_specs:
            player = Player.objects.create(name=name, color=color)
            game_players.append(
                GamePlayer.objects.create(
                    game=game,
                    player=player,
                    topic=random.choice(topics),
                )
            )

        squares = [
            Square(game=game, row=row, col=col)
            for row in range(5)
            for col in range(5)
        ]
        Square.objects.bulk_create(squares)

        available_squares = list(game.squares.all())
        for game_player, square in zip(
            game_players,
            random.sample(available_squares, len(game_players)),
        ):
            square.owner = game_player

        Square.objects.bulk_update(
            [square for square in available_squares if square.owner_id is not None],
            ["owner"],
        )

        self.stdout.write(self.style.SUCCESS(f"Seeded demo game {game.pk}"))
