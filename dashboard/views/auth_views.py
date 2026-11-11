from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.utils.translation import gettext as _

from ..forms import FarmerSignupForm


def _home_for(user):
    """Farmers land in their own space; everyone else on the dashboard."""
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.role == 'farmer' and not user.is_superuser:
        return 'dashboard:farmer_home'
    return 'dashboard:dashboard'


def landing_view(request):
    """Show the home page with project description — no redirect for authenticated users."""
    if request.user.is_authenticated:
        return redirect(_home_for(request.user))
    return render(request, 'dashboard/home.html')


def login_view(request):
    """Display login page and handle authentication."""
    if request.user.is_authenticated:
        next_url = request.GET.get('next') or request.POST.get('next') or _home_for(request.user)
        if not next_url.startswith('/') or '//' in next_url:
            next_url = _home_for(request.user)
        return redirect(next_url)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        # Check if the account exists but is inactive (pending confirmation)
        # before calling authenticate(), because Django's ModelBackend returns
        # None for is_active=False users and we'd lose the specific message.
        user_qs = User.objects.filter(username__iexact=username).first()
        if user_qs is not None and not user_qs.is_active:
            messages.error(
                request,
                _('Your account is not yet confirmed. Please wait for an administrator to approve it before signing in.')
            )
            return render(request, 'dashboard/login.html')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next') or _home_for(user)
            if not next_url.startswith('/') or '//' in next_url:
                next_url = _home_for(user)
            return redirect(next_url)
        if user_qs is None:
            messages.error(request, _('No account found with this username.'))
        else:
            messages.error(request, _('Invalid username or password.'))

    return render(request, 'dashboard/login.html')


def signup_view(request):
    """Public farmer self-registration.

    Collects username, optional email, phone number, password and confirm
    password. The account is active immediately; the farmer is sent to the
    login page to sign in.
    """
    if request.user.is_authenticated:
        return redirect(_home_for(request.user))

    if request.method == 'POST':
        form = FarmerSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                _('Account created for "{username}". You can now sign in.').format(username=user.username)
            )
            return redirect('dashboard:login')
    else:
        form = FarmerSignupForm()

    return render(request, 'dashboard/signup.html', {'form': form})


def logout_view(request):
    """Log out current user and redirect to login."""
    auth_logout(request)
    messages.info(request, _('You have been logged out.'))
    return redirect('dashboard:login')
