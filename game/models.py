from django.core.validators import RegexValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Color must be a valid hex value like #A1B2C3.",
)
DEFAULT_BATTLE_TIME_MS = 60000


class Player(models.Model):
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=7, validators=[hex_color_validator])
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Topic(models.Model):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True, default="")

    def __str__(self):
        return self.name


class Question(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField(blank=True, default="")
    image = models.FileField(upload_to="questions/", blank=True)
    image_url = models.URLField(blank=True)
    answer = models.TextField()

    def __str__(self):
        return self.text or self.answer or f"Question {self.pk}"


class Game(models.Model):
    class Status(models.TextChoices):
        LOBBY = "lobby", "Lobby"
        ACTIVE = "active", "Active"
        FINISHED = "finished", "Finished"

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.LOBBY)

    def __str__(self):
        return f"Game {self.pk}"


class GamePlayer(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="game_players")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="game_players")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="game_players")
    is_eliminated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.player} in {self.game}"


class Square(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="squares")
    row = models.IntegerField(validators=[MinValueValidator(0)])
    col = models.IntegerField(validators=[MinValueValidator(0)])
    owner = models.ForeignKey(
        GamePlayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_squares",
    )

    def __str__(self):
        return f"({self.row}, {self.col}) in {self.game}"


class Battle(models.Model):
    class Turn(models.TextChoices):
        ATTACKER = "attacker", "Attacker"
        DEFENDER = "defender", "Defender"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        FINISHED = "finished", "Finished"
        CLOSED = "closed", "Closed"

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="battles")
    attacker = models.ForeignKey(
        GamePlayer,
        on_delete=models.CASCADE,
        related_name="attacks_started",
    )
    defender = models.ForeignKey(
        GamePlayer,
        on_delete=models.CASCADE,
        related_name="defenses_faced",
    )
    contested_square = models.ForeignKey(
        Square,
        on_delete=models.CASCADE,
        related_name="battles",
    )
    attacker_time_remaining_ms = models.IntegerField(
        default=DEFAULT_BATTLE_TIME_MS,
        validators=[MinValueValidator(0)],
    )
    defender_time_remaining_ms = models.IntegerField(
        default=DEFAULT_BATTLE_TIME_MS,
        validators=[MinValueValidator(0)],
    )
    current_turn = models.CharField(
        max_length=20,
        choices=Turn.choices,
        default=Turn.ATTACKER,
    )
    attacker_score = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    defender_score = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    turn_started_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    winner = models.ForeignKey(
        GamePlayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="battles_won",
    )

    def __str__(self):
        return f"Battle {self.pk}"


class BattleQuestion(models.Model):
    class AskedTo(models.TextChoices):
        ATTACKER = "attacker", "Attacker"
        DEFENDER = "defender", "Defender"

    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name="battle_questions")
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="battle_questions",
    )
    asked_to = models.CharField(max_length=20, choices=AskedTo.choices)
    answered_correctly = models.BooleanField(null=True, blank=True)
    time_taken_ms = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(validators=[MinValueValidator(0)])

    def __str__(self):
        return f"Battle {self.battle_id} Q{self.order}"
