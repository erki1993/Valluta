from django.urls import path

from . import views

urlpatterns = [
    path("game/", views.api_start_game, name="api-game-start"),
    path("battle/state/", views.api_battle_state, name="api-battle-state"),
    path("battle/answer/", views.api_battle_answer, name="api-battle-answer"),
]
