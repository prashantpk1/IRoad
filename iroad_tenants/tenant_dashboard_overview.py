"""
Server-side metrics for the tenant portal dashboard (Overview, Operations Hub, Fleet Hub).

Uses ``TenantProfile`` / ``SubscriptionPlan`` (public schema) and workspace ORM
counts inside each tenant's ``schema_name`` via ``schema_context``.
"""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context

from iroad_tenants.models import TenantRegistry
from superadmin.models import PlanPricingCycle, TenantProfile
from tenant_workspace.models import (
    DriverAttachment,
    DriverMaster,
    TenantBooking,
    TenantShipment,
    TenantTruckMovementLog,
    TenantUser,
    TruckAttachment,
    TruckMaster,
)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    ny, rem = divmod(idx, 12)
    return ny, rem + 1


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _nice_y_axis_max(*values: int) -> int:
    """Scale axis to data so small fleets (e.g. 1 truck) are visible, not pinned to 40."""
    top = max(values) if values else 0
    if top <= 0:
        return 1
    if top <= 12:
        return top
    step = max(10, int(math.ceil(top / 4 / 10.0)) * 10)
    return max(step, int(math.ceil(top / float(step))) * step)


def _chart_y_ticks(y_max: int) -> list[int]:
    if y_max <= 1:
        return [1, 0]
    if y_max <= 10:
        ticks: list[int] = []
        for share in (1.0, 0.75, 0.5, 0.25, 0.0):
            tick = int(round(y_max * share))
            if not ticks or ticks[-1] != tick:
                ticks.append(tick)
        return ticks
    return [y_max, int(y_max * 0.75), int(y_max * 0.5), int(y_max * 0.25), 0]


CHART_PLOT_HEIGHT_PX = 140


def _bar_height_pct(value: int, y_max: int) -> int:
    if y_max <= 0 or value <= 0:
        return 0
    return min(100, int(round(100.0 * float(value) / float(y_max))))


def _bar_height_px(value: int, y_max: int) -> int:
    if y_max <= 0 or value <= 0:
        return 0
    px = int(round(CHART_PLOT_HEIGHT_PX * float(value) / float(y_max)))
    return max(6, px) if value > 0 else 0


def _pct_used(used: int, cap: int) -> int:
    if cap <= 0:
        return 0
    return int(min(100, round(100.0 * float(used) / float(cap))))


def _fmt_int(n: int) -> str:
    return f"{int(n):,}"


def _money_str(amount: Decimal, currency_code: str, symbol: str) -> str:
    code = (currency_code or "").strip() or "—"
    sym = (symbol or "").strip()
    body = f"{amount.quantize(Decimal('0.01')):,.2f}"
    if sym:
        return f"{sym} {body}".strip()
    return f"{code} {body}".strip()


def _build_conic_gradient(weights: list[tuple[str, float]]) -> str:
    total = sum(w for _, w in weights if w > 0)
    if total <= 0:
        return "conic-gradient(#e2e8f0 0 100%)"
    parts: list[str] = []
    cursor = 0.0
    for color, w in weights:
        if w <= 0:
            continue
        share = (w / total) * 100.0
        nxt = cursor + share
        parts.append(f"{color} {cursor:.4f}% {nxt:.4f}%")
        cursor = nxt
    return f"conic-gradient({', '.join(parts)})"


def _allocate_percentages(counts: list[int], total: int) -> list[int]:
    """Integer percentages that always sum to 100 when total > 0."""
    if total <= 0 or not counts:
        return [0 for _ in counts]
    raw = [100.0 * c / total for c in counts]
    floors = [int(r) for r in raw]
    remainder = 100 - sum(floors)
    if remainder > 0:
        order = sorted(
            range(len(counts)),
            key=lambda i: (raw[i] - floors[i]),
            reverse=True,
        )
        for idx in order[:remainder]:
            floors[idx] += 1
    return floors


def _effective_cap(tenant_val: int, plan_val: int | None) -> int:
    tv = int(tenant_val or 0)
    if tv > 0:
        return tv
    if plan_val is None:
        return 0
    return int(plan_val)


def _is_unlimited_cap(cap: int) -> bool:
    return cap < 0


