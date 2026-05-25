"""
Base view for driver job **execution** routes (POST mutate).

Separated from read-only job detail to enforce ``mobile.driver.jobs.execute``.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.helpers.job_execution_security import (
    resolve_secure_job_execution_context,
)
from mobile_api.permissions import HasDriverJobsExecuteAccess
from mobile_api.throttling import MobileJobListThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.views.driver_profile import (
    _mobile_tenant_schema,
    _mobile_user_id,
)


class _DriverJobExecutionBaseView(MobileAPIView):
    permission_classes = [HasDriverJobsExecuteAccess]
    required_mobile_capability = 'mobile.driver.jobs.execute'
    throttle_classes = [MobileJobListThrottle]

    def _resolve_execution_context(self, request):
        tenant_schema = _mobile_tenant_schema(request)
        secured = resolve_secure_job_execution_context(
            user_id=_mobile_user_id(request),
            tenant_schema=tenant_schema,
            request=request,
        )
        if not secured.get('success'):
            return None, secured
        return secured['ctx'], None

    def _execution_context_error(self, err: dict):
        return self.error(
            message=err.get('error', _('mobile.validation.failed')),
            code='execution_context_failed',
            message_key='mobile.error.generic',
            http_code=403,
        )
