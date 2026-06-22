from django.conf import settings
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    """Require login for all requests except those in a whitelist.

    Whitelist includes: LOGIN_URL, '/logout/', admin path, static and media files, and i18n.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = [
            settings.STATIC_URL,
            '/admin/',
            '/i18n/',
            '/favicon.ico',
        ]
        # exact paths that should be exempt (no prefix matching)
        self.exact_exempt = {'/'}
        # include explicit login/logout if set
        login_url = getattr(settings, 'LOGIN_URL', '/login/')
        logout_url = getattr(settings, 'LOGOUT_URL', '/logout/')
        self.exact_exempt.add(login_url)
        self.exact_exempt.add(logout_url)
        self.exact_exempt.add('/api/drought-prediction/')
        self.exact_exempt.add('/api/live-metrics/')
        self.exact_exempt.add('/api/submit-metrics/')
        self.exact_exempt.add('/accounts/login/')
        # Django's default post-login redirect target — prevent redirect loops
        self.exact_exempt.add('/accounts/profile/')

    def __call__(self, request):
        path = request.path
        # Check exact-match exempt paths first
        if path in self.exact_exempt:
            return self.get_response(request)
        # Allow if path starts with any exempt prefix
        for prefix in self.exempt_prefixes:
            if prefix and path.startswith(prefix):
                return self.get_response(request)

        # If user is authenticated, proceed
        if getattr(request, 'user', None) and request.user.is_authenticated:
            return self.get_response(request)

        # Otherwise redirect to login page
        return redirect(getattr(settings, 'LOGIN_URL', '/login/'))
