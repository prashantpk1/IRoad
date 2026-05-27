#!/usr/bin/env python3
"""Regenerate Iroad_Mobile_Driver_POD_Capture.postman_collection.json."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / 'Iroad_Mobile_Driver_POD_Capture.postman_collection.json'

COMMON_HEADERS = [
    {'key': 'Content-Type', 'value': 'application/json'},
    {'key': 'Accept', 'value': 'application/json'},
    {'key': 'Accept-Language', 'value': '{{accept_language}}'},
    {'key': 'X-Request-ID', 'value': '{{request_id}}'},
    {'key': 'X-Tenant-ID', 'value': '{{tenant_header}}'},
]

CAPTURE_BASE = """{
  "client_capture_id": "{{pod_client_capture_id}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "{{pod_capture_type}}",
  "notes": "{{pod_notes}}",
  "latitude": {{pod_latitude}},
  "longitude": {{pod_longitude}},
  "media": {{pod_media_json}}
}"""

CAPTURE_NO_GPS = """{
  "client_capture_id": "{{pod_client_capture_id}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "digital",
  "notes": "{{pod_notes}}",
  "media": {{pod_media_json}}
}"""

CAPTURE_REPLAY = """{
  "client_capture_id": "{{pod_replay_client_capture_id}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "digital",
  "notes": "{{pod_notes}}",
  "latitude": {{pod_latitude}},
  "longitude": {{pod_longitude}},
  "media": [
    {
      "media_type": "photo",
      "file_ref": "{{pod_path_prefix}}digital-photo.jpg",
      "file_name": "digital-photo.jpg"
    }
  ]
}"""

EXECUTE_PROMOTE = """{
  "client_action_id": "{{execute_client_action_id}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "latitude": {{execute_latitude}},
  "longitude": {{execute_longitude}},
  "notes": "{{pod_execute_notes}}",
  "capture_bundle_id": "{{capture_bundle_id}}",
  "media": []
}"""

EXECUTE_PROMOTE_REPLAY = EXECUTE_PROMOTE.replace(
    '{{execute_client_action_id}}',
    '{{execute_replay_client_action_id}}',
)

EXECUTE_EXPIRED = EXECUTE_PROMOTE.replace(
    '{{capture_bundle_id}}',
    '{{expired_bundle_id}}',
)

MEDIA_SETTERS = {
    'digital': """[
  {
    "media_type": "photo",
    "file_ref": "{{pod_path_prefix}}digital-photo.jpg",
    "file_name": "digital-photo.jpg",
    "description": "Digital POD photo"
  }
]""",
    'video': """[
  {
    "media_type": "video",
    "file_ref": "{{pod_path_prefix}}delivery-video.mp4",
    "file_name": "delivery-video.mp4",
    "description": "POD video evidence"
  }
]""",
    'signature': """[
  {
    "media_type": "signature",
    "file_ref": "{{pod_path_prefix}}signature.png",
    "file_name": "signature.png",
    "description": "Recipient signature"
  }
]""",
    'hard': """[
  {
    "media_type": "photo",
    "file_ref": "{{pod_path_prefix}}hard-copy-scan.jpg",
    "file_name": "hard-copy-scan.jpg",
    "description": "Hard POD scan"
  }
]""",
    'multi_page': """[
  {
    "media_type": "photo",
    "file_ref": "{{pod_path_prefix}}page-1.jpg",
    "file_name": "page-1.jpg",
    "description": "Page 1"
  },
  {
    "media_type": "document",
    "file_ref": "{{pod_path_prefix}}page-2.jpg",
    "file_name": "page-2.jpg",
    "description": "Page 2"
  }
]""",
    'invalid_mime': """[
  {
    "media_type": "photo",
    "file_ref": "{{pod_path_prefix}}malware.exe",
    "file_name": "malware.exe"
  }
]""",
    'wrong_driver': """[
  {
    "media_type": "photo",
    "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{wrong_driver_id}}/{{shipment_id}}/pod_capture/orphan.jpg",
    "file_name": "orphan.jpg"
  }
]""",
}

PREREQUEST_GLOBAL = [
    "if (!pm.variables.get('request_id') || String(pm.variables.get('request_id')).indexOf('{{') >= 0) {",
    "    pm.variables.set('request_id', 'postman-' + pm.variables.replaceIn('{{$guid}}'));",
    "}",
    "const bearer = pm.variables.get('bearer_token');",
    "const access = pm.variables.get('access_token');",
    "if ((!bearer || String(bearer).indexOf('{{') >= 0) && access && String(access).indexOf('{{') < 0) {",
    "    pm.variables.set('bearer_token', access);",
    "}",
    "const schema = pm.variables.get('tenant_schema') || pm.variables.get('tenant_header');",
    "if (schema && String(schema).indexOf('{{') < 0) {",
    "    pm.environment.set('tenant_header', schema);",
    "}",
]

PREREQUEST_CAPTURE = PREREQUEST_GLOBAL + [
    "if (!pm.variables.get('pod_client_capture_id') || String(pm.variables.get('pod_client_capture_id')).indexOf('{{') >= 0) {",
    "    pm.variables.set('pod_client_capture_id', pm.variables.replaceIn('{{$guid}}'));",
    "}",
    "const tenant = pm.variables.get('tenant_schema') || pm.variables.get('tenant_header') || 'tenant';",
    "const driver = pm.variables.get('driver_id') || 'driver';",
    "const shipment = pm.variables.get('shipment_id') || 'shipment';",
    "pm.variables.set('pod_path_prefix', 'mobile_driver_uploads/' + tenant + '/' + driver + '/' + shipment + '/pod_capture/');",
]

TESTS_CAPTURE_201 = [
    "pm.test('HTTP 201', function () { pm.response.to.have.status(201); });",
    "pm.test('envelope ok', function () { pm.expect(pm.response.json().status).to.eql(1); });",
    "const data = pm.response.json().data;",
    "pm.test('capture_bundle_id present', function () {",
    "    pm.expect(data.capture_bundle.capture_bundle_id).to.be.a('string');",
    "});",
    "pm.test('execute ready', function () {",
    "    pm.expect(data.next_step.requires_execute_action).to.be.true;",
    "});",
    "pm.environment.set('capture_bundle_id', data.capture_bundle.capture_bundle_id);",
    "pm.environment.set('pod_replay_client_capture_id', data.capture_bundle.client_capture_id);",
    "if (data.sync_metadata && data.sync_metadata.content_hash) {",
    "    pm.environment.set('pod_content_hash', data.sync_metadata.content_hash);",
    "}",
]

TESTS_CAPTURE_REPLAY = [
    "pm.test('HTTP 200 replay', function () { pm.response.to.have.status(200); });",
    "pm.test('replayed', function () {",
    "    pm.expect(pm.response.json().data.capture_bundle.replayed).to.be.true;",
    "});",
]

TESTS_NEGATIVE = [
    "pm.test('client error', function () { pm.expect(pm.response.code).to.be.at.least(400); });",
    "pm.test('status 0', function () { pm.expect(pm.response.json().status).to.eql(0); });",
]

TESTS_JOB_DETAIL = [
    "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
    "const sync = pm.response.json().data.sync_metadata || {};",
    "if (sync.content_hash) pm.environment.set('pod_content_hash', sync.content_hash);",
    "if (sync.workflow_version) pm.environment.set('pod_workflow_version', sync.workflow_version);",
]

TESTS_EXECUTE_PROMOTE = [
    "pm.test('HTTP 201 or 200', function () { pm.expect([200, 201]).to.include(pm.response.code); });",
    "const pc = pm.response.json().data.pod_capture;",
    "pm.test('promoted_bundle_id', function () {",
    "    pm.expect(pc.promoted_bundle_id).to.eql(pm.environment.get('capture_bundle_id'));",
    "});",
    "pm.environment.set('execute_replay_client_action_id', pm.environment.get('execute_client_action_id'));",
]


def _body_with_type(pod_type: str) -> str:
    return CAPTURE_BASE.replace('{{pod_capture_type}}', pod_type)


def _capture_item(
    name: str,
    *,
    description: str,
    body: str,
    shipment: str = '{{shipment_id}}',
    tenant: str | None = None,
    prerequest_extra: list[str] | None = None,
    tests: list[str] | None = None,
    skip_tenant: bool = False,
) -> dict:
    headers = [h for h in COMMON_HEADERS if not (skip_tenant and h['key'] == 'X-Tenant-ID')]
    if tenant:
        headers = [
            h if h['key'] != 'X-Tenant-ID' else {'key': 'X-Tenant-ID', 'value': tenant}
            for h in headers
        ]
    pre = list(PREREQUEST_CAPTURE)
    if prerequest_extra:
        pre.extend(prerequest_extra)
    return {
        'name': name,
        'request': {
            'method': 'POST',
            'header': headers,
            'url': f'{{{{base_url}}}}/driver/jobs/shipments/{shipment}/pod/capture/',
            'description': description,
            'body': {'mode': 'raw', 'raw': body, 'options': {'raw': {'language': 'json'}}},
        },
        'event': [
            {'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': pre}},
            {'listen': 'test', 'script': {'type': 'text/javascript', 'exec': tests or TESTS_NEGATIVE}},
        ],
    }


def _execute_item(name: str, description: str, body: str, tests: list[str]) -> dict:
    return {
        'name': name,
        'request': {
            'method': 'POST',
            'header': COMMON_HEADERS,
            'url': '{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{execute_pod_action_code}}/execute/',
            'description': description,
            'body': {'mode': 'raw', 'raw': body, 'options': {'raw': {'language': 'json'}}},
        },
        'event': [
            {
                'listen': 'prerequest',
                'script': {
                    'type': 'text/javascript',
                    'exec': PREREQUEST_GLOBAL
                    + [
                        "if (!pm.variables.get('execute_client_action_id') || String(pm.variables.get('execute_client_action_id')).indexOf('{{') >= 0) {",
                        "    pm.variables.set('execute_client_action_id', pm.variables.replaceIn('{{$guid}}'));",
                        "}",
                    ],
                },
            },
            {'listen': 'test', 'script': {'type': 'text/javascript', 'exec': tests}},
        ],
    }


def _media_pre(pod_type: str) -> list[str]:
    compact = ' '.join(MEDIA_SETTERS[pod_type].split())
    return [f'pm.variables.set("pod_media_json", `{compact}`);']


collection = {
    'info': {
        '_postman_id': 'f1a2b3c4-d5e6-7890-abcd-ef1234567891',
        'name': 'Iroad — Mobile Driver API (POD Capture)',
        'description': (
            'POD Capture + Execute bundle promotion.\n\n'
            '**Auth:** `Bearer {{bearer_token}}` (no login).\n'
            '**Tenant:** `X-Tenant-ID: {{tenant_header}}`.\n\n'
            'See `POD_CAPTURE_SETUP.md` and `POD_CAPTURE_SAMPLE_PAYLOADS.md`.'
        ),
        'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
    },
    'auth': {
        'type': 'bearer',
        'bearer': [{'key': 'token', 'value': '{{bearer_token}}', 'type': 'string'}],
    },
    'event': [
        {'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': PREREQUEST_GLOBAL}}
    ],
    'variable': [
        {'key': 'base_url', 'value': 'http://127.0.0.1:8000/api/v1/mobile'},
        {'key': 'bearer_token', 'value': ''},
        {'key': 'tenant_header', 'value': ''},
        {'key': 'tenant_schema', 'value': ''},
        {'key': 'shipment_id', 'value': ''},
        {'key': 'driver_id', 'value': ''},
        {'key': 'pod_capture_type', 'value': 'digital'},
    ],
    'item': [
        {
            'name': '00 — Prerequisites',
            'item': [
                {
                    'name': '0. GET Shipment Job Detail (sync hashes)',
                    'request': {
                        'method': 'GET',
                        'header': [
                            {'key': 'Accept', 'value': 'application/json'},
                            {'key': 'X-Tenant-ID', 'value': '{{tenant_header}}'},
                            {'key': 'X-Request-ID', 'value': '{{request_id}}'},
                        ],
                        'url': '{{base_url}}/driver/jobs/shipment/{{shipment_id}}/',
                        'description': 'Copies `pod_content_hash` / `pod_workflow_version` for stale guards.',
                    },
                    'event': [
                        {
                            'listen': 'test',
                            'script': {'type': 'text/javascript', 'exec': TESTS_JOB_DETAIL},
                        }
                    ],
                }
            ],
        },
        {
            'name': '01 — POD Capture (success)',
            'item': [
                _capture_item(
                    '1. POD image capture (digital)',
                    description='Digital POD — one photo. Saves `capture_bundle_id`.',
                    body=_body_with_type('digital'),
                    prerequest_extra=_media_pre('digital'),
                    tests=TESTS_CAPTURE_201,
                ),
                _capture_item(
                    '2. POD video capture',
                    description='`pod_type: video`.',
                    body=_body_with_type('video'),
                    prerequest_extra=_media_pre('video'),
                    tests=TESTS_CAPTURE_201,
                ),
                _capture_item(
                    '3. Signature POD capture',
                    description='`pod_type: signature` + signature media.',
                    body=_body_with_type('signature'),
                    prerequest_extra=_media_pre('signature'),
                    tests=TESTS_CAPTURE_201,
                ),
                _capture_item(
                    '4. Hard POD capture',
                    description='`pod_type: hard` — delivery note scan.',
                    body=_body_with_type('hard'),
                    prerequest_extra=_media_pre('hard'),
                    tests=TESTS_CAPTURE_201,
                ),
                _capture_item(
                    '5. Multi-page POD capture',
                    description='`pod_type: multi_page` — photo + document.',
                    body=_body_with_type('multi_page'),
                    prerequest_extra=_media_pre('multi_page'),
                    tests=TESTS_CAPTURE_201,
                ),
                _capture_item(
                    '6. Replay-safe capture',
                    description='Same `client_capture_id` as request 1 — expect **200** + `replayed: true`. Run after **1**.',
                    body=CAPTURE_REPLAY,
                    tests=TESTS_CAPTURE_REPLAY,
                ),
            ],
        },
        {
            'name': '02 — Security & validation (negative)',
            'item': [
                _capture_item(
                    '7. Wrong shipment',
                    description='`foreign_shipment_id` not assigned to driver.',
                    body=_body_with_type('digital'),
                    shipment='{{foreign_shipment_id}}',
                    prerequest_extra=_media_pre('digital'),
                ),
                _capture_item(
                    '8. Wrong driver (orphan upload)',
                    description='`file_ref` uses `wrong_driver_id` in path.',
                    body=_body_with_type('digital'),
                    prerequest_extra=_media_pre('wrong_driver'),
                ),
                _capture_item(
                    '9. Wrong tenant',
                    description='`X-Tenant-ID` = `wrong_tenant_id`.',
                    body=_body_with_type('digital'),
                    tenant='{{wrong_tenant_id}}',
                    prerequest_extra=_media_pre('digital'),
                ),
                _capture_item(
                    '11. Invalid MIME / extension',
                    description='`.exe` in `file_ref`.',
                    body=_body_with_type('digital'),
                    prerequest_extra=_media_pre('invalid_mime'),
                ),
                _capture_item(
                    '12. Missing GPS',
                    description='No latitude/longitude when action requires GPS.',
                    body=CAPTURE_NO_GPS,
                    prerequest_extra=_media_pre('digital'),
                ),
                _capture_item(
                    '13. Invalid POD type',
                    description='Unknown pod_type token.',
                    body=_body_with_type('not_a_valid_type'),
                    prerequest_extra=_media_pre('digital'),
                ),
            ],
        },
        {
            'name': '03 — Execute promotion flow',
            'description': 'Complete **01 → 1** first. Set `execute_pod_action_code` from Job Detail.',
            'item': [
                _execute_item(
                    '14. Execute — promote staged bundle',
                    'Kernel execute + `capture_bundle_id` promotion. Expect `data.pod_capture`.',
                    EXECUTE_PROMOTE,
                    TESTS_EXECUTE_PROMOTE,
                ),
                _execute_item(
                    '14b. Execute — idempotent replay (same client_action_id)',
                    'Re-run after 14 with saved `execute_replay_client_action_id`.',
                    EXECUTE_PROMOTE_REPLAY,
                    [
                        "pm.test('HTTP 200', function () { pm.expect(pm.response.code).to.eql(200); });",
                        "pm.test('reused_existing', function () {",
                        "    pm.expect(pm.response.json().data.execution.reused_existing).to.be.true;",
                        "});",
                    ],
                ),
                _execute_item(
                    '14c. Execute — duplicate promotion',
                    'New `client_action_id` on already-promoted bundle — expect **409**.',
                    EXECUTE_PROMOTE,
                    TESTS_NEGATIVE,
                ),
                _execute_item(
                    '10 / 14d. Execute — expired bundle',
                    'Set `expired_bundle_id` to an expired bundle UUID — expect **410**.',
                    EXECUTE_EXPIRED,
                    TESTS_NEGATIVE,
                ),
            ],
        },
    ],
}

OUT.write_text(json.dumps(collection, indent=2), encoding='utf-8')
print(f'Wrote {OUT}')
