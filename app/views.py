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


def contact(request):
    """Renders the contact page."""
    return render(request, 'app/contact.html', {
        'title': 'Contact',
        'message': 'Your contact page.',
        'year': datetime.now().year,
    })


def about(request):
    """Renders the about page."""
    return render(request, 'app/about.html', {
        'title': 'About',
        'message': 'Your application description page.',
        'year': datetime.now().year,
    })
