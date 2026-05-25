"""Generate IRoad Mobile Driver Job Detail Postman collection + environment."""
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


def prerequest_idempotency() -> dict:
    return {
        "listen": "prerequest",
        "script": {
            "type": "text/javascript",
            "exec": [
                "pm.environment.set('idempotency_key', pm.variables.replaceIn('{{$guid}}'));",
                "pm.environment.set('source_ref', 'postman-' + Date.now());",
            ],
        },
    }


def hdrs(*, include_tenant: bool = True, content_type: str | None = None) -> list:
    h = [
        {"key": "Authorization", "value": "Bearer {{access_token}}"},
        {"key": "Accept-Language", "value": "{{accept_language}}"},
    ]
    if include_tenant and content_type is None:
        h.append({"key": "X-Tenant-ID", "value": "{{tenant_id}}"})
    if content_type:
        h.append({"key": "Content-Type", "value": content_type})
    return h


def sample(name: str, code: int, status: str, body: str) -> dict:
    return {
        "name": name,
        "status": status,
        "code": code,
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "body": body,
    }


def get_req(name: str, path: str, desc: str, *, query: str | None = None, tests: list | None = None, responses: list | None = None, include_tenant: bool = True) -> dict:
    url = "{{base_url}}{{api_prefix}}" + path
    if query:
        url += "?" + query
    item = {"name": name, "request": {"method": "GET", "header": hdrs(include_tenant=include_tenant), "url": url, "description": desc}}
    if tests:
        item["event"] = [test_lines(*tests)]
    if responses:
        item["response"] = responses
    return item


def post_json(name: str, path: str, desc: str, body: str, *, tests: list | None = None, prerequest: list | None = None, responses: list | None = None) -> dict:
    events = []
    if prerequest:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": prerequest}})
    if tests:
        events.append(test_lines(*tests))
    item = {
        "name": name,
        "request": {
            "method": "POST",
            "header": hdrs(content_type="application/json"),
            "body": {"mode": "raw", "raw": body},
            "url": "{{base_url}}{{api_prefix}}" + path,
            "description": desc,
        },
    }
    if events:
        item["event"] = events
    if responses:
        item["response"] = responses
    return item


def post_form(name: str, path: str, desc: str, form: list, *, tests: list | None = None, prerequest: list | None = None, responses: list | None = None) -> dict:
    events = []
    if prerequest:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": prerequest}})
    if tests:
        events.append(test_lines(*tests))
    item = {
        "name": name,
        "request": {
            "method": "POST",
            "header": hdrs(include_tenant=True),
            "body": {"mode": "formdata", "formdata": form},
            "url": "{{base_url}}{{api_prefix}}" + path,
            "description": desc,
        },
    }
    if events:
        item["event"] = events
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
    "    if (j.data.tenant && j.data.tenant.tenant_id) pm.environment.set('tenant_id', j.data.tenant.tenant_id);",
    "    if (j.data.tenant && j.data.tenant.schema_name) pm.environment.set('tenant_schema', j.data.tenant.schema_name);",
    "}",
]

RESOLVE_SHIPMENT_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "if (j.data && j.data.items && j.data.items[0]) {",
    "    pm.environment.set('shipment_id', j.data.items[0].job_id);",
    "    pm.environment.set('last_job_type', 'shipment');",
    "}",
]

RESOLVE_MOVEMENT_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "if (j.data && j.data.items && j.data.items[0]) {",
    "    pm.environment.set('movement_id', j.data.items[0].job_id);",
    "    pm.environment.set('last_job_type', 'movement');",
    "}",
]

DETAIL_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "pm.test('snapshot present', () => pm.expect(j.data.snapshot).to.be.an('object'));",
    "const s = j.data.snapshot;",
    "if (s.job_id) pm.environment.set('shipment_id', s.job_id);",
]

ACTIONS_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "const aa = j.data.allowed_actions;",
    "pm.test('allowed_actions block', () => pm.expect(aa).to.have.property('actions');",
    "if (aa.primary_action && aa.primary_action.action_id) {",
    "    pm.environment.set('action_id', aa.primary_action.action_id);",
    "}",
    "if (aa.actions && aa.actions[0] && aa.actions[0].action_id) {",
    "    pm.environment.set('action_id', aa.actions[0].action_id);",
    "}",
]

