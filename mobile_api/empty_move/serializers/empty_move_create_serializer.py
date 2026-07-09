"""Request validation for driver empty-move creation."""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from iroad_tenants.operation_runtime.movement_ops import VALID_EMPTY_MOVE_REASONS


def _coord_pair(latitude, longitude) -> tuple[float, float] | None:
    if latitude is None or longitude is None:
        return None
    try:
        return float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None


class EmptyMoveCreateRequestSerializer(serializers.Serializer):
    """
    PCS §5.1 — GPS-only empty move create.

    Driver selects a reason and presses Start with current GPS. Manual from/to
    pickers are optional legacy fields only.
    """

    empty_move_reason = serializers.ChoiceField(
        choices=sorted(VALID_EMPTY_MOVE_REASONS),
    )
    from_location_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        error_messages={
            'invalid': _('mobile.empty_move.from_location_id_invalid'),
        },
    )
    to_location_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        error_messages={
            'invalid': _('mobile.empty_move.to_location_id_invalid'),
        },
    )
    from_address = serializers.CharField(required=False, allow_blank=True, max_length=500)
    to_address = serializers.CharField(required=False, allow_blank=True, max_length=500)
    truck_id = serializers.UUIDField(required=False, allow_null=True)
    movement_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='', max_length=5000)
    client_action_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    from_latitude = serializers.FloatField(required=False, allow_null=True)
    from_longitude = serializers.FloatField(required=False, allow_null=True)
    to_latitude = serializers.FloatField(required=False, allow_null=True)
    to_longitude = serializers.FloatField(required=False, allow_null=True)

    @staticmethod
    def _endpoint_complete(
        *,
        location_id,
        address: str,
        latitude: float | None,
        longitude: float | None,
    ) -> bool:
        if location_id is not None:
            return True
        return bool(address) and latitude is not None and longitude is not None

    @staticmethod
    def _start_gps_complete(attrs: dict) -> bool:
        if _coord_pair(attrs.get('from_latitude'), attrs.get('from_longitude')):
            return True
        return _coord_pair(attrs.get('latitude'), attrs.get('longitude')) is not None

    def validate(self, attrs):
        attrs['from_address'] = str(attrs.get('from_address') or '').strip()
        attrs['to_address'] = str(attrs.get('to_address') or '').strip()

        legacy_from = self._endpoint_complete(
            location_id=attrs.get('from_location_id'),
            address=attrs['from_address'],
            latitude=attrs.get('from_latitude'),
            longitude=attrs.get('from_longitude'),
        )
        legacy_to = self._endpoint_complete(
            location_id=attrs.get('to_location_id'),
            address=attrs['to_address'],
            latitude=attrs.get('to_latitude'),
            longitude=attrs.get('to_longitude'),
        )
        legacy_manual_route = legacy_from and legacy_to

        if not legacy_manual_route:
            if not self._start_gps_complete(attrs):
                raise serializers.ValidationError(
                    {
                        'latitude': _(
                            'mobile.empty_move.start_gps_required',
                        ),
                    },
                )
            if attrs.get('from_latitude') is None and attrs.get('latitude') is not None:
                attrs['from_latitude'] = attrs.get('latitude')
                attrs['from_longitude'] = attrs.get('longitude')
            return attrs

        from_id = attrs.get('from_location_id')
        to_id = attrs.get('to_location_id')
        if from_id and to_id and from_id == to_id:
            raise serializers.ValidationError(
                {'to_location_id': _('mobile.empty_move.same_location')},
            )

        from_coords = _coord_pair(attrs.get('from_latitude'), attrs.get('from_longitude'))
        to_coords = _coord_pair(attrs.get('to_latitude'), attrs.get('to_longitude'))
        if from_coords and to_coords and from_coords == to_coords:
            raise serializers.ValidationError(
                {'to_address': _('mobile.empty_move.same_location')},
            )

        return attrs
