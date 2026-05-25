"""Generate IRoad Mobile Driver Jobs Postman collection + environment."""
from __future__ import annotations

import json
import os


def test_lines(*lines: str) -> dict:
    return {"listen": "test", "script": {"type": "text/javascript", "exec": list(lines)}}


def prerequest_warn() -> dict:
    return {
        "listen": "prerequest",
        "script": {
            "type": "text/javascript",
            "exec": [
                "if (!pm.environment.get('access_token') && !pm.request.url.path.join('/').includes('login')) {",
                "    console.warn('access_token empty — run Setup → Login first');",
                "}",
            ],
        },
    }


def hdrs(*, include_tenant: bool = False) -> list:
    h = [
        {"key": "Authorization", "value": "Bearer {{access_token}}"},
        {"key": "Accept-Language", "value": "{{accept_language}}"},
    ]
    if include_tenant:
        h.append({"key": "X-Tenant-ID", "value": "{{tenant_id}}"})
    return h


def sample(name: str, code: int, status: str, body: str) -> dict:
    return {
        "name": name,
        "status": status,
        "code": code,
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "body": body,
    }


def get_req(
    name: str,
    path: str,
    desc: str,
    *,
    query: str | None = None,
    tests: list[str] | None = None,
    responses: list | None = None,
    include_tenant: bool = False,
) -> dict:
    url = "{{base_url}}{{api_prefix}}" + path
    if query:
        url += "?" + query
    item = {
        "name": name,
        "request": {
            "method": "GET",
            "header": hdrs(include_tenant=include_tenant),
            "url": url,
            "description": desc,
        },
    }
    if tests:
        item["event"] = [test_lines(*tests)]
    if responses:
        item["response"] = responses
    return item


LOGIN_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "if (j.status === 1 && j.data) {",
    "    if (j.data.access_token) pm.environment.set('access_token', j.data.access_token);",
    "    if (j.data.refresh_token) pm.environment.set('refresh_token', j.data.refresh_token);",
    "    if (j.data.driver && j.data.driver.driver_id) pm.environment.set('driver_id', j.data.driver.driver_id);",
    "}",
]

LIST_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "pm.test('paginated items array', () => {",
    "    pm.expect(j.data).to.have.property('items');",
    "    pm.expect(j.data.items).to.be.an('array');",
    "});",
    "pm.test('pagination_mode present', () => {",
    "    pm.expect(j.data).to.have.property('pagination_mode');",
    "});",
    "if (j.data.pagination_mode === 'cursor') {",
    "    pm.test('cursor fields', () => {",
    "        pm.expect(j.data).to.have.property('has_more');",
    "    });",
    "    if (j.data.next_cursor) pm.environment.set('jobs_next_cursor', j.data.next_cursor);",
    "}",
    "pm.test('list meta present', () => {",
    "    pm.expect(j.data).to.have.property('meta');",
    "    pm.expect(j.data.meta).to.have.property('entity_type');",
    "});",
    "if (j.data.items && j.data.items[0]) {",
    "    const card = j.data.items[0];",
    "    pm.environment.set('last_job_id', card.job_id || '');",
    "    pm.environment.set('last_job_type', card.job_type || '');",
    "}",
]

SUMMARY_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "pm.test('counters object', () => {",
    "    const c = j.data.counters;",
    "    pm.expect(c).to.have.all.keys('active_shipments','completed_shipments','cancelled_shipments','active_movements','completed_movements','cancelled_movements','pod_pending','cod_pending');",
    "});",
    "if (j.data && j.data.counters) {",
    "    pm.environment.set('jobs_active_shipments', String(j.data.counters.active_shipments));",
    "}",
]

