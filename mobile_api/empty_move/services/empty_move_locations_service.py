"""Active serviceable locations for driver empty-move location picker."""
from __future__ import annotations

from typing import Any

from django.db.models import Q
from django_tenants.utils import schema_context

from mobile_api.job_detail.projections.job_location_projection import (
    serialize_location_point,
)
from tenant_workspace.models import TenantLocationMaster


class EmptyMoveLocationsService:
    """List tenant Location Master rows for empty move from/to pickers."""

    def list_locations(
        self,
        *,
        tenant_schema: str,
        request: Any | None = None,
        search: str = '',
        limit: int = 100,
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        if not schema:
            return {'locations': []}

        term = (search or '').strip()
        cap = max(1, min(int(limit or 100), 200))

        with schema_context(schema):
            qs = TenantLocationMaster.active_serviceable_objects.select_related(
                'country',
            ).order_by('display_label', 'location_code')
            if term:
                qs = qs.filter(
                    Q(display_label__icontains=term)
                    | Q(location_name_english__icontains=term)
                    | Q(location_name_arabic__icontains=term)
                    | Q(location_code__icontains=term)
                    | Q(province__icontains=term)
                )
            rows = list(qs[:cap])

        locations = [
            serialize_location_point(row, request=request)
            for row in rows
        ]
        return {'locations': locations}
