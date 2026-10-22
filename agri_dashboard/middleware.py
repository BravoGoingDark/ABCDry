from django.conf import settings
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin


class NoCacheHTMLMiddleware(MiddlewareMixin):
    """Mark HTML responses no-cache so browsers never serve stale pages.

    A page cached on disk keeps referencing whatever hashed JS it was rendered
    with. When the tile architecture changes (or any JS changes), an old cached
    page keeps loading the old script — which is how a fixed map can still show
    "Access blocked" tiles days later. Marking HTML responses no-cache makes
    the browser revalidate every page load, while hashed static assets (unique
    URLs per content) stay aggressively cacheable.
    """

    def process_response(self, request, response):
        if response.get('Content-Type', '').startswith('text/html'):
            response['Cache-Control'] = 'no-cache'
        return response


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
            # Public basemap tiles: Leaflet requests them as plain <img> and
            # cannot follow a login redirect, so an expired session would
            # otherwise blank the map.
            '/api/tiles/',
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