def _time_ago_label(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    now = timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} MIN{'S' if minutes != 1 else ''} AGO"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} H AGO"
    days = hours // 24
    return f"{days} D AGO"


def _shipment_active_statuses() -> set[str]:
    return {
        TenantShipment.ShipmentStatus.LOADED,
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }


def _fleet_trip_statuses() -> set[str]:
    """In-progress trips for fleet donut / hub loaded state (excludes Delivered/Closed)."""
    return {
        TenantShipment.ShipmentStatus.LOADED,
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
    }


def _truck_status_badge(op_status: str) -> tuple[str, str]:
    key = (op_status or "").strip().lower()
    if key == "loaded":
        return "expired", "Loaded"
    if key == "suspended":
        return "inactive", "Suspended"
    return "success", "Available"


def _truck_ops_hint(op_status: str) -> str:
    key = (op_status or "").strip().lower()
    if key == "loaded":
        return "On active trip"
    if key == "suspended":
        return "Compliance hold"
    if key:
        return "Ready for dispatch"
    return "In service"


def _driver_loaded_driver_ids() -> set:
    return set(
        TenantShipment.objects.filter(
            shipment_status__in=_fleet_trip_statuses(),
            driver_id__isnull=False,
        ).values_list("driver_id", flat=True)
    )


def _truck_ids_on_active_shipments() -> set:
    """Trucks tied to in-progress shipments (same trip scope as loaded drivers)."""
    return set(
        TenantShipment.objects.filter(
            shipment_status__in=_fleet_trip_statuses(),
            truck_id__isnull=False,
        ).values_list("truck_id", flat=True)
    )


def _effective_truck_operational_status(truck, active_trip_truck_ids: set) -> str:
    """Dashboard fleet status: honor DB field plus active shipment assignment."""
    op = (truck.operational_status or "").strip()
    if op == TruckMaster.OperationalStatus.SUSPENDED:
        return TruckMaster.OperationalStatus.SUSPENDED
    if op == TruckMaster.OperationalStatus.LOADED or truck.truck_id in active_trip_truck_ids:
        return TruckMaster.OperationalStatus.LOADED
    return TruckMaster.OperationalStatus.AVAILABLE


def _fleet_truck_status_counts(truck_qs, active_trip_truck_ids: set) -> tuple[int, int, int]:
    """Mutually exclusive Available / Loaded / Suspended counts for fleet donut."""
    suspended = 0
    loaded = 0
    available = 0
    for truck in truck_qs.only("truck_id", "operational_status"):
        status = _effective_truck_operational_status(truck, active_trip_truck_ids)
        if status == TruckMaster.OperationalStatus.SUSPENDED:
            suspended += 1
        elif status == TruckMaster.OperationalStatus.LOADED:
            loaded += 1
        else:
            available += 1
    return available, loaded, suspended


@dataclass
class _WorkspaceSnapshot:
    internal_users: int
    internal_trucks: int
    active_insource_drivers: int
    monthly_shipments: int
    storage_gb_used: int


def _workspace_counts(schema_name: str) -> _WorkspaceSnapshot:
    with schema_context(schema_name):
        users = TenantUser.objects.count()
        trucks = TruckMaster.active_objects.filter(
            sourcing_mode=TruckMaster.SourcingMode.IN_SOURCE,
        ).count()
        drivers = DriverMaster.active_objects.filter(
            driver_source=DriverMaster.DriverSource.IN_SOURCE,
        ).count()
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        shipments = TenantShipment.objects.filter(created_at__gte=month_start).count()
        return _WorkspaceSnapshot(
            internal_users=users,
            internal_trucks=trucks,
            active_insource_drivers=drivers,
            monthly_shipments=shipments,
            storage_gb_used=0,
        )


