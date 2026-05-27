"""
mobile_api/payment_collection/urls.py
"""
from django.urls import path

from mobile_api.payment_collection.views.payment_collection_view import (
    PaymentCollectionAPIView,
)

urlpatterns = [
    path(
        'driver/payments/collect/',
        PaymentCollectionAPIView.as_view(),
        name='driver_payment_collect',
    ),
]

