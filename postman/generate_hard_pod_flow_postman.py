#!/usr/bin/env python3
"""
Generate Postman collections for Hard POD + video evidence mobile APIs.

Outputs:
  - IRoute_Hard_POD_Flow_Collection.json (full job flow + Hard POD steps)
  - IRoute_Video_Hard_POD_API_Collection.json (focused API slice)
  - IRoute-Hard-POD-Flow.postman_environment.json
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).parent
JOB_FLOW = ROOT / 'IRoute_Job_Flow_Collection.json'
OUT_COLL = ROOT / 'IRoute_Hard_POD_Flow_Collection.json'
OUT_API_COLL = ROOT / 'IRoute_Video_Hard_POD_API_Collection.json'
OUT_ENV = ROOT / 'IRoute-Hard-POD-Flow.postman_environment.json'

A7H_EXECUTE_BODY = """{
  "client_action_id": "a7h-{{$guid}}",
  "workflow_version": "{{workflow_version}}",
  "content_hash": "{{content_hash}}",
  "latitude": 21.3891,
  "longitude": 39.8579,
  "custody_submission_id": "{{hard_pod_custody_submission_id}}",
  "notes": "Hard POD collection confirmed — signed DN received",
  "media": []
}"""

HARD_POD_SUBMIT_BODY = """{
  "client_submission_id": "{{hard_pod_client_submission_id}}",
  "shipment_id": "{{shipment_id}}",
  "receiver_name": "{{hard_pod_receiver_name}}",
  "receiver_contact": "{{hard_pod_receiver_contact}}",
  "handoff_notes": "{{hard_pod_handoff_notes}}",
  "latitude": 21.3891,
  "longitude": 39.8579,
  "confirmed_pages": {{hard_pod_confirmed_pages_json}},
  "media": []
}"""

BUILD_CONFIRMED_PAGES_JS = [
    'function buildConfirmedPages(pages) {',
    '    return (pages || []).map(function (p) {',
    '        return {',
    '            page_id: p.page_id || "",',
    '            document_id: p.document_id || "",',
    '            line_no: p.line_no || 1,',
    '            confirmed: true',
    '        };',
    '    });',
    '}',
]

FETCH_DOCS_TESTS = BUILD_CONFIRMED_PAGES_JS + [
    'var resp = pm.response.json();',
    'pm.test("HTTP 200", function() { pm.response.to.have.status(200); });',
    'pm.test("status success", function() { pm.expect(resp.status).to.eql(1); });',
    'if (resp.data) {',
    '    var section = resp.data.pod_section || {};',
    '    var block = section.hard_copy_confirmation || {};',
    '    var pages = block.pages || resp.data.pages || [];',
    '    var documents = block.documents || resp.data.documents || [];',
    '    pm.test("shipment document pages returned", function() {',
    '        pm.expect(pages.length).to.be.at.least(1);',
    '    });',
    '    if (documents.length) {',
    '        pm.test("shipment document header present", function() {',
    '            pm.expect(documents[0].document_ref_no || documents[0].record_no).to.exist;',
    '        });',
    '    }',
    '    if (pages.length) {',
    '        pm.collectionVariables.set("hard_pod_page_count", String(pages.length));',
    '        pm.collectionVariables.set("hard_pod_confirmed_pages_json", JSON.stringify(buildConfirmedPages(pages)));',
    '    }',
    '}',
]

FETCH_DOCS_DEDICATED_TESTS = BUILD_CONFIRMED_PAGES_JS + [
    'var resp = pm.response.json();',
    'pm.test("HTTP 200", function() { pm.response.to.have.status(200); });',
    'pm.test("status success", function() { pm.expect(resp.status).to.eql(1); });',
    'if (resp.data) {',
    '    pm.test("action_code is A7H", function() {',
    '        pm.expect(resp.data.action_code).to.eql("A7H");',
    '    });',
    '    var pages = resp.data.pages || [];',
    '    var documents = resp.data.documents || [];',
    '    pm.test("pages returned", function() { pm.expect(pages.length).to.be.at.least(1); });',
    '    if (pages.length) {',
    '        pm.collectionVariables.set("hard_pod_page_count", String(pages.length));',
    '        pm.collectionVariables.set("hard_pod_confirmed_pages_json", JSON.stringify(buildConfirmedPages(pages)));',
    '    }',
    '    if (documents.length) {',
    '        pm.collectionVariables.set("hard_pod_document_id", documents[0].document_id || "");',
    '    }',
    '}',
]

SUBMIT_DOCS_PREREQUEST = [
    "if (!pm.variables.get('hard_pod_client_submission_id') || String(pm.variables.get('hard_pod_client_submission_id')).indexOf('{{') >= 0) {",
    "    pm.collectionVariables.set('hard_pod_client_submission_id', 'hard-pod-' + pm.variables.replaceIn('{{$guid}}'));",
    "}",
    "var pagesJson = pm.collectionVariables.get('hard_pod_confirmed_pages_json');",
    "if (!pagesJson || String(pagesJson).indexOf('{{') >= 0) {",
    "    pm.collectionVariables.set('hard_pod_confirmed_pages_json', JSON.stringify([{page_id:'', document_id:'', line_no:1, confirmed:true}]));",
    "}",
]

SUBMIT_DOCS_TESTS = [
    'pm.test("HTTP 201 or 200", function() { pm.expect([200, 201]).to.include(pm.response.code); });',
    'var json = pm.response.json();',
    'pm.test("status=1", function() { pm.expect(json.status).to.eql(1); });',
    'var custody = (json.data || {}).custody_submission || {};',
    'var sid = custody.submission_id;',
    'pm.test("custody_submission_id saved", function() { pm.expect(sid).to.be.a("string"); });',
    'pm.test("confirmed pages persisted", function() {',
    '    pm.expect(custody.confirmed_page_count || 0).to.be.at.least(1);',
    '});',
    'if (sid) {',
    '    pm.collectionVariables.set("hard_pod_custody_submission_id", sid);',
    '}',
]

A7H_PREREQUEST = [
    'const sid = pm.collectionVariables.get("hard_pod_custody_submission_id");',
    'if (!sid || String(sid).indexOf("{{") >= 0) {',
    '    throw new Error("Run request 11c first — hard_pod_custody_submission_id missing");',
    '}',
]

A7H_TESTS = [
    'var resp = pm.response.json();',
    'pm.test("HTTP 201 or 200", function() { pm.expect([200, 201]).to.include(pm.response.code); });',
    'if (resp.status === 1 && resp.data && resp.data.sync_metadata) {',
    '    pm.collectionVariables.set("content_hash", resp.data.sync_metadata.content_hash);',
    '    pm.collectionVariables.set("workflow_version", resp.data.sync_metadata.workflow_version);',
    '}',
]

POD_CAPTURE_10A_TESTS = [
    'var resp = pm.response.json();',
    'pm.test("HTTP 200", function() { pm.response.to.have.status(200); });',
    'if (resp.data) {',
    '    var digital = (resp.data.pod_section || {}).digital_evidence || {};',
    '    var reqs = digital.requirements || {};',
    '    pm.test("video_optional exposed", function() { pm.expect(reqs.video_optional).to.eql(true); });',
    '    pm.test("video max duration 15s", function() { pm.expect(reqs.video_max_duration_seconds).to.eql(15); });',
    '}',
]

HARD_POD_EXTRA = (
    '\n\nVIDEO + HARD POD (updated Jun 2026):\n'
    '  10 POD Capture — photo + signature + optional video (max 15s, duration_seconds)\n'
    '  11 Execute A7\n'
    '  11b GET .../pod/capture/?step=hard_copy_confirmation — DN checklist\n'
    '  11b-alt GET .../hard-pod/documents/ — dedicated Shipment Documents API\n'
    '  11c POST .../hard-pod/submit/ — confirmed_pages[] required (all DN pages)\n'
    '  11d POST .../actions/A7H/execute/ — custody_submission_id from 11c\n'
    '  12 Execute A8 → ...\n'
    'Skip 11b–11d for digital/soft POD shipments.'
)

ENV_VALUES = [
    ('base_url', 'http://127.0.0.1:8000/api/v1/mobile', 'default'),
    ('driver_email', '', 'default'),
    ('driver_password', '', 'secret'),
    ('tenant_id', '', 'default'),
    ('driver_extension', '', 'default'),
    ('driver_phone', '', 'default'),
    ('job_id', '', 'default'),
    ('job_type', 'shipment', 'default'),
    ('shipment_id', '', 'default'),
    ('capture_bundle_id', '', 'default'),
    ('content_hash', '', 'default'),
    ('workflow_version', '', 'default'),
    ('pod_content_hash', '', 'default'),
    ('pod_workflow_version', '', 'default'),
    ('hard_pod_custody_submission_id', '', 'default'),
    ('hard_pod_client_submission_id', '', 'default'),
    ('hard_pod_receiver_name', 'Receiver Name', 'default'),
    ('hard_pod_receiver_contact', '0500000000', 'default'),
    ('hard_pod_handoff_notes', 'Hard copy DN collected from receiver', 'default'),
    ('hard_pod_page_count', '', 'default'),
    ('hard_pod_confirmed_pages_json', '[]', 'default'),
    ('hard_pod_document_id', '', 'default'),
    ('access_token', '', 'default'),
    ('refresh_token', '', 'default'),
]


def _auth_header() -> list[dict]:
    return [{'key': 'Authorization', 'value': 'Bearer {{access_token}}'}]


def _post_json_header() -> list[dict]:
    return [
        {'key': 'Authorization', 'value': 'Bearer {{access_token}}'},
        {'key': 'Content-Type', 'value': 'application/json'},
        {'key': 'Accept', 'value': 'application/json'},
    ]


def _hard_pod_confirmation_items() -> list[dict]:
    base = '{{base_url}}'
    return [
        {
            'name': '11b — Fetch DN Checklist (pod/capture GET)',
            'request': {
                'method': 'GET',
                'header': _auth_header(),
                'url': f'{base}/driver/jobs/shipments/{{{{shipment_id}}}}/pod/capture/?step=hard_copy_confirmation',
                'description': (
                    'Hard POD checklist via POD capture GET.\n'
                    'Reads pod_section.hard_copy_confirmation.documents[] + pages[].\n'
                    'Auto-builds hard_pod_confirmed_pages_json for 11c.'
                ),
            },
            'event': [{
                'listen': 'test',
                'script': {'type': 'text/javascript', 'exec': FETCH_DOCS_TESTS},
            }],
        },
        {
            'name': '11b-alt — Fetch Shipment Documents (hard-pod/documents GET)',
            'request': {
                'method': 'GET',
                'header': _auth_header(),
                'url': f'{base}/driver/jobs/shipments/{{{{shipment_id}}}}/hard-pod/documents/',
                'description': (
                    'Dedicated Hard POD documents API.\n'
                    'Returns documents[] (TenantShipmentDocument DN headers) and pages[].'
                ),
            },
            'event': [{
                'listen': 'test',
                'script': {'type': 'text/javascript', 'exec': FETCH_DOCS_DEDICATED_TESTS},
            }],
        },
        {
            'name': '11c — Confirm Physical Custody (hard-pod/submit POST)',
            'request': {
                'method': 'POST',
                'header': _post_json_header(),
                'url': f'{base}/driver/hard-pod/submit/',
                'body': {
                    'mode': 'raw',
                    'raw': HARD_POD_SUBMIT_BODY,
                    'options': {'raw': {'language': 'json'}},
                },
                'description': (
                    'Requires confirmed_pages[] for every DN page from 11b/11b-alt.\n'
                    'Saves custody_submission.submission_id for 11d.'
                ),
            },
            'event': [
                {
                    'listen': 'prerequest',
                    'script': {'type': 'text/javascript', 'exec': SUBMIT_DOCS_PREREQUEST},
                },
                {
                    'listen': 'test',
                    'script': {'type': 'text/javascript', 'exec': SUBMIT_DOCS_TESTS},
                },
            ],
        },
        {
            'name': '11d — Execute A7H — Hard POD Confirmation',
            'request': {
                'method': 'POST',
                'header': _post_json_header(),
                'url': f'{base}/driver/jobs/{{{{job_type}}}}/{{{{job_id}}}}/actions/A7H/execute/',
                'body': {
                    'mode': 'raw',
                    'raw': A7H_EXECUTE_BODY,
                    'options': {'raw': {'language': 'json'}},
                },
                'description': (
                    'Execute A7H with custody_submission_id from 11c.\n'
                    'Then continue to 12 (A8).'
                ),
            },
            'event': [
                {
                    'listen': 'prerequest',
                    'script': {'type': 'text/javascript', 'exec': A7H_PREREQUEST},
                },
                {
                    'listen': 'test',
                    'script': {'type': 'text/javascript', 'exec': A7H_TESTS},
                },
            ],
        },
    ]


def _find_item_by_prefix(items: list[dict], prefix: str) -> int | None:
    for i, item in enumerate(items):
        if item.get('name', '').startswith(prefix) and 'request' in item:
            return i
    return None


def _find_a7_index(items: list[dict]) -> int:
    idx = _find_item_by_prefix(items, '11 ')
    if idx is not None:
        return idx
    raise ValueError('A7 request not found in top-level items')


def _append_hard_pod_variables(variables: list[dict]) -> list[dict]:
    keys = {v['key'] for v in variables}
    extras = [
        {'key': 'hard_pod_custody_submission_id', 'value': ''},
        {'key': 'hard_pod_client_submission_id', 'value': ''},
        {'key': 'hard_pod_receiver_name', 'value': 'Receiver Name'},
        {'key': 'hard_pod_receiver_contact', 'value': '0500000000'},
        {'key': 'hard_pod_handoff_notes', 'value': 'Hard copy DN collected from receiver'},
        {'key': 'hard_pod_page_count', 'value': ''},
        {'key': 'hard_pod_confirmed_pages_json', 'value': '[]'},
        {'key': 'hard_pod_document_id', 'value': ''},
    ]
    for var in extras:
        if var['key'] not in keys:
            variables.append(var)
    return variables


def _patch_pod_capture_step_10(items: list[dict]) -> None:
    idx = _find_item_by_prefix(items, '10 — POD Capture')
    if idx is None:
        return
    req = items[idx]['request']
    formdata = req.get('body', {}).get('formdata', [])
    has_video = any(
        row.get('key') == 'media[2][media_type]' and row.get('value') == 'video'
        for row in formdata
    )
    if not has_video:
        formdata.extend([
            {'key': 'pod_type', 'value': 'digital', 'type': 'text'},
            {
                'key': 'media[2][media_type]',
                'value': 'video',
                'type': 'text',
            },
            {
                'key': 'media[2][file_name]',
                'value': 'signed_paper.mp4',
                'type': 'text',
            },
            {
                'key': 'media[2][description]',
                'value': 'Optional delivery video evidence (max 15s)',
                'type': 'text',
            },
            {'key': 'media[2][duration_seconds]', 'value': '8', 'type': 'text'},
            {'key': 'media[2][sort_order]', 'value': '3', 'type': 'text'},
            {'key': 'media[2][file_ref]', 'value': '', 'type': 'file'},
        ])
        req['body']['formdata'] = formdata
    req['description'] = (
        'STEP 10 — STAGE POD EVIDENCE (digital + optional video).\n'
        'PREREQUISITE: Run 10a first.\n\n'
        'FILES:\n'
        '  media[0] photo — delivery note scan (required)\n'
        '  media[1] signature — customer signature (required)\n'
        '  media[2] video — optional, max 15s (set duration_seconds)\n\n'
        'pod_type=digital. Saves capture_bundle_id for A7.'
    )


def _patch_sync_metadata_environment_saves(root) -> None:
    """Postman resolves environment before collection — mirror sync vars to both scopes."""
    patch_lines = [
        '    pm.environment.set("content_hash", resp.data.sync_metadata.content_hash);',
        '    pm.environment.set("workflow_version", resp.data.sync_metadata.workflow_version);',
        '    console.log("sync saved — hash: " + String(resp.data.sync_metadata.content_hash).substring(0, 16) + "...");',
    ]

    def walk(node) -> None:
        if isinstance(node, dict):
            for event in node.get('event') or []:
                if event.get('listen') != 'test':
                    continue
                script = event.get('script') or {}
                lines = list(script.get('exec') or [])
                joined = '\n'.join(lines)
                if 'sync_metadata.content_hash' not in joined:
                    continue
                if 'pm.environment.set("content_hash"' in joined:
                    continue
                new_lines: list[str] = []
                i = 0
                while i < len(lines):
                    line = lines[i]
                    new_lines.append(line)
                    if (
                        'resp.data.sync_metadata.workflow_version' in line
                        and i + 1 < len(lines)
                        and lines[i + 1].strip() == ');'
                    ):
                        new_lines.append(lines[i + 1])
                        new_lines.extend(patch_lines)
                        i += 2
                        continue
                    i += 1
                script['exec'] = new_lines
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(root)


def _patch_login_requests(items: list[dict]) -> None:
    """tenant_id is optional on login — email/password resolve tenant from driver record."""
    email_body = '{\n  "email": "{{driver_email}}",\n  "password": "{{driver_password}}"\n}'
    phone_body = (
        '{\n  "extension": "{{driver_extension}}",\n  "phone": "{{driver_phone}}",\n'
        '  "password": "{{driver_password}}"\n}'
    )
    for item in items:
        name = item.get('name', '')
        if not item.get('request'):
            continue
        body = item['request'].get('body', {})
        if name.startswith('01 — Login'):
            body['raw'] = email_body
            item['request']['description'] = (
                'EMAIL LOGIN — tenant_id optional.\n'
                'Send email + password only; tenant resolves from driver record.\n'
                'Add tenant_id only if the same email exists on multiple subscribers.'
            )
        elif name.startswith('01b — Login'):
            body['raw'] = phone_body
        if name.startswith('01'):
            for event in item.get('event', []):
                if event.get('listen') != 'test':
                    continue
                script = event.get('script', {})
                lines = list(script.get('exec') or [])
                if lines and 'pm.environment.set("access_token"' not in '\\n'.join(lines):
                    patched = []
                    for line in lines:
                        patched.append(line)
                        if 'pm.collectionVariables.set("refresh_token"' in line:
                            patched.extend(_LOGIN_TEST_TAIL[2:])
                    script['exec'] = patched


def _patch_pod_capture_sync_10a(items: list[dict]) -> None:
    idx = _find_item_by_prefix(items, '10a — POD Capture Sync')
    if idx is None:
        return
    events = items[idx].setdefault('event', [])
    if not any(e.get('listen') == 'test' for e in events):
        events.append({
            'listen': 'test',
            'script': {'type': 'text/javascript', 'exec': POD_CAPTURE_10A_TESTS},
        })


def _build_api_collection() -> dict:
    base = '{{base_url}}'
    return {
        'info': {
            '_postman_id': 'a1b2c3d4-e5f6-7890-abcd-videohardpod',
            'name': 'IRoute — Video + Hard POD APIs',
            'description': (
                'Focused Postman collection for digital POD video evidence and '
                'Hard POD Shipment Document confirmation.\n\n'
                'Prerequisites: login (or set access_token), shipment_id, job_id, '
                'job_type, content_hash, workflow_version from job detail.\n\n'
                'Flow:\n'
                '  1. GET pod/capture sync (video requirements)\n'
                '  2. POST pod/capture (photo + optional video)\n'
                '  3. POST execute A7\n'
                '  4. GET hard-pod/documents OR pod/capture?step=hard_copy_confirmation\n'
                '  5. POST hard-pod/submit with confirmed_pages[]\n'
                '  6. POST execute A7H with custody_submission_id'
            ),
            'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
        },
        'variable': [
            {'key': 'base_url', 'value': 'http://127.0.0.1:8000/api/v1/mobile'},
            {'key': 'access_token', 'value': ''},
            {'key': 'shipment_id', 'value': ''},
            {'key': 'job_id', 'value': ''},
            {'key': 'job_type', 'value': 'shipment'},
            {'key': 'capture_bundle_id', 'value': ''},
            {'key': 'content_hash', 'value': ''},
            {'key': 'workflow_version', 'value': ''},
            {'key': 'pod_content_hash', 'value': ''},
            {'key': 'pod_workflow_version', 'value': ''},
            {'key': 'hard_pod_custody_submission_id', 'value': ''},
            {'key': 'hard_pod_client_submission_id', 'value': ''},
            {'key': 'hard_pod_confirmed_pages_json', 'value': '[]'},
            {'key': 'hard_pod_receiver_name', 'value': 'Receiver Name'},
            {'key': 'hard_pod_receiver_contact', 'value': '0500000000'},
            {'key': 'hard_pod_handoff_notes', 'value': 'Hard copy DN collected'},
        ],
        'item': [
            {
                'name': '01 — POD Capture Sync (video requirements)',
                'request': {
                    'method': 'GET',
                    'header': _auth_header(),
                    'url': f'{base}/driver/jobs/shipments/{{{{shipment_id}}}}/pod/capture/',
                },
                'event': [{
                    'listen': 'test',
                    'script': {'type': 'text/javascript', 'exec': POD_CAPTURE_10A_TESTS},
                }],
            },
            {
                'name': '02 — POD Capture POST (photo + optional video)',
                'request': {
                    'method': 'POST',
                    'header': _auth_header(),
                    'url': f'{base}/driver/jobs/shipments/{{{{shipment_id}}}}/pod/capture/',
                    'body': {
                        'mode': 'formdata',
                        'formdata': [
                            {'key': 'client_capture_id', 'value': 'pod-cap-{{$guid}}', 'type': 'text'},
                            {'key': 'content_hash', 'value': '{{pod_content_hash}}', 'type': 'text'},
                            {'key': 'workflow_version', 'value': '{{pod_workflow_version}}', 'type': 'text'},
                            {'key': 'pod_type', 'value': 'digital', 'type': 'text'},
                            {'key': 'latitude', 'value': '21.3891', 'type': 'text'},
                            {'key': 'longitude', 'value': '39.8579', 'type': 'text'},
                            {'key': 'notes', 'value': 'Digital POD with optional video', 'type': 'text'},
                            {'key': 'media[0][media_type]', 'value': 'photo', 'type': 'text'},
                            {'key': 'media[0][file_name]', 'value': 'delivery_note.jpg', 'type': 'text'},
                            {'key': 'media[0][sort_order]', 'value': '1', 'type': 'text'},
                            {'key': 'media[0][file_ref]', 'value': '', 'type': 'file'},
                            {'key': 'media[1][media_type]', 'value': 'video', 'type': 'text'},
                            {'key': 'media[1][file_name]', 'value': 'signed_paper.mp4', 'type': 'text'},
                            {'key': 'media[1][duration_seconds]', 'value': '8', 'type': 'text'},
                            {'key': 'media[1][sort_order]', 'value': '2', 'type': 'text'},
                            {'key': 'media[1][file_ref]', 'value': '', 'type': 'file'},
                        ],
                    },
                },
                'event': [{
                    'listen': 'test',
                    'script': {
                        'type': 'text/javascript',
                        'exec': [
                            'var resp = pm.response.json();',
                            'if (resp.data && resp.data.capture_bundle) {',
                            '    pm.collectionVariables.set("capture_bundle_id", resp.data.capture_bundle.capture_bundle_id);',
                            '}',
                        ],
                    },
                }],
            },
            {
                'name': '03 — Execute A7 (Upload POD)',
                'request': {
                    'method': 'POST',
                    'header': _post_json_header(),
                    'url': f'{base}/driver/jobs/{{{{job_type}}}}/{{{{job_id}}}}/actions/A7/execute/',
                    'body': {
                        'mode': 'raw',
                        'raw': (
                            '{\n'
                            '  "client_action_id": "a7-{{$guid}}",\n'
                            '  "workflow_version": "{{workflow_version}}",\n'
                            '  "content_hash": "{{content_hash}}",\n'
                            '  "latitude": 21.3891,\n'
                            '  "longitude": 39.8579,\n'
                            '  "capture_bundle_id": "{{capture_bundle_id}}",\n'
                            '  "notes": "POD with video evidence"\n'
                            '}'
                        ),
                        'options': {'raw': {'language': 'json'}},
                    },
                },
            },
            *_hard_pod_confirmation_items(),
        ],
    }


def main() -> None:
    job_flow = json.loads(JOB_FLOW.read_text(encoding='utf-8'))
    collection = copy.deepcopy(job_flow)

    collection['info']['_postman_id'] = 'f1e2d3c4-b5a6-7890-abcd-hardpodflow01'
    collection['info']['name'] = 'IRoute — Hard POD Flow (A7 → A7H)'
    collection['info']['description'] = (
        job_flow['info'].get('description', '').split('\n\nHARD POD')[0].split('\n\nVIDEO')[0]
        + HARD_POD_EXTRA
    )
    collection['variable'] = _append_hard_pod_variables(collection.get('variable', []))
    collection.pop('auth', None)
    collection.pop('event', None)

    items = collection['item']
    _patch_login_requests(items)
    _patch_sync_metadata_environment_saves(collection)
    _patch_pod_capture_sync_10a(items)
    _patch_pod_capture_step_10(items)

    a7_idx = _find_a7_index(items)
    # Remove old hard pod steps if re-running generator on already-patched collection
    while a7_idx + 1 < len(items) and items[a7_idx + 1]['name'].startswith('11b'):
        items.pop(a7_idx + 1)
    items[a7_idx + 1:a7_idx + 1] = _hard_pod_confirmation_items()

    OUT_COLL.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    api_coll = _build_api_collection()
    OUT_API_COLL.write_text(json.dumps(api_coll, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    env = {
        'id': '91aeb7d6-3c8b-4ba1-bfbe-6c23a84e4088',
        'name': 'IRoute Hard POD Flow — Local',
        'values': [
            {'key': k, 'value': v, 'type': t, 'enabled': True}
            for k, v, t in ENV_VALUES
        ],
        '_postman_variable_scope': 'environment',
        '_postman_exported_at': '2026-06-05T12:00:00.000Z',
        '_postman_exported_using': 'Cursor',
    }
    OUT_ENV.write_text(json.dumps(env, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    print(f'Wrote {OUT_COLL}')
    print(f'Wrote {OUT_API_COLL}')
    print(f'Wrote {OUT_ENV}')


if __name__ == '__main__':
    main()