def _fleet_chart_months(schema_name: str) -> tuple[list[dict[str, Any]], list[int]]:
    today = timezone.localdate()
    chart_months: list[dict[str, Any]] = []
    series_trucks: list[int] = []
    series_drivers: list[int] = []

    for back in (3, 2, 1, 0):
        y, m = _shift_month(today.year, today.month, -back)
        end_d = _month_end(y, m)
        next_d = end_d + timedelta(days=1)
        end_ts_exclusive = timezone.make_aware(
            datetime.combine(next_d, time.min),
            timezone.get_current_timezone(),
        )
        with schema_context(schema_name):
            t_count = TruckMaster.active_objects.filter(
                sourcing_mode=TruckMaster.SourcingMode.IN_SOURCE,
                created_at__lt=end_ts_exclusive,
            ).count()
            d_count = DriverMaster.active_objects.filter(
                driver_source=DriverMaster.DriverSource.IN_SOURCE,
                created_at__lt=end_ts_exclusive,
            ).count()
        label = date(y, m, 1).strftime("%b")
        chart_months.append(
            {
                "label": label,
                "truck_count": t_count,
                "driver_count": d_count,
            }
        )
        series_trucks.append(t_count)
        series_drivers.append(d_count)

    y_max = _nice_y_axis_max(*(series_trucks + series_drivers))
    y_ticks = _chart_y_ticks(y_max)
    for row in chart_months:
        tc = int(row["truck_count"])
        dc = int(row["driver_count"])
        label = row["label"]
        row["truck_pct"] = _bar_height_pct(tc, y_max)
        row["driver_pct"] = _bar_height_pct(dc, y_max)
        row["truck_height_px"] = _bar_height_px(tc, y_max)
        row["driver_height_px"] = _bar_height_px(dc, y_max)
        row["truck_tip"] = f"Total Trucks: {_fmt_int(tc)} · {label}"
        row["driver_tip"] = f"Active Drivers: {_fmt_int(dc)} · {label}"
    return chart_months, y_ticks


def _attachment_compliance_counts(today: date, threshold: date) -> dict[str, int]:
    truck_expired = truck_near = driver_expired = driver_near = 0

    for att in TruckAttachment.objects.filter(is_deleted=False).only(
        "is_expiry_applicable",
        "expiry_date",
    ):
        if not att.is_expiry_applicable or not att.expiry_date:
            continue
        if att.expiry_date < today:
            truck_expired += 1
        elif att.expiry_date <= threshold:
            truck_near += 1

    for att in DriverAttachment.objects.all().only(
        "is_expiry_applicable",
        "expiry_date",
    ):
        if not att.is_expiry_applicable or not att.expiry_date:
            continue
        if att.expiry_date < today:
            driver_expired += 1
        elif att.expiry_date <= threshold:
            driver_near += 1

    return {
        "truck_expired": truck_expired,
        "truck_near_expiry": truck_near,
        "driver_expired": driver_expired,
        "driver_near_expiry": driver_near,
    }


