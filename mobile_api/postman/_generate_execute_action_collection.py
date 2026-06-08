#!/usr/bin/env python3
"""Regenerate Iroad_Mobile_Driver_Execute_Action.postman_collection.json."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / 'Iroad_Mobile_Driver_Execute_Action.postman_collection.json'

COMMON_HEADERS = [
    {'key': 'Content-Type', 'value': 'application/json'},
    {'key': 'Accept', 'value': 'application/json'},
    {'key': 'Accept-Language', 'value': '{{accept_language}}'},
    {'key': 'X-Request-ID', 'value': '{{request_id}}'},
]

EXEC_BODY = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "notes": "{{execute_notes}}",
  "media": {{execute_media_json}}
}"""

REPLAY_BODY = """{
  "client_action_id": "{{execute_replay_client_action_id}}",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "notes": "{{execute_notes}}",
  "media": []
}"""

STALE_BODY = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{stale_workflow_version}}",
  "content_hash": "{{stale_content_hash}}",
  "latitude": 25.0,
  "longitude": 55.0,
  "notes": "",
  "media": []
}"""

MISSING_IDEM_BODY = """{
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.0,
  "longitude": 55.0,
  "notes": "",
  "media": []
}"""

EVIDENCE_FAIL_BODY = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "notes": "",
  "media": []
}"""

POD_BODY = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "notes": "POD capture — Postman",
  "media": [
    {
      "media_type": "photo",
      "file_ref": "{{pod_photo_file_ref}}",
      "file_name": "pod-proof.jpg",
      "description": "Delivery proof"
    },
    {
      "media_type": "signature",
      "file_ref": "{{pod_signature_file_ref}}",
      "file_name": "receiver-sign.png"
    }
  ]
}"""

COD_BODY = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "notes": "COD collected — Postman",
  "mobile_cod_amount": "{{execute_cod_amount}}",
  "media": []
}"""

