"""
Definition of urls for Radient_Django.
"""

from datetime import datetime

from django.contrib.auth import views as auth_views
from django.urls import path

from app import views
from app.forms import BootstrapAuthenticationForm

urlpatterns = [
    path('', views.home, name='home'),
    path('contact', views.contact, name='contact'),
    path('about', views.about, name='about'),
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='app/login.html',
            authentication_form=BootstrapAuthenticationForm,
            extra_context={'title': 'Log in', 'year': datetime.now().year},
        ),
        name='login',
    ),
    path('logout', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
]