TIMELINE_PAGE1_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "const t = j.data.timeline;",
    "pm.test('cursor pagination', () => {",
    "    pm.expect(t.pagination.mode).to.eql('cursor');",
    "    pm.expect(t.items).to.be.an('array');",
    "});",
    "if (t.pagination && t.pagination.next_cursor) {",
    "    pm.environment.set('timeline_next_cursor', t.pagination.next_cursor);",
    "}",
]

TIMELINE_PAGE2_TESTS = [
    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
    "const j = pm.response.json();",
    "pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
]

EXECUTE_TESTS = [
    "const code = pm.response.code;",
    "pm.test('HTTP 200 or 403 policy', () => pm.expect([200, 403]).to.include(code));",
    "if (code === 200) {",
    "    const j = pm.response.json();",
    "    pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "    pm.test('execution block', () => pm.expect(j.data.execution).to.have.property('log_id'));",
    "    if (j.data.execution.log_id) pm.environment.set('last_log_id', j.data.execution.log_id);",
    "    const key = pm.environment.get('idempotency_key');",
    "    if (key) pm.environment.set('saved_idempotency_key', key);",
    "}",
]

POD_TESTS = [
    "const code = pm.response.code;",
    "pm.test('HTTP 200 or validation', () => pm.expect([200, 400, 403]).to.include(code));",
    "if (code === 200) {",
    "    const j = pm.response.json();",
    "    pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "    pm.expect(j.data.operation).to.eql('upload_pod');",
    "}",
]

COD_TESTS = [
    "const code = pm.response.code;",
    "pm.test('HTTP 200 or validation', () => pm.expect([200, 400, 403]).to.include(code));",
    "if (code === 200) {",
    "    const j = pm.response.json();",
    "    pm.test('status === 1', () => pm.expect(j.status).to.eql(1));",
    "    pm.expect(j.data.operation).to.eql('collect_cod');",
    "}",
]

ERR_401 = sample("401 Unauthorized", 401, "Unauthorized", json.dumps({"status": 2, "message_key": "mobile.auth.unauthorized", "data": {"error_code": "unauthorized"}}))
ERR_403_JOBS = sample("403 Jobs denied", 403, "Forbidden", json.dumps({"status": 0, "message_key": "mobile.auth.jobs_denied", "data": {"error_code": "jobs_denied"}}))
ERR_403_EXECUTE = sample("403 Execute denied", 403, "Forbidden", json.dumps({"status": 0, "message_key": "mobile.auth.jobs_execute_denied", "data": {"error_code": "capability_denied"}}))
ERR_404 = sample("404 Job not found", 404, "Not Found", json.dumps({"status": 0, "message_key": "mobile.jobs.detail.not_found", "data": {"error_code": "job_not_found"}}))
ERR_403_ACTION = sample("403 Action not allowed", 403, "Forbidden", json.dumps({"status": 0, "message_key": "mobile.jobs.execute.not_allowed", "data": {"error_code": "action_not_allowed"}}))
ERR_400_CURSOR = sample("400 Invalid cursor", 400, "Bad Request", json.dumps({"status": 0, "message_key": "mobile.jobs.timeline.invalid_cursor", "data": {"error_code": "invalid_cursor"}}))
ERR_403_TENANT = sample("403 Tenant mismatch", 403, "Forbidden", json.dumps({"status": 0, "message_key": "mobile.auth.tenant_mismatch", "data": {"error_code": "tenant_mismatch"}}))


