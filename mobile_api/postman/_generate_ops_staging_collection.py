#!/usr/bin/env python3
"""Regenerate Iroad_Mobile_Driver_Ops_Staging.postman_collection.json."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).parent / 'Iroad_Mobile_Driver_Ops_Staging.postman_collection.json'

COMMON_HEADERS = [
    {'key': 'Accept', 'value': 'application/json'},
    {'key': 'Accept-Language', 'value': '{{accept_language}}'},
    {'key': 'X-Request-ID', 'value': '{{request_id}}'},
    {'key': 'X-Tenant-ID', 'value': '{{tenant_header}}'},
]

POST_HEADERS = [
    {'key': 'Content-Type', 'value': 'application/json'},
    *COMMON_HEADERS,
]

PREREQUEST = [
    "if (!pm.variables.get('request_id') || String(pm.variables.get('request_id')).indexOf('{{') >= 0) {",
    "    pm.variables.set('request_id', 'postman-' + pm.variables.replaceIn('{{$guid}}'));",
    "}",
    "const bearer = pm.variables.get('bearer_token');",
    "const access = pm.variables.get('access_token');",
    "if ((!bearer || String(bearer).indexOf('{{') >= 0) && access && String(access).indexOf('{{') < 0) {",
    "    pm.environment.set('bearer_token', access);",
    "}",
    "const schema = pm.variables.get('tenant_schema') || pm.variables.get('tenant_header');",
    "if (schema && String(schema).indexOf('{{') < 0) {",
    "    pm.environment.set('tenant_header', schema);",
    "}",
    "const tenant = pm.variables.get('tenant_header') || pm.variables.get('tenant_schema') || 'tenant_schema';",
    "const driver = pm.variables.get('driver_id') || 'driver_id';",
    "const ship = pm.variables.get('shipment_id') || 'shipment_id';",
    "pm.variables.set('hard_pod_path_prefix', `mobile_driver_uploads/${tenant}/${driver}/${ship}/hard_pod/`);",
    "pm.variables.set('payment_path_prefix', `mobile_driver_uploads/${tenant}/${driver}/${ship}/payment_collection/`);",
    "pm.variables.set('issue_path_prefix', `mobile_driver_uploads/${tenant}/${driver}/${ship}/issues/`);",
]

HARD_POD_SUBMIT = """{
  "client_submission_id": "{{hard_pod_client_submission_id}}",
  "shipment_id": "{{shipment_id}}",
  "receiver_name": "{{hard_pod_receiver_name}}",
  "receiver_contact": "{{hard_pod_receiver_contact}}",
  "handoff_notes": "{{hard_pod_handoff_notes}}",
  "latitude": {{hard_pod_latitude}},
  "longitude": {{hard_pod_longitude}},
  "media": [
    {
      "media_type": "photo",
      "file_ref": "{{hard_pod_path_prefix}}scan-001.jpg",
      "file_name": "scan-001.jpg",
      "mime_type": "image/jpeg",
      "sort_order": 1
    }
  ]
}"""

HARD_POD_REPLAY = HARD_POD_SUBMIT.replace(
    '{{hard_pod_client_submission_id}}',
    '{{hard_pod_replay_client_submission_id}}',
)

HARD_POD_WRONG_SHIPMENT = HARD_POD_SUBMIT.replace(
    '{{shipment_id}}',
    '{{foreign_shipment_id}}',
)

PAYMENT_COLLECT = """{
  "client_payment_id": "{{payment_client_payment_id}}",
  "shipment_id": "{{shipment_id}}",
  "amount": "{{payment_amount_full}}",
  "notes": "{{payment_notes}}",
  "payment_mode": "COD",
  "proof_media": [
    {
      "media_type": "photo",
      "file_ref": "{{payment_path_prefix}}proof.jpg",
      "file_name": "proof.jpg",
      "mime_type": "image/jpeg",
      "sort_order": 1
    }
  ]
}"""

PAYMENT_REPLAY = PAYMENT_COLLECT.replace(
    '{{payment_client_payment_id}}',
    '{{payment_replay_client_payment_id}}',
)

PAYMENT_DUPLICATE = PAYMENT_COLLECT.replace(
    '{{payment_client_payment_id}}',
    '{{payment_duplicate_client_payment_id}}',
)

PAYMENT_VARIANCE = PAYMENT_COLLECT.replace(
    '{{payment_amount_full}}',
    '{{payment_amount_variance}}',
)

ISSUE_DELAY = """{
  "client_issue_id": "{{issue_client_issue_id}}",
  "shipment_id": "{{shipment_id}}",
  "issue_type": "delay",
  "severity": "medium",
  "notes": "{{issue_delay_notes}}",
  "latitude": {{issue_latitude}},
  "longitude": {{issue_longitude}},
  "media": [
    {
      "media_type": "photo",
      "file_ref": "{{issue_path_prefix}}delay-traffic.jpg",
      "file_name": "delay-traffic.jpg",
      "mime_type": "image/jpeg",
      "sort_order": 1
    }
  ]
}"""

ISSUE_BREAKDOWN = """{
  "client_issue_id": "{{issue_breakdown_client_issue_id}}",
  "shipment_id": "{{shipment_id}}",
  "issue_type": "vehicle_breakdown",
  "severity": "high",
  "notes": "Engine failure — awaiting roadside assistance",
  "latitude": {{issue_latitude}},
  "longitude": {{issue_longitude}},
  "media": []
}"""

ISSUE_ESCALATION = """{
  "client_issue_id": "{{issue_escalation_client_issue_id}}",
  "shipment_id": "{{shipment_id}}",
  "issue_type": "route_blocked",
  "severity": "critical",
  "notes": "Highway closed — police diversion",
  "latitude": {{issue_latitude}},
  "longitude": {{issue_longitude}},
  "media": []
}"""

ISSUE_REPLAY = ISSUE_DELAY.replace(
    '{{issue_client_issue_id}}',
    '{{issue_replay_client_issue_id}}',
)


def _req(
    name: str,
    method: str,
    url: str,
    *,
    body: str | None = None,
    description: str = '',
    tests: list[str] | None = None,
    prerequest: list[str] | None = None,
    headers: list[dict] | None = None,
) -> dict:
    hdrs = list(headers or (POST_HEADERS if method != 'GET' else COMMON_HEADERS))
    request: dict = {
        'method': method,
        'header': hdrs,
        'url': url,
        'description': description,
    }
    if body is not None:
        request['body'] = {'mode': 'raw', 'raw': body, 'options': {'raw': {'language': 'json'}}}
    events = []
    if prerequest:
        events.append({'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': prerequest}})
    if tests:
        events.append({'listen': 'test', 'script': {'type': 'text/javascript', 'exec': tests}})
    item: dict = {'name': name, 'request': request}
    if events:
        item['event'] = events
    return item


def _folder(name: str, items: list[dict], *, description: str = '') -> dict:
    folder: dict = {'name': name, 'item': items}
    if description:
        folder['description'] = description
    return folder


TESTS_200 = [
    "pm.test('HTTP 2xx', function () { pm.expect(pm.response.code).to.be.oneOf([200, 201]); });",
    "const body = pm.response.json();",
    "pm.test('success envelope', function () { pm.expect(body.status).to.eql('success'); });",
]

TESTS_HARD_POD_LIST = TESTS_200 + [
    "const data = pm.response.json().data || {};",
    "pm.test('has items array', function () { pm.expect(data.items).to.be.an('array'); });",
]

TESTS_HARD_POD_SUBMIT = TESTS_200 + [
    "const data = pm.response.json().data || {};",
    "pm.test('custody_submission present', function () { pm.expect(data.custody_submission).to.be.an('object'); });",
    "if (data.custody_submission && data.custody_submission.client_submission_id) {",
    "    pm.environment.set('hard_pod_replay_client_submission_id', data.custody_submission.client_submission_id);",
    "}",
]

TESTS_HARD_POD_REPLAY = [
    "pm.test('HTTP 200 replay', function () { pm.response.to.have.status(200); });",
    "const sub = (pm.response.json().data || {}).custody_submission || {};",
    "pm.test('replayed flag', function () { pm.expect(sub.replayed).to.eql(true); });",
]

TESTS_PAYMENT_COLLECT = TESTS_200 + [
    "const bundle = (pm.response.json().data || {}).payment_bundle || {};",
    "pm.test('payment_bundle present', function () { pm.expect(bundle.bundle_id).to.be.ok; });",
    "if (bundle.client_payment_id) {",
    "    pm.environment.set('payment_replay_client_payment_id', bundle.client_payment_id);",
    "}",
]

TESTS_PAYMENT_REPLAY = [
    "pm.test('HTTP 200 replay', function () { pm.response.to.have.status(200); });",
    "pm.test('replayed', function () {",
    "    pm.expect((pm.response.json().data || {}).payment_bundle.replayed).to.eql(true);",
    "});",
]

TESTS_PAYMENT_VARIANCE = TESTS_200 + [
    "const recon = (pm.response.json().data || {}).reconciliation || {};",
    "pm.test('variance_detected', function () { pm.expect(recon.variance_detected).to.eql(true); });",
]

TESTS_ISSUE_REPORT = TESTS_200 + [
    "const data = pm.response.json().data || {};",
    "pm.test('issue payload', function () { pm.expect(data.issue).to.be.an('object'); });",
    "if (data.issue && data.issue.client_issue_id) {",
    "    pm.environment.set('issue_replay_client_issue_id', data.issue.client_issue_id);",
    "}",
]

TESTS_ISSUE_ESCALATION = TESTS_ISSUE_REPORT + [
    "const esc = (pm.response.json().data || {}).escalation || {};",
    "pm.test('auto-escalated state', function () {",
    "    pm.expect(['escalated', 'open']).to.include(esc.escalation_state);",
    "});",
]

TESTS_JOB_DETAIL_ISSUES = TESTS_200 + [
    "const data = pm.response.json().data || {};",
    "pm.test('operational_issues visibility', function () {",
    "    pm.expect(data).to.have.property('operational_issues');",
    "    pm.expect(data).to.have.property('unresolved_issue_count');",
    "    pm.expect(data).to.have.property('blocking_recommendation');",
    "});",
]

PREREQUEST_NEW_HARD_POD_ID = [
    "pm.environment.set('hard_pod_client_submission_id', 'hard-pod-' + pm.variables.replaceIn('{{$guid}}'));",
]

PREREQUEST_NEW_PAYMENT_ID = [
    "pm.environment.set('payment_client_payment_id', 'pay-' + pm.variables.replaceIn('{{$guid}}'));",
]

PREREQUEST_NEW_ISSUE_ID = [
    "pm.environment.set('issue_client_issue_id', 'issue-' + pm.variables.replaceIn('{{$guid}}'));",
]

PREREQUEST_NEW_BREAKDOWN_ID = [
    "pm.environment.set('issue_breakdown_client_issue_id', 'issue-bd-' + pm.variables.replaceIn('{{$guid}}'));",
]

PREREQUEST_NEW_ESCALATION_ID = [
    "pm.environment.set('issue_escalation_client_issue_id', 'issue-esc-' + pm.variables.replaceIn('{{$guid}}'));",
]

PREREQUEST_DUPLICATE_PAYMENT_ID = [
    "pm.environment.set('payment_duplicate_client_payment_id', 'pay-dup-' + pm.variables.replaceIn('{{$guid}}'));",
]

collection = {
    'info': {
        '_postman_id': str(uuid.uuid4()),
        'name': 'Iroad — Mobile Driver API (Ops Staging)',
        'description': (
            'Hard POD (list + submit), Payment Collection, and Delay/Issue Reporting.\n\n'
            '**Auth:** `Bearer {{bearer_token}}` (no login in this collection).\n'
            '**Tenant:** `X-Tenant-ID: {{tenant_header}}`.\n\n'
            'See `OPS_STAGING_SETUP.md` and `OPS_STAGING_SAMPLE_PAYLOADS.md`.'
        ),
        'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
    },
    'auth': {
        'type': 'bearer',
        'bearer': [{'key': 'token', 'value': '{{bearer_token}}', 'type': 'string'}],
    },
    'event': [
        {'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': PREREQUEST}},
    ],
    'variable': [
        {'key': 'base_url', 'value': 'http://127.0.0.1:8000/api/v1/mobile'},
        {'key': 'bearer_token', 'value': ''},
        {'key': 'tenant_header', 'value': ''},
        {'key': 'tenant_schema', 'value': ''},
        {'key': 'shipment_id', 'value': ''},
        {'key': 'driver_id', 'value': ''},
    ],
    'item': [
        _folder(
            '00 — Prerequisites',
            [
                _req(
                    '0. GET Shipment Job Detail (sync shipment + issues visibility)',
                    'GET',
                    '{{base_url}}/driver/jobs/shipment/{{shipment_id}}/',
                    description='Optional sync. After reporting issues, re-run to see `operational_issues` on Job Detail.',
                    tests=TESTS_JOB_DETAIL_ISSUES,
                ),
            ],
            description='Sync `shipment_id` from your tenant. No login — paste JWT first.',
        ),
        _folder(
            '01 — Hard POD List',
            [
                _req(
                    '1. GET Pending Hard POD list',
                    'GET',
                    '{{base_url}}/driver/hard-pod/pending/?limit={{hard_pod_list_limit}}',
                    description='Read-only queue of Hard POD shipments for the authenticated driver.',
                    tests=TESTS_HARD_POD_LIST,
                ),
            ],
            description='`GET /driver/hard-pod/pending/` — capability `mobile.driver.hard_pod`.',
        ),
        _folder(
            '02 — Hard POD Submit',
            [
                _req(
                    '1. POST Submit custody (success)',
                    'POST',
                    '{{base_url}}/driver/hard-pod/submit/',
                    body=HARD_POD_SUBMIT,
                    description='Stages custody evidence. Does not mutate workflow — Execute Action required next.',
                    tests=TESTS_HARD_POD_SUBMIT,
                    prerequest=PREREQUEST_NEW_HARD_POD_ID,
                ),
                _req(
                    '2. POST Replay submit (same client_submission_id)',
                    'POST',
                    '{{base_url}}/driver/hard-pod/submit/',
                    body=HARD_POD_REPLAY,
                    description='Idempotent replay — expect HTTP 200 and `replayed: true`.',
                    tests=TESTS_HARD_POD_REPLAY,
                ),
                _req(
                    '3. POST Wrong shipment (foreign)',
                    'POST',
                    '{{base_url}}/driver/hard-pod/submit/',
                    body=HARD_POD_WRONG_SHIPMENT,
                    description='Expect 403 `forbidden` or 404 `job_not_found` for shipment not owned by driver.',
                    tests=[
                        "pm.test('HTTP 403 or 404', function () {",
                        "    pm.expect(pm.response.code).to.be.oneOf([403, 404]);",
                        "});",
                    ],
                    prerequest=PREREQUEST_NEW_HARD_POD_ID,
                ),
                _req(
                    '4. POST Wrong driver / not Hard POD',
                    'POST',
                    '{{base_url}}/driver/hard-pod/submit/',
                    body=HARD_POD_SUBMIT.replace('{{shipment_id}}', '{{non_hard_pod_shipment_id}}'),
                    description='Use `non_hard_pod_shipment_id` (digital POD shipment) — expect `not_hard_pod_shipment` or `forbidden`.',
                    tests=[
                        "pm.test('HTTP 4xx', function () { pm.expect(pm.response.code).to.be.at.least(400); });",
                    ],
                    prerequest=PREREQUEST_NEW_HARD_POD_ID,
                ),
            ],
            description='`POST /driver/hard-pod/submit/` — prep-only custody staging.',
        ),
        _folder(
            '03 — Payment Collection',
            [
                _req(
                    '1. POST Collect COD (full amount)',
                    'POST',
                    '{{base_url}}/driver/payments/collect/',
                    body=PAYMENT_COLLECT,
                    description='Stages payment bundle for Execute Action A9. Expect 201 on first collect.',
                    tests=TESTS_PAYMENT_COLLECT,
                    prerequest=PREREQUEST_NEW_PAYMENT_ID,
                ),
                _req(
                    '2. POST Replay payment (same client_payment_id)',
                    'POST',
                    '{{base_url}}/driver/payments/collect/',
                    body=PAYMENT_REPLAY,
                    description='Idempotent replay — HTTP 200, `replayed: true`.',
                    tests=TESTS_PAYMENT_REPLAY,
                ),
                _req(
                    '3. POST Duplicate payment (new key, same shipment)',
                    'POST',
                    '{{base_url}}/driver/payments/collect/',
                    body=PAYMENT_DUPLICATE,
                    description='Run **after** step 1 on same shipment with a **new** `client_payment_id` — expect `duplicate_payment` 409/400.',
                    tests=[
                        "pm.test('duplicate rejected', function () {",
                        "    pm.expect(pm.response.code).to.be.at.least(400);",
                        "    const err = pm.response.json().error || pm.response.json();",
                        "    const code = err.code || (err.errors && err.errors[0] && err.errors[0].code) || '';",
                        "    if (code) pm.expect(String(code)).to.include('duplicate');",
                        "});",
                    ],
                    prerequest=PREREQUEST_DUPLICATE_PAYMENT_ID,
                ),
                _req(
                    '4. POST Collect with variance (partial amount)',
                    'POST',
                    '{{base_url}}/driver/payments/collect/',
                    body=PAYMENT_VARIANCE,
                    description='Use a **fresh** COD shipment. `payment_amount_variance` < expected — stages with `variance_detected: true`.',
                    tests=TESTS_PAYMENT_VARIANCE,
                    prerequest=PREREQUEST_NEW_PAYMENT_ID,
                ),
                _req(
                    '5. POST Wrong tenant header',
                    'POST',
                    '{{base_url}}/driver/payments/collect/',
                    body=PAYMENT_COLLECT,
                    description='Sends mismatched `X-Tenant-ID` — expect 403 `tenant_mismatch`.',
                    headers=[
                        {'key': 'Content-Type', 'value': 'application/json'},
                        {'key': 'Accept', 'value': 'application/json'},
                        {'key': 'Accept-Language', 'value': '{{accept_language}}'},
                        {'key': 'X-Request-ID', 'value': '{{request_id}}'},
                        {'key': 'X-Tenant-ID', 'value': '{{wrong_tenant_header}}'},
                    ],
                    tests=[
                        "pm.test('tenant mismatch', function () {",
                        "    pm.expect(pm.response.code).to.be.oneOf([403, 400]);",
                        "});",
                    ],
                    prerequest=PREREQUEST_NEW_PAYMENT_ID,
                ),
            ],
            description='`POST /driver/payments/collect/` — capability `mobile.driver.payment_collection`.',
        ),
        _folder(
            '04 — Delay / Issue Reporting',
            [
                _req(
                    '1. POST Delay report',
                    'POST',
                    '{{base_url}}/driver/issues/report/',
                    body=ISSUE_DELAY,
                    description='`issue_type: delay` — prep-only operational exception.',
                    tests=TESTS_ISSUE_REPORT,
                    prerequest=PREREQUEST_NEW_ISSUE_ID,
                ),
                _req(
                    '2. POST Vehicle breakdown report',
                    'POST',
                    '{{base_url}}/driver/issues/report/',
                    body=ISSUE_BREAKDOWN,
                    description='High-impact type — `blocking_recommended` likely true.',
                    tests=TESTS_ISSUE_REPORT,
                    prerequest=PREREQUEST_NEW_BREAKDOWN_ID,
                ),
                _req(
                    '3. POST Escalation flow (critical route_blocked)',
                    'POST',
                    '{{base_url}}/driver/issues/report/',
                    body=ISSUE_ESCALATION,
                    description='Critical severity + high-impact type triggers auto-escalation in response.',
                    tests=TESTS_ISSUE_ESCALATION,
                    prerequest=PREREQUEST_NEW_ESCALATION_ID,
                ),
                _req(
                    '4. POST Issue replay (same client_issue_id)',
                    'POST',
                    '{{base_url}}/driver/issues/report/',
                    body=ISSUE_REPLAY,
                    description='Replay delay report — HTTP 200, `replayed: true`.',
                    tests=[
                        "pm.test('HTTP 200 replay', function () { pm.response.to.have.status(200); });",
                        "pm.test('replayed', function () {",
                        "    pm.expect((pm.response.json().data || {}).issue.replayed).to.eql(true);",
                        "});",
                    ],
                ),
                _req(
                    '5. GET Job Detail — unresolved issues visibility',
                    'GET',
                    '{{base_url}}/driver/jobs/shipment/{{shipment_id}}/',
                    description='After reporting issues: `operational_issues`, `unresolved_issue_count`, `blocking_recommendation`, timeline issue milestones.',
                    tests=TESTS_JOB_DETAIL_ISSUES + [
                        "const data = pm.response.json().data || {};",
                        "pm.test('unresolved count >= 1 after reports', function () {",
                        "    if (pm.environment.get('issue_client_issue_id')) {",
                        "        pm.expect(data.unresolved_issue_count).to.be.at.least(1);",
                        "    }",
                        "});",
                    ],
                ),
            ],
            description='`POST /driver/issues/report/` — capability `mobile.driver.issues`.',
        ),
    ],
}

OUT.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(f'Wrote {OUT}')
