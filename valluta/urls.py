"""
URL configuration for valluta project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('display/', include('host.urls', namespace='display')),
    path('control/', include('host.urls_control', namespace='control')),
    path('api/', include('host.urls_api')),
]
