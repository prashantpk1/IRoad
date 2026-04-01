from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.shortcuts import redirect


class SessionTimeoutMiddleware:
    EXEMPT_URLS = [
        "/login/",
        "/logout/",
        "/set-password/",
        "/reset-password/",
        "/new-password/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for non-authenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for exempt URLs
        if any(request.path.startswith(url) for url in self.EXEMPT_URLS):
            return self.get_response(request)

        # Skip static and media files
        if request.path.startswith("/static/") or request.path.startswith("/media/"):
            return self.get_response(request)

        try:
            from superadmin.auth_helpers import get_security_settings
            from superadmin.redis_helpers import refresh_admin_session

            settings_obj = get_security_settings()
            timeout_minutes = settings_obj.session_timeout_minutes

            jti = request.session.get("jti")

            if not jti:
                # No JTI in session — force logout
                auth_logout(request)
                messages.warning(
                    request,
                    "Your session has expired. Please login again.",
                )
                return redirect("/login/")

            # Check Redis and refresh TTL
            session_alive = refresh_admin_session(jti, timeout_minutes)

            if not session_alive:
                # Redis key gone — session expired
                auth_logout(request)
                messages.warning(
                    request,
                    "Your session has expired. Please login again.",
                )
                return redirect("/login/")

        except Exception:
            # If Redis is down — fail safe, allow request
            pass

        return self.get_response(request)

