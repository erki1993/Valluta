import random
from collections import defaultdict, deque

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from game.models import Battle, BattleQuestion, Game, GamePlayer, Question, Square


def get_game_winner(game_id: int) -> GamePlayer | None:
    game_players = list(
        GamePlayer.objects.filter(game_id=game_id)
        .select_related("player", "topic")
        .order_by("id")
    )
    owner_ids = set(
        Square.objects.filter(game_id=game_id, owner__isnull=False).values_list("owner_id", flat=True)
    )

    players_with_squares = [
        game_player for game_player in game_players if game_player.id in owner_ids
    ]
    if len(players_with_squares) == 1:
        return players_with_squares[0]

    non_eliminated_players = [
        game_player for game_player in game_players if not game_player.is_eliminated
    ]
    if len(non_eliminated_players) == 1:
        return non_eliminated_players[0]

    return None


def check_game_over(game_id: int) -> GamePlayer | None:
    game = Game.objects.get(pk=game_id)
    game_players = list(
        GamePlayer.objects.filter(game=game)
        .select_related("player", "topic")
        .order_by("id")
    )
    owner_ids = set(
        Square.objects.filter(game=game, owner__isnull=False).values_list("owner_id", flat=True)
    )

    eliminated_player_ids = [
        game_player.id
        for game_player in game_players
        if game_player.id not in owner_ids and not game_player.is_eliminated
    ]
    if eliminated_player_ids:
        GamePlayer.objects.filter(id__in=eliminated_player_ids).update(is_eliminated=True)

    winner = get_game_winner(game_id)
    if winner is not None and game.status != Game.Status.FINISHED:
        game.status = Game.Status.FINISHED
        game.save(update_fields=["status"])

    return winner


def _assign_contiguous_regions(active_game_players: list, rows: int = 5, cols: int = 5) -> dict:
    """Partition a rows×cols grid into contiguous regions, one per player.

    Phase 1 – BFS flood-fill from maximally-spread seed positions to guarantee
    every player gets a fully-connected territory.
    Phase 2 – Border-swap balancing: cells are moved from over-quota players to
    under-quota players (along shared borders, preserving contiguity) until
    quotas are met or no further swaps are possible.  When two players don't
    share a direct border a chain transfer is attempted through intermediate
    players.

    Returns a dict mapping (row, col) -> GamePlayer.
    """
    n = len(active_game_players)
    total = rows * cols
    base = total // n
    extra = total % n
    quotas = [base + (1 if i < extra else 0) for i in range(n)]

    # --- Phase 1: BFS flood-fill from spread-out seeds ---

    def _spread_seeds() -> list:
        all_cells = [(r, c) for r in range(rows) for c in range(cols)]
        random.shuffle(all_cells)
        selected = [all_cells[0]]
        remaining = all_cells[1:]
        while len(selected) < n:
            best = max(remaining, key=lambda c: min(abs(c[0] - s[0]) + abs(c[1] - s[1]) for s in selected))
            selected.append(best)
            remaining.remove(best)
        random.shuffle(selected)
        return selected

    seeds = _spread_seeds()
    owner: dict[tuple, int] = {seed: i for i, seed in enumerate(seeds)}
    frontiers: list[deque] = [deque([seed]) for seed in seeds]
    unassigned = set((r, c) for r in range(rows) for c in range(cols)) - set(seeds)

    while unassigned:
        progress = False
        for i in range(n):
            while frontiers[i]:
                r, c = frontiers[i][0]
                neighbor = None
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nb = (r + dr, c + dc)
                    if nb in unassigned:
                        neighbor = nb
                        break
                if neighbor is not None:
                    owner[neighbor] = i
                    unassigned.discard(neighbor)
                    frontiers[i].append(neighbor)
                    progress = True
                    break
                else:
                    frontiers[i].popleft()
        if not progress:
            break

    # --- Phase 2: border-swap balancing ---

    def _is_contiguous(cells_set: set) -> bool:
        if not cells_set:
            return True
        start = next(iter(cells_set))
        visited: set = {start}
        stack = [start]
        while stack:
            r, c = stack.pop()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nb = (r + dr, c + dc)
                if nb in cells_set and nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        return visited == cells_set

    def _is_removable(cells_set: set, cell: tuple) -> bool:
        if len(cells_set) <= 1:
            return False
        return _is_contiguous(cells_set - {cell})

    player_cells: list[set] = [set(k for k, v in owner.items() if v == i) for i in range(n)]
    counts = [len(c) for c in player_cells]

    def _player_adjacency() -> dict[int, set]:
        adj: dict[int, set] = defaultdict(set)
        for (r, c), pi in owner.items():
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nb = (r + dr, c + dc)
                if nb in owner and owner[nb] != pi:
                    adj[pi].add(owner[nb])
        return adj

    def _transfer_one(from_i: int, to_i: int) -> bool:
        for cell in list(player_cells[from_i]):
            r, c = cell
            if any((r + dr, c + dc) in player_cells[to_i] for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))):
                if _is_removable(player_cells[from_i], cell):
                    player_cells[from_i].discard(cell)
                    player_cells[to_i].add(cell)
                    owner[cell] = to_i
                    counts[from_i] -= 1
                    counts[to_i] += 1
                    return True
        return False

    def _find_path(src: int, dst: int) -> list | None:
        adj = _player_adjacency()
        queue: deque = deque([(src, [src])])
        visited: set = {src}
        while queue:
            node, path = queue.popleft()
            if node == dst:
                return path
            for nb in adj[node]:
                if nb not in visited:
                    visited.add(nb)
                    queue.append((nb, path + [nb]))
        return None

    # Upper bound on balancing iterations: each iteration transfers at least one
    # cell, and at most `total` cells ever need moving, so this limit is generous
    # while still preventing an infinite loop in degenerate cases.
    _MAX_BALANCING_ITERATIONS = total * 2
    for _ in range(_MAX_BALANCING_ITERATIONS):
        overs = [i for i in range(n) if counts[i] > quotas[i]]
        unders = [i for i in range(n) if counts[i] < quotas[i]]
        if not overs or not unders:
            break
        transferred = False
        for oi in overs:
            for ui in unders:
                if _transfer_one(oi, ui):
                    transferred = True
                    break
                path = _find_path(oi, ui)
                if path and len(path) > 1:
                    if all(_transfer_one(path[k], path[k + 1]) for k in range(len(path) - 1)):
                        transferred = True
                        break
            if transferred:
                break
        if not transferred:
            break

    return {cell: active_game_players[i] for cell, i in owner.items()}


