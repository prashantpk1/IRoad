"""
mobile_api/views/driver_dashboard.py

Driver home dashboard endpoints (full + summary).
"""
from django.utils.translation import gettext as _

from mobile_api.views.base import MobileAPIView
from mobile_api.permissions import HasDriverDashboardAccess
from mobile_api.throttling import MobileUserThrottle
from mobile_api.services.driver_dashboard_service import (
    get_driver_dashboard,
    get_driver_dashboard_current_job,
    get_driver_dashboard_quick_actions,
    get_driver_dashboard_summary,
)
from mobile_api.services.driver_dashboard_notifications import (
    get_driver_notifications_summary,
)
from mobile_api.services.driver_dashboard_recent_activity import (
    get_driver_recent_activity,
)
from mobile_api.views.driver_profile import (
    _mobile_jwt_payload,
    _mobile_tenant_schema,
    _mobile_user_id,
)


class _DriverDashboardBaseView(MobileAPIView):
    """
    Driver home dashboard — requires ``mobile.driver.dashboard`` capability.

    Enforced by ``HasDriverDashboardAccess`` (driver principal + tenant binding).
    """

    permission_classes = [HasDriverDashboardAccess]
    required_mobile_capability = 'mobile.driver.dashboard'
    throttle_classes = [MobileUserThrottle]

    fetch_fn = None
    success_message_key = 'mobile.dashboard.fetch_success'

    def get(self, request):
        result = self.fetch_fn(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='dashboard_fetch_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_(self.success_message_key),
            data=result.get('dashboard') or {},
            message_key=self.success_message_key,
        )


class DriverDashboardView(_DriverDashboardBaseView):
    """
    GET /api/v1/mobile/driver/dashboard/

    Full home dashboard: welcome, driver summary, counters, current job,
    quick actions, notifications stub, recent activity (default limit 10).
    """

    fetch_fn = staticmethod(get_driver_dashboard)
    success_message_key = 'mobile.dashboard.fetch_success'


class DriverDashboardNotificationsSummaryView(_DriverDashboardBaseView):
    """
    GET /api/v1/mobile/driver/dashboard/notifications-summary/

    Lightweight notification summary only (counts + capped items + FCM meta).
    """

    success_message_key = 'mobile.dashboard.notifications_fetch_success'

    def get(self, request):
        variant = (request.query_params.get('variant') or 'full').strip().lower()
        if variant not in ('full', 'summary'):
            variant = 'full'

        result = get_driver_notifications_summary(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
            variant=variant,
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='notifications_fetch_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_(self.success_message_key),
            data=result.get('notifications_summary') or {},
            message_key=self.success_message_key,
        )


class DriverDashboardRecentActivityView(_DriverDashboardBaseView):
    """
    GET /api/v1/mobile/driver/dashboard/recent-activity/

    Lightweight merged activity feed (actions, shipments, movements, POD).
    Query ``limit`` optional (1–10, default 10).
    """

    success_message_key = 'mobile.dashboard.activity_fetch_success'

    def get(self, request):
        result = get_driver_recent_activity(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='activity_fetch_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_(self.success_message_key),
            data=result.get('activity') or {},
            message_key=self.success_message_key,
        )


class DriverDashboardCurrentJobView(_DriverDashboardBaseView):
    """
    GET /api/v1/mobile/driver/dashboard/current-job/

    Lightweight current-job snapshot for high-frequency polling.
    """

    success_message_key = 'mobile.dashboard.current_job_fetch_success'

    def get(self, request):
        result = get_driver_dashboard_current_job(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
        )
        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='current_job_fetch_failed',
                message_key='mobile.error.generic',
                data={},
            )
        return self.success(
            message=_(self.success_message_key),
            data=result.get('current_job') or {},
            message_key=self.success_message_key,
        )


class DriverDashboardQuickActionsView(_DriverDashboardBaseView):
    """
    GET /api/v1/mobile/driver/dashboard/quick-actions/

    Dynamic quick-action metadata without loading the full dashboard.
    """

    success_message_key = 'mobile.dashboard.quick_actions_fetch_success'

    def get(self, request):
        result = get_driver_dashboard_quick_actions(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
        )
        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='quick_actions_fetch_failed',
                message_key='mobile.error.generic',
                data={},
            )
        return self.success(
            message=_(self.success_message_key),
            data=result.get('quick_actions') or {},
            message_key=self.success_message_key,
        )


class DriverDashboardSummaryView(_DriverDashboardBaseView):
    """
    GET /api/v1/mobile/driver/dashboard/summary/

    Same response contract as the full dashboard, optimized for polling:
    ``variant=summary`` and a smaller recent-activity cap (default 5).
    """

    fetch_fn = staticmethod(get_driver_dashboard_summary)
    success_message_key = 'mobile.dashboard.summary_fetch_success'
