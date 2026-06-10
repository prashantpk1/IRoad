#!/usr/bin/env python3
"""Generate IRoute_POD_Branching_Flow_Collection.json"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).with_name("IRoute_POD_Branching_Flow_Collection.json")
ENV_OUT = Path(__file__).with_name("IRoute-POD-Branching-Flow.postman_environment.json")

HELPERS = """
function irouteSaveSync(data) {
  if (!data || !data.sync_metadata) return;
  var sm = data.sync_metadata;
  pm.collectionVariables.set('content_hash', sm.content_hash || '');
  pm.collectionVariables.set('workflow_version', sm.workflow_version || '');
  pm.environment.set('content_hash', sm.content_hash || '');
  pm.environment.set('workflow_version', sm.workflow_version || '');
}
function irouteSavePodSync(data) {
  if (!data) return;
  pm.collectionVariables.set('pod_content_hash', data.content_hash || '');
  pm.collectionVariables.set('pod_workflow_version', data.workflow_version || '');
  pm.environment.set('pod_content_hash', data.content_hash || '');
  pm.environment.set('pod_workflow_version', data.workflow_version || '');
}
function irouteSaveJobIds(data) {
  var job = data.job || {};
  var sid = job.job_id || data.shipment_id || '';
  if (sid) {
    pm.collectionVariables.set('shipment_id', sid);
    pm.collectionVariables.set('job_id', sid);
    pm.collectionVariables.set('job_type', job.job_type || 'shipment');
    pm.environment.set('shipment_id', sid);
    pm.environment.set('job_id', sid);
    pm.environment.set('job_type', job.job_type || 'shipment');
  }
  if (job.job_no) {
    pm.collectionVariables.set('shipment_no', job.job_no);
    pm.environment.set('shipment_no', job.job_no);
  }
}
function irouteSaveBranchState(data) {
  var pod = data.pod_cod || {};
  var hint = data.next_action_hint || {};
  var hard = pod.hard_pod_pending === true || (pod.hard_copy_confirmation || {}).required === true;
  var branch = hard ? 'hard_pod' : 'digital_only';
  pm.collectionVariables.set('hard_pod_required', hard ? 'true' : 'false');
  pm.environment.set('hard_pod_required', hard ? 'true' : 'false');
  pm.collectionVariables.set('pod_branch', branch);
  pm.environment.set('pod_branch', branch);
  pm.collectionVariables.set('next_action_code', String(hint.action_code || '').toUpperCase());
  pm.environment.set('next_action_code', String(hint.action_code || '').toUpperCase());
}
function irouteAssertToken() {
  var t = pm.variables.get('access_token') || '';
  if (!t || String(t).indexOf('{{') >= 0) throw new Error('Run 01 Login first.');
}
function irouteLogHint(hint, label) {
  hint = hint || {};
  console.log('=== ' + (label || 'NEXT ACTION HINT') + ' ===');
  console.log('action:', hint.action, '| screen:', hint.screen, '| code:', hint.action_code);
  console.log('capture_mode:', hint.capture_mode, '| reason:', hint.reason);
  console.log('job_closed:', hint.job_closed);
}
""".strip()

EVAL = "eval(pm.collectionVariables.get('_iroute_helpers') || '');"

DESCRIPTION = """# IRoute POD Branching Flow (Digital + Video + Hard POD)

Manual E2E test for driver mobile POD workflows with **automatic branch detection after A7**.

## Import
1. `IRoute_POD_Branching_Flow_Collection.json`
2. `IRoute-POD-Branching-Flow.postman_environment.json`
3. Set `driver_email`, `driver_password`, `shipment_id` (optional — dashboard fills it)

## Branching rules (after A7 execute)

| Shipment type | After A7 execute | Next step |
|---------------|------------------|-----------|
| **Digital / Soft POD** (no hard copy) | `next_action_hint` → **A8** | Folder **04A** |
| **Hard POD + DN** | `next_action_hint` → **A7H** confirmation (no camera) | Folder **04B** then A8 |

```
Without Hard POD:  A7 execute → A8
With Hard POD+DN:  A7 execute → A7H confirmation page → A8
```

