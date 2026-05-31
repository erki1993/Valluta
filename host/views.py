from django.shortcuts import render
from game.models import Game


def display(request):
    return render(request, 'host/display.html')


def control(request):
    active_games = Game.objects.filter(status=Game.Status.ACTIVE).order_by("-created_at")
    return render(request, "host/control.html", {"active_games": active_games})
