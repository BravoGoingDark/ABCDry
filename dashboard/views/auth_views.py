from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.utils.translation import gettext as _


def landing_view(request):
    """Always show the login/landing page — no redirect for authenticated users."""
    return render(request, 'dashboard/login.html')


def login_view(request):
    """Display login page and handle authentication."""
    if request.user.is_authenticated:
        next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard:dashboard'
        if not next_url.startswith('/') or '//' in next_url:
            next_url = 'dashboard:dashboard'
        return redirect(next_url)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard:dashboard'
            if not next_url.startswith('/') or '//' in next_url:
                next_url = 'dashboard:dashboard'
            return redirect(next_url)
        messages.error(request, _('Invalid username or password.'))

    return render(request, 'dashboard/login.html')


def logout_view(request):
    """Log out current user and redirect to login."""
    auth_logout(request)
    messages.info(request, _('You have been logged out.'))
    return redirect('dashboard:login')