def start_game(game_id: int) -> None:
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
        return

    # Create 25 squares fresh and distribute them in contiguous regions.
    game.squares.all().delete()
    Square.objects.bulk_create([
        Square(game=game, row=row, col=col)
        for row in range(5)
        for col in range(5)
    ])

    cell_to_player = _assign_contiguous_regions(active_game_players)

    all_squares = list(game.squares.all())
    to_update = []
    for sq in all_squares:
        gp = cell_to_player.get((sq.row, sq.col))
        if gp is not None:
            sq.owner = gp
            to_update.append(sq)
    Square.objects.bulk_update(to_update, ["owner"])


def start_battle(game_id: int, attacker_id: int, defender_id: int) -> Battle:
    game = Game.objects.get(pk=game_id)
    if game.status != Game.Status.ACTIVE:
        raise ValueError("Game is not active.")
    if get_active_battle(game_id=game_id) is not None:
        raise ValueError("A battle is already in progress.")

    attacker = GamePlayer.objects.get(pk=attacker_id, game=game, is_eliminated=False)
    defender = GamePlayer.objects.get(pk=defender_id, game=game, is_eliminated=False)
    if attacker.pk == defender.pk:
        raise ValueError("Attacker and defender must be different players.")

    contested_square = Square.objects.filter(game=game, owner=defender).order_by("?").first()
    if contested_square is None:
        raise ValueError("Defender has no squares to contest.")

    battle = Battle.objects.create(
        game=game,
        attacker=attacker,
        defender=defender,
        contested_square=contested_square,
        status=Battle.Status.PENDING,
    )
    ensure_current_question(battle)
    return battle


def begin_battle(battle: Battle) -> Battle:
    if battle.status != Battle.Status.PENDING:
        return battle
    battle.status = Battle.Status.ACTIVE
    battle.turn_started_at = timezone.now()
    battle.save(update_fields=["status", "turn_started_at"])
    return battle


def close_battle(battle: Battle) -> Battle:
    if battle.status != Battle.Status.FINISHED:
        return battle
    battle.status = Battle.Status.CLOSED
    battle.save(update_fields=["status"])
    return battle


def get_active_battle(game_id: int | None = None) -> Battle | None:
    queryset = Battle.objects.filter(
        status__in=[Battle.Status.PENDING, Battle.Status.ACTIVE, Battle.Status.FINISHED]
    ).select_related(
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

    Square.objects.filter(game=battle.game, owner=loser).update(owner=winner)
    loser.is_eliminated = True
    loser.save(update_fields=["is_eliminated"])

    battle.status = Battle.Status.FINISHED
    battle.winner = winner
    battle.save(update_fields=["status", "winner"])
    check_game_over(battle.game_id)
    return battle


@transaction.atomic
def pass_battle_question(battle: Battle) -> Battle:
    PASS_PENALTY_MS = 3000
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
        current_question.answered_correctly = False
        current_question.time_taken_ms = elapsed_turn_ms
        current_question.save(update_fields=["answered_correctly", "time_taken_ms"])

    update_fields = ["turn_started_at"]
    if battle.current_turn == Battle.Turn.ATTACKER:
        battle.attacker_time_remaining_ms = max(0, battle.attacker_time_remaining_ms - PASS_PENALTY_MS)
        update_fields.append("attacker_time_remaining_ms")
    else:
        battle.defender_time_remaining_ms = max(0, battle.defender_time_remaining_ms - PASS_PENALTY_MS)
        update_fields.append("defender_time_remaining_ms")

    battle.turn_started_at = now
    battle.save(update_fields=update_fields)
    ensure_current_question(battle)
    battle.refresh_from_db()

    if battle.attacker_time_remaining_ms <= 0 or battle.defender_time_remaining_ms <= 0:
        resolve_battle(battle)
        battle.refresh_from_db()

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
