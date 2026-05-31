from django.test import TestCase
from django.urls import reverse
from game.models import Game


class ControlViewTests(TestCase):
    def test_control_view_shows_only_active_games(self):
        active_game = Game.objects.create(status=Game.Status.ACTIVE)
        lobby_game = Game.objects.create(status=Game.Status.LOBBY)

        response = self.client.get(reverse("control:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{active_game.id}"')
        self.assertNotContains(response, f'value="{lobby_game.id}"')
