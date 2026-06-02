#!/usr/bin/env python3
"""Generate IRoad Driver Issue Report Postman collection + environment."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT_COLL = Path(__file__).parent / 'IRoad-Driver-Issue-Report.postman_collection.json'
OUT_ENV = Path(__file__).parent / 'IRoad-Driver-Issue-Report.postman_environment.json'

ISSUE_TYPES = [
    ('delay', 'medium', 'Traffic delay — ETA pushed back'),
    ('vehicle_breakdown', 'high', 'Vehicle breakdown — roadside assistance requested'),
    ('customer_unavailable', 'medium', 'Customer not available at delivery location'),
    ('payment_dispute', 'high', 'COD amount disputed by customer'),
    ('pod_issue', 'medium', 'POD document rejected — rescan required'),
    ('accident', 'critical', 'Minor accident — vehicle damage reported'),
    ('route_blocked', 'critical', 'Route blocked — police diversion in effect'),
    ('other', 'low', 'Other operational issue — see notes'),
]

DELAY_SEVERITIES = [
    ('low', 'Minor delay — 15 minutes'),
    ('medium', 'Moderate delay — traffic congestion'),
    ('high', 'Significant delay — over 1 hour'),
    ('critical', 'Critical delay — shipment at risk'),
]

COMMON_HEADERS = [
    {'key': 'Accept', 'value': 'application/json'},
    {'key': 'Accept-Language', 'value': '{{accept_language}}'},
    {'key': 'Authorization', 'value': 'Bearer {{access_token}}'},
    {'key': 'X-Request-ID', 'value': '{{request_id}}'},
]

POST_JSON_HEADERS = [
    {'key': 'Content-Type', 'value': 'application/json'},
    *COMMON_HEADERS,
]

COLLECTION_PREREQUEST = [
    "if (!pm.variables.get('request_id') || String(pm.variables.get('request_id')).indexOf('{{') >= 0) {",
    "    pm.collectionVariables.set('request_id', 'postman-' + pm.variables.replaceIn('{{$guid}}'));",
    "}",
    "const token = pm.collectionVariables.get('access_token') || pm.environment.get('access_token') || '';",
    "let tokenTenant = '';",
    "let tokenUserId = '';",
    "if (token && String(token).split('.').length >= 2) {",
    "    try {",
    "        const payload = JSON.parse(atob(String(token).split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));",
    "        tokenTenant = String(payload.tenant_schema || '').trim();",
    "        tokenUserId = String(payload.user_id || '').trim();",
    "    } catch (e) {}",
    "}",
    "if (tokenTenant) { pm.collectionVariables.set('tenant_schema', tokenTenant); }",
    "if (tokenUserId) { pm.collectionVariables.set('driver_id', tokenUserId); }",
    "const tenant = pm.collectionVariables.get('tenant_schema') || 'tenant_schema';",
    "const driver = pm.collectionVariables.get('driver_id') || 'driver_id';",
    "const ship = pm.collectionVariables.get('shipment_id') || 'shipment_id';",
    "pm.collectionVariables.set('issue_path_prefix', `mobile_driver_uploads/${tenant}/${driver}/${ship}/issues/`);",
]

TESTS_ISSUE = [
    "pm.test('HTTP 2xx', function () { pm.expect(pm.response.code).to.be.oneOf([200, 201]); });",
    "const body = pm.response.json();",
    "pm.test('status === 1', function () { pm.expect(body.status).to.eql(1); });",
    "const data = body.data || {};",
    "pm.test('issue object present', function () { pm.expect(data.issue).to.be.an('object'); });",
    "if (data.issue && data.issue.issue_id) {",
    "    pm.collectionVariables.set('last_issue_id', data.issue.issue_id);",
    "}",
    "if (data.issue && data.issue.client_issue_id) {",
    "    pm.collectionVariables.set('issue_replay_client_issue_id', data.issue.client_issue_id);",
    "}",
]

TESTS_REPLAY = [
    "pm.test('HTTP 200 replay', function () { pm.response.to.have.status(200); });",
    "const body = pm.response.json();",
    "pm.test('status === 1', function () { pm.expect(body.status).to.eql(1); });",
    "pm.test('replayed true', function () {",
    "    pm.expect((body.data || {}).issue.replayed).to.eql(true);",
    "});",
]

TESTS_LOGIN = [
    "var json = pm.response.json();",
    "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
    "pm.test('status === 1', function () { pm.expect(json.status).to.eql(1); });",
    "if (json.status === 1 && json.data && json.data.access_token) {",
    "    pm.collectionVariables.set('access_token', json.data.access_token);",
    "    try { pm.environment.set('access_token', json.data.access_token); } catch (e) {}",
    "    try {",
    "        const payload = JSON.parse(atob(String(json.data.access_token).split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));",
    "        if (payload.tenant_schema) {",
    "            pm.collectionVariables.set('tenant_schema', String(payload.tenant_schema));",
    "        }",
    "        if (payload.user_id) {",
    "            pm.collectionVariables.set('driver_id', String(payload.user_id));",
    "        }",
    "    } catch (e) {}",
    "}",
]


def _issue_body(
    *,
    client_var: str,
    issue_type: str,
    severity: str,
    notes: str,
    with_media: bool = False,
) -> str:
    media = '[]'
    if with_media:
        fname = f'{issue_type}-evidence.jpg'
        media = f"""[
    {{
      "media_type": "photo",
      "file_ref": "{{{{issue_path_prefix}}}}{fname}",
      "file_name": "{fname}",
      "mime_type": "image/jpeg",
      "sort_order": 1
    }}
  ]"""
    return f"""{{
  "client_issue_id": "{{{{{client_var}}}}}",
  "shipment_id": "{{{{shipment_id}}}}",
  "issue_type": "{issue_type}",
  "severity": "{severity}",
  "notes": {json.dumps(notes)},
  "latitude": {{{{issue_latitude}}}},
  "longitude": {{{{issue_longitude}}}},
  "media": {media}
}}"""


def _req(
    name: str,
    body: str,
    *,
    description: str = '',
    tests: list[str] | None = None,
    prerequest: list[str] | None = None,
    headers: list[dict] | None = None,
) -> dict:
    events = []
    if prerequest:
        events.append({'listen': 'prerequest', 'script': {'type': 'text/javascript', 'exec': prerequest}})
    if tests:
        events.append({'listen': 'test', 'script': {'type': 'text/javascript', 'exec': tests}})
    return {
        'name': name,
        'request': {
            'method': 'POST',
            'header': headers or POST_JSON_HEADERS,
            'body': {'mode': 'raw', 'raw': body, 'options': {'raw': {'language': 'json'}}},
            'url': '{{base_url}}/driver/issues/report/',
            'description': description,
        },
        'event': events,
    }


def _req_issue(
    name: str,
    issue_type: str,
    severity: str,
    notes: str,
    *,
    with_media: bool = False,
    var_suffix: str | None = None,
    tests: list[str] | None = None,
    extra_pre: list[str] | None = None,
) -> dict:
    suffix = var_suffix or issue_type.replace('_', '-')
    client_var = f'issue_{suffix}_client_issue_id'
    pre = list(extra_pre or [])
    pre.append(
        f"pm.collectionVariables.set('{client_var}', 'issue-{suffix}-' + pm.variables.replaceIn('{{{{$guid}}}}'));"
    )
    body = _issue_body(
        client_var=client_var,
        issue_type=issue_type,
        severity=severity,
        notes=notes,
        with_media=with_media,
    )
    desc = (
        f"`issue_type`: **{issue_type}** | `severity`: **{severity}**\n\n"
        f"POST `/api/v1/mobile/driver/issues/report/`\n"
        f"Requires `mobile.driver.issues` capability."
    )
    return _req(name, body, description=desc, tests=tests or TESTS_ISSUE, prerequest=pre)


def main() -> None:
    delay_severity_items = []
    for sev, note in DELAY_SEVERITIES:
        delay_severity_items.append(
            _req_issue(
                f'Delay — severity {sev}',
                'delay',
                sev,
                note,
                with_media=(sev == 'medium'),
            )
        )

    all_types_items = []
    for itype, sev, note in ISSUE_TYPES:
        all_types_items.append(
            _req_issue(
                f'{itype.replace("_", " ").title()}',
                itype,
                sev,
                note,
                with_media=(itype == 'delay'),
            )
        )

    replay_body = _issue_body(
        client_var='issue_replay_client_issue_id',
        issue_type='delay',
        severity='medium',
        notes='Traffic delay — replay test',
        with_media=False,
    )

    multipart_item = {
        'name': 'Report delay — multipart (file upload)',
        'request': {
            'method': 'POST',
            'header': COMMON_HEADERS,
            'body': {
                'mode': 'formdata',
                'formdata': [
                    {'key': 'client_issue_id', 'value': 'issue-multipart-{{$guid}}', 'type': 'text'},
                    {'key': 'shipment_id', 'value': '{{shipment_id}}', 'type': 'text'},
                    {'key': 'issue_type', 'value': 'delay', 'type': 'text'},
                    {'key': 'severity', 'value': 'medium', 'type': 'text'},
                    {'key': 'notes', 'value': 'Delay with photo evidence (multipart)', 'type': 'text'},
                    {'key': 'latitude', 'value': '{{issue_latitude}}', 'type': 'text'},
                    {'key': 'longitude', 'value': '{{issue_longitude}}', 'type': 'text'},
                    {'key': 'media[0][media_type]', 'value': 'photo', 'type': 'text'},
                    {'key': 'media[0][file_name]', 'value': 'delay-traffic.jpg', 'type': 'text'},
                    {'key': 'media[0][mime_type]', 'value': 'image/jpeg', 'type': 'text'},
                    {'key': 'media[0][sort_order]', 'value': '1', 'type': 'text'},
                    {
                        'key': 'media[0][file_ref]',
                        'type': 'file',
                        'src': ['postman/assets/delay-evidence.jpg'],
                    },
                ],
            },
            'url': '{{base_url}}/driver/issues/report/',
            'description': (
                'Multipart upload via `process_media_files`. '
                'Select a JPG/PNG file for `media[0][file_ref]`. '
                'Do not set Content-Type manually.'
            ),
        },
        'event': [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': TESTS_ISSUE}}],
    }

    collection = {
        'info': {
            '_postman_id': str(uuid.uuid4()),
            'name': 'IRoad — Driver Issue Report (All Types)',
            'description': (
                'Report operational issues / delays for an active shipment.\n\n'
                '**Endpoint:** `POST /api/v1/mobile/driver/issues/report/`\n\n'
                '**Auth:** `Bearer {{access_token}}` + capability `mobile.driver.issues`\n\n'
                '### issue_type (all 8)\n'
                '`delay`, `vehicle_breakdown`, `customer_unavailable`, `payment_dispute`, '
                '`pod_issue`, `accident`, `route_blocked`, `other`\n\n'
                '### severity (all 4)\n'
                '`low`, `medium`, `high`, `critical`\n\n'
                '### Required fields\n'
                '- `client_issue_id` — idempotency key (unique per driver per tenant)\n'
                '- `shipment_id` — shipment UUID or `shipment_no`\n'
                '- `issue_type`, `severity`\n\n'
                '### Optional\n'
                '- `notes`, `latitude`, `longitude`, `media[]`\n\n'
                'Import `IRoad-Driver-Issue-Report.postman_environment.json` and run **00 Login** first.'
            ),
            'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
        },
        'event': [
            {
                'listen': 'prerequest',
                'script': {'type': 'text/javascript', 'exec': COLLECTION_PREREQUEST},
            }
        ],
        'variable': [
            {'key': 'base_url', 'value': 'http://127.0.0.1:8000/api/v1/mobile'},
            {'key': 'access_token', 'value': ''},
            {'key': 'email', 'value': 'vuhuxyzon@yopmail.com'},
            {'key': 'password', 'value': 'Test@1234'},
            {'key': 'shipment_id', 'value': ''},
            {'key': 'tenant_schema', 'value': 't_bb773f861f3048748c0a7f0ffbee0df6'},
            {'key': 'driver_id', 'value': ''},
            {'key': 'issue_latitude', 'value': '24.7136'},
            {'key': 'issue_longitude', 'value': '46.6753'},
            {'key': 'accept_language', 'value': 'en'},
            {'key': 'request_id', 'value': ''},
            {'key': 'issue_path_prefix', 'value': ''},
            {'key': 'issue_replay_client_issue_id', 'value': ''},
            {'key': 'last_issue_id', 'value': ''},
        ],
        'item': [
            {
                'name': '00 — Setup (Login)',
                'description': 'Get `access_token` before reporting issues. Set `shipment_id` to an active job you own.',
                'item': [
                    {
                        'name': 'Login (Email)',
                        'event': [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': TESTS_LOGIN}}],
                        'request': {
                            'method': 'POST',
                            'header': [
                                {'key': 'Content-Type', 'value': 'application/json'},
                                {'key': 'Accept-Language', 'value': '{{accept_language}}'},
                            ],
                            'body': {
                                'mode': 'raw',
                                'raw': '{\n  "email": "{{email}}",\n  "password": "{{password}}"\n}',
                                'options': {'raw': {'language': 'json'}},
                            },
                            'url': '{{base_url}}/driver/auth/login/',
                        },
                    },
                ],
            },
            {
                'name': '01 — Report Delay (all severities)',
                'description': (
                    'Delay reports with each severity. `blocking_recommended` is true for '
                    'medium, high, and critical.'
                ),
                'item': delay_severity_items,
            },
            {
                'name': '02 — All issue types',
                'description': 'One request per `issue_type` with a typical severity.',
                'item': all_types_items,
            },
            {
                'name': '03 — Media & multipart',
                'item': [
                    _req_issue(
                        'Delay — with JSON media refs',
                        'delay',
                        'medium',
                        'Delay with pre-uploaded file_ref paths',
                        with_media=True,
                    ),
                    multipart_item,
                ],
            },
            {
                'name': '04 — Idempotency (replay)',
                'item': [
                    _req(
                        'Replay last delay report (same client_issue_id)',
                        replay_body,
                        description=(
                            'Run after **Delay — severity medium** (or any request that sets '
                            '`issue_replay_client_issue_id`). Expect HTTP **200** and `replayed: true`.'
                        ),
                        tests=TESTS_REPLAY,
                    ),
                ],
            },
            {
                'name': '05 — Verify on Job Detail',
                'item': [
                    {
                        'name': 'GET Job Detail (shipment)',
                        'request': {
                            'method': 'GET',
                            'header': COMMON_HEADERS,
                            'url': '{{base_url}}/driver/jobs/shipment/{{shipment_id}}/',
                            'description': (
                                'Check `operational_issues`, `unresolved_issue_count`, '
                                '`blocking_recommendation`, timeline issue milestones.'
                            ),
                        },
                        'event': [
                            {
                                'listen': 'test',
                                'script': {
                                    'type': 'text/javascript',
                                    'exec': [
                                        "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                                        "const data = (pm.response.json().data || {});",
                                        "pm.test('operational_issues key', function () {",
                                        "    pm.expect(data).to.have.property('operational_issues');",
                                        "});",
                                    ],
                                },
                            }
                        ],
                    },
                ],
            },
        ],
    }

    env = {
        'id': str(uuid.uuid4()),
        'name': 'IRoad Driver Issue Report — Local',
        'values': [
            {'key': 'base_url', 'value': 'http://127.0.0.1:8000/api/v1/mobile', 'type': 'default', 'enabled': True},
            {'key': 'accept_language', 'value': 'en', 'type': 'default', 'enabled': True},
            {'key': 'email', 'value': 'vuhuxyzon@yopmail.com', 'type': 'default', 'enabled': True},
            {'key': 'password', 'value': 'Test@1234', 'type': 'secret', 'enabled': True},
            {'key': 'access_token', 'value': '', 'type': 'secret', 'enabled': True},
            {'key': 'shipment_id', 'value': '', 'type': 'default', 'enabled': True},
            {'key': 'tenant_schema', 'value': 't_bb773f861f3048748c0a7f0ffbee0df6', 'type': 'default', 'enabled': True},
            {'key': 'driver_id', 'value': '', 'type': 'default', 'enabled': True},
            {'key': 'issue_latitude', 'value': '24.7136', 'type': 'default', 'enabled': True},
            {'key': 'issue_longitude', 'value': '46.6753', 'type': 'default', 'enabled': True},
            {'key': 'request_id', 'value': '', 'type': 'default', 'enabled': True},
            {'key': 'issue_replay_client_issue_id', 'value': '', 'type': 'default', 'enabled': True},
            {'key': 'last_issue_id', 'value': '', 'type': 'default', 'enabled': True},
        ],
        '_postman_variable_scope': 'environment',
        '_postman_exported_at': '2026-06-01T12:00:00.000Z',
        '_postman_exported_using': 'Cursor',
    }

    OUT_COLL.write_text(json.dumps(collection, indent=2), encoding='utf-8')
    OUT_ENV.write_text(json.dumps(env, indent=2), encoding='utf-8')
    print('Wrote', OUT_COLL)
    print('Wrote', OUT_ENV)


if __name__ == '__main__':
    main()
