import random

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from game.models import Battle, BattleQuestion, Game, GamePlayer, Question, Square


def start_game(game_id: int) -> GamePlayer | None:
    """
    Activate the game and return a random active GamePlayer.

    Raises Game.DoesNotExist when the given game does not exist.
    Returns None when the game has no non-eliminated players with active Player records.
    """
    game = Game.objects.get(pk=game_id)
    game.status = Game.Status.ACTIVE
    game.save(update_fields=["status"])

    active_game_players = list(
        GamePlayer.objects.filter(
            game=game,
            is_eliminated=False,
            player__is_active=True,
        ).select_related("player", "topic")
    )
    if not active_game_players:
        return None

    return random.choice(active_game_players)


def get_active_battle(game_id: int | None = None) -> Battle | None:
    queryset = Battle.objects.filter(status=Battle.Status.ACTIVE).select_related(
        "attacker__player",
        "attacker__topic",
        "defender__player",
        "defender__topic",
        "contested_square",
        "game",
    )
    if game_id is not None:
        queryset = queryset.filter(game_id=game_id)
    return queryset.order_by("-id").first()


def sync_battle_timer(battle: Battle, now=None) -> Battle:
    if battle.status != Battle.Status.ACTIVE:
        return battle

    now = now or timezone.now()
    elapsed_ms = int((now - battle.turn_started_at).total_seconds() * 1000)
    if elapsed_ms <= 0:
        return battle

    current_timer_field = (
        "attacker_time_remaining_ms"
        if battle.current_turn == Battle.Turn.ATTACKER
        else "defender_time_remaining_ms"
    )
    current_value = getattr(battle, current_timer_field)
    next_value = max(0, current_value - elapsed_ms)
    setattr(battle, current_timer_field, next_value)
    battle.turn_started_at = now
    battle.save(update_fields=[current_timer_field, "turn_started_at"])

    if next_value == 0:
        resolve_battle(battle)

    return battle


def ensure_current_question(battle: Battle) -> BattleQuestion | None:
    unanswered_question = (
        battle.battle_questions.filter(answered_correctly__isnull=True)
        .select_related("question")
        .order_by("order", "id")
        .first()
    )
    if unanswered_question is not None:
        return unanswered_question

    if battle.current_turn == Battle.Turn.ATTACKER:
        target_topic = battle.attacker.topic
        asked_to = BattleQuestion.AskedTo.ATTACKER
    else:
        target_topic = battle.defender.topic
        asked_to = BattleQuestion.AskedTo.DEFENDER

    asked_question_ids = battle.battle_questions.values_list("question_id", flat=True)
    question = (
        Question.objects.filter(topic=target_topic)
        .exclude(id__in=asked_question_ids)
        .order_by("id")
        .first()
    )
    if question is None:
        question = Question.objects.filter(topic=target_topic).order_by("id").first()
    if question is None:
        return None

    max_order = battle.battle_questions.aggregate(max_order=Max("order"))["max_order"]
    return BattleQuestion.objects.create(
        battle=battle,
        question=question,
        asked_to=asked_to,
        order=(max_order + 1) if max_order is not None else 0,
    )


def resolve_battle(battle: Battle) -> Battle:
    if battle.status == Battle.Status.FINISHED:
        return battle

    if battle.attacker_score > battle.defender_score:
        winner = battle.attacker
        loser = battle.defender
    else:
        winner = battle.defender
        loser = battle.attacker

    battle.contested_square.owner = winner
    battle.contested_square.save(update_fields=["owner"])
    Square.objects.filter(game=battle.game, owner=loser).update(owner=None)

    battle.status = Battle.Status.FINISHED
    battle.winner = winner
    battle.save(update_fields=["status", "winner"])
    return battle


@transaction.atomic
def answer_battle_question(battle: Battle, is_correct: bool) -> Battle:
    battle = Battle.objects.select_for_update().get(id=battle.id)
    if battle.status != Battle.Status.ACTIVE:
        return battle

    now = timezone.now()
    elapsed_turn_ms = max(0, int((now - battle.turn_started_at).total_seconds() * 1000))
    sync_battle_timer(battle, now=now)
    battle.refresh_from_db()
    if battle.status != Battle.Status.ACTIVE:
        return battle

    current_question = ensure_current_question(battle)
    if current_question is not None:
        current_question.answered_correctly = is_correct
        current_question.time_taken_ms = elapsed_turn_ms
        current_question.save(update_fields=["answered_correctly", "time_taken_ms"])

    update_fields = ["current_turn", "turn_started_at"]
    if battle.current_turn == Battle.Turn.ATTACKER:
        if is_correct:
            battle.attacker_score += 1
            update_fields.append("attacker_score")
        battle.current_turn = Battle.Turn.DEFENDER
    else:
        if is_correct:
            battle.defender_score += 1
            update_fields.append("defender_score")
        battle.current_turn = Battle.Turn.ATTACKER

    battle.turn_started_at = now
    battle.save(update_fields=update_fields)
    ensure_current_question(battle)
    battle.refresh_from_db()

    if (
        battle.attacker_time_remaining_ms <= 0
        or battle.defender_time_remaining_ms <= 0
    ):
        resolve_battle(battle)
        battle.refresh_from_db()

    return battle