def _build_ops_hub_data() -> dict[str, Any]:
    from iroad_tenants.views import _tenant_booking_stats

    booking_stats = _tenant_booking_stats()
    stats_qs = TenantShipment.objects.all()
    active_statuses = _shipment_active_statuses()

    shipment_stats = {
        "active": stats_qs.filter(shipment_status__in=active_statuses).count(),
        "executed": stats_qs.filter(
            shipment_status__in={
                TenantShipment.ShipmentStatus.DELIVERED,
                TenantShipment.ShipmentStatus.CLOSED,
            }
        ).count(),
        "cancelled": stats_qs.filter(
            shipment_status=TenantShipment.ShipmentStatus.CANCELLED,
        ).count(),
        "pod_complete": stats_qs.filter(
            pod_status=TenantShipment.PodStatus.COMPLETED,
        ).count(),
        "pod_incomplete": stats_qs.exclude(
            pod_status=TenantShipment.PodStatus.COMPLETED,
        ).count(),
    }

    live_shipments = list(
        TenantShipment.objects.select_related(
            "booking",
            "truck",
            "driver",
        )
        .filter(shipment_status__in=active_statuses)
        .order_by("-updated_at")[:8]
    )
    live_trip_rows = []
    for sh in live_shipments:
        route = (sh.route_display or sh.booking.route_display if sh.booking else "") or "—"
        truck_label = sh.truck.plate_number if sh.truck else "—"
        driver_label = (
            sh.driver.english_name or sh.driver.arabic_name if sh.driver else "—"
        )
        live_trip_rows.append(
            {
                "booking_no": sh.booking.booking_no if sh.booking else "—",
                "shipment_no": sh.shipment_no,
                "time_ago": _time_ago_label(sh.updated_at),
                "trip_type": (sh.trip_type or sh.booking.trip_type if sh.booking else "") or "—",
                "route": route,
                "truck": truck_label,
                "driver": driver_label,
                "status": (sh.shipment_status or "").upper(),
            }
        )

    recent_bookings = list(
        TenantBooking.objects.select_related("client_account")
        .exclude(booking_status=TenantBooking.Status.CANCELLED)
        .order_by("-created_at")[:6]
    )
    recent_booking_rows = [
        {
            "client_name": (
                b.client_account.display_name if b.client_account else "—"
            ),
            "booking_no": b.booking_no,
            "time_ago": _time_ago_label(b.created_at),
            "detail_url": reverse(
                "iroad_tenants:tenant_operation_booking_detail",
                kwargs={"booking_id": b.booking_id},
            ),
        }
        for b in recent_bookings
    ]

    recent_shipments = list(
        TenantShipment.objects.select_related("booking")
        .order_by("-created_at")[:6]
    )
    recent_shipment_rows = [
        {
            "route": (s.route_display or (s.booking.route_display if s.booking else "")) or "—",
            "shipment_no": s.shipment_no,
            "time_ago": _time_ago_label(s.created_at),
            "status": (s.shipment_status or "").upper(),
            "detail_url": reverse(
                "iroad_tenants:tenant_operation_shipment_detail",
                kwargs={"shipment_id": s.shipment_id},
            ),
        }
        for s in recent_shipments
    ]

    live_movements = list(
        TenantTruckMovementLog.objects.select_related("truck", "driver")
        .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
        .order_by("-updated_at")[:8]
    )
    movement_rows = [
        {
            "movement_no": m.movement_no,
            "time_ago": _time_ago_label(m.updated_at),
            "movement_source": (m.movement_source or "—").upper(),
            "truck": m.truck.plate_number if m.truck else "—",
            "driver": (
                m.driver.english_name or m.driver.arabic_name if m.driver else "—"
            ),
            "status": (m.status or "").upper(),
        }
        for m in live_movements
    ]

    pending_pod_shipments = list(
        TenantShipment.objects.select_related("client_account")
        .filter(
            shipment_status__in={
                TenantShipment.ShipmentStatus.DELIVERED,
                TenantShipment.ShipmentStatus.POD_SUBMITTED,
                TenantShipment.ShipmentStatus.AT_DELIVERY,
            },
        )
        .exclude(pod_status=TenantShipment.PodStatus.COMPLETED)
        .order_by("-updated_at")[:6]
    )
    pending_pod_rows = [
        {
            "client_site": (
                f"{s.client_account.display_name if s.client_account else '—'}"
            ),
            "shipment_no": s.shipment_no,
            "time_ago": _time_ago_label(s.updated_at),
            "detail_url": reverse(
                "iroad_tenants:tenant_operation_shipment_pod_create",
            ),
        }
        for s in pending_pod_shipments
    ]

    return {
        "bookings": booking_stats,
        "shipments": shipment_stats,
        "live_trips": live_trip_rows,
        "live_movements": movement_rows,
        "recent_bookings": recent_booking_rows,
        "recent_shipments": recent_shipment_rows,
        "pending_pod": pending_pod_rows,
        "actions": [
            {
                "label": "Create Booking",
                "url": reverse("iroad_tenants:tenant_operation_booking_create"),
                "icon": "bi-calendar-plus",
                "tone": "text-primary",
            },
            {
                "label": "Bookings",
                "url": reverse("iroad_tenants:tenant_operation_booking_list"),
                "icon": "bi-journal-check",
                "tone": "text-primary",
            },
            {
                "label": "Create Shipments",
                "url": reverse("iroad_tenants:tenant_operation_shipment_create"),
                "icon": "bi-box-seam",
                "tone": "text-primary",
            },
            {
                "label": "Shipments",
                "url": reverse("iroad_tenants:tenant_operation_shipment_list"),
                "icon": "bi-truck-front",
                "tone": "text-primary",
            },
            {
                "label": "Upload POD",
                "url": reverse("iroad_tenants:tenant_operation_shipment_pod_create"),
                "icon": "bi-cloud-arrow-up",
                "tone": "text-success",
            },
            {
                "label": "PODs",
                "url": reverse("iroad_tenants:tenant_operation_shipment_pod_list"),
                "icon": "bi-file-earmark-check",
                "tone": "text-success",
            },
            {
                "label": "Receive Hard POD",
                "url": reverse("iroad_tenants:tenant_operation_shipment_pod_list"),
                "icon": "bi-file-earmark-arrow-up",
                "tone": "text-teal",
            },
            {
                "label": "Create Movements",
                "url": reverse("iroad_tenants:tenant_operation_truck_movement_log_create"),
                "icon": "bi-truck",
                "tone": "text-purple",
            },
            {
                "label": "Movements",
                "url": reverse("iroad_tenants:tenant_operation_truck_movement_log_list"),
                "icon": "bi-arrow-repeat",
                "tone": "text-purple",
            },
            {
                "label": "Reports",
                "url": reverse("iroad_tenants:tenant_dashboard"),
                "icon": "bi-pie-chart",
                "tone": "text-teal",
            },
        ],
    }