PAGINATED_OK = sample(
    "200 Paginated list",
    200,
    "OK",
    json.dumps(
        {
            "status": 1,
            "message": "Shipment jobs loaded successfully.",
            "message_key": "mobile.jobs.shipments_success",
            "data": {
                "items": [
                    {
                        "job_id": "660e8400-e29b-41d4-a716-446655440001",
                        "job_type": "shipment",
                        "job_no": "SH-2026-001",
                        "shipment_no": "SH-2026-001",
                        "current_status": "In Transit",
                        "route_summary": "Riyadh → Jeddah",
                        "latest_action_summary": None,
                        "next_action_hint": "Submit proof of delivery",
                        "pod_status": "Pending",
                        "needs_pod": True,
                        "is_active": True,
                    }
                ],
                "total_records": 42,
                "total_pages": 5,
                "current_page": 1,
                "page_size": 10,
                "meta": {
                    "tab": "active",
                    "queue": "none",
                    "sort": "updated_desc",
                    "entity_type": "shipment",
                    "tab_locked": True,
                    "queue_locked": False,
                    "search": "",
                    "date_from": "",
                    "date_to": "",
                    "date_field": "updated",
                    "include_actions": True,
                },
            },
            "meta": {"locale": "en", "api_version": "1.0"},
        },
        indent=2,
    ),
)

SUMMARY_OK = sample(
    "200 Summary",
    200,
    "OK",
    json.dumps(
        {
            "status": 1,
            "message": "Job summary loaded successfully.",
            "message_key": "mobile.jobs.summary_success",
            "data": {
                "counters": {
                    "active_shipments": 12,
                    "completed_shipments": 45,
                    "cancelled_shipments": 2,
                    "active_movements": 5,
                    "completed_movements": 30,
                    "cancelled_movements": 1,
                    "pod_pending": 3,
                    "cod_pending": 2,
                },
                "entity_types": ["shipment", "movement"],
            },
        },
        indent=2,
    ),
)

ERR_401 = sample(
    "401 Unauthorized",
    401,
    "Unauthorized",
    json.dumps(
        {
            "status": 2,
            "message": "Unauthorized access. Please login to continue.",
            "message_key": "mobile.auth.unauthorized",
            "data": {"error_code": "unauthorized"},
        },
        indent=2,
    ),
)

ERR_403_JOBS = sample(
    "403 Jobs denied",
    403,
    "Forbidden",
    json.dumps(
        {
            "status": 2,
            "message": "You do not have access to driver jobs.",
            "message_key": "mobile.auth.jobs_denied",
            "data": {"error_code": "jobs_denied"},
        },
        indent=2,
    ),
)

ERR_403_TENANT = sample(
    "403 Tenant mismatch",
    403,
    "Forbidden",
    json.dumps(
        {
            "status": 2,
            "message": "Tenant context does not match your session.",
            "message_key": "mobile.auth.tenant_mismatch",
            "data": {"error_code": "tenant_mismatch"},
        },
        indent=2,
    ),
)

ERR_405 = sample(
    "405 Method not allowed",
    405,
    "Method Not Allowed",
    json.dumps(
        {
            "status": 0,
            "message": "This jobs endpoint only supports read requests.",
            "data": {"error_code": "jobs_method_not_allowed"},
        },
        indent=2,
    ),
)


def flow_item(name: str, path: str, query: str = "") -> dict:
    url = "{{base_url}}{{api_prefix}}" + path + ("?" + query if query else "")
    return {"name": name, "request": {"method": "GET", "header": hdrs(), "url": url}}


