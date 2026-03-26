from datetime import datetime, timedelta

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone


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

        # Skip static files
        if request.path.startswith("/static/") or request.path.startswith(
            "/media/"
        ):
            return self.get_response(request)

        # Get timeout setting
        try:
            from superadmin.auth_helpers import get_security_settings

            settings_obj = get_security_settings()
            timeout_minutes = settings_obj.session_timeout_minutes
        except Exception:
            timeout_minutes = 240

        # Check last activity
        last_activity = request.session.get("last_activity")

        if last_activity:
            last_activity_time = datetime.fromisoformat(last_activity)
            if timezone.is_naive(last_activity_time):
                last_activity_time = timezone.make_aware(
                    last_activity_time,
                    timezone=timezone.get_current_timezone(),
                )

            expiry_time = last_activity_time + timedelta(minutes=timeout_minutes)

            if timezone.now() > expiry_time:
                request.session.flush()
                messages.warning(
                    request,
                    "Your session has expired. Please login again.",
                )
                return redirect("/login/")

        # Update last activity
        request.session["last_activity"] = timezone.now().isoformat()

        return self.get_response(request)