def main() -> None:
    collection = {
        "info": {
            "_postman_id": "c9d0e1f2-a3b4-5678-9012-jobdetail7890ab",
            "name": "IRoad Mobile Driver — Job Detail Module",
            "description": (
                "# IRoad Mobile — Job Detail Module\n\n"
                "## Prerequisites\n"
                "1. Import **IRoad Mobile Driver Job Detail — Local** environment.\n"
                "2. Set `base_url`, `email`, `password`, optional `tenant_id`.\n"
                "3. Run **Setup → Login**.\n"
                "4. Run **00 — Resolve IDs** (sets `shipment_id` / `movement_id`).\n"
                "5. Run **08 — Smoke Flows → Flow A** in Collection Runner.\n\n"
                "## Capabilities\n"
                "| Route type | Capability |\n"
                "|------------|------------|\n"
                "| GET detail / timeline / allowed-actions | `mobile.driver.jobs` |\n"
                "| POST execute / upload-pod / collect-cod | `mobile.driver.jobs.execute` |\n\n"
                "## Docs\n"
                "- `mobile_api/docs/driver_job_detail.md`\n"
                "- `mobile_api/docs/driver_job_detail_execution.md`\n"
                "- `mobile_api/docs/driver_job_timeline.md`\n"
                "- `mobile_api/docs/driver_job_pod_cod.md`\n"
                "- `postman/README-JobDetail.md`"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}]},
        "event": [prerequest_warn()],
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000"},
            {"key": "api_prefix", "value": "/api/v1/mobile"},
        ],
        "item": [],
    }

    setup = {
        "name": "Setup",
        "description": "JWT automation — run Login before all job detail calls.",
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
                        "raw": '{\n  "email": "{{email}}",\n  "password": "{{password}}",\n  "device_platform": "{{device_platform}}",\n  "device_id": "{{fcm_token}}",\n  "device_name": "{{device_name}}"\n}',
                    },
                    "url": "{{base_url}}{{api_prefix}}/driver/auth/login/",
                    "description": "**POST** · No auth · Saves `access_token`, `refresh_token`, `driver_id`, `tenant_id`.",
                },
            },
            {
                "name": "Refresh Token",
                "event": [test_lines(
                    "const j = pm.response.json();",
                    "if (j.status === 1 && j.data && j.data.access_token) pm.environment.set('access_token', j.data.access_token);",
                )],
                "request": {
                    "auth": {"type": "noauth"},
                    "method": "POST",
                    "header": [{"key": "Content-Type", "value": "application/json"}],
                    "body": {"mode": "raw", "raw": '{"refresh_token": "{{refresh_token}}"}'},
                    "url": "{{base_url}}{{api_prefix}}/driver/auth/refresh/",
                },
            },
        ],
    }

    resolve = {
        "name": "00 — Resolve IDs",
        "description": "Pick first active shipment/movement from job list into environment variables.",
        "item": [
            get_req(
                "GET Active Shipments (pick shipment_id)",
                "/driver/jobs/shipments/active/",
                "| Method | GET |\n| Capability | `mobile.driver.jobs` |\n| Sets | `shipment_id` |",
                query="page_size=5",
                tests=RESOLVE_SHIPMENT_TESTS,
            ),
            get_req(
                "GET Active Movements (pick movement_id)",
                "/driver/jobs/movements/active/",
                "| Method | GET |\n| Sets | `movement_id` |",
                query="page_size=5",
                tests=RESOLVE_MOVEMENT_TESTS,
            ),
        ],
    }

    read_detail = {
        "name": "01 — Job Detail (Read)",
        "item": [
            get_req(
                "GET Shipment Job Detail (full)",
                "/driver/jobs/shipments/{{shipment_id}}/",
                "| Method | GET |\n| URL | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/` |\n| Auth | Bearer + optional `X-Tenant-ID` |\n| Capability | `mobile.driver.jobs` |\n| Query | `include_timeline=1`, `include_actions=1` (default)",
                query="include_timeline=1&include_actions=1",
                tests=DETAIL_TESTS,
                responses=[ERR_401, ERR_403_JOBS, ERR_404],
            ),
            get_req(
                "GET Shipment Job Detail (light)",
                "/driver/jobs/shipments/{{shipment_id}}/",
                "Omit timeline + allowed-actions engine for faster load.",
                query="include_timeline=0&include_actions=0",
                tests=["pm.test('HTTP 200', () => pm.response.to.have.status(200));"],
            ),
            get_req(
                "GET Movement Job Detail",
                "/driver/jobs/movements/{{movement_id}}/",
                "| Method | GET |\n| URL | `/api/v1/mobile/driver/jobs/movements/{movement_id}/` |\n| Capability | `mobile.driver.jobs` |",
                query="include_timeline=1&include_actions=1",
                tests=DETAIL_TESTS,
                responses=[ERR_404],
            ),
        ],
    }

    allowed = {
        "name": "02 — Allowed Actions",
        "item": [
            get_req(
                "GET Shipment Allowed Actions",
                "/driver/jobs/shipments/{{shipment_id}}/actions/",
                "| Method | GET |\n| Engine | `operation_execution.get_allowed_actions` |\n| Sets | `action_id` from `primary_action` or first action |",
                tests=ACTIONS_TESTS,
                responses=[ERR_404, ERR_403_JOBS],
            ),
            get_req(
                "GET Movement Allowed Actions",
                "/driver/jobs/movements/{{movement_id}}/actions/",
                "| Method | GET |\n| Capability | `mobile.driver.jobs` |",
                tests=ACTIONS_TESTS,
            ),
        ],
    }

    timeline = {
        "name": "03 — Timeline (cursor)",
        "item": [
            get_req(
                "GET Shipment Timeline — page 1",
                "/driver/jobs/shipments/{{shipment_id}}/timeline/",
                "| Method | GET |\n| Query | `page_size` (default 20, max 50) |\n| Pagination | cursor only — **no offset** |\n| Sets | `timeline_next_cursor` |",
                query="page_size={{timeline_page_size}}",
                tests=TIMELINE_PAGE1_TESTS,
            ),
            get_req(
                "GET Shipment Timeline — page 2 (cursor)",
                "/driver/jobs/shipments/{{shipment_id}}/timeline/",
                "Pass opaque `cursor` from page 1 `pagination.next_cursor`.",
                query="page_size={{timeline_page_size}}&cursor={{timeline_next_cursor}}",
                tests=TIMELINE_PAGE2_TESTS,
            ),
            get_req(
                "GET Movement Timeline — page 1",
                "/driver/jobs/movements/{{movement_id}}/timeline/",
                "| Method | GET |\n| Capability | `mobile.driver.jobs` |",
                query="page_size={{timeline_page_size}}",
                tests=TIMELINE_PAGE1_TESTS,
            ),
            get_req(
                "GET Timeline — invalid cursor (400)",
                "/driver/jobs/shipments/{{shipment_id}}/timeline/",
                "Expect `invalid_cursor` when cursor token is malformed.",
                query="cursor=not-a-valid-cursor-token",
                tests=[
                    "pm.test('HTTP 400', () => pm.response.to.have.status(400));",
                    "const j = pm.response.json();",
                    "pm.test('invalid_cursor', () => pm.expect(j.data.error_code || j.message_key).to.be.ok);",
                ],
                responses=[ERR_400_CURSOR],
            ),
        ],
    }

    execute_body = (
        '{\n'
        '  "action_id": "{{action_id}}",\n'
        '  "idempotency_key": "{{idempotency_key}}",\n'
        '  "source_ref": "{{source_ref}}",\n'
        '  "notes": "Postman execute — GPS captured",\n'
        '  "latitude": "{{sample_latitude}}",\n'
        '  "longitude": "{{sample_longitude}}",\n'
        '  "map_link": "{{sample_map_link}}"\n'
        '}'
    )

    execute = {
        "name": "04 — Execute Action",
        "description": "Capability: `mobile.driver.jobs.execute`. Run **02 — Allowed Actions** first to set `action_id`.",
        "item": [
            post_json(
                "POST Shipment Execute Action (JSON + GPS)",
                "/driver/jobs/shipments/{{shipment_id}}/actions/execute/",
                "| Method | POST |\n| Content-Type | application/json |\n| Idempotency | `idempotency_key` + `source_ref` auto-generated in pre-request |\n| GPS | Riyadh example coordinates |",
                execute_body,
                prerequest=prerequest_idempotency()["script"]["exec"],
                tests=EXECUTE_TESTS,
                responses=[ERR_403_EXECUTE, ERR_403_ACTION, ERR_404],
            ),
            post_json(
                "POST Shipment Execute — idempotency replay",
                "/driver/jobs/shipments/{{shipment_id}}/actions/execute/",
                "Re-send **same** `idempotency_key` (disable pre-request or copy saved key). Expect `reused_existing: true`.",
                execute_body.replace("{{idempotency_key}}", "{{saved_idempotency_key}}"),
                tests=[
                    "pm.test('HTTP 200', () => pm.response.to.have.status(200));",
                    "const j = pm.response.json();",
                    "if (j.data && j.data.execution) {",
                    "    pm.test('reused_existing true', () => pm.expect(j.data.execution.reused_existing).to.eql(true));",
                    "}",
                ],
            ),
            post_form(
                "POST Shipment Execute (multipart + media_file)",
                "/driver/jobs/shipments/{{shipment_id}}/actions/execute/",
                "Multipart execute when action requires photo proof.\n\nSelect a file for `media_file` in Postman.",
                [
                    {"key": "action_id", "value": "{{action_id}}", "type": "text"},
                    {"key": "idempotency_key", "value": "{{idempotency_key}}", "type": "text"},
                    {"key": "notes", "value": "POD photo via Postman", "type": "text"},
                    {"key": "latitude", "value": "{{sample_latitude}}", "type": "text"},
                    {"key": "longitude", "value": "{{sample_longitude}}", "type": "text"},
                    {"key": "media_file", "type": "file", "src": [], "description": "Attach image file"},
                    {"key": "media_type", "value": "photo", "type": "text"},
                ],
                prerequest=prerequest_idempotency()["script"]["exec"],
                tests=EXECUTE_TESTS,
            ),
            post_json(
                "POST Movement Execute Action (JSON)",
                "/driver/jobs/movements/{{movement_id}}/actions/execute/",
                "| Method | POST |\n| URL | `/movements/{movement_id}/actions/execute/` |",
                execute_body,
                prerequest=prerequest_idempotency()["script"]["exec"],
                tests=EXECUTE_TESTS,
            ),
            post_json(
                "POST Execute — invalid action_id (400)",
                "/driver/jobs/shipments/{{shipment_id}}/actions/execute/",
                "Tampered / unknown action UUID.",
                json.dumps({
                    "action_id": "00000000-0000-0000-0000-000000000099",
                    "idempotency_key": "{{idempotency_key}}",
                    "latitude": "{{sample_latitude}}",
                    "longitude": "{{sample_longitude}}",
                }),
                prerequest=prerequest_idempotency()["script"]["exec"],
                tests=["pm.test('HTTP 400 or 403', () => pm.expect([400, 403]).to.include(pm.response.code));"],
            ),
        ],
    }

    pod = {
        "name": "05 — Upload POD",
        "item": [
            post_form(
                "POST Upload POD (multipart)",
                "/driver/jobs/shipments/{{shipment_id}}/upload-pod/",
                "| Method | POST |\n| Capability | `mobile.driver.jobs.execute` |\n| Resolves | Action 7 / Upload POD from Action Master |\n| Required | `media_file` + GPS when compliance requires |\n\nAttach a JPEG/PNG to `media_file`.",
                [
                    {"key": "idempotency_key", "value": "{{idempotency_key}}", "type": "text"},
                    {"key": "source_ref", "value": "{{source_ref}}", "type": "text"},
                    {"key": "notes", "value": "POD upload from Postman", "type": "text"},
                    {"key": "latitude", "value": "{{sample_latitude}}", "type": "text"},
                    {"key": "longitude", "value": "{{sample_longitude}}", "type": "text"},
                    {"key": "map_link", "value": "{{sample_map_link}}", "type": "text"},
                    {"key": "media_file", "type": "file", "src": [], "description": "POD image (required)"},
                ],
                prerequest=prerequest_idempotency()["script"]["exec"],
                tests=POD_TESTS,
                responses=[ERR_403_EXECUTE, ERR_404],
            ),
        ],
    }

    cod = {
        "name": "06 — Collect COD",
        "item": [
            post_json(
                "POST Collect COD (JSON + GPS + amount)",
                "/driver/jobs/shipments/{{shipment_id}}/collect-cod/",
                "| Method | POST |\n| Capability | `mobile.driver.jobs.execute` |\n| Resolves | Action 9 / Collect Payment |\n| Body | `cod_amount` optional — defaults to shipment COD |",
                '{\n'
                '  "idempotency_key": "{{idempotency_key}}",\n'
                '  "source_ref": "{{source_ref}}",\n'
                '  "notes": "COD collected via Postman",\n'
                '  "latitude": "{{sample_latitude}}",\n'
                '  "longitude": "{{sample_longitude}}",\n'
                '  "map_link": "{{sample_map_link}}",\n'
                '  "cod_amount": "{{sample_cod_amount}}"\n'
                '}',
                prerequest=prerequest_idempotency()["script"]["exec"],
                tests=COD_TESTS,
            ),
        ],
    }

    errors = {
        "name": "07 — Error & Security Flows",
        "item": [
            {
                "name": "GET Detail — no JWT (401)",
                "request": {
                    "auth": {"type": "noauth"},
                    "method": "GET",
                    "header": [{"key": "Accept-Language", "value": "{{accept_language}}"}],
                    "url": "{{base_url}}{{api_prefix}}/driver/jobs/shipments/{{shipment_id}}/",
                },
                "event": [test_lines("pm.test('HTTP 401', () => pm.response.to.have.status(401));")],
                "response": [ERR_401],
            },
            {
                "name": "GET Detail — wrong tenant header (403)",
                "request": {
                    "method": "GET",
                    "header": [
                        {"key": "Authorization", "value": "Bearer {{access_token}}"},
                        {"key": "X-Tenant-ID", "value": "{{wrong_tenant_id}}"},
                    ],
                    "url": "{{base_url}}{{api_prefix}}/driver/jobs/shipments/{{shipment_id}}/",
                    "description": "JWT tenant must match `X-Tenant-ID` when hint is sent.",
                },
                "event": [test_lines("pm.test('HTTP 403', () => pm.response.to.have.status(403));")],
                "response": [ERR_403_TENANT],
            },
            get_req(
                "GET Detail — foreign shipment (404 IDOR)",
                "/driver/jobs/shipments/{{foreign_shipment_id}}/",
                "Shipment UUID not owned by authenticated driver.",
                tests=[
                    "pm.test('HTTP 404', () => pm.response.to.have.status(404));",
                    "const j = pm.response.json();",
                    "pm.test('job_not_found', () => pm.expect(j.message_key || j.data.error_code).to.be.ok);",
                ],
                responses=[ERR_404],
            ),
            get_req(
                "GET Allowed Actions — foreign shipment (404)",
                "/driver/jobs/shipments/{{foreign_shipment_id}}/actions/",
                "Ownership guard — driver cannot read another driver's job.",
                tests=["pm.test('HTTP 404', () => pm.response.to.have.status(404));"],
            ),
            post_json(
                "POST Execute — foreign shipment (404)",
                "/driver/jobs/shipments/{{foreign_shipment_id}}/actions/execute/",
                "IDOR attempt on execute route.",
                execute_body,
                tests=["pm.test('HTTP 404', () => pm.response.to.have.status(404));"],
            ),
        ],
    }

    smoke = {
        "name": "08 — Smoke Flows (Collection Runner)",
        "description": "Run folder in order after Login. Mutating steps may change tenant data — use a test driver.",
        "item": [
            {
                "name": "Flow A — Read + Timeline + Actions",
                "item": [
                    get_req("1 Pick active shipment", "/driver/jobs/shipments/active/", "Run Setup → Login before this flow.", query="page_size=1", tests=RESOLVE_SHIPMENT_TESTS),
                    get_req("2 Shipment detail", "/driver/jobs/shipments/{{shipment_id}}/", "", query="include_timeline=0&include_actions=0", tests=DETAIL_TESTS),
                    get_req("3 Allowed actions", "/driver/jobs/shipments/{{shipment_id}}/actions/", "", tests=ACTIONS_TESTS),
                    get_req("4 Timeline page 1", "/driver/jobs/shipments/{{shipment_id}}/timeline/", "", query="page_size=10", tests=TIMELINE_PAGE1_TESTS),
                    get_req("5 Timeline page 2", "/driver/jobs/shipments/{{shipment_id}}/timeline/", "", query="page_size=10&cursor={{timeline_next_cursor}}", tests=TIMELINE_PAGE2_TESTS),
                ],
            },
            {
                "name": "Flow B — Execute + POD + COD (mutating)",
                "description": "**Warning:** creates action logs. Requires valid `action_id` and job state.",
                "item": [
                    get_req("1 Resolve shipment", "/driver/jobs/shipments/active/", "", query="page_size=1", tests=RESOLVE_SHIPMENT_TESTS),
                    get_req("2 Allowed actions", "/driver/jobs/shipments/{{shipment_id}}/actions/", "", tests=ACTIONS_TESTS),
                    post_json(
                        "3 Execute primary action",
                        "/driver/jobs/shipments/{{shipment_id}}/actions/execute/",
                        "",
                        execute_body,
                        prerequest=prerequest_idempotency()["script"]["exec"],
                        tests=EXECUTE_TESTS,
                    ),
                ],
            },
        ],
    }

    collection["item"] = [setup, resolve, read_detail, allowed, timeline, execute, pod, cod, errors, smoke]

    env = {
        "id": "d0e1f2a3-b4c5-6789-0123-jobdetailenv01",
        "name": "IRoad Mobile Driver Job Detail — Local",
        "values": [
            {"key": "base_url", "value": "http://127.0.0.1:8000", "type": "default", "enabled": True},
            {"key": "api_prefix", "value": "/api/v1/mobile", "type": "default", "enabled": True},
            {"key": "email", "value": "driver@example.com", "type": "default", "enabled": True},
            {"key": "password", "value": "Password@123", "type": "secret", "enabled": True},
            {"key": "access_token", "value": "", "type": "secret", "enabled": True},
            {"key": "refresh_token", "value": "", "type": "secret", "enabled": True},
            {"key": "accept_language", "value": "en", "type": "default", "enabled": True},
            {"key": "tenant_id", "value": "", "type": "default", "enabled": True, "description": "Set by Login or manually (registry UUID or schema_name)"},
            {"key": "tenant_schema", "value": "", "type": "default", "enabled": True},
            {"key": "driver_id", "value": "", "type": "default", "enabled": True},
            {"key": "device_platform", "value": "Android", "type": "default", "enabled": True},
            {"key": "device_name", "value": "Postman", "type": "default", "enabled": True},
            {"key": "fcm_token", "value": "", "type": "secret", "enabled": True},
            {"key": "shipment_id", "value": "", "type": "default", "enabled": True, "description": "From Resolve IDs or detail response"},
            {"key": "movement_id", "value": "", "type": "default", "enabled": True},
            {"key": "action_id", "value": "", "type": "default", "enabled": True, "description": "From GET allowed-actions"},
            {"key": "foreign_shipment_id", "value": "00000000-0000-0000-0000-000000000099", "type": "default", "enabled": True},
            {"key": "wrong_tenant_id", "value": "wrong-tenant-schema", "type": "default", "enabled": True},
            {"key": "timeline_page_size", "value": "20", "type": "default", "enabled": True},
            {"key": "timeline_next_cursor", "value": "", "type": "default", "enabled": True},
            {"key": "idempotency_key", "value": "", "type": "default", "enabled": True},
            {"key": "saved_idempotency_key", "value": "", "type": "default", "enabled": True, "description": "Copy from last execute pre-request for replay test"},
            {"key": "source_ref", "value": "", "type": "default", "enabled": True},
            {"key": "sample_latitude", "value": "24.7136", "type": "default", "enabled": True, "description": "Riyadh GPS example"},
            {"key": "sample_longitude", "value": "46.6753", "type": "default", "enabled": True},
            {"key": "sample_map_link", "value": "https://maps.google.com/?q=24.7136,46.6753", "type": "default", "enabled": True},
            {"key": "sample_cod_amount", "value": "150.00", "type": "default", "enabled": True},
            {"key": "last_log_id", "value": "", "type": "default", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": "2026-05-21T12:00:00.000Z",
        "_postman_exported_using": "Cursor",
    }

    root = os.path.dirname(__file__)
    coll_path = os.path.join(root, "IRoad-Mobile-Driver-JobDetail.postman_collection.json")
    env_path = os.path.join(root, "IRoad-Mobile-Driver-JobDetail.postman_environment.json")
    with open(coll_path, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent="\t", ensure_ascii=False)
    with open(env_path, "w", encoding="utf-8") as f:
        json.dump(env, f, indent="\t", ensure_ascii=False)

    def count_items(items):
        n = 0
        for it in items:
            if "request" in it:
                n += 1
            if "item" in it:
                n += count_items(it["item"])
        return n

    print(f"Wrote {coll_path} ({count_items(collection['item'])} requests)")
    print(f"Wrote {env_path}")


if __name__ == "__main__":
    main()