def main() -> None:
    collection = {
        "info": {
            "_postman_id": "a7b8c9d0-e1f2-3456-a789-joblist123456",
            "name": "IRoad Mobile Driver — Job List Module",
            "description": (
                "# IRoad Mobile — Job List Module\n\n"
                "## Prerequisites\n"
                "1. Import **IRoad Mobile Driver Jobs — Local** environment.\n"
                "2. Set `base_url`, `email`, `password`, optional `tenant_id`.\n"
                "3. Run **Setup → Login**.\n"
                "4. Run **Testing Flows → Flow A** (Collection Runner).\n\n"
                "## Auth & tenant\n"
                "| Item | Rule |\n|------|------|\n"
                "| **Authorization** | `Bearer {{access_token}}` |\n"
                "| **Capability** | `mobile.driver.jobs` |\n"
                "| **X-Tenant-ID** | Optional; must match JWT if sent |\n\n"
                "## Docs\n"
                "- `mobile_api/docs/driver_job_list.md`\n"
                "- `postman/README-Jobs.md`"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
        },
        "event": [prerequest_warn()],
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000"},
            {"key": "api_prefix", "value": "/api/v1/mobile"},
        ],
        "item": [],
    }

    collection["item"].append(
        {
            "name": "Setup",
            "description": "JWT automation — run Login before job list calls.",
            "item": [
                {
                    "name": "Login",
                    "event": [test_lines(*LOGIN_TESTS)],
                    "request": {
                        "auth": {"type": "noauth"},
                        "method": "POST",
                        "header": [
                            {"key": "Content-Type", "value": "application/json"},
                            {"key": "Accept-Language", "value": "{{accept_language}}"},
                        ],
                        "body": {
                            "mode": "raw",
                            "raw": (
                                '{\n  "email": "{{email}}",\n  "password": "{{password}}",\n'
                                '  "device_platform": "{{device_platform}}",\n'
                                '  "device_id": "{{fcm_token}}",\n'
                                '  "device_name": "{{device_name}}"\n}'
                            ),
                        },
                        "url": "{{base_url}}{{api_prefix}}/driver/auth/login/",
                        "description": "**POST** · No auth · Saves tokens + driver_id.",
                    },
                    "response": [],
                },
                {
                    "name": "Refresh Token",
                    "event": [
                        test_lines(
                            "const j = pm.response.json();",
                            "if (j.status === 1 && j.data) {",
                            "    if (j.data.access_token) pm.environment.set('access_token', j.data.access_token);",
                            "    if (j.data.refresh_token) pm.environment.set('refresh_token', j.data.refresh_token);",
                            "}",
                        )
                    ],
                    "request": {
                        "auth": {"type": "noauth"},
                        "method": "POST",
                        "header": [{"key": "Content-Type", "value": "application/json"}],
                        "body": {
                            "mode": "raw",
                            "raw": '{"refresh_token": "{{refresh_token}}"}',
                        },
                        "url": "{{base_url}}{{api_prefix}}/driver/auth/refresh/",
                    },
                    "response": [],
                },
            ],
        }
    )

    collection["item"].append(
        {
            "name": "00 — Summary",
            "item": [
                get_req(
                    "GET Job Summary",
                    "/driver/jobs/summary/",
                    "| Method | GET |\n| URL | `/api/v1/mobile/driver/jobs/summary/` |\n| Auth | Bearer |\n| Capability | `mobile.driver.jobs` |",
                    tests=SUMMARY_TESTS,
                    responses=[SUMMARY_OK, ERR_401, ERR_403_JOBS],
                ),
            ],
        }
    )

    ship_rows = [
        ("GET Shipments — All (query tab)", "/driver/jobs/shipments/", "General list; query tab/queue/q/sort.", "tab=active&page=1&page_size={{jobs_page_size}}&sort={{jobs_sort}}"),
        ("GET Shipments — Active (locked)", "/driver/jobs/shipments/active/", "Path locks tab=active.", "page=1&page_size={{jobs_page_size}}&tab=cancelled"),
        ("GET Shipments — Completed (locked)", "/driver/jobs/shipments/completed/", "Delivered / Closed.", "page=1&page_size={{jobs_page_size}}"),
        ("GET Shipments — Cancelled (locked)", "/driver/jobs/shipments/cancelled/", "Cancelled only.", "page=1&page_size={{jobs_page_size}}"),
        ("GET Shipments — POD Pending (locked)", "/driver/jobs/shipments/pod-pending/", "queue=pod_pending locked.", "page=1&page_size={{jobs_page_size}}"),
        ("GET Shipments — COD Pending (locked)", "/driver/jobs/shipments/cod-pending/", "queue=cod_pending locked.", "page=1&page_size={{jobs_page_size}}"),
    ]
    collection["item"].append(
        {
            "name": "01 — Shipment Lists",
            "description": "Paginated shipment job cards.",
            "item": [
                get_req(n, p, d, query=q, tests=LIST_TESTS, responses=[PAGINATED_OK, ERR_401])
                for n, p, d, q in ship_rows
            ],
        }
    )

    mov_rows = [
        ("GET Movements — All", "/driver/jobs/movements/", "tab=active default.", "tab=active&page=1&page_size={{jobs_page_size}}"),
        ("GET Movements — Active", "/driver/jobs/movements/active/", "Scheduled / In Progress.", "page=1&page_size={{jobs_page_size}}"),
        ("GET Movements — Completed", "/driver/jobs/movements/completed/", "Completed.", "page=1&page_size={{jobs_page_size}}"),
        ("GET Movements — Cancelled", "/driver/jobs/movements/cancelled/", "Cancelled.", "page=1&page_size={{jobs_page_size}}"),
        ("GET Movements — Empty Moves", "/driver/jobs/movements/empty/", "empty_move queue.", "page=1&page_size={{jobs_page_size}}"),
    ]
    collection["item"].append(
        {
            "name": "02 — Movement Lists",
            "item": [
                get_req(n, p, d, query=q, tests=LIST_TESTS, responses=[PAGINATED_OK])
                for n, p, d, q in mov_rows
            ],
        }
    )

    collection["item"].append(
        {
            "name": "03 — Examples (pagination · search · filters)",
            "item": [
                get_req("Cursor - first page", "/driver/jobs/shipments/active/", "Default cursor pagination.", query="page_size=10", tests=LIST_TESTS),
                get_req("Cursor - next page", "/driver/jobs/shipments/active/", "Uses jobs_next_cursor from prior response.", query="page_size=10&cursor={{jobs_next_cursor}}", tests=LIST_TESTS),
                get_req("Pagination - offset page 2 (legacy)", "/driver/jobs/shipments/active/", "Offset via page= forces offset mode.", query="page=2&page_size=5", tests=LIST_TESTS),
                get_req("Pagination - skip COUNT (default)", "/driver/jobs/shipments/active/", "COUNT only when include_total=1.", query="page_size=10", tests=LIST_TESTS),
                get_req("Pagination - explicit COUNT", "/driver/jobs/shipments/active/", "include_total=1", query="page_size=10&include_total=1", tests=LIST_TESTS),
                get_req("Search - shipment_no", "/driver/jobs/shipments/", "q= prefix search", query="tab=active&q={{jobs_search_shipment}}", tests=LIST_TESTS),
                get_req("Search - movement_no", "/driver/jobs/movements/", "movement or linked shipment", query="q={{jobs_search_movement}}", tests=LIST_TESTS),
                get_req("Filter - date range", "/driver/jobs/shipments/completed/", "date_field=operational", query="date_from={{jobs_date_from}}&date_to={{jobs_date_to}}&date_field=operational", tests=LIST_TESTS),
                get_req("Filter - priority sort", "/driver/jobs/shipments/pod-pending/", "sort=priority_desc", query="page=1&sort=priority_desc", tests=LIST_TESTS),
                get_req("Performance - no actions", "/driver/jobs/shipments/active/", "include_actions=0", query="page=1&include_actions=0", tests=LIST_TESTS),
            ],
        }
    )

    collection["item"].append(
        {
            "name": "04 — Errors & RBAC",
            "description": "Manual negative tests.",
            "item": [
                {
                    "name": "401 — No Bearer token",
                    "request": {
                        "auth": {"type": "noauth"},
                        "method": "GET",
                        "url": "{{base_url}}{{api_prefix}}/driver/jobs/summary/",
                    },
                    "response": [ERR_401],
                },
                {
                    "name": "403 — Tenant mismatch (X-Tenant-ID)",
                    "request": {
                        "method": "GET",
                        "header": hdrs(include_tenant=True),
                        "url": "{{base_url}}{{api_prefix}}/driver/jobs/summary/",
                    },
                    "response": [ERR_403_TENANT],
                },
                {
                    "name": "405 — POST not allowed",
                    "request": {
                        "method": "POST",
                        "header": hdrs()
                        + [{"key": "Content-Type", "value": "application/json"}],
                        "body": {"mode": "raw", "raw": "{}"},
                        "url": "{{base_url}}{{api_prefix}}/driver/jobs/shipments/active/",
                    },
                    "response": [ERR_405],
                },
                get_req(
                    "400 — offset rejected (page=)",
                    "/driver/jobs/shipments/active/",
                    "MOBILE_API_JOBS_ALLOW_OFFSET_PAGINATION=false rejects page=.",
                    query="page=2&page_size=10",
                    tests=[
                        "pm.test('offset rejected', () => { pm.expect([400,403,422]).to.include(pm.response.code); });",
                    ],
                ),
                get_req(
                    "400 — tab=all blocked",
                    "/driver/jobs/shipments/",
                    "tab=all rejected when MOBILE_API_JOBS_DISALLOW_TAB_ALL=true (default).",
                    query="tab=all",
                    tests=[
                        "pm.test('blocked tab=all', () => { pm.expect([400,403,422]).to.include(pm.response.code); });",
                    ],
                ),
                get_req(
                    "403 — Jobs RBAC (non-driver token)",
                    "/driver/jobs/summary/",
                    "Use dispatcher/admin JWT — expect 403 jobs_denied.",
                    tests=[
                        "pm.test('403 or auth failure', () => { pm.expect([401,403]).to.include(pm.response.code); });",
                    ],
                    responses=[ERR_403_JOBS],
                ),
            ],
        }
    )

    collection["item"].append(
        {
            "name": "Testing Flows",
            "description": "Collection Runner: run folder top-to-bottom.",
            "item": [
                {
                    "name": "Flow A — Full Job List Smoke",
                    "item": [
                        {
                            "name": "A0 Login",
                            "event": [test_lines(*LOGIN_TESTS)],
                            "request": {
                                "auth": {"type": "noauth"},
                                "method": "POST",
                                "header": [{"key": "Content-Type", "value": "application/json"}],
                                "body": {
                                    "mode": "raw",
                                    "raw": '{"email":"{{email}}","password":"{{password}}"}',
                                },
                                "url": "{{base_url}}{{api_prefix}}/driver/auth/login/",
                            },
                        },
                        flow_item("A1 Summary", "/driver/jobs/summary/"),
                        flow_item("A2 Shipments Active", "/driver/jobs/shipments/active/", "page_size=10"),
                        flow_item("A3 Shipments POD Pending", "/driver/jobs/shipments/pod-pending/", "page=1&page_size=10"),
                        flow_item("A4 Movements Active", "/driver/jobs/movements/active/", "page=1&page_size=10"),
                        flow_item("A5 Movements Empty", "/driver/jobs/movements/empty/", "page=1&page_size=10"),
                    ],
                },
                {
                    "name": "Flow B — All tab routes",
                    "item": [
                        flow_item("B1 Summary", "/driver/jobs/summary/"),
                        flow_item("B2 Shipments Completed", "/driver/jobs/shipments/completed/"),
                        flow_item("B3 Shipments Cancelled", "/driver/jobs/shipments/cancelled/"),
                        flow_item("B4 Shipments COD", "/driver/jobs/shipments/cod-pending/"),
                        flow_item("B5 Movements Completed", "/driver/jobs/movements/completed/"),
                        flow_item("B6 Movements Cancelled", "/driver/jobs/movements/cancelled/"),
                    ],
                },
                {
                    "name": "Flow C — Cursor & search",
                    "item": [
                        flow_item("C1 Cursor page 1", "/driver/jobs/shipments/active/", "page_size=5"),
                        flow_item("C2 Cursor page 2", "/driver/jobs/shipments/active/", "page_size=5&cursor={{jobs_next_cursor}}"),
                        flow_item("C3 Search shipment", "/driver/jobs/shipments/", "q={{jobs_search_shipment}}&tab=active"),
                        flow_item("C4 Search movement", "/driver/jobs/movements/", "q={{jobs_search_movement}}"),
                    ],
                },
                {
                    "name": "Flow D — Error cases (manual)",
                    "item": [
                        {
                            "name": "D1 No token",
                            "request": {
                                "auth": {"type": "noauth"},
                                "method": "GET",
                                "url": "{{base_url}}{{api_prefix}}/driver/jobs/summary/",
                            },
                        },
                        {
                            "name": "D2 POST jobs",
                            "request": {
                                "method": "POST",
                                "header": hdrs(),
                                "body": {"mode": "raw", "raw": "{}"},
                                "url": "{{base_url}}{{api_prefix}}/driver/jobs/movements/",
                            },
                        },
                    ],
                },
            ],
        }
    )

    env = {
        "id": "b8c9d0e1-f2a3-4567-b890-jobsenv12345",
        "name": "IRoad Mobile Driver Jobs — Local",
        "values": [
            {"key": "base_url", "value": "http://127.0.0.1:8000", "type": "default", "enabled": True},
            {"key": "api_prefix", "value": "/api/v1/mobile", "type": "default", "enabled": True},
            {"key": "email", "value": "driver@example.com", "type": "default", "enabled": True},
            {"key": "password", "value": "Password@123", "type": "secret", "enabled": True},
            {"key": "access_token", "value": "", "type": "secret", "enabled": True},
            {"key": "refresh_token", "value": "", "type": "secret", "enabled": True},
            {"key": "accept_language", "value": "en", "type": "default", "enabled": True},
            {"key": "tenant_id", "value": "", "type": "default", "enabled": True},
            {"key": "tenant_schema", "value": "", "type": "default", "enabled": True},
            {"key": "driver_id", "value": "", "type": "default", "enabled": True},
            {"key": "device_platform", "value": "Android", "type": "default", "enabled": True},
            {"key": "device_name", "value": "Postman", "type": "default", "enabled": True},
            {"key": "fcm_token", "value": "", "type": "secret", "enabled": True},
            {"key": "jobs_page_size", "value": "10", "type": "default", "enabled": True},
            {"key": "jobs_page", "value": "1", "type": "default", "enabled": True},
            {"key": "jobs_search_shipment", "value": "SH", "type": "default", "enabled": True},
            {"key": "jobs_search_movement", "value": "MV", "type": "default", "enabled": True},
            {"key": "jobs_date_from", "value": "2026-01-01", "type": "default", "enabled": True},
            {"key": "jobs_date_to", "value": "2026-12-31", "type": "default", "enabled": True},
            {"key": "jobs_tab", "value": "active", "type": "default", "enabled": True},
            {"key": "jobs_sort", "value": "updated_desc", "type": "default", "enabled": True},
            {"key": "last_job_id", "value": "", "type": "default", "enabled": True},
            {"key": "last_job_type", "value": "", "type": "default", "enabled": True},
            {"key": "jobs_active_shipments", "value": "0", "type": "default", "enabled": True},
            {"key": "jobs_next_cursor", "value": "", "type": "default", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": "2026-05-20T14:00:00.000Z",
        "_postman_exported_using": "Cursor",
    }

    root = os.path.dirname(__file__)
    coll_path = os.path.join(root, "IRoad-Mobile-Driver-Jobs.postman_collection.json")
    env_path = os.path.join(root, "IRoad-Mobile-Driver-Jobs.postman_environment.json")
    with open(coll_path, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent="\t", ensure_ascii=False)
    with open(env_path, "w", encoding="utf-8") as f:
        json.dump(env, f, indent="\t", ensure_ascii=False)
    count = sum(len(folder.get("item", [])) for folder in collection["item"])
    print(f"Wrote {coll_path} ({count} requests in folders)")


if __name__ == "__main__":
    main()
