"""Append-only debug log for FCM token store + push send checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings


def append_push_debug(message: str) -> None:
    """
    Append one timestamped line to project root ``time.txt``.

    Used by login token upsert and push dispatch so you can open time.txt
    without running a separate debug script.
    """
    try:
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc + timedelta(hours=5, minutes=30)
        line = (
            f"[{now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC | "
            f"{now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST] {message}\n"
        )
        out = Path(settings.BASE_DIR) / 'time.txt'
        with open(out, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        # Never break login/push because of debug logging.
        pass
