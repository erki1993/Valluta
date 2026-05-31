import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from game.models import Battle, BattleQuestion, Game, GamePlayer, Player, Question, Square, Topic


class ControlViewTests(TestCase):
    def test_control_view_shows_only_active_games(self):
        active_game = Game.objects.create(status=Game.Status.ACTIVE)
        lobby_game = Game.objects.create(status=Game.Status.LOBBY)

        response = self.client.get(reverse("control:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{active_game.id}"')
        self.assertNotContains(response, f'value="{lobby_game.id}"')
        self.assertContains(response, 'id="battle-section"')


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
            turn_started_at=timezone.now(),
        )
        self.question_a = Question.objects.create(
            topic=self.topic_a,
            text="What is H2O?",
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

    def test_battle_state_returns_active_battle_data(self):
        response = self.client.get("/api/battle/state/", {"game_id": self.game.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["active"])
        self.assertEqual(payload["attacker"]["name"], "Alice")
        self.assertEqual(payload["defender"]["name"], "Bob")
        self.assertEqual(payload["question_text"], "What is H2O?")
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
        self.battle.refresh_from_db()
        self.contested_square.refresh_from_db()
        self.other_defender_square.refresh_from_db()
        self.assertEqual(self.battle.status, Battle.Status.FINISHED)
        self.assertEqual(self.battle.winner, self.attacker)
        self.assertEqual(self.contested_square.owner, self.attacker)
        self.assertIsNone(self.other_defender_square.owner)
