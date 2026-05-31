from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from game.models import Game, GamePlayer, Player, Question, Square, Topic
from game.services import start_game


class StartGameTests(TestCase):
    def test_start_game_activates_game_and_returns_random_active_player(self):
        game = Game.objects.create()
        science = Topic.objects.create(name="Science")
        active_player = Player.objects.create(name="Alice", color="#FF5733")
        inactive_player = Player.objects.create(
            name="Bob",
            color="#33A1FF",
            is_active=False,
        )
        expected_game_player = GamePlayer.objects.create(
            game=game,
            player=active_player,
            topic=science,
        )
        GamePlayer.objects.create(
            game=game,
            player=inactive_player,
            topic=science,
        )

        with patch("game.services.random.choice", return_value=expected_game_player):
            selected_game_player = start_game(game.id)

        game.refresh_from_db()
        self.assertEqual(game.status, Game.Status.ACTIVE)
        self.assertEqual(selected_game_player, expected_game_player)

    def test_start_game_returns_none_when_no_active_players_exist(self):
        game = Game.objects.create()
        science = Topic.objects.create(name="Science")
        inactive_player = Player.objects.create(
            name="Bob",
            color="#33A1FF",
            is_active=False,
        )
        GamePlayer.objects.create(
            game=game,
            player=inactive_player,
            topic=science,
            is_eliminated=True,
        )

        selected_game_player = start_game(game.id)

        game.refresh_from_db()
        self.assertEqual(game.status, Game.Status.ACTIVE)
        self.assertIsNone(selected_game_player)


class SeedDemoCommandTests(TestCase):
    @patch("game.management.commands.seed_demo.random.choice")
    @patch("game.management.commands.seed_demo.random.sample")
    def test_seed_demo_creates_expected_demo_data(self, sample_mock, choice_mock):
        topics = [Topic(name="Science"), Topic(name="History"), Topic(name="Sports")]
        chosen_topic_indexes = [0, 1, 2, 0]

        def choose_topic(_):
            return topics[chosen_topic_indexes.pop(0)]

        choice_mock.side_effect = choose_topic
        sample_mock.side_effect = lambda population, count: population[:count]

        stdout = StringIO()
        call_command("seed_demo", stdout=stdout)

        game = Game.objects.get()
        self.assertEqual(game.status, Game.Status.LOBBY)
        self.assertCountEqual(
            Topic.objects.values_list("name", flat=True),
            ["Science", "History", "Sports"],
        )
        self.assertEqual(Question.objects.count(), 15)
        self.assertEqual(Player.objects.count(), 4)
        self.assertEqual(GamePlayer.objects.filter(game=game).count(), 4)
        self.assertEqual(Square.objects.filter(game=game).count(), 25)

        owners = list(
            Square.objects.filter(game=game, owner__isnull=False).values_list(
                "row",
                "col",
                flat=False,
            )
        )
        self.assertEqual(len(owners), 4)
        self.assertEqual(len(set(owners)), 4)
        self.assertEqual(
            set(Player.objects.values_list("color", flat=True)),
            {"#FF5733", "#33A1FF", "#7D3C98", "#27AE60"},
        )
        self.assertEqual(
            list(
                GamePlayer.objects.filter(game=game)
                .order_by("player__name")
                .values_list("topic__name", flat=True)
            ),
            ["Science", "History", "Sports", "Science"],
        )
        self.assertIn(f"Seeded demo game {game.pk}", stdout.getvalue())
