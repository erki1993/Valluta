from django.shortcuts import render


def display(request):
    return render(request, 'host/display.html')


def control(request):
    return render(request, 'host/control.html')
