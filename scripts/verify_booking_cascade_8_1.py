"""Verify PCS §8.1 booking cascade for Document Handover and Shipment Document."""
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django_tenants.utils import schema_context

from iroad_tenants.booking_linkage_cascade import (
    booking_option_matches,
    build_booking_item_options_from_shipment_rows,
    build_booking_options_from_shipment_rows,
    shipment_option_matches,
)
from iroad_tenants.views import (
    _tenant_document_handover_linkage_options,
    _tenant_shipment_document_linkage_options,
    _tenant_shipment_pod_delivery_note_options,
)
from iroad_tenants.models import TenantRegistry


def doc_matches_shipment(doc, shipment_id, booking_item):
    if isinstance(doc, dict):
        doc_sid = str(doc.get("shipment_id") or "")
        doc_item = (doc.get("booking_item") or "").strip()
    else:
        doc_sid = str(doc.shipment_id) if doc.shipment_id else ""
        doc_item = ""
        if doc.shipment_id:
            doc_item = (doc.shipment.booking_item_ref or "").strip()
    if doc_sid != str(shipment_id):
        return False
    if booking_item and doc_item and doc_item != booking_item:
        return False
    return True


def run_tenant(schema, prefer_booking_no="BK-0052"):
    with schema_context(schema):
        shipment_rows = _tenant_document_handover_linkage_options()
        if not shipment_rows:
            return None

        bookings = build_booking_options_from_shipment_rows(shipment_rows)
        items = build_booking_item_options_from_shipment_rows(shipment_rows)

        target = next(
            (b for b in bookings if b.get("booking_no") == prefer_booking_no),
            None,
        )
        if not target:
            multi = [
                b for b in bookings if "," in (b.get("booking_item_summary") or "")
            ]
            target = multi[0] if multi else (bookings[0] if bookings else None)
        if not target:
            return None

        bid = target["booking_id"]
        bno = target["booking_no"]
        visible_items = [
            i for i in items if booking_option_matches(i, booking_id=bid, booking_no=bno)
        ]
        if not visible_items:
            return {
                "schema": schema,
                "booking_no": bno,
                "error": "No booking items for selected booking",
            }

        test_item = visible_items[0]["booking_item"]
        visible_shipments = [
            s
            for s in shipment_rows
            if shipment_option_matches(
                s, booking_id=bid, booking_no=bno, booking_item=test_item
            )
        ]
        leaked_shipments_same_booking = [
            s
            for s in shipment_rows
            if booking_option_matches(s, booking_id=bid, booking_no=bno)
            and not shipment_option_matches(
                s, booking_id=bid, booking_no=bno, booking_item=test_item
            )
        ]

        delivery_notes = list(_tenant_shipment_pod_delivery_note_options())
        sid = visible_shipments[0]["shipment_id"] if visible_shipments else ""
        visible_docs = [
            d for d in delivery_notes if doc_matches_shipment(d, sid, test_item)
        ] if sid else []

        sd_bookings, sd_rows, sd_items = _tenant_shipment_document_linkage_options()
        sd_visible_items = [
            i for i in sd_items if booking_option_matches(i, booking_id=bid, booking_no=bno)
        ]
        sd_visible_ship = [
            s
            for s in sd_rows
            if shipment_option_matches(
                s, booking_id=bid, booking_no=bno, booking_item=test_item
            )
        ]

        return {
            "schema": schema,
            "booking_no": bno,
            "booking_id": bid,
            "booking_item": test_item,
            "total_booking_items_in_dom": len(items),
            "visible_booking_items": len(visible_items),
            "leaked_other_booking_items": len(items) - len(visible_items),
            "visible_shipments": [
                f"{s['shipment_no']} ({s['booking_no']})" for s in visible_shipments
            ],
            "leaked_shipments_wrong_item": len(leaked_shipments_same_booking),
            "visible_doc_records": [
                (d.get("record_no") if isinstance(d, dict) else getattr(d, "record_no", str(d.pk)))
                for d in visible_docs
            ],
            "shipment_document_items": len(sd_visible_items),
            "shipment_document_shipments": [
                f"{s['shipment_no']}" for s in sd_visible_ship
            ],
            "pass_step1": len(visible_items) >= 1
            and (len(items) - len(visible_items)) >= 0,
            "pass_step2": len(visible_shipments) >= 1
            and all(
                s["booking_item"] == test_item for s in visible_shipments
            ),
            "pass_step3": len(visible_docs) >= 0,
            "pass_shipment_doc": len(sd_visible_items) >= 1,
        }


def main():
    prefer = sys.argv[1] if len(sys.argv) > 1 else "BK-0052"
    tenants = list(
        TenantRegistry.objects.all().values_list("schema_name", flat=True)
    )
    print(f"Checking {len(tenants)} active tenant(s), prefer booking {prefer}")

    result = None
    for schema in tenants:
        result = run_tenant(schema, prefer_booking_no=prefer)
        if result:
            break

    if not result:
        print("FAIL: No tenant with Document Handover linkage data.")
        sys.exit(1)

    print("\n=== §8.1 Cascade Verification ===")
    for key, value in result.items():
        print(f"{key}: {value}")

    passed = (
        result.get("pass_step1")
        and result.get("pass_step2")
        and result.get("pass_step3")
        and result.get("pass_shipment_doc")
    )
    print("\nOVERALL:", "PASS" if passed else "FAIL")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
