"""
Definition of urls for Radient_Django.
"""

from django.urls import path

from app import views

urlpatterns = [
    path('', views.home, name='home'),
]
