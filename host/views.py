import json
import random

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from game.models import Battle, Game, GamePlayer, Player, Square, Topic
from game.services import (
    answer_battle_question,
    ensure_current_question,
    get_active_battle,
    start_game,
    sync_battle_timer,
)


def display(request):
    game = _get_display_game()
    game_id = game.id if game else None
    return render(request, 'host/display.html', {'game_id': game_id})


def control(request):
    available_games = Game.objects.exclude(status=Game.Status.FINISHED).order_by("-created_at")
    return render(request, "host/control.html", {"active_games": available_games})


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
        .order_by("id")
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
        .order_by("row", "col")
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
        ensure_current_question(battle)
        battle.refresh_from_db()
        current_question = (
            battle.battle_questions.filter(answered_correctly__isnull=True)
            .select_related("question")
            .order_by("order", "id")
            .first()
        )
        contested_square = battle.contested_square
        attacker_square = (
            Square.objects.filter(game=game, owner=battle.attacker)
            .exclude(id=contested_square.id)
            .order_by("row", "col")
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
            "battle_id": battle.id,
            "status": battle.status,
            "winner_name": battle.winner.player.name if battle.winner_id else None,
            "current_turn": battle.current_turn,
            "attacker_name": battle.attacker.player.name,
            "defender_name": battle.defender.player.name,
            "attacker_timer": _format_timer(battle.attacker_time_remaining_ms),
            "defender_timer": _format_timer(battle.defender_time_remaining_ms),
            "attacker_timer_ms": battle.attacker_time_remaining_ms,
            "defender_timer_ms": battle.defender_time_remaining_ms,
            "attacker_score": battle.attacker_score,
            "defender_score": battle.defender_score,
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


def _normalize_players_payload(players_payload):
    if not isinstance(players_payload, list):
        return []

    players = []
    for index, player_data in enumerate(players_payload):
        if not isinstance(player_data, dict):
            continue
        name = (player_data.get("name") or "").strip() or f"Player {index + 1}"
        color = (player_data.get("color") or "").strip() or "#FF5733"
        players.append({"name": name[:255], "color": color})
    return players


@require_GET
def api_topics(request):
    topics = Topic.objects.order_by("name").annotate(question_count=models.Count("questions"))
    return JsonResponse(
        {
            "topics": [
                {"id": topic.id, "name": topic.name, "question_count": topic.question_count}
                for topic in topics
            ]
        }
    )


@require_POST
def api_create_game(request):
    payload = _get_payload(request)
    if payload is None:
        return HttpResponseBadRequest("Invalid JSON payload.")

    active_topics_payload = payload.get("active_topics", [])
    active_topic_ids = [topic_id for topic_id in active_topics_payload if isinstance(topic_id, int)]
    if not active_topic_ids:
        return HttpResponseBadRequest("active_topics must contain topic ids.")

    topics = list(Topic.objects.filter(id__in=active_topic_ids).order_by("id"))
    if not topics:
        return HttpResponseBadRequest("No valid active topics selected.")

    topics_with_questions = list(
        Topic.objects.filter(id__in=active_topic_ids, questions__isnull=False)
        .distinct()
        .order_by("id")
    )
    if len(topics_with_questions) != len(topics):
        topics_with_questions_ids = {topic.id for topic in topics_with_questions}
        missing_names = [
            topic.name for topic in topics if topic.id not in topics_with_questions_ids
        ]
        return HttpResponseBadRequest(
            f"Selected topics without questions: {', '.join(missing_names)}."
        )

    players = _normalize_players_payload(payload.get("players", []))
    if not players:
        players = [
            {"name": "Player 1", "color": "#FF5733"},
            {"name": "Player 2", "color": "#33A1FF"},
        ]
    if len(players) > 25:
        return HttpResponseBadRequest("A game supports at most 25 players.")

    with transaction.atomic():
        game = Game.objects.create(status=Game.Status.LOBBY)

        game_players = []
        available_topics = topics_with_questions
        for index, player_payload in enumerate(players):
            player = Player.objects.create(
                name=player_payload["name"],
                color=player_payload["color"],
            )
            game_players.append(
                GamePlayer.objects.create(
                    game=game,
                    player=player,
                    topic=available_topics[index % len(available_topics)],
                )
            )

        squares = [
            Square(game=game, row=row, col=col)
            for row in range(5)
            for col in range(5)
        ]
        Square.objects.bulk_create(squares)

        available_squares = list(game.squares.all())
        owned_squares = []
        for game_player, square in zip(
            game_players,
            random.sample(available_squares, len(game_players)),
        ):
            square.owner = game_player
            owned_squares.append(square)

        Square.objects.bulk_update(owned_squares, ["owner"])

    return JsonResponse({"game_id": game.id})


def broadcast_game_state(game_id: int) -> None:
    """Broadcast full game state to the WebSocket group for the given game."""
    channel_layer = get_channel_layer()
    game = _get_display_game(game_id=game_id)
    state = _serialize_game_state(game)
    async_to_sync(channel_layer.group_send)(
        f"game_{game_id}",
        {"type": "game.state.update", "state": state},
    )


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

    broadcast_game_state(game_id)
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
    broadcast_game_state(updated_battle.game_id)
    return JsonResponse(_serialize_battle_state(updated_battle))
