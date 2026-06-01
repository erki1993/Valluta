from django.urls import path

from . import views

urlpatterns = [
    path("topics/", views.api_topics, name="api-topics"),
    path("game/create/", views.api_create_game, name="api-game-create"),
    path("game/new/", views.api_new_game, name="api-game-new"),
    path("game/", views.api_start_game, name="api-game-start"),
    path("game/state/", views.api_game_state, name="api-game-state"),
    path("battle/state/", views.api_battle_state, name="api-battle-state"),
    path("battle/start/", views.api_start_battle, name="api-battle-start"),
    path("battle/answer/", views.api_battle_answer, name="api-battle-answer"),
]
