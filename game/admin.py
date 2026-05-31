import csv
import io

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
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


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ("text", "answer")
    show_change_link = True


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "color", "is_active")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "question_count")
    inlines = [QuestionInline]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(question_total=Count("questions"))

    @admin.display(ordering="question_total", description="Question count")
    def question_count(self, obj):
        return obj.question_total


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "topic_name", "text", "answer")
    list_filter = ("topic",)
    search_fields = ("text", "answer")
    actions = ("import_questions_from_csv",)
    change_list_template = "admin/game/question/change_list.html"

    @admin.display(ordering="topic__name", description="Topic")
    def topic_name(self, obj):
        return obj.topic.name

    @admin.action(description="Import questions from CSV")
    def import_questions_from_csv(self, request, queryset):
        return HttpResponseRedirect(reverse("admin:game_question_import_csv"))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_csv_view),
                name="game_question_import_csv",
            ),
        ]
        return custom_urls + urls

    def import_csv_view(self, request):
        if request.method == "POST":
            csv_file = request.FILES.get("csv_file")
            if not csv_file:
                self.message_user(request, "Please upload a CSV file.", level=messages.ERROR)
                return HttpResponseRedirect(request.path)

            try:
                decoded = csv_file.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                self.message_user(request, "CSV must be UTF-8 encoded.", level=messages.ERROR)
                return HttpResponseRedirect(request.path)

            reader = csv.DictReader(io.StringIO(decoded))
            required_columns = {"topic", "question", "answer"}
            missing_columns = required_columns - set(reader.fieldnames or [])
            if missing_columns:
                self.message_user(
                    request,
                    f"Missing CSV columns: {', '.join(sorted(missing_columns))}.",
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.path)

            questions_to_create = []
            created_topics = 0
            topic_cache = {}

            try:
                with transaction.atomic():
                    for row_number, row in enumerate(reader, start=2):
                        topic_name = (row.get("topic") or "").strip()
                        question_text = (row.get("question") or "").strip()
                        answer_text = (row.get("answer") or "").strip()

                        if not topic_name and not question_text and not answer_text:
                            continue
                        if not topic_name or not question_text or not answer_text:
                            missing = [
                                column
                                for column, value in {
                                    "topic": topic_name,
                                    "question": question_text,
                                    "answer": answer_text,
                                }.items()
                                if not value
                            ]
                            raise ValueError(
                                f"Row {row_number} is missing values for: {', '.join(missing)}."
                            )

                        topic = topic_cache.get(topic_name)
                        if topic is None:
                            topic = Topic.objects.filter(name=topic_name).first()
                            if topic is None:
                                topic = Topic.objects.create(name=topic_name)
                                created_topics += 1
                            topic_cache[topic_name] = topic

                        questions_to_create.append(
                            Question(topic=topic, text=question_text, answer=answer_text)
                        )

                    if not questions_to_create:
                        raise ValueError("No valid question rows found in CSV.")

                    Question.objects.bulk_create(questions_to_create)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return HttpResponseRedirect(request.path)

            self.message_user(
                request,
                (
                    f"Imported {len(questions_to_create)} questions. "
                    f"Created {created_topics} new topics."
                ),
                level=messages.SUCCESS,
            )
            return HttpResponseRedirect(reverse("admin:game_question_changelist"))

        context = {
            **self.admin_site.each_context(request),
            "title": "Import questions from CSV",
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/game/question/import_csv.html", context)


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
