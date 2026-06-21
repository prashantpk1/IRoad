"""Request validation for driver empty move creation."""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from iroad_tenants.operation_runtime.movement_ops import VALID_EMPTY_MOVE_REASONS


def _coord_pair(lat: float | None, lng: float | None) -> tuple[float, float] | None:
    if lat is None or lng is None:
        return None
    return lat, lng


class EmptyMoveCreateRequestSerializer(serializers.Serializer):
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

    def validate(self, attrs):
        attrs['from_address'] = str(attrs.get('from_address') or '').strip()
        attrs['to_address'] = str(attrs.get('to_address') or '').strip()

        if not self._endpoint_complete(
            location_id=attrs.get('from_location_id'),
            address=attrs['from_address'],
            latitude=attrs.get('from_latitude'),
            longitude=attrs.get('from_longitude'),
        ):
            raise serializers.ValidationError(
                {'from_address': _('mobile.empty_move.from_location_required')},
            )
        if not self._endpoint_complete(
            location_id=attrs.get('to_location_id'),
            address=attrs['to_address'],
            latitude=attrs.get('to_latitude'),
            longitude=attrs.get('to_longitude'),
        ):
            raise serializers.ValidationError(
                {'to_address': _('mobile.empty_move.to_location_required')},
            )

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
