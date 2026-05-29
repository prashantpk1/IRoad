"""
mobile_api/wallet/constants.py

Tunable limits for driver Wallet APIs.
"""
from __future__ import annotations

from django.conf import settings


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


WALLET_LIST_MAX_RESULTS = _int_setting('MOBILE_WALLET_LIST_MAX_RESULTS', 200)
WALLET_DEFAULT_CURRENCY = getattr(settings, 'MOBILE_WALLET_DEFAULT_CURRENCY', 'SAR')
