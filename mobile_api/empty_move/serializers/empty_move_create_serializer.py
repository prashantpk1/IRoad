"""Request validation for driver empty move creation."""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from iroad_tenants.operation_runtime.movement_ops import VALID_EMPTY_MOVE_REASONS


class EmptyMoveCreateRequestSerializer(serializers.Serializer):
    empty_move_reason = serializers.ChoiceField(
        choices=sorted(VALID_EMPTY_MOVE_REASONS),
    )
    from_location_id = serializers.UUIDField(
        error_messages={
            'invalid': _('mobile.empty_move.from_location_id_invalid'),
        },
    )
    to_location_id = serializers.UUIDField(
        error_messages={
            'invalid': _('mobile.empty_move.to_location_id_invalid'),
        },
    )
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

    def validate(self, attrs):
        from_id = attrs.get('from_location_id')
        to_id = attrs.get('to_location_id')
        if from_id and to_id and from_id == to_id:
            raise serializers.ValidationError(
                {'to_location_id': _('mobile.empty_move.same_location')}
            )
        return attrs
