"""
Definition of views.
"""

from datetime import datetime

from django.shortcuts import render


def home(request):
    """Renders the home page."""
    return render(request, 'app/index.html', {
        'title': 'Home Page',
        'year': datetime.now().year,
    })
