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
        self.exact_exempt.add('/signup/')
        self.exact_exempt.add('/api/drought-prediction/')
        self.exact_exempt.add('/api/live-metrics/')
        self.exact_exempt.add('/api/submit-metrics/')
        self.exact_exempt.add('/accounts/login/')
        # Django's default post-login redirect target — prevent redirect loops
        self.exact_exempt.add('/accounts/profile/')
        # Installable farmer app: phones fetch these without the session cookie.
        # Neither contains user data (app name, icons, caching rules only).
        self.exact_exempt.add('/farmer/manifest.webmanifest')
        self.exact_exempt.add('/farmer/sw.js')
        # Mobile app login (the app then sends its token)
        self.exact_exempt.add('/farmer/api/auth/login/')
        # Mobile app sign-up (same rules as the public /signup/ page)
        self.exact_exempt.add('/farmer/api/auth/signup/')

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


class ApiTokenMiddleware:
    """Login for the farmer mobile app: "Authorization: Token <key>".

    Only on the farmer API and the assistant; the web pages keep their session
    cookie. A token request carries no cookie, so there is no cross-site
    request to forge and the CSRF check is skipped for it alone. Runs after
    AuthenticationMiddleware and before LoginRequiredMiddleware.
    """
    PREFIXES = ('/farmer/api/', '/assistant/chat/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if header.startswith('Token ') and request.path.startswith(self.PREFIXES):
            from django.http import JsonResponse
            from rest_framework.authtoken.models import Token
            token = Token.objects.select_related('user').filter(key=header[6:].strip()).first()
            if token is None or not token.user.is_active:
                return JsonResponse({'error': 'Invalid or expired login.'}, status=401)
            request.user = token.user
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)


class FarmerScopeMiddleware:
    """Keep accounts with the "farmer" role inside the farmer space.

    Farmers get their own simplified pages (/farmer/) and the assistant chat
    endpoint; the analyst dashboard, data ingestion, admin and regional APIs
    are not theirs to see. Pages redirect to /farmer/, API calls get 403.
    Runs after LoginRequiredMiddleware, so request.user is resolved.
    """

    ALLOWED_PREFIXES = ('/farmer/', '/assistant/chat/', '/logout/', '/i18n/',
                        '/api/tiles/', '/favicon.ico')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and not user.is_superuser:
            profile = getattr(user, 'profile', None)
            if profile is not None and profile.role == 'farmer':
                path = request.path
                allowed = path.startswith(self.ALLOWED_PREFIXES) or (
                    settings.STATIC_URL and path.startswith(settings.STATIC_URL))
                if not allowed:
                    if path.startswith('/api/'):
                        from django.http import JsonResponse
                        return JsonResponse({'error': 'Not available for farmer accounts.'},
                                            status=403)
                    return redirect('/farmer/')
        return self.get_response(request)
