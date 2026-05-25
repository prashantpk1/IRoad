"""
mobile_api/helpers/job_list_search.py

Index-friendly search for driver job lists (prefix / exact match, minimal OR).
"""
from __future__ import annotations

import re

from django.db.models import Exists, OuterRef, Q

MIN_SEARCH_LENGTH = 2

# Optional booking lookup when term does not look like a shipment/movement code.
_BOOKING_PREFIX_RE = re.compile(r'^(bk|book|bkg)[-\s]?', re.I)
_SHIPMENT_PREFIX_RE = re.compile(r'^sh[-\s]?', re.I)
_MOVEMENT_PREFIX_RE = re.compile(r'^mv[-\s]?', re.I)


def normalize_search_term(term: str | None) -> str:
    return (term or '').strip()


def is_searchable(term: str) -> bool:
    return len(normalize_search_term(term)) >= MIN_SEARCH_LENGTH


def _exact_code_q(field: str, term: str) -> Q:
    """Prefer equality on unique ``shipment_no`` / ``movement_no`` when unambiguous."""
    if len(term) >= 6 and ' ' not in term:
        return Q(**{f'{field}__iexact': term})
    return Q(**{f'{field}__istartswith': term})


def shipment_job_search_q(term: str, *, include_booking: bool = True) -> Q:
    """
    Shipment list search — primary ``shipment_no`` (indexed, prefix/exact).

    Booking number lookup is optional and only when the term suggests a booking ref.
    """
    normalized = normalize_search_term(term)
    if not is_searchable(normalized):
        return Q()

    clauses: list[Q] = [_exact_code_q('shipment_no', normalized)]
    if include_booking and _BOOKING_PREFIX_RE.match(normalized):
        booking_term = _BOOKING_PREFIX_RE.sub('', normalized).strip() or normalized
        clauses.append(Q(booking__booking_no__istartswith=booking_term))
    return clauses[0] if len(clauses) == 1 else clauses[0] | clauses[1]


def movement_job_search_q(term: str, *, driver) -> Q:
    """
    Movement list search — ``movement_no`` prefix/exact, linked shipment via EXISTS.

    Avoids capped IN subqueries and join OR chains on the movement table.
    """
    normalized = normalize_search_term(term)
    if not is_searchable(normalized):
        return Q()

    movement_q = _exact_code_q('movement_no', normalized)

    if _MOVEMENT_PREFIX_RE.match(normalized) and not _SHIPMENT_PREFIX_RE.match(normalized):
        return movement_q

    from mobile_api.helpers.job_list_driver_scope import filter_shipments_for_driver

    shipment_match = filter_shipments_for_driver(driver).filter(
        _exact_code_q('shipment_no', normalized),
    )
    return movement_q | Q(
        Exists(shipment_match.filter(pk=OuterRef('shipment_id'))),
    )
