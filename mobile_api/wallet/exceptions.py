"""
mobile_api/wallet/exceptions.py
"""
from __future__ import annotations


class WalletError(Exception):
    """Domain error for Wallet APIs."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'wallet_error',
        http_status: int = 400,
        message_key: str = 'mobile.wallet.error',
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message_key = message_key
