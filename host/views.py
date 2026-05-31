import json

from django.db import models
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from game.models import Battle, Game, GamePlayer, Square
from game.services import (
    answer_battle_question,
    ensure_current_question,
    get_active_battle,
    start_game,
    sync_battle_timer,
)


def display(request):
    return render(request, 'host/display.html')


def control(request):
    active_games = Game.objects.filter(status=Game.Status.ACTIVE).order_by("-created_at")
    return render(request, "host/control.html", {"active_games": active_games})


def _format_timer(milliseconds: int) -> str:
    """Format millisecond duration into MM:SS display text."""
    total_seconds = max(0, milliseconds // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _serialize_battle_state(battle: Battle | None) -> dict:
    if battle is None:
        return {"active": False}

    ensure_current_question(battle)
    battle.refresh_from_db()
    current_question = (
        battle.battle_questions.filter(answered_correctly__isnull=True)
        .select_related("question")
        .order_by("order", "id")
        .first()
    )

    return {
        "active": battle.status == Battle.Status.ACTIVE,
        "battle_id": battle.id,
        "status": battle.status,
        "winner_name": battle.winner.player.name if battle.winner_id else None,
        "current_turn": battle.current_turn,
        "attacker": {
            "name": battle.attacker.player.name,
            "time_remaining_ms": battle.attacker_time_remaining_ms,
            "time_remaining": _format_timer(battle.attacker_time_remaining_ms),
            "score": battle.attacker_score,
            "is_current_turn": battle.current_turn == Battle.Turn.ATTACKER,
        },
        "defender": {
            "name": battle.defender.player.name,
            "time_remaining_ms": battle.defender_time_remaining_ms,
            "time_remaining": _format_timer(battle.defender_time_remaining_ms),
            "score": battle.defender_score,
            "is_current_turn": battle.current_turn == Battle.Turn.DEFENDER,
        },
        "question_text": current_question.question.text if current_question else "",
    }


def _get_display_game(game_id: int | None = None) -> Game | None:
    if game_id is not None:
        return Game.objects.filter(id=game_id).first()

    return Game.objects.filter(status=Game.Status.ACTIVE).order_by("-created_at").first()


def _serialize_game_state(game: Game | None) -> dict:
    if game is None:
        return {"game": None, "players": [], "grid_size": 5, "squares": [], "battle": {"active": False}}

    game_players = list(
        GamePlayer.objects.filter(game=game)
        .select_related("player")
        .order_by("player__name", "id")
    )
    owner_counts = {
        entry["owner_id"]: entry["count"]
        for entry in Square.objects.filter(game=game, owner__isnull=False)
        .values("owner_id")
        .annotate(count=models.Count("id"))
    }

    squares = []
    for square in (
        Square.objects.filter(game=game)
        .select_related("owner__player")
        .order_by("row", "col", "id")
    ):
        owner_name = square.owner.player.name if square.owner_id else None
        owner_color = square.owner.player.color if square.owner_id else None
        payload = {
            "row": square.row,
            "col": square.col,
            "owner_game_player_id": square.owner_id,
            "owner_name": owner_name,
            "owner_color": owner_color,
        }
        squares.append(payload)

    battle = get_active_battle(game_id=game.id)
    battle_payload = {"active": False}
    if battle is not None:
        sync_battle_timer(battle)
        battle.refresh_from_db()
        contested_square = battle.contested_square
        attacker_square = (
            Square.objects.filter(game=game, owner=battle.attacker)
            .exclude(id=contested_square.id)
            .order_by("row", "col", "id")
            .first()
        )

        highlight_squares = [
            {"row": contested_square.row, "col": contested_square.col, "role": "defender"}
        ]
        if attacker_square is not None:
            highlight_squares.insert(
                0,
                {"row": attacker_square.row, "col": attacker_square.col, "role": "attacker"},
            )

        battle_payload = {
            "active": battle.status == Battle.Status.ACTIVE,
            "attacker_name": battle.attacker.player.name,
            "defender_name": battle.defender.player.name,
            "attacker_timer": _format_timer(battle.attacker_time_remaining_ms),
            "defender_timer": _format_timer(battle.defender_time_remaining_ms),
            "attacker_timer_ms": battle.attacker_time_remaining_ms,
            "defender_timer_ms": battle.defender_time_remaining_ms,
            "highlight_squares": highlight_squares,
        }

    return {
        "game": {"id": game.id, "status": game.status},
        "grid_size": 5,
        "players": [
            {
                "game_player_id": game_player.id,
                "name": game_player.player.name,
                "color": game_player.player.color,
                "score": owner_counts.get(game_player.id, 0),
                "is_eliminated": game_player.is_eliminated,
            }
            for game_player in game_players
        ],
        "squares": squares,
        "battle": battle_payload,
    }


def _get_payload(request):
    """Parse request JSON body and return dict, or None when invalid JSON."""
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return None


@require_POST
def api_start_game(request):
    payload = _get_payload(request)
    if payload is None:
        return HttpResponseBadRequest("Invalid JSON payload.")

    game_id = payload.get("game_id")
    if not isinstance(game_id, int) or game_id <= 0:
        return HttpResponseBadRequest("game_id must be a positive integer.")

    try:
        selected_game_player = start_game(game_id)
    except Game.DoesNotExist:
        return JsonResponse({"error": "Game not found."}, status=404)

    selected_player_name = (
        selected_game_player.player.name if selected_game_player is not None else None
    )
    return JsonResponse(
        {
            "ok": True,
            "selected_player": selected_player_name,
        }
    )


@require_GET
def api_battle_state(request):
    game_id = request.GET.get("game_id")
    if game_id is not None:
        try:
            game_id = int(game_id)
        except ValueError:
            return HttpResponseBadRequest("game_id must be an integer.")

    battle = get_active_battle(game_id=game_id)
    if battle is not None:
        sync_battle_timer(battle)
        battle.refresh_from_db()
    return JsonResponse(_serialize_battle_state(battle))


@require_GET
def api_game_state(request):
    game_id = request.GET.get("game_id")
    if game_id is not None:
        try:
            game_id = int(game_id)
        except ValueError:
            return HttpResponseBadRequest("game_id must be an integer.")

    game = _get_display_game(game_id=game_id)
    return JsonResponse(_serialize_game_state(game))


@require_POST
def api_battle_answer(request):
    payload = _get_payload(request)
    if payload is None:
        return HttpResponseBadRequest("Invalid JSON payload.")

    if "correct" not in payload or not isinstance(payload["correct"], bool):
        return HttpResponseBadRequest("correct must be a boolean.")
    is_correct = payload["correct"]

    game_id = payload.get("game_id")
    if game_id is not None and not isinstance(game_id, int):
        return HttpResponseBadRequest("game_id must be an integer when provided.")

    battle = get_active_battle(game_id=game_id)
    if battle is None:
        return JsonResponse({"error": "No active battle found."}, status=404)

    updated_battle = answer_battle_question(battle, is_correct=is_correct)
    return JsonResponse(_serialize_battle_state(updated_battle))
