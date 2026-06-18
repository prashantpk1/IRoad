"""Bounded execution timeline projections for mobile job detail."""

from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.impacts import operation_action_matches
from iroad_tenants.services.timeline_query import (
    TIMELINE_ORDER,
    base_action_log_queryset,
    fetch_timeline_page,
    scoped_movement_action_log_queryset,
    scoped_shipment_action_log_queryset,
    shipment_action_log_scope_q,
)
from tenant_workspace.models import TenantOperationActionLog


class TimelineService:
    DEFAULT_LIMIT = 50
    MAX_LIMIT = 100

    @classmethod
    def clamp_limit(cls, raw_limit) -> int:
        try:
            value = int(raw_limit)
        except (TypeError, ValueError):
            value = cls.DEFAULT_LIMIT
        return max(1, min(value, cls.MAX_LIMIT))

    @staticmethod
    def _action_label(log_row, request=None) -> str:
        action = getattr(log_row, 'operation_action', None)
        if action is None:
            return ''
        label = action.english_label or action.action_code or ''
        if request is not None:
            try:
                from mobile_api.helpers.i18n import get_localized_value

                label = get_localized_value(
                    request,
                    action.english_label or action.action_code or '',
                    action.arabic_label or '',
                )
            except Exception:
                pass
        return label

    @classmethod
    def build_execution_timeline(
        cls,
        *,
        shipment=None,
        movement=None,
        driver_id=None,
        limit: int | None = None,
        request=None,
    ) -> list[dict[str, Any]]:
        """
        Chronological action log rows (newest first), scoped to shipment and/or movement.
        """
        cap = cls.clamp_limit(limit)
        qs = TenantOperationActionLog.objects.select_related(
            'operation_action',
            'shipment',
            'truck_movement',
        ).order_by('-log_date', '-created_at')

        if driver_id:
            qs = qs.filter(driver_id=driver_id)

        if shipment is not None:
            qs = qs.filter(
                shipment_action_log_scope_q(
                    shipment.pk,
                    booking_id=getattr(shipment, 'booking_id', None),
                ),
            )
        elif movement is not None:
            qs = qs.filter(truck_movement_id=movement.pk)

        rows = []
        for log in qs[:cap]:
            action = getattr(log, 'operation_action', None)
            impact = ''
            if action is not None:
                impact = (action.shipment_status_impact or action.movement_status_impact or '').strip()
            rows.append(
                {
                    'log_id': str(log.log_id),
                    'log_no': log.log_no,
                    'log_date': log.log_date.isoformat() if log.log_date else None,
                    'action_code': action.action_code if action else None,
                    'action_label': cls._action_label(log, request),
                    'source': log.source or '',
                    'source_channel': log.source_channel or '',
                    'notes': log.notes or '',
                    'shipment_id': str(log.shipment_id) if log.shipment_id else None,
                    'movement_id': str(log.truck_movement_id) if log.truck_movement_id else None,
                    'status_impact': impact or None,
                    'latitude': log.latitude or '',
                    'longitude': log.longitude or '',
                    'is_reversal': operation_action_matches(
                        action,
                        'reversal',
                        'reject pod',
                        'reject',
                        'r1',
                        'r2',
                        'r3',
                        'r4',
                        'cancel shipment',
                        'undo',
                    )
                    if action
                    else False,
                }
            )
        return rows

    @staticmethod
    def build_movement_timeline(*, movement, driver_id=None, limit: int | None = None, request=None):
        return TimelineService.build_execution_timeline(
            movement=movement,
            driver_id=driver_id,
            limit=limit,
            request=request,
        )

    @classmethod
    def scoped_action_log_queryset(
        cls,
        *,
        shipment=None,
        movement=None,
        driver_id=None,
        cursor=None,
    ):
        """
        Driver-scoped action logs for mobile timeline (newest first).

        Shipment scope: UNION of direct shipment logs and movement-linked logs
        (no ``truck_movement__shipment_id`` join). Movement scope: single FK filter.
        """
        if shipment is not None:
            return scoped_shipment_action_log_queryset(
                shipment=shipment,
                driver_id=driver_id,
                cursor=cursor,
                select_related=True,
            )
        if movement is not None:
            return scoped_movement_action_log_queryset(
                movement=movement,
                driver_id=driver_id,
                cursor=cursor,
                select_related=True,
            )
        return base_action_log_queryset(driver_id=driver_id).none().order_by(*TIMELINE_ORDER)

    @classmethod
    def fetch_scoped_timeline_page(
        cls,
        *,
        shipment=None,
        movement=None,
        driver_id=None,
        cursor=None,
        limit: int,
    ) -> list:
        """
        Bounded timeline slice with UNION hydration for shipment scope.
        """
        qs = cls.scoped_action_log_queryset(
            shipment=shipment,
            movement=movement,
            driver_id=driver_id,
            cursor=cursor,
        )
        return fetch_timeline_page(
            qs,
            limit=limit,
            hydrate_union=shipment is not None,
        )
