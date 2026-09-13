"""Absolute session lifetime.

``SESSION_COOKIE_AGE`` combined with ``SESSION_SAVE_EVERY_REQUEST`` gives a
*sliding* expiry: every request pushes the deadline out, so a session used once
a day never expires. That is the behaviour you want for idle timeout and the
wrong one for a stolen cookie, which an attacker will happily keep warm.

This caps the total life of a session from the moment of sign-in, regardless of
activity. Stack the two: idle timeout ends abandoned sessions quickly, the
absolute cap guarantees every session dies eventually.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

SESSION_STARTED_KEY = "_session_started_at"


@receiver(user_logged_in)
def stamp_session_start(sender, request, user, **kwargs) -> None:
    """Record when this session began. Runs after the key is cycled on login."""
    request.session[SESSION_STARTED_KEY] = time.time()


class AbsoluteSessionTimeoutMiddleware:
    """Sign out any session older than ``SESSION_ABSOLUTE_TIMEOUT`` seconds.

    Must sit after ``AuthenticationMiddleware`` so ``request.user`` is resolved.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            started = request.session.get(SESSION_STARTED_KEY)
            if started is None:
                # Session predates this middleware, or was created some other
                # way. Start its clock now rather than letting it live forever.
                request.session[SESSION_STARTED_KEY] = time.time()
            elif time.time() - started > settings.SESSION_ABSOLUTE_TIMEOUT:
                logout(request)
        return self.get_response(request)
