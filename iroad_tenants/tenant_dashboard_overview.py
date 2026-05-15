"""
Server-side metrics for the tenant portal dashboard overview (Quota Analytics + Plan).

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

from django.utils import timezone
from django_tenants.utils import schema_context

from iroad_tenants.models import TenantRegistry
from superadmin.models import PlanPricingCycle, TenantProfile
from tenant_workspace.models import DriverMaster, TenantShipment, TenantUser, TruckMaster


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    ny, rem = divmod(idx, 12)
    return ny, rem + 1


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _nice_y_axis_max(*values: int) -> int:
    top = max(values) if values else 1
    if top <= 0:
        return 40
    step = max(10, int(math.ceil(top / 4 / 10.0)) * 10)
    return max(40, int(math.ceil(top / float(step))) * step)


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
    """
    ``weights`` is (hex_color, positive_weight). Builds a full-ring conic-gradient.
    """
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


def _effective_cap(tenant_val: int, plan_val: int | None) -> int:
    tv = int(tenant_val or 0)
    if tv > 0:
        return tv
    if plan_val is None:
        return 0
    return int(plan_val)


def _is_unlimited_cap(cap: int) -> bool:
    return cap < 0


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


def build_tenant_dashboard_overview(tenant: TenantProfile) -> dict[str, Any]:
    """
    Return a dict of template-friendly values for the dashboard overview card.
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
            pct_int = 100 if used > 0 else 0
            pct_label = "∞" if used > 0 else "0%"
            bar_w = 100 if used > 0 else 2
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

    donut_weights = [
        ("#8b5cf6", float(resource_rows[0]["pct_int"])),
        ("#6366f1", float(resource_rows[1]["pct_int"])),
        ("#10b981", float(resource_rows[2]["pct_int"])),
        ("#06b6d4", float(resource_rows[3]["pct_int"])),
        ("#f59e0b", float(resource_rows[4]["pct_int"])),
    ]
    donut_style = f"background: {_build_conic_gradient(donut_weights)};"

    today = timezone.localdate()
    chart_months: list[dict[str, Any]] = []
    series_trucks: list[int] = []
    series_drivers: list[int] = []

    if schema_name:
        for back in (3, 2, 1, 0):
            y, m = _shift_month(today.year, today.month, -back)
            end_d = _month_end(y, m)
            next_d = end_d + timedelta(days=1)
            end_ts_exclusive = timezone.make_aware(
                datetime.combine(next_d, time.min),
                timezone.get_current_timezone(),
            )
            with schema_context(schema_name):
                t_count = (
                    TruckMaster.active_objects.filter(
                        sourcing_mode=TruckMaster.SourcingMode.IN_SOURCE,
                        created_at__lt=end_ts_exclusive,
                    ).count()
                )
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
    else:
        for back in (3, 2, 1, 0):
            y, m = _shift_month(today.year, today.month, -back)
            label = date(y, m, 1).strftime("%b")
            chart_months.append(
                {
                    "label": label,
                    "truck_count": 0,
                    "driver_count": 0,
                }
            )
            series_trucks.append(0)
            series_drivers.append(0)

    y_max = _nice_y_axis_max(*(series_trucks + series_drivers))
    y_ticks = [y_max, int(y_max * 0.75), int(y_max * 0.5), int(y_max * 0.25), 0]
    for row in chart_months:
        tc = int(row["truck_count"])
        dc = int(row["driver_count"])
        row["truck_pct"] = min(100, int(round(100.0 * tc / float(y_max)))) if y_max else 0
        row["driver_pct"] = min(100, int(round(100.0 * dc / float(y_max)))) if y_max else 0

    range_start = date(*_shift_month(today.year, today.month, -3), 1)
    range_label = (
        f"{range_start.strftime('%b %Y')} – {today.strftime('%b %Y')}"
    )

    return {
        "plan_name": plan_name,
        "plan_price_line": price_line,
        "plan_cycle_label": cycle_label,
        "plan_renewal_display": renewal_display,
        "plan_driver_attr": driver_attr,
        "plan_backup_attr": backup_attr,
        "chart_months": chart_months,
        "chart_y_ticks": y_ticks,
        "chart_y_max": y_max,
        "donut_style": donut_style,
        "month_range_label": range_label,
        "resource_rows": resource_rows,
        "workspace_schema": schema_name,
    }