HARD_POD_BODY = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "notes": "Hard POD — Postman",
  "custody_submission_id": "{{hard_pod_custody_submission_id}}",
  "media": [
    {
      "media_type": "photo",
      "file_ref": "{{hard_pod_photo_file_ref}}",
      "file_name": "hard-pod.jpg"
    }
  ]
}"""

HARD_POD_SUBMIT_BODY = """{
  "client_submission_id": "{{hard_pod_client_submission_id}}",
  "shipment_id": "{{shipment_id}}",
  "receiver_name": "{{hard_pod_receiver_name}}",
  "receiver_contact": "{{hard_pod_receiver_contact}}",
  "handoff_notes": "{{hard_pod_handoff_notes}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "media": [
    {
      "media_type": "photo",
      "file_ref": "{{hard_pod_photo_file_ref}}",
      "file_name": "hard-pod.jpg"
    }
  ]
}"""

PREREQUEST_NEW_ID = [
    "if (!pm.variables.get('execute_client_action_id') || String(pm.variables.get('execute_client_action_id')).indexOf('{{') >= 0) {",
    "    pm.variables.set('execute_client_action_id', pm.variables.replaceIn('{{$guid}}'));",
    "}",
]

EXEC_SUCCESS_TEST = [
    "pm.test('HTTP 201 or 200', function () {",
    "    pm.expect([200, 201]).to.include(pm.response.code);",
    "});",
    "const json = pm.response.json();",
    "pm.test('status=1', function () { pm.expect(json.status).to.eql(1); });",
    "const data = json.data || {};",
    "pm.test('has execution + workflow + sync_metadata', function () {",
    "    pm.expect(data).to.have.property('execution');",
    "    pm.expect(data).to.have.property('workflow');",
    "    pm.expect(data).to.have.property('sync_metadata');",
    "});",
    "if (pm.response.code === 201) {",
    "    const cid = pm.variables.get('execute_client_action_id');",
    "    if (cid) {",
    "        pm.environment.set('execute_replay_client_action_id', cid);",
    "        pm.collectionVariables.set('execute_replay_client_action_id', cid);",
    "    }",
    "}",
    "const sync = data.sync_metadata || {};",
    "if (sync.content_hash) {",
    "    pm.environment.set('execute_content_hash', sync.content_hash);",
    "    pm.collectionVariables.set('execute_content_hash', sync.content_hash);",
    "}",
    "if (sync.workflow_version) {",
    "    pm.environment.set('execute_workflow_version', sync.workflow_version);",
    "    pm.collectionVariables.set('execute_workflow_version', sync.workflow_version);",
    "}",
]

REPLAY_TEST = [
    "pm.test('HTTP 200 idempotent replay', function () { pm.response.to.have.status(200); });",
    "const json = pm.response.json();",
    "const exec = (json.data || {}).execution || {};",
    "pm.test('reused_existing', function () { pm.expect(exec.reused_existing).to.eql(true); });",
]

NEGATIVE_TEST = """pm.test('HTTP {code}', function () {{ pm.response.to.have.status({code}); }});
const json = pm.response.json();
pm.test('status=0 on error', function () {{ pm.expect(json.status).to.eql(0); }});
const err = (json.data || {{}}).error_code || json.data;
if (err) {{ console.log('error_code:', err); }}"""


def _req(
    name: str,
    *,
    url: str,
    body: str | None = None,
    method: str = 'POST',
    tenant_header: str = '{{tenant_schema}}',
    description: str = '',
    prerequest: list[str] | None = None,
    tests: list[str] | None = None,
    extra_headers: list[dict] | None = None,
) -> dict:
    headers = list(COMMON_HEADERS)
    if tenant_header:
        headers.append({'key': 'X-Tenant-ID', 'value': tenant_header})
    if extra_headers:
        headers.extend(extra_headers)
    item: dict = {
        'name': name,
        'request': {
            'method': method,
            'header': headers,
            'url': url,
        },
    }
    if description:
        item['request']['description'] = description
    if body is not None:
        item['request']['body'] = {
            'mode': 'raw',
            'raw': body,
            'options': {'raw': {'language': 'json'}},
        }
    events = []
    if prerequest:
        events.append({'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': prerequest}})
    if tests:
        events.append({'listen': 'test', 'script': {'type': 'text/javascript', 'exec': tests}})
    if events:
        item['event'] = events
    return item


def main() -> None:
    base = '{{base_url}}'
    shipment_execute = (
        f'{base}/driver/jobs/shipment/{{{{shipment_id}}}}/actions/'
        f'{{{{execute_action_code}}}}/execute/'
    )
    movement_execute = (
        f'{base}/driver/jobs/movement/{{{{movement_id}}}}/actions/'
        f'{{{{execute_action_code}}}}/execute/'
    )
    pod_execute = (
        f'{base}/driver/jobs/shipment/{{{{shipment_id}}}}/actions/'
        f'{{{{execute_pod_action_code}}}}/execute/'
    )
    cod_execute = (
        f'{base}/driver/jobs/shipment/{{{{shipment_id}}}}/actions/'
        f'{{{{execute_cod_action_code}}}}/execute/'
    )
    hard_pod_execute = (
        f'{base}/driver/jobs/shipment/{{{{shipment_id}}}}/actions/'
        f'{{{{execute_hard_pod_action_code}}}}/execute/'
    )
    hard_pod_submit = f'{base}/driver/hard-pod/submit/'
    foreign_execute = (
        f'{base}/driver/jobs/shipment/{{{{foreign_shipment_id}}}}/actions/'
        f'{{{{execute_action_code}}}}/execute/'
    )
    invalid_execute = (
        f'{base}/driver/jobs/shipment/{{{{shipment_id}}}}/actions/'
        f'{{{{invalid_action_code}}}}/execute/'
    )
    evidence_execute = (
        f'{base}/driver/jobs/shipment/{{{{shipment_id}}}}/actions/'
        f'{{{{execute_evidence_action_code}}}}/execute/'
    )
    collection = {
        'info': {
            '_postman_id': 'e7f8a9b0-c1d2-3456-7890-abcdef123456',
            'name': 'Iroad — Mobile Driver API (Unified Execute Action)',
            'description': (
                'Complete Postman collection for **Unified Driver Execute Action** API.\n\n'
                '## Auth\n'
                'Bearer token only — **no login requests**. Set `{{bearer_token}}` '
                '(or `access_token` copied from your auth flow).\n\n'
                '## Base\n'
                '`{{base_url}}` → `http://127.0.0.1:8000/api/v1/mobile`\n\n'
                '## Setup\n'
                'See `EXECUTE_ACTION_SETUP.md` and `EXECUTE_ACTION_SAMPLE_PAYLOADS.md`.\n\n'
                '## RBAC\n'
                '`mobile.driver.execute`'
            ),
            'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
        },
        'auth': {
            'type': 'bearer',
            'bearer': [{'key': 'token', 'value': '{{bearer_token}}', 'type': 'string'}],
        },
        'event': [
            {
                'listen': 'prerequest',
                'script': {
                    'type': 'text/javascript',
                    'exec': [
                        "if (!pm.variables.get('request_id') || String(pm.variables.get('request_id')).indexOf('{{') >= 0) {",
                        "    pm.variables.set('request_id', 'postman-' + pm.variables.replaceIn('{{$guid}}'));",
                        '}',
                        "const bearer = pm.variables.get('bearer_token');",
                        "const access = pm.variables.get('access_token');",
                        "if ((!bearer || String(bearer).indexOf('{{') >= 0) && access && String(access).indexOf('{{') < 0) {",
                        "    pm.variables.set('bearer_token', access);",
                        '}',
                    ],
                },
            },
        ],
        'variable': [
            {'key': 'base_url', 'value': 'http://127.0.0.1:8000/api/v1/mobile'},
            {'key': 'bearer_token', 'value': ''},
            {'key': 'tenant_schema', 'value': ''},
            {'key': 'shipment_id', 'value': ''},
            {'key': 'movement_id', 'value': ''},
            {'key': 'execute_action_code', 'value': 'A2'},
            {'key': 'execute_pod_action_code', 'value': ''},
            {'key': 'execute_cod_action_code', 'value': ''},
            {'key': 'execute_hard_pod_action_code', 'value': ''},
            {'key': 'execute_evidence_action_code', 'value': ''},
            {'key': 'execute_client_action_id', 'value': ''},
            {'key': 'execute_replay_client_action_id', 'value': ''},
            {'key': 'execute_workflow_version', 'value': ''},
            {'key': 'execute_content_hash', 'value': ''},
            {'key': 'execute_latitude', 'value': '25.2048'},
            {'key': 'execute_longitude', 'value': '55.2708'},
            {'key': 'execute_notes', 'value': 'Driver execute via Postman'},
            {'key': 'execute_media_json', 'value': '[]'},
            {'key': 'execute_cod_amount', 'value': '150.00'},
            {'key': 'stale_workflow_version', 'value': 'stale-workflow-version-intentionally-wrong'},
            {'key': 'stale_content_hash', 'value': 'stale-content-hash-intentionally-wrong'},
            {'key': 'wrong_tenant_id', 'value': 'wrong-tenant-schema'},
            {'key': 'foreign_shipment_id', 'value': '00000000-0000-0000-0000-000000000099'},
            {'key': 'invalid_action_code', 'value': 'ZZZ_NOT_ALLOWED'},
            {'key': 'pod_photo_file_ref', 'value': 'tenant-uploads/pod/photo-001.jpg'},
            {'key': 'pod_signature_file_ref', 'value': 'tenant-uploads/pod/signature-001.png'},
            {'key': 'hard_pod_photo_file_ref', 'value': 'tenant-uploads/hard-pod/scan-001.jpg'},
            {'key': 'hard_pod_client_submission_id', 'value': ''},
            {'key': 'hard_pod_custody_submission_id', 'value': ''},
            {'key': 'hard_pod_receiver_name', 'value': 'Receiver Name'},
            {'key': 'hard_pod_receiver_contact', 'value': '0500000000'},
            {'key': 'hard_pod_handoff_notes', 'value': 'Hard POD handoff via Postman'},
        ],
        'item': [
            {
                'name': '01 — Execute (success paths)',
                'description': (
                    'Set `execute_content_hash`, `execute_workflow_version`, and action codes '
                    'from Job Detail (separate collection) before executing. '
                    'Each request generates a new `execute_client_action_id` except replay.'
                ),
                'item': [
                    _req(
                        '1. Shipment Execute',
                        url=shipment_execute,
                        body=EXEC_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=EXEC_SUCCESS_TEST,
                        description='Primary workflow action on assigned shipment.',
                    ),
                    _req(
                        '2. Empty Move Execute',
                        url=movement_execute,
                        body=EXEC_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=EXEC_SUCCESS_TEST,
                        description='Execute on movement / empty-move job.',
                    ),
                    _req(
                        '3. POD Execute',
                        url=pod_execute,
                        body=POD_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=EXEC_SUCCESS_TEST,
                        description='Set execute_pod_action_code from Job Detail when pod_cod.pod_pending.',
                    ),
                    _req(
                        '4. COD Execute',
                        url=cod_execute,
                        body=COD_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=EXEC_SUCCESS_TEST,
                        description='Set execute_cod_action_code when pod_cod.cod_pending.',
                    ),
                    _req(
                        '5a. Hard POD Submit (get custody_submission_id)',
                        url=hard_pod_submit,
                        body=HARD_POD_SUBMIT_BODY,
                        prerequest=[
                            "if (!pm.variables.get('hard_pod_client_submission_id') || String(pm.variables.get('hard_pod_client_submission_id')).indexOf('{{') >= 0) {",
                            "    pm.variables.set('hard_pod_client_submission_id', 'hard-pod-' + pm.variables.replaceIn('{{$guid}}'));",
                            "}",
                        ],
                        tests=[
                            "pm.test('HTTP 201 or 200', function () { pm.expect([200, 201]).to.include(pm.response.code); });",
                            "const json = pm.response.json();",
                            "pm.test('status=1', function () { pm.expect(json.status).to.eql(1); });",
                            "const custody = (json.data || {}).custody_submission || {};",
                            "pm.test('submission id present', function () { pm.expect(custody.submission_id).to.be.a('string'); });",
                            "if (custody.submission_id) {",
                            "    pm.environment.set('hard_pod_custody_submission_id', custody.submission_id);",
                            "    pm.collectionVariables.set('hard_pod_custody_submission_id', custody.submission_id);",
                            "}",
                        ],
                        description=(
                            'Run before Hard POD Execute. Stores `hard_pod_custody_submission_id` '
                            'required by A7H execute.'
                        ),
                    ),
                    _req(
                        '5. Hard POD Execute',
                        url=hard_pod_execute,
                        body=HARD_POD_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=EXEC_SUCCESS_TEST,
                        description=(
                            'Set execute_hard_pod_action_code when pod_cod.hard_pod_pending. '
                            'Requires `hard_pod_custody_submission_id` from request 5a.'
                        ),
                    ),
                    _req(
                        '6. Idempotent Replay (retry)',
                        url=shipment_execute,
                        body=REPLAY_BODY,
                        tests=REPLAY_TEST,
                        description=(
                            'Run **1. Shipment Execute** first. Uses '
                            'execute_replay_client_action_id saved from 201 response.'
                        ),
                    ),
                ],
            },
            {
                'name': '02 — Negative & security',
                'description': 'Expected failures for stale sync, tenant, ownership, validation.',
                'item': [
                    _req(
                        '7. Stale Workflow Rejection',
                        url=shipment_execute,
                        body=STALE_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=NEGATIVE_TEST.format(code=409).split('\n'),
                        description='Expect 409 stale_content_hash or stale_workflow_version.',
                    ),
                    _req(
                        '8. Wrong Tenant',
                        url=shipment_execute,
                        body=EXEC_BODY,
                        tenant_header='{{wrong_tenant_id}}',
                        prerequest=PREREQUEST_NEW_ID,
                        tests=NEGATIVE_TEST.format(code=403).split('\n'),
                        description='X-Tenant-ID must not match JWT tenant_schema.',
                    ),
                    _req(
                        '9. Wrong Driver (foreign shipment)',
                        url=foreign_execute,
                        body=EXEC_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=NEGATIVE_TEST.format(code=403).split('\n'),
                        description='Shipment not owned by authenticated driver.',
                    ),
                    _req(
                        '10. Missing Idempotency Key',
                        url=shipment_execute,
                        body=MISSING_IDEM_BODY,
                        tests=NEGATIVE_TEST.format(code=400).split('\n'),
                        description='Omits client_action_id — expect validation_failed.',
                    ),
                    _req(
                        '11. Invalid Action',
                        url=invalid_execute,
                        body=EXEC_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=NEGATIVE_TEST.format(code=400).split('\n'),
                        description='action_not_allowed or action_not_found.',
                    ),
                    _req(
                        '12. Evidence Validation Failure',
                        url=evidence_execute,
                        body=EVIDENCE_FAIL_BODY,
                        prerequest=PREREQUEST_NEW_ID,
                        tests=NEGATIVE_TEST.format(code=400).split('\n'),
                        description=(
                            'Set execute_evidence_action_code to an action requiring GPS/photo '
                            'but send empty evidence body.'
                        ),
                    ),
                ],
            },
        ],
    }

    OUT.write_text(json.dumps(collection, indent=2), encoding='utf-8')
    print(f'Wrote {OUT}')


if __name__ == '__main__':
    main()
