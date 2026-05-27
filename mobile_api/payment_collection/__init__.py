"""Payment Collection (mobile) — treasury evidence staging (prep-only).

This module prepares evidence for Execute Action (A9). It must NOT:
- mutate shipment workflow state
- post treasury transactions
- directly close jobs
"""

