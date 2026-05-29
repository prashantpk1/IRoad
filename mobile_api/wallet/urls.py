"""
mobile_api/wallet/urls.py

Driver My Wallet routes (included from ``mobile_api.urls``).
"""
from django.urls import path

from mobile_api.wallet.views.wallet_detail_view import WalletTransactionDetailAPIView
from mobile_api.wallet.views.wallet_list_view import WalletListAPIView

urlpatterns = [
    path(
        'driver/wallet/',
        WalletListAPIView.as_view(),
        name='driver_wallet_list',
    ),
    path(
        'driver/wallet/transactions/<str:transaction_id>/',
        WalletTransactionDetailAPIView.as_view(),
        name='driver_wallet_transaction_detail',
    ),
]
