from django.contrib import admin
from game.models import (
    Battle,
    BattleQuestion,
    Game,
    GamePlayer,
    Player,
    Question,
    Square,
    Topic,
)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "color", "is_active")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "text", "answer")


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "status")


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ("id", "game", "player", "topic", "is_eliminated")


@admin.register(Square)
class SquareAdmin(admin.ModelAdmin):
    list_display = ("id", "game", "row", "col", "owner")


@admin.register(Battle)
class BattleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "game",
        "attacker",
        "defender",
        "contested_square",
        "current_turn",
        "attacker_score",
        "defender_score",
        "status",
        "winner",
    )


@admin.register(BattleQuestion)
class BattleQuestionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "battle",
        "question",
        "asked_to",
        "answered_correctly",
        "time_taken_ms",
        "order",
    )