def _build_fleet_hub_data(schema_name: str) -> dict[str, Any]:
    truck_qs = TruckMaster.active_objects.filter(
        sourcing_mode=TruckMaster.SourcingMode.IN_SOURCE,
    )
    driver_qs = DriverMaster.active_objects.filter(
        driver_source=DriverMaster.DriverSource.IN_SOURCE,
    )
    loaded_ids = _driver_loaded_driver_ids()

    total_trucks = truck_qs.count()
    active_trip_truck_ids = _truck_ids_on_active_shipments()
    if loaded_ids:
        for tid in truck_qs.filter(
            default_driver_id_id__in=loaded_ids,
        ).values_list("truck_id", flat=True):
            active_trip_truck_ids.add(tid)
    avail, loaded, suspended = _fleet_truck_status_counts(truck_qs, active_trip_truck_ids)
    total_drivers = driver_qs.count()
    drivers_loaded = sum(1 for d in driver_qs if d.driver_id in loaded_ids)
    drivers_suspended = DriverMaster.objects.filter(
        driver_source=DriverMaster.DriverSource.IN_SOURCE,
        driver_status=DriverMaster.Status.INACTIVE,
    ).count()
    drivers_available = max(0, total_drivers - drivers_loaded)

    today = timezone.localdate()
    threshold = today + timedelta(days=30)
    compliance = _attachment_compliance_counts(today, threshold)

    fleet_donut_segment_defs = [
        ("available", "Available (READY)", "#10b981", avail),
        ("loaded", "Loaded (IN TRIP)", "#f59e0b", loaded),
        ("suspended", "Suspended (OFF-RD)", "#ef4444", suspended),
    ]
    fleet_pct_values = _allocate_percentages(
        [avail, loaded, suspended],
        total_trucks,
    )
    fleet_donut_segments: list[dict[str, Any]] = []
    fleet_donut_weights: list[tuple[str, float]] = []
    for idx, (key, label, color, count) in enumerate(fleet_donut_segment_defs):
        pct_int = fleet_pct_values[idx] if total_trucks > 0 else 0
        weight = float(count) if count > 0 else 0.0
        fleet_donut_weights.append((color, weight))
        fleet_donut_segments.append(
            {
                "key": key,
                "label": label,
                "color": color,
                "used": int(count),
                "used_display": _fmt_int(count),
                "total_display": _fmt_int(total_trucks),
                "pct_label": f"{pct_int}%",
                "pct_int": pct_int,
                "weight": weight,
            }
        )
    fleet_donut_style = f"background: {_build_conic_gradient(fleet_donut_weights)};"

    chart_months, chart_y_ticks = _fleet_chart_months(schema_name)

    truck_rows = []
    for truck in truck_qs.order_by("-updated_at")[:25]:
        effective_status = _effective_truck_operational_status(truck, active_trip_truck_ids)
        badge_class, badge_label = _truck_status_badge(effective_status)
        truck_rows.append(
            {
                "truck_code": truck.truck_code,
                "plate_number": truck.plate_number or "—",
                "sourcing_label": truck.get_sourcing_mode_display(),
                "badge_class": badge_class,
                "badge_label": badge_label or "Available",
                "ops_hint": _truck_ops_hint(effective_status),
                "detail_url": reverse(
                    "iroad_tenants:truck_master_detail",
                    kwargs={"truck_id": truck.truck_id},
                ),
            }
        )

    driver_rows = []
    for driver in driver_qs.order_by("-updated_at")[:25]:
        is_loaded = driver.driver_id in loaded_ids
        badge_class = "expired" if is_loaded else "success"
        badge_label = "Loaded" if is_loaded else "Available"
        driver_rows.append(
            {
                "driver_code": driver.driver_code,
                "driver_id_label": driver.id_number or driver.driver_code,
                "english_name": driver.english_name or driver.arabic_name,
                "ops_hint": "On active trip" if is_loaded else "Ready for dispatch",
                "badge_class": badge_class,
                "badge_label": badge_label,
                "detail_url": reverse(
                    "iroad_tenants:driver_master_detail",
                    kwargs={"driver_id": driver.driver_id},
                ),
            }
        )

    return {
        "truck_metrics": {
            "total": total_trucks,
            "available": avail,
            "loaded": loaded,
            "suspended": suspended,
        },
        "driver_metrics": {
            "total": total_drivers,
            "available": drivers_available,
            "loaded": drivers_loaded,
            "suspended": drivers_suspended,
        },
        "compliance": compliance,
        "chart_months": chart_months,
        "chart_y_ticks": chart_y_ticks,
        "fleet_donut_style": fleet_donut_style,
        "fleet_donut_segments": fleet_donut_segments,
        "truck_rows": truck_rows,
        "driver_rows": driver_rows,
        "actions": [
            {
                "label": "ADD TRUCK",
                "url": reverse("iroad_tenants:truck_master_create"),
                "icon": "bi-truck",
                "tone": "text-primary",
            },
            {
                "label": "ADD TRUCK ATT",
                "url": reverse("iroad_tenants:truck_attachment_select_truck"),
                "icon": "bi-file-earmark-plus",
                "tone": "text-purple",
            },
            {
                "label": "TRUCKS",
                "url": reverse("iroad_tenants:truck_master"),
                "icon": "bi-list-ul",
                "tone": "text-primary",
            },
            {
                "label": "ADD DRIVER",
                "url": reverse("iroad_tenants:driver_master_create"),
                "icon": "bi-person-plus",
                "tone": "text-success",
            },
            {
                "label": "ADD DRIVER ATT",
                "url": reverse("iroad_tenants:driver_attachment_select_driver"),
                "icon": "bi-person-vcard",
                "tone": "text-teal",
            },
            {
                "label": "DRIVERS",
                "url": reverse("iroad_tenants:driver_master"),
                "icon": "bi-people",
                "tone": "text-success",
            },
        ],
    }