## Run order
1. **00 Setup** — Login, Dashboard, Job Detail
2. **01 Workflow** — A1–A6 (skip done steps)
3. **02 Digital POD** — Sync → Capture (photo+signature+video) → Execute A7
4. **03 Branch Check** — reads `hard_pod_required` + `next_action_hint`
5. **04A Digital only** OR **04B Hard POD** — run ONE branch
6. **05 Close** — A8 → A9 (COD) → A10

## Attach files (Postman Body → form-data)
- **A4**: 2 photos
- **POD Capture**: photo + signature + MP4 video (≤15s) on `media[0/1/2][file_ref]`
"""


def _auth_header():
    return [{"key": "Authorization", "value": "Bearer {{access_token}}"}]


def _json_headers():
    return _auth_header() + [{"key": "Content-Type", "value": "application/json"}]


def _event_prerequest(extra: list[str] | None = None):
    lines = [EVAL] + (extra or [])
    return [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": lines}}]


def _event_test(exec_lines: list[str]):
    return [{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL] + exec_lines}}]


def _req(name: str, method: str, url: str, *, body=None, description: str = "", events=None):
    r = {"name": name, "request": {"method": method, "header": _auth_header(), "url": url}}
    if body is not None:
        r["request"]["body"] = body
    if description:
        r["request"]["description"] = description
    if events:
        r["event"] = events
    return r


def _execute_body(action: str, extra_fields: str = ""):
    raw = (
        '{\n  "client_action_id": "' + action.lower() + '-{{$guid}}",\n'
        '  "workflow_version": "{{workflow_version}}",\n'
        '  "content_hash": "{{content_hash}}",\n'
        '  "latitude": 21.3891,\n  "longitude": 39.8579,\n'
        '  "notes": "' + action + ' — {{shipment_no}}"'
    )
    if extra_fields:
        raw += ",\n  " + extra_fields
    raw += "\n}"
    return {"mode": "raw", "raw": raw, "options": {"raw": {"language": "json"}}}


def _sync_test(action_label: str = ""):
    return [
        "var resp = pm.response.json();",
        "pm.test('HTTP OK', function () { pm.expect([200, 201]).to.include(pm.response.code); });",
        "if (resp.status === 1 && resp.data) { irouteSaveSync(resp.data); }",
        "var hint = (resp.data || {}).next_action_hint;",
        "if (hint) { irouteLogHint(hint, '" + action_label + "'); }",
    ]


def _folder(name: str, description: str, items: list):
    return {"name": name, "description": description, "item": items}


# --- Build collection ---
collection = {
    "info": {
        "_postman_id": str(uuid.uuid4()),
        "name": "IRoute — POD Branching Flow (Digital + Video + Hard)",
        "description": DESCRIPTION,
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "variable": [
        {"key": "base_url", "value": "http://127.0.0.1:8001/api/v1/mobile"},
        {"key": "_iroute_helpers", "value": HELPERS},
        {"key": "driver_email", "value": ""},
        {"key": "driver_password", "value": ""},
        {"key": "driver_extension", "value": "+966"},
        {"key": "driver_phone", "value": ""},
        {"key": "access_token", "value": ""},
        {"key": "refresh_token", "value": ""},
        {"key": "shipment_id", "value": ""},
        {"key": "job_id", "value": ""},
        {"key": "job_type", "value": "shipment"},
        {"key": "shipment_no", "value": ""},
        {"key": "content_hash", "value": ""},
        {"key": "workflow_version", "value": ""},
        {"key": "pod_content_hash", "value": ""},
        {"key": "pod_workflow_version", "value": ""},
        {"key": "capture_bundle_id", "value": ""},
        {"key": "pod_video_duration_seconds", "value": "8"},
        {"key": "hard_pod_required", "value": ""},
        {"key": "pod_branch", "value": ""},
        {"key": "next_action_code", "value": ""},
        {"key": "mobile_cod_amount", "value": ""},
        {"key": "hard_pod_confirmed_pages_json", "value": "[]"},
        {"key": "hard_pod_custody_submission_id", "value": ""},
        {"key": "hard_pod_client_submission_id", "value": ""},
        {"key": "hard_pod_receiver_name", "value": "Receiver Name"},
        {"key": "hard_pod_receiver_contact", "value": "0500000000"},
        {"key": "hard_pod_handoff_notes", "value": "Hard copy DN collected"},
        {"key": "document_ref_no", "value": ""},
    ],
    "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": [EVAL]}}],
    "item": [],
}

BASE = "{{base_url}}"

# 00 Setup
setup = _folder(
    "00 — Setup",
    "Login and resolve job. Run Job Detail before any execute.",
    [
        _req(
            "01 — Login (Email)",
            "POST",
            f"{BASE}/driver/auth/login/",
            body={
                "mode": "raw",
                "raw": '{\n  "email": "{{driver_email}}",\n  "password": "{{driver_password}}"\n}',
                "options": {"raw": {"language": "json"}},
            },
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            "var r = pm.response.json();",
                            "if (r.status === 1 && r.data && r.data.access_token) {",
                            "  pm.collectionVariables.set('access_token', r.data.access_token);",
                            "  pm.environment.set('access_token', r.data.access_token);",
                            "  pm.test('Login OK', function () { pm.expect(r.status).to.eql(1); });",
                            "} else { pm.test('Login failed', function () { pm.expect.fail(r.message); }); }",
                        ],
                    },
                }
            ],
        ),
        _req(
            "02 — Dashboard",
            "GET",
            f"{BASE}/driver/dashboard/",
            events=[
                _event_prerequest(["irouteAssertToken();"])[0],
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                            "var job = (pm.response.json().data || {}).active_job;",
                            "if (job && job.job_id) {",
                            "  pm.collectionVariables.set('job_id', job.job_id);",
                            "  pm.collectionVariables.set('shipment_id', job.job_id);",
                            "  pm.environment.set('job_id', job.job_id);",
                            "  pm.environment.set('shipment_id', job.job_id);",
                            "  console.log('Active job:', job.job_no || job.job_id);",
                            "}",
                        ],
                    },
                },
            ],
        ),
        _req(
            "03 — Job Detail",
            "GET",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/",
            events=[
                _event_prerequest(["irouteAssertToken();"])[0],
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                            "var data = pm.response.json().data || {};",
                            "irouteSaveJobIds(data);",
                            "irouteSaveSync(data);",
                            "irouteSaveBranchState(data);",
                            "irouteLogHint(data.next_action_hint, 'JOB DETAIL');",
                            "var pod = data.pod_cod || {};",
                            "console.log('pod_type/shipment:', (data.job || {}).pod_type);",
                            "console.log('hard_pod_pending:', pod.hard_pod_pending);",
                        ],
                    },
                },
            ],
        ),
    ],
)

# 01 Workflow A1-A6
workflow_actions = [
    ("04", "A1", "Start job"),
    ("05", "A2", "Pickup arrival"),
    ("06", "A3", "Start loading"),
    ("07", "A4", "Confirm loaded — attach 2 photos (form-data in Job Flow collection pattern; use JSON GPS-only skip if already done)"),
    ("08", "A5", "Depart in transit"),
    ("09", "A6", "Delivery arrival"),
]
workflow_items = []
for num, code, note in workflow_actions:
    if code == "A4":
        continue  # A4 needs multipart — separate item
    workflow_items.append(
        _req(
            f"{num} — Execute {code}",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/{code}/execute/",
            body=_execute_body(code),
            description=note,
            events=[{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL] + _sync_test(code)}}],
        )
    )

workflow_items.insert(
    3,
    _req(
        "07 — Execute A4 (2 photos — form-data)",
        "POST",
        f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A4/execute/",
        body={
            "mode": "formdata",
            "formdata": [
                {"key": "client_action_id", "value": "a4-{{$guid}}", "type": "text"},
                {"key": "workflow_version", "value": "{{workflow_version}}", "type": "text"},
                {"key": "content_hash", "value": "{{content_hash}}", "type": "text"},
                {"key": "latitude", "value": "21.4858", "type": "text"},
                {"key": "longitude", "value": "39.1925", "type": "text"},
                {"key": "notes", "value": "Confirm loaded", "type": "text"},
                {"key": "media[0][media_type]", "value": "photo", "type": "text"},
                {"key": "media[0][file_ref]", "type": "file", "src": []},
                {"key": "media[1][media_type]", "value": "photo", "type": "text"},
                {"key": "media[1][file_ref]", "type": "file", "src": []},
            ],
        },
        description="Attach 2 JPG/PNG on media[0] and media[1] file rows.",
        events=[{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL] + _sync_test("A4")}}],
    ),
)

workflow = _folder(
    "01 — Workflow → A6",
    "Run through delivery arrival. Skip steps already done (action_not_allowed = skip).",
    workflow_items,
)

# 02 Digital POD
digital_pod = _folder(
    "02 — Digital POD (photo + signature + video → A7)",
    "Stage digital evidence then execute A7. Video required for digital POD.",
    [
        _req(
            "10a — POD Capture Sync",
            "GET",
            f"{BASE}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                            "var d = pm.response.json().data || {};",
                            "irouteSavePodSync(d);",
                            "pm.test('digital_evidence screen', function () {",
                            "  pm.expect(d.screen).to.eql('pod_capture');",
                            "  pm.expect(d.capture_mode).to.eql('digital_evidence');",
                            "});",
                        ],
                    },
                }
            ],
        ),
        _req(
            "10 — POD Capture POST (photo + signature + video)",
            "POST",
            f"{BASE}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
            body={
                "mode": "formdata",
                "formdata": [
                    {"key": "client_capture_id", "value": "pod-{{$guid}}", "type": "text"},
                    {"key": "content_hash", "value": "{{pod_content_hash}}", "type": "text"},
                    {"key": "workflow_version", "value": "{{pod_workflow_version}}", "type": "text"},
                    {"key": "pod_type", "value": "digital", "type": "text"},
                    {"key": "target_action_code", "value": "A7", "type": "text"},
                    {"key": "latitude", "value": "21.3891", "type": "text"},
                    {"key": "longitude", "value": "39.8579", "type": "text"},
                    {"key": "notes", "value": "Digital POD evidence", "type": "text"},
                    {"key": "media[0][media_type]", "value": "photo", "type": "text"},
                    {"key": "media[0][file_name]", "value": "dn-photo.jpg", "type": "text"},
                    {"key": "media[0][sort_order]", "value": "1", "type": "text"},
                    {"key": "media[0][file_ref]", "type": "file", "src": []},
                    {"key": "media[1][media_type]", "value": "signature", "type": "text"},
                    {"key": "media[1][file_name]", "value": "signature.png", "type": "text"},
                    {"key": "media[1][sort_order]", "value": "2", "type": "text"},
                    {"key": "media[1][file_ref]", "type": "file", "src": []},
                    {"key": "media[2][media_type]", "value": "video", "type": "text"},
                    {"key": "media[2][file_name]", "value": "dn-video.mp4", "type": "text"},
                    {"key": "media[2][duration_seconds]", "value": "{{pod_video_duration_seconds}}", "type": "text"},
                    {"key": "media[2][sort_order]", "value": "3", "type": "text"},
                    {"key": "media[2][file_ref]", "type": "file", "src": []},
                ],
            },
            description="Attach photo, signature, MP4 (≤15s) on media[0/1/2][file_ref].",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('HTTP 200/201', function () { pm.expect([200,201]).to.include(pm.response.code); });",
                            "var d = pm.response.json().data || {};",
                            "var b = d.capture_bundle || {};",
                            "var id = b.capture_bundle_id || d.capture_bundle_id || '';",
                            "pm.collectionVariables.set('capture_bundle_id', id);",
                            "pm.environment.set('capture_bundle_id', id);",
                            "var sum = (d.compliance || {}).summary || {};",
                            "pm.test('video staged', function () { pm.expect(sum.video_count).to.be.at.least(1); });",
                            "pm.test('execute_ready', function () { pm.expect(b.execute_ready).to.eql(true); });",
                        ],
                    },
                }
            ],
        ),
        _req(
            "10.5 — Job Detail (refresh before A7)",
            "GET",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var data = pm.response.json().data || {};",
                            "irouteSaveSync(data);",
                            "pm.test('A7 allowed', function () {",
                            "  var codes = (data.workflow.allowed_actions || []).map(function (a) { return a.action_code; });",
                            "  pm.expect(codes).to.include('A7');",
                            "});",
                        ],
                    },
                }
            ],
        ),
        _req(
            "11 — Execute A7 (digital POD)",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A7/execute/",
            body=_execute_body("A7", '"capture_bundle_id": "{{capture_bundle_id}}"'),
            description="JSON only — promotes staged bundle. No files.",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('A7 OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
                            "var data = (pm.response.json().data || {});",
                            "irouteSaveSync(data);",
                            "irouteSaveBranchState(data);",
                            "var hint = data.next_action_hint || {};",
                            "irouteLogHint(hint, 'AFTER A7');",
                            "var hard = pm.variables.get('hard_pod_required') === 'true';",
                            "if (hard) {",
                            "  pm.test('Hard POD: next is A7H confirmation (no camera)', function () {",
                            "    pm.expect(hint.action).to.eql('go_to_pod_capture');",
                            "    pm.expect(hint.capture_mode).to.eql('hard_copy_confirmation');",
                            "    pm.expect(hint.action_code).to.eql('A7H');",
                            "    pm.expect(hint.ui_mode).to.eql('hard_pod_collection_confirmation');",
                            "  });",
                            "  console.log('>>> RUN FOLDER 04B Hard POD branch');",
                            "} else {",
                            "  pm.test('Digital only: next is A8', function () {",
                            "    pm.expect(hint.action).to.eql('execute_action');",
                            "    pm.expect(hint.action_code).to.eql('A8');",
                            "    pm.expect(hint.screen).to.eql('job_detail');",
                            "  });",
                            "  console.log('>>> RUN FOLDER 04A Digital-only branch (skip 04B)');",
                            "}",
                        ],
                    },
                }
            ],
        ),
    ],
)

# 03 Branch check
branch_check = _folder(
    "03 — After A7 Branch Check",
    "Confirms which path to run. Sets `pod_branch` = hard_pod | digital_only.",
    [
        _req(
            "12 — Job Detail (branch decision)",
            "GET",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var data = pm.response.json().data || {};",
                            "irouteSaveSync(data);",
                            "irouteSaveBranchState(data);",
                            "var hint = data.next_action_hint || {};",
                            "irouteLogHint(hint, 'BRANCH CHECK');",
                            "var branch = pm.variables.get('pod_branch');",
                            "console.log('pod_branch=', branch, '| hard_pod_required=', pm.variables.get('hard_pod_required'));",
                            "if (branch === 'hard_pod') {",
                            "  pm.test('Branch: Hard POD → run folder 04B', function () {",
                            "    pm.expect(hint.action_code).to.be.oneOf(['A7H', 'A7']);",
                            "    pm.expect(hint.capture_mode || hint.ui_mode).to.satisfy(function (v) {",
                            "      return v === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation';",
                            "    });",
                            "  });",
                            "} else {",
                            "  pm.test('Branch: Digital only → run folder 04A', function () {",
                            "    pm.expect(hint.action_code).to.eql('A8');",
                            "  });",
                            "}",
                        ],
                    },
                }
            ],
        ),
    ],
)

# 04A Digital only → A8
digital_only = _folder(
    "04A — Digital POD only → A8 (skip if hard_pod_required=true)",
    "Run when after A7 next_action is A8. No A7H steps.",
    [
        _req(
            "13A — Job Detail before A8",
            "GET",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/",
            events=[
                _event_prerequest([
                    "if (pm.variables.get('hard_pod_required') === 'true') {",
                    "  console.warn('Hard POD required — skip 04A, use folder 04B instead');",
                    "}",
                ])[0],
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var data = pm.response.json().data || {};",
                            "irouteSaveSync(data);",
                            "var hint = data.next_action_hint || {};",
                            "pm.test('next is A8', function () {",
                            "  if (pm.variables.get('hard_pod_required') !== 'true') {",
                            "    pm.expect(hint.action_code).to.eql('A8');",
                            "  }",
                            "});",
                        ],
                    },
                },
            ],
        ),
        _req(
            "14A — Execute A8 (Unloading)",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A8/execute/",
            body=_execute_body("A8"),
            description="GPS + notes only. No media.",
            events=[{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL] + _sync_test("A8")}}],
        ),
    ],
)

# 04B Hard POD → A7H → A8
hard_pod = _folder(
    "04B — Hard POD + DN → A7H confirmation → A8",
    "After A7: confirmation page only (no camera). Run when hard_pod_required=true.",
    [
        _req(
            "13B — POD Capture GET (hard copy unlocked)",
            "GET",
            f"{BASE}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var d = pm.response.json().data || {};",
                            "pm.test('hard copy mode after A7', function () {",
                            "  pm.expect(d.capture_mode).to.eql('hard_copy_confirmation');",
                            "  pm.expect(d.screen).to.eql('pod_capture');",
                            "});",
                        ],
                    },
                }
            ],
        ),
        _req(
            "13C — Hard copy confirmation UI (?step=hard_copy_confirmation)",
            "GET",
            f"{BASE}/driver/jobs/shipments/{{shipment_id}}/pod/capture/?step=hard_copy_confirmation",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var d = pm.response.json().data || {};",
                            "pm.test('confirmation page — no capture UI', function () {",
                            "  pm.expect(d.ui_mode).to.eql('hard_pod_collection_confirmation');",
                            "  pm.expect(Object.keys(d.capture_ui || {}).length).to.eql(0);",
                            "  pm.expect((d.confirmation_ui || {}).screen_title).to.eql('Hard POD Collection Confirmation');",
                            "});",
                        ],
                    },
                }
            ],
        ),
        _req(
            "14B — Hard POD Documents GET",
            "GET",
            f"{BASE}/driver/jobs/shipments/{{shipment_id}}/hard-pod/documents/",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var pages = (pm.response.json().data || {}).pages || [];",
                            "pm.test('DN pages present', function () { pm.expect(pages.length).to.be.at.least(1); });",
                            "var confirmed = pages.map(function (p) {",
                            "  return { page_id: p.page_id, document_id: p.document_id, line_no: p.line_no || 1, confirmed: true };",
                            "});",
                            "var json = JSON.stringify(confirmed);",
                            "pm.collectionVariables.set('hard_pod_confirmed_pages_json', json);",
                            "pm.environment.set('hard_pod_confirmed_pages_json', json);",
                            "pm.collectionVariables.set('hard_pod_client_submission_id', 'hard-' + Date.now());",
                            "pm.environment.set('hard_pod_client_submission_id', 'hard-' + Date.now());",
                        ],
                    },
                }
            ],
        ),
        _req(
            "15B — Hard POD Submit",
            "POST",
            f"{BASE}/driver/hard-pod/submit/",
            body={
                "mode": "raw",
                "raw": (
                    '{\n  "client_submission_id": "{{hard_pod_client_submission_id}}",\n'
                    '  "shipment_id": "{{shipment_id}}",\n'
                    '  "receiver_name": "{{hard_pod_receiver_name}}",\n'
                    '  "receiver_contact": "{{hard_pod_receiver_contact}}",\n'
                    '  "handoff_notes": "{{hard_pod_handoff_notes}}",\n'
                    '  "latitude": 21.3891,\n  "longitude": 39.8579,\n'
                    '  "confirmed_pages": {{hard_pod_confirmed_pages_json}},\n'
                    '  "media": []\n}'
                ),
                "options": {"raw": {"language": "json"}},
            },
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "var sub = (pm.response.json().data || {}).custody_submission || {};",
                            "pm.collectionVariables.set('hard_pod_custody_submission_id', sub.submission_id || '');",
                            "pm.environment.set('hard_pod_custody_submission_id', sub.submission_id || '');",
                            "pm.test('custody_submission_id saved', function () { pm.expect(sub.submission_id).to.be.ok; });",
                        ],
                    },
                }
            ],
        ),
        _req(
            "15.5B — Job Detail refresh (before A7H)",
            "GET",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/",
            events=[{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL, "irouteSaveSync(pm.response.json().data || {});"]}}],
        ),
        _req(
            "16B — Execute A7H (hard copy confirmation)",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A7H/execute/",
            body=_execute_body(
                "A7H",
                '"custody_submission_id": "{{hard_pod_custody_submission_id}}",\n  '
                '"client_submission_id": "{{hard_pod_client_submission_id}}"',
            ),
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('A7H OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
                            "var data = (pm.response.json().data || {});",
                            "irouteSaveSync(data);",
                            "var hint = data.next_action_hint || {};",
                            "irouteLogHint(hint, 'AFTER A7H');",
                            "pm.test('after A7H next is A8', function () {",
                            "  pm.expect(hint.action_code).to.eql('A8');",
                            "  pm.expect(hint.action).to.eql('execute_action');",
                            "});",
                        ],
                    },
                }
            ],
        ),
        _req(
            "17B — Execute A8 (after Hard POD)",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A8/execute/",
            body=_execute_body("A8"),
            events=[{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL] + _sync_test("A8")}}],
        ),
    ],
)

# 05 Close COD
close_folder = _folder(
    "05 — COD Close (A9 → A10)",
    "Run after A8. Skip A9 if Credit order.",
    [
        _req(
            "18 — Execute A9 (COD)",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A9/execute/",
            body=_execute_body("A9", '"mobile_cod_amount": {{mobile_cod_amount}}'),
            events=[{"listen": "test", "script": {"type": "text/javascript", "exec": [EVAL] + _sync_test("A9")}}],
        ),
        _req(
            "19 — Job Detail (expect A10)",
            "GET",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/",
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "irouteSaveSync(pm.response.json().data || {});",
                            "var hint = (pm.response.json().data || {}).next_action_hint || {};",
                            "pm.test('A10 ready', function () { pm.expect(hint.action_code).to.eql('A10'); });",
                        ],
                    },
                }
            ],
        ),
        _req(
            "20 — Execute A10 (Job Closed)",
            "POST",
            f"{BASE}/driver/jobs/shipment/{{shipment_id}}/actions/A10/execute/",
            body=_execute_body("A10"),
            events=[
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            EVAL,
                            "pm.test('A10 OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
                            "var hint = (pm.response.json().data || {}).next_action_hint || {};",
                            "pm.test('job closed', function () { pm.expect(hint.job_closed).to.eql(true); });",
                        ],
                    },
                }
            ],
        ),
    ],
)

collection["item"] = [setup, workflow, digital_pod, branch_check, digital_only, hard_pod, close_folder]

OUT.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

env = {
    "id": str(uuid.uuid4()),
    "name": "IRoute POD Branching Flow",
    "values": [
        {"key": k, "value": v, "type": "secret" if "password" in k or "token" in k else "default", "enabled": True}
        for k, v in [
            ("base_url", "http://127.0.0.1:8001/api/v1/mobile"),
            ("driver_email", ""),
            ("driver_password", ""),
            ("driver_extension", "+966"),
            ("driver_phone", ""),
            ("access_token", ""),
            ("refresh_token", ""),
            ("shipment_id", ""),
            ("job_id", ""),
            ("job_type", "shipment"),
            ("shipment_no", ""),
            ("content_hash", ""),
            ("workflow_version", ""),
            ("pod_content_hash", ""),
            ("pod_workflow_version", ""),
            ("capture_bundle_id", ""),
            ("pod_video_duration_seconds", "8"),
            ("hard_pod_required", ""),
            ("pod_branch", ""),
            ("next_action_code", ""),
            ("mobile_cod_amount", ""),
            ("hard_pod_confirmed_pages_json", "[]"),
            ("hard_pod_custody_submission_id", ""),
            ("hard_pod_client_submission_id", ""),
            ("hard_pod_receiver_name", "Receiver Name"),
            ("hard_pod_receiver_contact", "0500000000"),
            ("hard_pod_handoff_notes", "Hard copy DN collected"),
            ("document_ref_no", ""),
        ]
    ],
    "_postman_variable_scope": "environment",
    "_postman_exported_at": "2026-06-10T14:00:00.000Z",
    "_postman_exported_using": "Cursor",
}
ENV_OUT.write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {OUT}")
print(f"Wrote {ENV_OUT}")
