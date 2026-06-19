"""Empty move mobile API URLs."""
from django.urls import path

from mobile_api.empty_move.views.empty_move_create_view import EmptyMoveCreateAPIView
from mobile_api.empty_move.views.empty_move_locations_view import (
    EmptyMoveLocationsAPIView,
)

urlpatterns = [
    path(
        'driver/empty-moves/locations/',
        EmptyMoveLocationsAPIView.as_view(),
        name='driver_empty_move_locations',
    ),
    path(
        'driver/empty-moves/',
        EmptyMoveCreateAPIView.as_view(),
        name='driver_empty_move_create',
    ),
]