def build_tenant_dashboard_overview(tenant: TenantProfile) -> dict[str, Any]:
    """
    Return template-friendly dashboard context (overview + hub sections).
    """
    profile = (
        TenantProfile.objects.select_related("current_plan")
        .filter(pk=tenant.pk)
        .first()
    )
    if profile is None:
        profile = tenant

    plan = profile.current_plan
    registry = TenantRegistry.objects.filter(tenant_profile_id=profile.pk).first()
    schema_name = (registry.schema_name if registry else "") or ""

    ws = (
        _workspace_counts(schema_name)
        if schema_name
        else _WorkspaceSnapshot(0, 0, 0, 0, 0)
    )

    cap_users = _effective_cap(
        profile.active_max_users,
        getattr(plan, "max_internal_users", None) if plan else None,
    )
    cap_trucks = _effective_cap(
        profile.active_max_internal_trucks,
        getattr(plan, "max_internal_trucks", None) if plan else None,
    )
    cap_drivers = _effective_cap(
        profile.active_max_drivers,
        getattr(plan, "max_active_drivers", None) if plan else None,
    )
    cap_shipments = int(getattr(plan, "max_monthly_shipments", -1) or -1) if plan else -1
    cap_storage = int(getattr(plan, "max_storage_gb", -1) or -1) if plan else -1

    plan_name = (plan.plan_name_en if plan else "") or "No active plan"
    renewal = profile.subscription_expiry_date
    renewal_display = renewal.strftime("%d %b %Y") if renewal else "—"

    price_line = "—"
    cycle_label = "/ month"
    if plan:
        pricing = (
            PlanPricingCycle.objects.filter(plan=plan, number_of_cycles=1)
            .select_related("currency")
            .order_by("currency_id")
            .first()
        )
        if pricing:
            cur = pricing.currency
            price_line = _money_str(
                pricing.price,
                getattr(cur, "currency_code", "") or "",
                getattr(cur, "currency_symbol", "") or "",
            )
            if int(pricing.number_of_cycles or 1) != 1:
                cycle_label = f"/ {int(pricing.number_of_cycles)} cycles"

    driver_attr = (
        "Driver App: Active"
        if (plan and plan.has_driver_app)
        else "Driver App: Not included"
    )
    backup_level = plan.get_backup_restore_level_display() if plan else "Standard"
    backup_attr = f"Backup Restore Level: {backup_level}"

    def resource_row(
        label: str,
        used: int,
        cap: int,
        bar_class: str,
    ) -> dict[str, Any]:
        unlimited = _is_unlimited_cap(cap)
        if unlimited:
            total_display = "∞"
            pct_int = 0
            pct_label = "Unlimited"
            bar_w = min(12, max(2, used * 3)) if used else 2
        else:
            total_display = _fmt_int(cap) if cap > 0 else "0"
            pct_int = _pct_used(used, cap) if cap > 0 else 0
            pct_label = f"{pct_int}%"
            bar_w = pct_int
        return {
            "label": label,
            "current_display": _fmt_int(used),
            "total_display": total_display,
            "pct_int": pct_int,
            "pct_label": pct_label,
            "bar_class": bar_class,
            "bar_width": bar_w,
            "unlimited": unlimited,
        }

    resource_rows = [
        resource_row("Internal Users", ws.internal_users, cap_users, "indigo"),
        resource_row("Internal Trucks", ws.internal_trucks, cap_trucks, "purple"),
        resource_row(
            "Active Drivers", ws.active_insource_drivers, cap_drivers, "green"
        ),
        resource_row(
            "Monthly Shipments", ws.monthly_shipments, cap_shipments, "cyan"
        ),
        resource_row(
            "Storage GB", ws.storage_gb_used, cap_storage, "amber"
        ),
    ]

    donut_segment_defs = [
        ("users", "Users", "#8b5cf6", ws.internal_users, cap_users),
        ("trucks", "Trucks", "#6366f1", ws.internal_trucks, cap_trucks),
        ("drivers", "Driver", "#10b981", ws.active_insource_drivers, cap_drivers),
        ("shipments", "Shipments", "#06b6d4", ws.monthly_shipments, cap_shipments),
        ("storage", "Storage GB", "#f59e0b", ws.storage_gb_used, cap_storage),
    ]
    donut_segments: list[dict[str, Any]] = []
    donut_weights: list[tuple[str, float]] = []
    for key, label, color, used, cap in donut_segment_defs:
        unlimited = _is_unlimited_cap(cap)
        if unlimited:
            pct_int = 0
            pct_label = "Unlimited"
            weight = float(used) if used > 0 else 0.0
        else:
            pct_int = _pct_used(used, cap) if cap > 0 else 0
            pct_label = f"{pct_int}%"
            weight = float(pct_int) if cap > 0 else (1.0 if used > 0 else 0.0)
        if weight <= 0 and used <= 0:
            weight = 0.0
        donut_weights.append((color, weight))
        donut_segments.append(
            {
                "key": key,
                "label": label,
                "color": color,
                "used": int(used),
                "used_display": _fmt_int(used),
                "total_display": "∞" if unlimited else (_fmt_int(cap) if cap > 0 else "0"),
                "pct_label": pct_label,
                "pct_int": pct_int,
                "unlimited": unlimited,
                "weight": weight,
            }
        )
    donut_style = f"background: {_build_conic_gradient(donut_weights)};"

    chart_months, chart_y_ticks = _fleet_chart_months(schema_name) if schema_name else ([], [40, 30, 20, 10, 0])
    y_max = chart_y_ticks[0] if chart_y_ticks else 40

    today = timezone.localdate()
    range_start = date(*_shift_month(today.year, today.month, -3), 1)
    range_label = f"{range_start.strftime('%b %Y')} – {today.strftime('%b %Y')}"

    overview_actions = [
        {
            "label": "Upgrade Plan",
            "url": reverse("iroad_tenants:tenant_subscription_plan"),
            "icon": "bi-bar-chart-line",
            "tone": "text-primary",
        },
        {
            "label": "Downgrade Plan",
            "url": reverse("iroad_tenants:tenant_subscription_plan"),
            "icon": "bi-cart-dash",
            "tone": "text-primary",
        },
        {
            "label": "Billing Logs",
            "url": reverse("iroad_tenants:tenant_subscription_billing"),
            "icon": "bi-receipt",
            "tone": "text-primary",
        },
        {
            "label": "Payment Logs",
            "url": reverse("iroad_tenants:tenant_subscription_billing"),
            "icon": "bi-journal-check",
            "tone": "text-primary",
        },
        {
            "label": "Add Users",
            "url": reverse("iroad_tenants:tenant_users_administration_create"),
            "icon": "bi-person-plus",
            "tone": "text-success",
        },
        {
            "label": "Users",
            "url": reverse("iroad_tenants:tenant_users_administration"),
            "icon": "bi-people",
            "tone": "text-success",
        },
        {
            "label": "Create Support Ticket",
            "url": reverse("iroad_tenants:tenant_support_ticket_create"),
            "icon": "bi-ticket-detailed",
            "tone": "text-teal",
        },
        {
            "label": "Support Ticket",
            "url": reverse("iroad_tenants:tenant_support_ticket_list"),
            "icon": "bi-life-preserver",
            "tone": "text-teal",
        },
    ]

    ops: dict[str, Any] = {
        "actions": [],
        "bookings": {"active": 0, "executed": 0, "cancelled": 0, "draft": 0},
        "shipments": {
            "active": 0,
            "executed": 0,
            "cancelled": 0,
            "pod_complete": 0,
            "pod_incomplete": 0,
        },
        "live_trips": [],
        "live_movements": [],
        "recent_bookings": [],
        "recent_shipments": [],
        "pending_pod": [],
    }
    fleet: dict[str, Any] = {
        "actions": [],
        "truck_metrics": {"total": 0, "available": 0, "loaded": 0, "suspended": 0},
        "driver_metrics": {"total": 0, "available": 0, "loaded": 0, "suspended": 0},
        "compliance": {
            "truck_expired": 0,
            "truck_near_expiry": 0,
            "driver_expired": 0,
            "driver_near_expiry": 0,
        },
        "chart_months": chart_months,
        "chart_y_ticks": chart_y_ticks,
        "fleet_donut_style": "background: conic-gradient(#e2e8f0 0 100%);",
        "fleet_donut_segments": [],
        "truck_rows": [],
        "driver_rows": [],
    }
    if schema_name:
        with schema_context(schema_name):
            ops = _build_ops_hub_data()
            fleet = _build_fleet_hub_data(schema_name)

    return {
        "plan_name": plan_name,
        "plan_price_line": price_line,
        "plan_cycle_label": cycle_label,
        "plan_renewal_display": renewal_display,
        "plan_driver_attr": driver_attr,
        "plan_backup_attr": backup_attr,
        "chart_months": chart_months,
        "chart_y_ticks": chart_y_ticks,
        "chart_y_max": y_max,
        "donut_style": donut_style,
        "donut_segments": donut_segments,
        "month_range_label": range_label,
        "resource_rows": resource_rows,
        "workspace_schema": schema_name,
        "overview_actions": overview_actions,
        "ops": ops,
        "fleet": fleet,
    }
