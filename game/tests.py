from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from game.admin import PlayerAdmin, QuestionAdmin, QuestionInline, TopicAdmin
from game.models import Game, GamePlayer, Player, Question, Square, Topic
from game.services import check_game_over, start_game


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


class CheckGameOverTests(TestCase):
    def test_check_game_over_finishes_game_when_one_player_has_squares_left(self):
        game = Game.objects.create(status=Game.Status.ACTIVE)
        topic = Topic.objects.create(name="Science")
        alice = GamePlayer.objects.create(
            game=game,
            player=Player.objects.create(name="Alice", color="#FF5733"),
            topic=topic,
        )
        bob = GamePlayer.objects.create(
            game=game,
            player=Player.objects.create(name="Bob", color="#33A1FF"),
            topic=topic,
        )
        Square.objects.create(game=game, row=0, col=0, owner=alice)
        Square.objects.create(game=game, row=0, col=1, owner=alice)
        Square.objects.create(game=game, row=0, col=2, owner=None)

        winner = check_game_over(game.id)

        game.refresh_from_db()
        bob.refresh_from_db()
        self.assertEqual(game.status, Game.Status.FINISHED)
        self.assertEqual(winner, alice)
        self.assertTrue(bob.is_eliminated)


class SeedDemoCommandTests(TestCase):
    @patch("game.management.commands.seed_demo.random.choice")
    @patch("game.management.commands.seed_demo.random.sample")
    def test_seed_demo_creates_expected_demo_data(self, sample_mock, choice_mock):
        chosen_topic_indexes = [0, 1, 2, 0]

        def choose_topic(choices):
            return choices[chosen_topic_indexes.pop(0)]

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


class AdminConfigurationTests(TestCase):
    def test_player_admin_hides_color_on_add_form(self):
        player_admin = PlayerAdmin(Player, admin.site)
        self.assertEqual(player_admin.get_fields(request=None, obj=None), ("name", "is_active"))

    def test_topic_admin_lists_question_count_and_inline_questions(self):
        self.assertIn("question_count", TopicAdmin.list_display)
        self.assertIn(QuestionInline, TopicAdmin.inlines)

    def test_question_admin_enables_topic_filter_and_search(self):
        self.assertIn("topic_name", QuestionAdmin.list_display)
        self.assertEqual(QuestionAdmin.list_filter, ("topic",))
        self.assertEqual(QuestionAdmin.search_fields, ("text", "answer"))


class QuestionCsvImportAdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(
            username="admin",
            email="admin@example.com",
            is_staff=True,
            is_superuser=True,
        )
        user.set_password("admin-pass-123")
        user.save(update_fields=["password"])
        self.client.force_login(user)

    def test_import_csv_creates_topics_and_questions(self):
        csv_file = SimpleUploadedFile(
            "questions.csv",
            b"topic,question,answer\nScience,What is H2O?,Water\nHistory,First president?,Washington\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("admin:game_question_import_csv"),
            {"csv_file": csv_file},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Topic.objects.filter(name="Science").count(), 1)
        self.assertEqual(Topic.objects.filter(name="History").count(), 1)
        self.assertEqual(Question.objects.count(), 2)

    def test_import_csv_rejects_missing_required_columns(self):
        csv_file = SimpleUploadedFile(
            "bad.csv",
            b"topic,question\nScience,What is H2O?\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("admin:game_question_import_csv"),
            {"csv_file": csv_file},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Missing CSV columns: answer.")
        self.assertEqual(Question.objects.count(), 0)


class PlayerAdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(
            username="admin-player",
            email="admin-player@example.com",
            is_staff=True,
            is_superuser=True,
        )
        user.set_password("admin-pass-123")
        user.save(update_fields=["password"])
        self.client.force_login(user)

    def test_add_player_in_admin_auto_generates_color(self):
        response = self.client.post(
            reverse("admin:game_player_add"),
            {"name": "Alice", "is_active": "on", "_save": "Save"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        player = Player.objects.get(name="Alice")
        self.assertRegex(player.color, r"^#[0-9A-F]{6}$")

    def test_change_player_keeps_existing_color(self):
        player = Player.objects.create(name="Bob", color="#123ABC")

        response = self.client.post(
            reverse("admin:game_player_change", args=[player.pk]),
            {"name": "Bobby", "color": "#123ABC", "is_active": "on", "_save": "Save"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        player.refresh_from_db()
        self.assertEqual(player.name, "Bobby")
        self.assertEqual(player.color, "#123ABC")

    @patch("game.admin.secrets.randbelow", side_effect=[1, 2])
    def test_add_player_retries_when_generated_color_already_exists(self, _randbelow):
        Player.objects.create(name="Existing", color="#000001")

        self.client.post(
            reverse("admin:game_player_add"),
            {"name": "New Player", "is_active": "on", "_save": "Save"},
            follow=True,
        )

        player = Player.objects.get(name="New Player")
        self.assertEqual(player.color, "#000002")
