from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import SAFE_METHODS, BasePermission


class CsrfProtected(BasePermission):
    """Require a valid CSRF token, even when nobody is signed in yet.

    DRF marks every ``@api_view`` handler ``csrf_exempt`` and re-checks CSRF
    only inside ``SessionAuthentication`` — which returns early when the request
    carries no session cookie. So an unauthenticated POST gets no CSRF check at
    all, and the sign-in endpoints are exactly the unauthenticated POSTs that
    need one: without it, a third-party page can silently POST a token of its
    choosing and sign a visitor into an account the attacker controls.

    Clients must fetch ``/api/auth/options/`` first — it sets the cookie.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        # Raises rest_framework.exceptions.PermissionDenied, so the client gets
        # a JSON 403 rather than Django's HTML error page.
        SessionAuthentication().enforce_csrf(request)
        return True
