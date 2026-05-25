"""
mobile_api/views/driver_job_allowed_actions.py

Dynamic allowed-actions from ``get_allowed_actions()`` only.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.services.driver_job_allowed_actions_service import (
    DriverJobAllowedActionsService,
)
from mobile_api.views.driver_job_detail import _DriverJobDetailBaseView


class DriverShipmentAllowedActionsView(_DriverJobDetailBaseView):
    """
    GET /api/v1/mobile/driver/jobs/shipments/{shipment_id}/actions/

    Membership from ``get_allowed_actions()`` only; metadata from Action Master rows.
    """

    def get(self, request, shipment_id):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='job_actions_context_failed',
                message_key='mobile.error.generic',
            )

        result = DriverJobAllowedActionsService.get_shipment_allowed_actions(
            driver=ctx.driver,
            shipment_id=shipment_id,
            request=request,
        )
        return self._respond_allowed_actions(result)


class DriverMovementAllowedActionsView(_DriverJobDetailBaseView):
    """
    GET /api/v1/mobile/driver/jobs/movements/{movement_id}/actions/
    """

    def get(self, request, movement_id):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='job_actions_context_failed',
                message_key='mobile.error.generic',
            )

        result = DriverJobAllowedActionsService.get_movement_allowed_actions(
            driver=ctx.driver,
            movement_id=movement_id,
            request=request,
        )
        return self._respond_allowed_actions(result)
