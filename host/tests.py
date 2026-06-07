import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from game.models import Battle, BattleQuestion, Game, GamePlayer, Player, Question, Square, Topic


class ControlViewTests(TestCase):
    def test_control_view_shows_non_finished_games_and_setup_section(self):
        active_game = Game.objects.create(status=Game.Status.ACTIVE)
        lobby_game = Game.objects.create(status=Game.Status.LOBBY)
        finished_game = Game.objects.create(status=Game.Status.FINISHED)

        response = self.client.get(reverse("control:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{active_game.id}"')
        self.assertContains(response, f'value="{lobby_game.id}"')
        self.assertNotContains(response, f'value="{finished_game.id}"')
        self.assertContains(response, "Game Setup")
        self.assertContains(response, "/api/game/create/")
        self.assertContains(response, "/api/game/new/")
        self.assertContains(response, "/api/topics/")
        self.assertContains(response, 'id="battle-section"')
        self.assertContains(response, 'id="finished-game-section"')


class DisplayViewTests(TestCase):
    def test_display_view_contains_big_screen_layout(self):
        response = self.client.get(reverse("display:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="game-grid"')
        self.assertContains(response, 'id="battle-question-screen"')
        self.assertContains(response, 'id="battle-question-image"')
        self.assertContains(response, "VÕITJA!")
        self.assertContains(response, "canvas-confetti")
        self.assertContains(response, "ws/game/")


class BattleApiTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(status=Game.Status.ACTIVE)
        self.topic_a = Topic.objects.create(name="Science")
        self.topic_b = Topic.objects.create(name="History")
        self.attacker_player = Player.objects.create(name="Alice", color="#FF5733")
        self.defender_player = Player.objects.create(name="Bob", color="#33A1FF")
        self.attacker = GamePlayer.objects.create(
            game=self.game,
            player=self.attacker_player,
            topic=self.topic_a,
        )
        self.defender = GamePlayer.objects.create(
            game=self.game,
            player=self.defender_player,
            topic=self.topic_b,
        )
        self.contested_square = Square.objects.create(
            game=self.game,
            row=0,
            col=0,
            owner=self.defender,
        )
        self.other_attacker_square = Square.objects.create(
            game=self.game,
            row=0,
            col=1,
            owner=self.attacker,
        )
        self.other_defender_square = Square.objects.create(
            game=self.game,
            row=0,
            col=2,
            owner=self.defender,
        )
        self.battle = Battle.objects.create(
            game=self.game,
            attacker=self.attacker,
            defender=self.defender,
            contested_square=self.contested_square,
            current_turn=Battle.Turn.ATTACKER,
            turn_started_at=timezone.now() + timedelta(seconds=1),
        )
        self.question_a = Question.objects.create(
            topic=self.topic_a,
            text="What is H2O?",
            image_url="https://example.com/science.png",
            answer="Water",
        )
        self.question_b = Question.objects.create(
            topic=self.topic_b,
            text="Who built pyramids?",
            answer="Egyptians",
        )
        BattleQuestion.objects.create(
            battle=self.battle,
            question=self.question_a,
            asked_to=BattleQuestion.AskedTo.ATTACKER,
            answered_correctly=None,
            order=0,
        )

    def test_battle_state_includes_defender_topic(self):
        response = self.client.get("/api/battle/state/", {"game_id": self.game.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["defender_topic"], "History")

    def test_attacker_turn_question_uses_defender_topic(self):
        # Mark the existing question as answered and leave no unanswered question so
        # ensure_current_question will create a fresh one for the attacker's turn.
        BattleQuestion.objects.filter(battle=self.battle).update(answered_correctly=True)
        # Only question_b belongs to defender's topic (History).
        response = self.client.get("/api/battle/state/", {"game_id": self.game.id})

        self.assertEqual(response.status_code, 200)
        new_bq = (
            BattleQuestion.objects.filter(battle=self.battle, answered_correctly__isnull=True)
            .select_related("question__topic")
            .first()
        )
        self.assertIsNotNone(new_bq)
        self.assertEqual(new_bq.asked_to, BattleQuestion.AskedTo.ATTACKER)
        self.assertEqual(new_bq.question.topic, self.topic_b)

    def test_defender_inherits_attacker_topic_when_attacker_loses(self):
        self.battle.attacker_score = 0
        self.battle.defender_score = 1
        self.battle.turn_started_at = timezone.now() - timedelta(seconds=61)
        self.battle.save(update_fields=["attacker_score", "defender_score", "turn_started_at"])

        self.client.post(
            "/api/battle/answer/",
            data=json.dumps({"correct": False, "game_id": self.game.id}),
            content_type="application/json",
        )

        self.attacker.refresh_from_db()
        self.defender.refresh_from_db()
        self.battle.refresh_from_db()
        # Defender won, so defender's topic is replaced with the attacker's original topic.
        self.assertEqual(self.battle.winner, self.defender)
        self.assertTrue(self.attacker.is_eliminated)
        self.assertEqual(self.defender.topic, self.topic_a)

    def test_topic_unchanged_when_attacker_wins(self):
        self.battle.attacker_score = 1
        self.battle.defender_score = 0
        self.battle.turn_started_at = timezone.now() - timedelta(seconds=61)
        self.battle.save(update_fields=["attacker_score", "defender_score", "turn_started_at"])

        self.client.post(
            "/api/battle/answer/",
            data=json.dumps({"correct": False, "game_id": self.game.id}),
            content_type="application/json",
        )

        self.attacker.refresh_from_db()
        self.defender.refresh_from_db()
        self.battle.refresh_from_db()
        # Attacker won, so defender's topic must remain unchanged.
        self.assertEqual(self.battle.winner, self.attacker)
        self.assertTrue(self.defender.is_eliminated)
        self.assertEqual(self.defender.topic, self.topic_b)

    def test_battle_state_returns_active_battle_data(self):
        response = self.client.get("/api/battle/state/", {"game_id": self.game.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["active"])
        self.assertEqual(payload["attacker"]["name"], "Alice")
        self.assertEqual(payload["defender"]["name"], "Bob")
        self.assertEqual(payload["question_text"], "What is H2O?")
        self.assertEqual(payload["question_image_url"], "https://example.com/science.png")
        self.assertEqual(payload["answer_text"], "Water")
        self.assertEqual(payload["attacker"]["time_remaining"], "01:00")

    def test_correct_answer_adds_score_switches_turn_and_creates_next_question(self):
        response = self.client.post(
            "/api/battle/answer/",
            data=json.dumps({"correct": True, "game_id": self.game.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.battle.refresh_from_db()
        self.assertEqual(self.battle.attacker_score, 1)
        self.assertEqual(self.battle.current_turn, Battle.Turn.DEFENDER)
        self.assertEqual(self.battle.status, Battle.Status.ACTIVE)

        next_question = (
            BattleQuestion.objects.filter(battle=self.battle, answered_correctly__isnull=True)
            .order_by("order")
            .first()
        )
        self.assertIsNotNone(next_question)
        self.assertEqual(next_question.asked_to, BattleQuestion.AskedTo.DEFENDER)
        self.assertEqual(next_question.question, self.question_b)

    def test_answer_resolves_battle_when_timer_is_depleted(self):
        self.battle.attacker_score = 1
        self.battle.defender_score = 0
        self.battle.turn_started_at = timezone.now() - timedelta(seconds=61)
        self.battle.save(update_fields=["attacker_score", "defender_score", "turn_started_at"])

        response = self.client.post(
            "/api/battle/answer/",
            data=json.dumps({"correct": False, "game_id": self.game.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.game.refresh_from_db()
        self.defender.refresh_from_db()
        self.battle.refresh_from_db()
        self.contested_square.refresh_from_db()
        self.other_defender_square.refresh_from_db()
        self.assertEqual(self.game.status, Game.Status.FINISHED)
        self.assertEqual(self.battle.status, Battle.Status.FINISHED)
        self.assertEqual(self.battle.winner, self.attacker)
        self.assertEqual(self.contested_square.owner, self.attacker)
        self.assertIsNone(self.other_defender_square.owner)
        self.assertTrue(self.defender.is_eliminated)


class GameStateApiTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(status=Game.Status.ACTIVE)
        self.topic = Topic.objects.create(name="Science")
        self.attacker_player = Player.objects.create(name="Alice", color="#FF5733")
        self.defender_player = Player.objects.create(name="Bob", color="#33A1FF")
        self.attacker = GamePlayer.objects.create(
            game=self.game,
            player=self.attacker_player,
            topic=self.topic,
        )
        self.defender = GamePlayer.objects.create(
            game=self.game,
            player=self.defender_player,
            topic=self.topic,
        )
        self.contested_square = Square.objects.create(
            game=self.game,
            row=0,
            col=0,
            owner=self.defender,
        )
        Square.objects.create(
            game=self.game,
            row=0,
            col=1,
            owner=self.attacker,
        )
        for row in range(5):
            for col in range(5):
                if (row, col) in {(0, 0), (0, 1)}:
                    continue
                Square.objects.create(game=self.game, row=row, col=col)
        self.battle = Battle.objects.create(
            game=self.game,
            attacker=self.attacker,
            defender=self.defender,
            contested_square=self.contested_square,
            current_turn=Battle.Turn.ATTACKER,
        )

    def test_game_state_returns_grid_players_and_battle_data(self):
        response = self.client.get("/api/game/state/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["grid_size"], 5)
        self.assertEqual(len(payload["squares"]), 25)
        self.assertCountEqual(
            [player["name"] for player in payload["players"]],
            ["Alice", "Bob"],
        )
        self.assertEqual(
            {player["name"]: player["score"] for player in payload["players"]},
            {"Alice": 1, "Bob": 1},
        )
        self.assertTrue(payload["battle"]["active"])
        self.assertEqual(payload["battle"]["attacker_name"], "Alice")
        self.assertEqual(payload["battle"]["defender_name"], "Bob")
        self.assertGreaterEqual(len(payload["battle"]["highlight_squares"]), 1)

    def test_game_state_returns_winner_for_finished_game(self):
        finished_game = Game.objects.create(status=Game.Status.FINISHED)
        topic = Topic.objects.create(name="History")
        winner_player = Player.objects.create(name="Cara", color="#7D3C98")
        loser_player = Player.objects.create(name="Dan", color="#27AE60")
        winner = GamePlayer.objects.create(
            game=finished_game,
            player=winner_player,
            topic=topic,
        )
        GamePlayer.objects.create(
            game=finished_game,
            player=loser_player,
            topic=topic,
            is_eliminated=True,
        )
        Square.objects.create(game=finished_game, row=0, col=0, owner=winner)

        response = self.client.get("/api/game/state/", {"game_id": finished_game.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["game"]["status"], Game.Status.FINISHED)
        self.assertEqual(payload["game"]["winner_name"], "Cara")
        self.assertEqual(payload["game"]["winner_color"], "#7D3C98")


class GameSetupApiTests(TestCase):
    def setUp(self):
        self.science = Topic.objects.create(name="Science")
        self.history = Topic.objects.create(name="History")
        Question.objects.create(topic=self.science, text="S1", answer="A1")
        Question.objects.create(topic=self.science, text="S2", answer="A2")
        Question.objects.create(topic=self.history, text="H1", answer="A3")

    def test_topics_endpoint_returns_question_counts(self):
        response = self.client.get("/api/topics/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["topics"],
            [
                {"id": self.history.id, "name": "History", "question_count": 1},
                {"id": self.science.id, "name": "Science", "question_count": 2},
            ],
        )

    def test_create_game_endpoint_creates_game_players_and_grid(self):
        response = self.client.post(
            "/api/game/create/",
            data=json.dumps(
                {
                    "active_topics": [self.science.id, self.history.id],
                    "players": [
                        {"name": "Alice", "color": "#FF5733"},
                        {"name": "Bob", "color": "#33A1FF"},
                        {"name": "Cara", "color": "#7D3C98"},
                    ],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        game = Game.objects.get(id=payload["game_id"])
        self.assertEqual(game.status, Game.Status.LOBBY)
        self.assertEqual(game.game_players.count(), 3)
        self.assertEqual(game.squares.count(), 25)
        self.assertEqual(game.squares.filter(owner__isnull=False).count(), 3)

    def test_create_game_rejects_more_than_twenty_five_players(self):
        players = [
            {"name": f"Player {idx + 1}", "color": "#FF5733"}
            for idx in range(26)
        ]
        response = self.client.post(
            "/api/game/create/",
            data=json.dumps(
                {
                    "active_topics": [self.science.id],
                    "players": players,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most 25 players", response.content.decode())

    def test_new_game_endpoint_clones_finished_game_into_lobby(self):
        finished_game = Game.objects.create(status=Game.Status.FINISHED)
        first = GamePlayer.objects.create(
            game=finished_game,
            player=Player.objects.create(name="Alice", color="#FF5733"),
            topic=self.science,
        )
        GamePlayer.objects.create(
            game=finished_game,
            player=Player.objects.create(name="Bob", color="#33A1FF"),
            topic=self.history,
            is_eliminated=True,
        )
        Square.objects.create(game=finished_game, row=0, col=0, owner=first)

        response = self.client.post(
            "/api/game/new/",
            data=json.dumps({"game_id": finished_game.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        new_game = Game.objects.get(id=payload["game_id"])
        self.assertEqual(new_game.status, Game.Status.LOBBY)
        self.assertEqual(new_game.game_players.count(), 2)
        self.assertEqual(new_game.squares.count(), 25)
        self.assertEqual(new_game.squares.filter(owner__isnull=False).count(), 2)
        self.assertEqual(
            list(
                new_game.game_players.order_by("id").values_list(
                    "player__name",
                    "player__color",
                    "topic__name",
                )
            ),
            [
                ("Alice", "#FF5733", "Science"),
                ("Bob", "#33A1FF", "History"),
            ],
        )
