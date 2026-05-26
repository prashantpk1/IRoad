"""One-off generator for Job Detail Postman collection. Run from repo root."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent

COMMON_HEADERS = [
    {"key": "Accept", "value": "application/json"},
    {"key": "Accept-Language", "value": "{{accept_language}}"},
    {"key": "X-Request-ID", "value": "{{request_id}}"},
]

AUTH_HEADERS = COMMON_HEADERS + [
    {
        "key": "X-Tenant-ID",
        "value": "{{tenant_id}}",
        "description": "Optional — must match JWT when provided",
    },
]


def req(method, url, headers=None, body=None, desc=""):
    r = {"method": method, "header": headers or AUTH_HEADERS, "url": url}
    if desc:
        r["description"] = desc
    if body is not None:
        r["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    return r


def test_script(lines):
    return [{"listen": "test", "script": {"type": "text/javascript", "exec": lines}}]


def prerequest(lines):
    return [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": lines}}]


LOGIN_TESTS = [
    "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
    "const json = pm.response.json();",
    "pm.test('Login success', function () { pm.expect(json.status).to.eql(1); });",
    "const data = json.data || {};",
    "if (data.access_token) { pm.environment.set('access_token', data.access_token); pm.collectionVariables.set('access_token', data.access_token); }",
    "if (data.refresh_token) { pm.environment.set('refresh_token', data.refresh_token); pm.collectionVariables.set('refresh_token', data.refresh_token); }",
    "const org = data.organization || {};",
    "if (org.schema_name) { pm.environment.set('tenant_schema', org.schema_name); pm.collectionVariables.set('tenant_schema', org.schema_name); }",
    "if (org.tenant_id) { pm.environment.set('tenant_id', org.tenant_id); pm.collectionVariables.set('tenant_id', org.tenant_id); }",
    "const driver = data.driver || {};",
    "const did = driver.driver_id || driver.id || ''; if (did) { pm.environment.set('driver_id', String(did)); pm.collectionVariables.set('driver_id', String(did)); }",
]

JOB_DETAIL_TESTS = [
    "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
    "const json = pm.response.json();",
    "pm.test('App status success', function () { pm.expect(json.status).to.eql(1); });",
    "pm.test('Job Detail contract keys', function () { const d = json.data || {}; ['job','workflow','timeline','pod_cod','round_trip','alerts','sync_metadata'].forEach(function (k) { pm.expect(d).to.have.property(k); }); });",
    "pm.test('sync_metadata required fields', function () { const sm = (json.data || {}).sync_metadata || {}; ['content_hash','entity_versions','workflow_version','generated_at'].forEach(function (k) { pm.expect(sm).to.have.property(k); }); });",
    "const etag = pm.response.headers.get('ETag'); if (etag) { pm.environment.set('job_detail_etag', etag); pm.collectionVariables.set('job_detail_etag', etag); }",
    "const sm = (json.data || {}).sync_metadata || {}; if (sm.content_hash) { pm.environment.set('job_detail_content_hash', sm.content_hash); pm.collectionVariables.set('job_detail_content_hash', sm.content_hash); }",
    "const job = (json.data || {}).job || {}; if (job.job_id) { pm.environment.set('shipment_id', job.job_id); pm.collectionVariables.set('shipment_id', job.job_id); }",
]

TIMELINE_TESTS = [
    "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
    "const json = pm.response.json();",
    "pm.test('Timeline contract', function () { const d = json.data || {}; pm.expect(d).to.have.property('events'); pm.expect(d).to.have.property('next_cursor'); pm.expect(d).to.have.property('has_more'); });",
    "const d = json.data || {}; if (d.next_cursor) { pm.environment.set('timeline_cursor', d.next_cursor); pm.collectionVariables.set('timeline_cursor', d.next_cursor); }",
]


def saved_response(name, code, body, headers=None):
    status_map = {200: "OK", 304: "Not Modified", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found"}
    h = headers or [{"key": "Content-Type", "value": "application/json"}]
    return {
        "name": name,
        "status": status_map.get(code, "OK"),
        "code": code,
        "_postman_previewlanguage": "json",
        "header": h,
        "body": json.dumps(body, indent=2),
    }


EX_SHIPMENT_ONEWAY = {
    "status": 1,
    "message": "Data retrieved successfully",
    "message_key": "mobile.success.data_retrieved",
    "data": {
        "job": {
            "job_type": "shipment",
            "job_id": "s1111111-1111-1111-1111-111111111111",
            "job_no": "SH-2026-0099",
            "entity_type": "shipment",
        },
        "workflow": {
            "current_stage": "In Transit",
            "next_action": {"action_code": "A5"},
            "allowed_actions": [{"action_code": "A5"}],
            "workflow_source": "operation_execution.get_allowed_actions",
        },
        "timeline": {
            "scope": "shipment",
            "preview_limit": 5,
            "timeline_preview": [
                {"log_id": "log-1001", "event_type": "action", "authority": "action_log"}
            ],
            "timeline_cursor": "",
            "has_more": False,
        },
        "pod_cod": {
            "pod_pending": True,
            "pod_compliant": False,
            "hard_pod_pending": False,
            "cod_pending": False,
            "cod_collected": False,
            "treasury_pending": False,
            "delivery_blocked": True,
            "compliance_integrity": {
                "compliance_drift": False,
                "authority_source": "action_logs",
            },
        },
        "round_trip": {
            "booking_no": "BK-2026-0042",
            "trip_type": "One-Way",
            "booking_execution_stage": "PARTIAL",
            "progression_mode": "same_driver",
            "legs": [],
            "outbound_progression": {"legs_total": 1},
            "backload_progression": {"legs_total": 0},
        },
        "alerts": {"has_drift": False},
        "sync_metadata": {
            "job_detail_projection_version": "1",
            "content_hash": "jd_hash_one_way_example_64hex000000000000000000000000000000000000000000000000",
            "workflow_version": "jd_wf_ver_001",
            "generated_at": "2026-05-26T10:15:00.000Z",
            "entity_versions": {
                "booking": "bk_v",
                "shipment": "sh_v",
                "movement": "",
                "action_log": "log-1001",
                "pod_cod": "pod_v",
            },
            "workflow_integrity": {"authority_source": "action_logs"},
            "compliance_integrity": {"compliance_drift": False},
            "drift_detected": False,
        },
    },
    "meta": {
        "request_id": "postman-jd-001",
        "content_hash": "jd_hash_one_way_example_64hex000000000000000000000000000000000000000000000000",
    },
}

EX_ROUND_TRIP = {
    "status": 1,
    "data": {
        "job": {
            "job_type": "shipment",
            "job_id": "s2222222-2222-2222-2222-222222222222",
            "job_no": "SH-RT-BACK",
            "entity_type": "shipment",
        },
        "workflow": {"current_stage": "Pickup", "next_action": {"action_code": "A2"}},
        "timeline": {
            "scope": "shipment",
            "timeline_preview": [],
            "has_more": True,
            "timeline_cursor": "cursor_rt_page1",
        },
        "pod_cod": {"pod_pending": True, "pod_compliant": False, "cod_pending": False},
        "round_trip": {
            "booking_no": "BK-RT-0015",
            "trip_type": "Round",
            "booking_execution_stage": "OUTBOUND_COMPLETED",
            "progression_mode": "same_driver",
            "next_executable_leg": {"booking_item_type": "Backload"},
            "outbound_progression": {"all_execution_complete": True},
            "backload_progression": {
                "all_execution_complete": False,
                "active_leg": {"shipment_no": "SH-RT-BACK"},
            },
        },
        "alerts": {},
        "sync_metadata": {
            "content_hash": "jd_rt_hash",
            "workflow_version": "jd_rt_wf",
            "generated_at": "2026-05-26T11:00:00.000Z",
            "entity_versions": {"booking": "bk_rt", "shipment": "sh_rt"},
        },
    },
}

EX_SPLIT_DRIVER = {
    "status": 1,
    "data": {
        "job": {"job_type": "shipment", "job_no": "SH-RT-BACK"},
        "round_trip": {
            "progression_mode": "split_driver",
            "booking_execution_stage": "BACKLOAD_ACTIVE",
            "outbound_progression": {"driver_owns_any_leg": False},
            "backload_progression": {"driver_owns_any_leg": True},
            "current_leg": {"driver_owns_leg": True},
        },
        "pod_cod": {},
        "workflow": {},
        "timeline": {},
        "alerts": {},
        "sync_metadata": {
            "content_hash": "jd_split",
            "entity_versions": {},
            "workflow_version": "w",
            "generated_at": "2026-05-26T12:00:00.000Z",
        },
    },
}

EX_EMPTY_MOVE = {
    "status": 1,
    "data": {
        "job": {
            "job_type": "movement",
            "job_id": "m3333333-3333-3333-3333-333333333333",
            "job_no": "EM-2026-0007",
            "entity_type": "movement",
        },
        "workflow": {
            "current_stage": "In Transit",
            "allowed_actions": [{"action_code": "EM3"}],
            "workflow_source": "operation_execution.get_allowed_actions",
        },
        "timeline": {
            "scope": "movement",
            "timeline_preview": [
                {"log_id": "log-em-1", "event_type": "movement", "authority": "action_log"}
            ],
            "has_more": False,
        },
        "pod_cod": {},
        "round_trip": {},
        "alerts": {},
        "sync_metadata": {
            "content_hash": "jd_em_hash",
            "workflow_version": "jd_em_wf",
            "generated_at": "2026-05-26T10:30:00.000Z",
            "entity_versions": {
                "movement": "mv_v",
                "shipment": "",
                "action_log": "log-em-1",
            },
        },
    },
}

EX_POD_COMPLIANT = {
    "status": 1,
    "data": {
        "job": {"job_type": "shipment", "job_no": "SH-POD-OK"},
        "pod_cod": {
            "pod_pending": False,
            "pod_compliant": True,
            "hard_pod_pending": False,
            "delivery_blocked": False,
            "compliance_integrity": {
                "compliance_drift": False,
                "authority_source": "action_logs",
            },
        },
        "workflow": {},
        "timeline": {},
        "round_trip": {},
        "alerts": {},
        "sync_metadata": {
            "content_hash": "jd_pod_ok",
            "entity_versions": {"pod_cod": "pod_compliant_v"},
            "workflow_version": "w",
            "generated_at": "2026-05-26T12:00:00.000Z",
        },
    },
}

EX_HARD_POD = {
    "status": 1,
    "data": {
        "pod_cod": {
            "pod_pending": True,
            "pod_compliant": False,
            "hard_pod_pending": True,
            "delivery_blocked": True,
            "compliance_integrity": {"compliance_drift": False},
        },
        "job": {"job_type": "shipment"},
        "workflow": {},
        "timeline": {},
        "round_trip": {},
        "alerts": {"has_drift": False},
        "sync_metadata": {
            "content_hash": "jd_hard_pod",
            "entity_versions": {},
            "workflow_version": "w",
            "generated_at": "2026-05-26T12:00:00.000Z",
        },
    },
}

EX_COD = {
    "status": 1,
    "data": {
        "pod_cod": {
            "cod_pending": False,
            "cod_collected": True,
            "treasury_pending": True,
            "delivery_blocked": False,
            "compliance_integrity": {
                "cod_reconciled": False,
                "treasury_reconciled": False,
                "compliance_drift": True,
                "drift_reasons": ["cod_collected_without_treasury_post"],
            },
        },
        "job": {"job_type": "shipment"},
        "workflow": {},
        "timeline": {},
        "round_trip": {},
        "alerts": {"has_drift": True},
        "sync_metadata": {
            "content_hash": "jd_cod",
            "drift_detected": True,
            "entity_versions": {},
            "workflow_version": "w",
            "generated_at": "2026-05-26T12:00:00.000Z",
        },
    },
}

EX_SYNC = {
    "status": 1,
    "data": {
        "sync_metadata": {
            "job_detail_projection_version": "1",
            "content_hash": "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
            "workflow_version": "wf_abc123def456",
            "generated_at": "2026-05-26T14:00:00.000Z",
            "last_action_log_id": "log-9999",
            "entity_versions": {
                "booking": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "shipment": "sh_ver_token",
                "movement": "",
                "action_log": "log-9999",
                "pod_cod": "pod_ver_token",
            },
            "workflow_integrity": {
                "authority_source": "action_logs",
                "workflow_integrity_state": "aligned",
                "missing_log_warning": False,
            },
            "compliance_integrity": {
                "pod_reconciled": True,
                "cod_reconciled": True,
                "compliance_drift": False,
            },
            "reconciliation_version": "rev_example",
            "workflow_reconciled": True,
            "drift_detected": False,
            "job_etag": '"jd_etag_example"',
            "tenant_schema": "tenant_demo",
            "job_type": "shipment",
            "job_id": "s1111111-1111-1111-1111-111111111111",
        },
        "job": {},
        "workflow": {},
        "timeline": {},
        "pod_cod": {},
        "round_trip": {},
        "alerts": {},
    },
}

EX_TIMELINE = {
    "status": 1,
    "data": {
        "events": [
            {
                "log_id": "log-1003",
                "log_no": "AL-1003",
                "event_type": "pod",
                "action_code": "A7",
                "action_label": "Upload POD",
                "authority": "action_log",
                "append_only": True,
            },
            {
                "log_id": "log-1002",
                "log_no": "AL-1002",
                "event_type": "action",
                "action_code": "A5",
                "authority": "action_log",
            },
        ],
        "next_cursor": "eyJsb2dfZGF0ZSI6IjIwMjYtMDUtMjBUMTA6MDA6MDBaIiwibG9nX2lkIjoibG9nLTEwMDIifQ",
        "has_more": True,
    },
}

EX_401 = {
    "status": 0,
    "message": "Unauthorized",
    "message_key": "mobile.auth.unauthorized",
    "errors": [{"code": "unauthorized"}],
}
EX_403_FORBIDDEN = {
    "status": 0,
    "message": "Forbidden",
    "message_key": "mobile.auth.forbidden",
    "errors": [{"code": "forbidden"}],
}
EX_403_TENANT = {
    "status": 0,
    "message": "Tenant mismatch",
    "message_key": "mobile.auth.tenant_mismatch",
    "errors": [{"code": "tenant_mismatch"}],
}
EX_404 = {
    "status": 0,
    "message": "Job not found",
    "message_key": "mobile.jobs.not_found",
    "errors": [{"code": "job_not_found"}],
}


def example_item(name, url, responses, method="GET", extra_headers=None):
    hdr = [{"key": "Accept", "value": "application/json"}]
    if extra_headers:
        hdr.extend(extra_headers)
    return {"name": name, "request": {"method": method, "header": hdr, "url": url}, "response": responses}


def main():
    collection = {
        "info": {
            "_postman_id": "c3d4e5f6-a7b8-9012-cdef-123456789abc",
            "name": "Iroad — Mobile Driver API (Unified Job Detail)",
            "description": (
                "Complete Postman collection for **Unified Driver Job Detail** + timeline pagination.\n\n"
                "## Base\n`{{base_url}}` (default `http://127.0.0.1:8000/api/v1/mobile`)\n\n"
                "## Folders\n"
                "1. **01 — Auth & JWT** — login, refresh, logout\n"
                "2. **02 — Job Detail (Live)** — shipment, empty move, security negatives, ETag polling\n"
                "3. **03 — Timeline Pagination (Live)** — cursor pages\n"
                "4. **04 — Examples (Reference)** — saved responses\n\n"
                "## RBAC\n`mobile.driver.job_detail`\n\n"
                "## Setup\nSee `JOB_DETAIL_SETUP.md` in this folder."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
        },
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "if (!pm.variables.get('request_id') || String(pm.variables.get('request_id')).indexOf('{{') >= 0) {",
                        "    pm.variables.set('request_id', 'postman-' + pm.variables.replaceIn('{{$guid}}'));",
                        "}",
                    ],
                },
            }
        ],
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000/api/v1/mobile"},
            {"key": "access_token", "value": ""},
            {"key": "refresh_token", "value": ""},
            {"key": "tenant_id", "value": ""},
            {"key": "tenant_schema", "value": ""},
            {"key": "driver_id", "value": ""},
            {"key": "shipment_id", "value": ""},
            {"key": "movement_id", "value": ""},
            {"key": "job_detail_etag", "value": ""},
            {"key": "job_detail_content_hash", "value": ""},
            {"key": "timeline_cursor", "value": ""},
            {"key": "wrong_tenant_id", "value": "wrong-tenant-schema"},
            {"key": "foreign_shipment_id", "value": "00000000-0000-0000-0000-000000000099"},
        ],
        "item": [],
    }

    auth_folder = {
        "name": "01 — Auth & JWT",
        "description": "Run **Driver Login** first.",
        "item": [
            {
                "name": "Driver Login",
                "event": test_script(LOGIN_TESTS),
                "request": req(
                    "POST",
                    "{{base_url}}/driver/auth/login/",
                    headers=COMMON_HEADERS,
                    body={
                        "email": "{{driver_email}}",
                        "password": "{{driver_password}}",
                        "tenant_id": "{{tenant_id}}",
                        "device_platform": "{{device_platform}}",
                        "device_id": "{{device_id}}",
                        "device_name": "{{device_name}}",
                    },
                ),
                "response": [
                    saved_response(
                        "200 Login success",
                        200,
                        {
                            "status": 1,
                            "data": {
                                "access_token": "eyJ.example.access",
                                "refresh_token": "eyJ.example.refresh",
                                "organization": {
                                    "tenant_id": "t-demo",
                                    "schema_name": "tenant_demo",
                                },
                                "driver": {"driver_id": "d1111111-1111-1111-1111-111111111111"},
                            },
                        },
                    )
                ],
            },
            {
                "name": "Refresh Token",
                "event": test_script(
                    [
                        "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                        "const data = (pm.response.json().data || {});",
                        "if (data.access_token) pm.environment.set('access_token', data.access_token);",
                    ]
                ),
                "request": req(
                    "POST",
                    "{{base_url}}/driver/auth/refresh/",
                    headers=COMMON_HEADERS,
                    body={"refresh_token": "{{refresh_token}}", "tenant_id": "{{tenant_id}}"},
                ),
                "response": [],
            },
            {
                "name": "Logout",
                "request": req(
                    "POST",
                    "{{base_url}}/driver/auth/logout/",
                    headers=COMMON_HEADERS,
                    body={"refresh_token": "{{refresh_token}}"},
                ),
                "response": [],
            },
        ],
    }

    job_folder = {
        "name": "02 — Job Detail (Live)",
        "description": "GET `/driver/jobs/<job_type>/<job_id>/`",
        "item": [
            {
                "name": "Get Shipment Job Detail",
                "event": test_script(JOB_DETAIL_TESTS),
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                ),
                "response": [],
            },
            {
                "name": "Get Shipment Job Detail (If-None-Match — expect 304)",
                "event": prerequest(
                    [
                        "if (!pm.collectionVariables.get('job_detail_etag')) console.warn('Run Get Shipment Job Detail first');"
                    ]
                )
                + test_script(
                    ["pm.test('HTTP 304', function () { pm.response.to.have.status(304); });"]
                ),
                "request": {
                    "method": "GET",
                    "header": AUTH_HEADERS
                    + [{"key": "If-None-Match", "value": "{{job_detail_etag}}"}],
                    "url": "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                },
                "response": [
                    saved_response("304", 304, {}, [{"key": "ETag", "value": '"jd_etag"'}])
                ],
            },
            {
                "name": "Get Empty Move Job Detail",
                "event": test_script(
                    JOB_DETAIL_TESTS
                    + [
                        "const job = (pm.response.json().data || {}).job || {}; if (job.job_id) pm.environment.set('movement_id', job.job_id);",
                        "pm.test('pod_cod empty', function () { const d = pm.response.json().data; pm.expect(d.pod_cod).to.eql({}); });",
                    ]
                ),
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/movement/{{movement_id}}/",
                ),
                "response": [],
            },
            {
                "name": "Get Job Detail — No Authorization (expect 401)",
                "request": {
                    "auth": {"type": "noauth"},
                    "method": "GET",
                    "header": COMMON_HEADERS,
                    "url": "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                },
                "response": [saved_response("401", 401, EX_401)],
            },
            {
                "name": "Get Job Detail — Wrong Tenant Header (expect 403)",
                "request": {
                    "method": "GET",
                    "header": COMMON_HEADERS
                    + [{"key": "X-Tenant-ID", "value": "{{wrong_tenant_id}}"}],
                    "url": "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                },
                "response": [saved_response("403 Tenant", 403, EX_403_TENANT)],
            },
            {
                "name": "Get Job Detail — Wrong Driver (expect 403)",
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/shipment/{{foreign_shipment_id}}/",
                ),
                "response": [saved_response("403 Forbidden", 403, EX_403_FORBIDDEN)],
            },
            {
                "name": "Get Job Detail — Not Found (expect 404)",
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/shipment/00000000-0000-0000-0000-000000000001/",
                ),
                "response": [saved_response("404", 404, EX_404)],
            },
        ],
    }

    timeline_folder = {
        "name": "03 — Timeline Pagination (Live)",
        "description": "GET `.../timeline/?cursor=&limit=`",
        "item": [
            {
                "name": "Timeline — Page 1 (shipment)",
                "event": test_script(TIMELINE_TESTS),
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/timeline/?limit=10",
                ),
                "response": [],
            },
            {
                "name": "Timeline — Page 2 (cursor)",
                "event": test_script(TIMELINE_TESTS),
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/timeline/?limit=10&cursor={{timeline_cursor}}",
                ),
                "response": [],
            },
            {
                "name": "Timeline — Empty Move",
                "event": test_script(TIMELINE_TESTS),
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/movement/{{movement_id}}/timeline/?limit=20",
                ),
                "response": [],
            },
            {
                "name": "Timeline — Invalid cursor (expect 400)",
                "request": req(
                    "GET",
                    "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/timeline/?cursor=not-valid",
                ),
                "response": [
                    saved_response(
                        "400",
                        400,
                        {
                            "status": 0,
                            "errors": [{"code": "invalid_timeline_cursor"}],
                        },
                    )
                ],
            },
        ],
    }

    examples_folder = {
        "name": "04 — Job Detail Examples (Reference)",
        "description": "Saved examples — no server required.",
        "item": [
            example_item(
                "[Example] Shipment — One-Way",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [
                    saved_response(
                        "200",
                        200,
                        EX_SHIPMENT_ONEWAY,
                        [
                            {"key": "Content-Type", "value": "application/json"},
                            {"key": "ETag", "value": '"jd_etag_one_way"'},
                        ],
                    )
                ],
            ),
            example_item(
                "[Example] Round Trip — Outbound Completed",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("200", 200, EX_ROUND_TRIP)],
            ),
            example_item(
                "[Example] Round Trip — Split Driver",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("200", 200, EX_SPLIT_DRIVER)],
            ),
            example_item(
                "[Example] Empty Move",
                "{{base_url}}/driver/jobs/movement/{{movement_id}}/",
                [saved_response("200", 200, EX_EMPTY_MOVE)],
            ),
            example_item(
                "[Example] POD Pending",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("200", 200, EX_SHIPMENT_ONEWAY)],
            ),
            example_item(
                "[Example] POD Compliant",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("200", 200, EX_POD_COMPLIANT)],
            ),
            example_item(
                "[Example] Hard POD Pending",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("200", 200, EX_HARD_POD)],
            ),
            example_item(
                "[Example] COD / Treasury",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("200", 200, EX_COD)],
            ),
            example_item(
                "[Example] Sync Metadata",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [
                    saved_response(
                        "200",
                        200,
                        EX_SYNC,
                        [
                            {"key": "Content-Type", "value": "application/json"},
                            {"key": "ETag", "value": '"jd_etag_example"'},
                        ],
                    )
                ],
            ),
            example_item(
                "[Example] Timeline Page",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/timeline/",
                [saved_response("200", 200, EX_TIMELINE)],
            ),
            example_item(
                "[Example] 401 Unauthorized",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("401", 401, EX_401)],
            ),
            example_item(
                "[Example] 403 Wrong Driver",
                "{{base_url}}/driver/jobs/shipment/{{foreign_shipment_id}}/",
                [saved_response("403", 403, EX_403_FORBIDDEN)],
            ),
            example_item(
                "[Example] 403 Tenant Mismatch",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                [saved_response("403", 403, EX_403_TENANT)],
                extra_headers=[{"key": "X-Tenant-ID", "value": "wrong-tenant-schema"}],
            ),
        ],
    }

    collection["item"] = [auth_folder, job_folder, timeline_folder, examples_folder]

    out_path = OUT / "Iroad_Mobile_Driver_Job_Detail.postman_collection.json"
    out_path.write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
