"""
apps/authentication/middleware.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. SessionActivityMiddleware  — updates UserProfile.last_activity on every
   authenticated request; enforces configurable session timeout.
2. RBACMiddleware             — enforces role-based access control by checking
   Django Group permissions for protected URL prefixes.

Bug fix (Phase 3 → Phase 5):
   last_activity is a DB column, not a session value. A fresh login after
   db.sqlite3 was kept from a previous run would find an old last_activity
   timestamp and immediately trigger "session expired". The fix:
   - Store the session start time in the SESSION (not only the DB profile).
   - Timeout is checked against session['last_activity'], which is reset
     on every new login by the post-login signal.
   - The DB profile.last_activity is still updated (for audit / admin display)
     but is NOT used for the timeout decision.
"""

import logging
from django.utils import timezone
from django.shortcuts import redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in

logger = logging.getLogger(__name__)

SESSION_ACTIVITY_KEY = '_kb_last_activity'

# URL prefixes that are always public (no login required)
PUBLIC_PREFIXES = [
    '/auth/login/',
    '/auth/logout/',
    '/admin/',
    '/static/',
    '/media/',
    '/api/health/',
    '/ai/health/',
]


# Reset session activity timestamp on every fresh login
def _reset_session_activity(sender, request, user, **kwargs):
    """
    Called by Django's user_logged_in signal immediately after login().
    Stamps the current time into the SESSION so the timeout clock starts
    from now — not from whatever last_activity was in the DB.
    """
    request.session[SESSION_ACTIVITY_KEY] = timezone.now().isoformat()
    # Also clear any stale "session expired" messages that may have been
    # queued in a previous anonymous session and carried over by cycle_key()
    from django.contrib.messages import get_messages
    list(get_messages(request))   # consuming clears the message queue


user_logged_in.connect(_reset_session_activity)


class SessionActivityMiddleware:
    """
    Enforces idle-session timeout using the SESSION (not the DB).
    The DB profile.last_activity is updated for display purposes only.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = getattr(settings, 'SESSION_COOKIE_AGE', 1800)

    def __call__(self, request):
        if request.user.is_authenticated:
            now = timezone.now()

            # --- Timeout check against SESSION value (not DB) ---
            last_str = request.session.get(SESSION_ACTIVITY_KEY)
            if last_str:
                try:
                    from django.utils.dateparse import parse_datetime
                    last = parse_datetime(last_str)
                    if last and (now - last).total_seconds() > self.timeout:
                        logger.info(
                            "Session timeout for user %s (idle %ds)",
                            request.user.username,
                            (now - last).total_seconds(),
                        )
                        logout(request)
                        messages.warning(
                            request, 'Your session has expired. Please sign in again.'
                        )
                        return redirect(settings.LOGIN_URL)
                except Exception:
                    pass  # malformed timestamp — treat as fresh session

            # --- Refresh session timestamp (throttled to once per 60s) ---
            if not last_str or (
                last_str and (now - parse_datetime_safe(last_str)).total_seconds() > 60
            ):
                request.session[SESSION_ACTIVITY_KEY] = now.isoformat()

            # --- Update DB profile for audit/display (best-effort) ---
            try:
                profile = request.user.profile
                if not profile.last_activity or (
                    now - profile.last_activity
                ).total_seconds() > 60:
                    profile.last_activity = now
                    profile.save(update_fields=['last_activity'])
            except Exception:
                pass   # profile may not exist yet; non-fatal

        return self.get_response(request)


def parse_datetime_safe(value: str):
    """Parse ISO datetime string; return epoch on failure."""
    try:
        from django.utils.dateparse import parse_datetime
        return parse_datetime(value) or timezone.now()
    except Exception:
        return timezone.now()


class RBACMiddleware:
    """
    Lightweight role-based access control middleware.

    Rules (checked in order):
    1. Public URL prefixes are always allowed.
    2. Unauthenticated requests to protected URLs are redirected to login.
    3. Staff-only URL prefixes require is_staff=True.
    4. All other authenticated requests are allowed (per-view decorators
       handle fine-grained permission checks).
    """

    STAFF_ONLY_PREFIXES = [
        '/settings/',
        '/audit-logs/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info

        # 1. Always allow public URLs
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return self.get_response(request)

        # 2. Require authentication for everything else
        if not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={path}")

        # 3. Staff-only sections
        if any(path.startswith(p) for p in self.STAFF_ONLY_PREFIXES):
            if not request.user.is_staff:
                logger.warning(
                    "RBAC: user %s attempted to access staff-only URL %s",
                    request.user.username, path,
                )
                messages.error(request, 'You do not have permission to access that page.')
                return redirect('dashboard:index')

        return self.get_response(request)
