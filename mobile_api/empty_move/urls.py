"""Empty move mobile API URLs."""
from django.urls import path

from mobile_api.empty_move.views.empty_move_create_view import EmptyMoveCreateAPIView

urlpatterns = [
    path(
        'driver/empty-moves/',
        EmptyMoveCreateAPIView.as_view(),
        name='driver_empty_move_create',
    ),
]
