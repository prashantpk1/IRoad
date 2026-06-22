"""Generate IRoute_Dynamic_Job_POD_Flow_Collection.json"""
from __future__ import annotations

import json
import uuid

COLLECTION_ID = "a3f8c2e1-9b4d-4f7a-8e6c-1d2b3c4d5e6f"

HELPERS = r"""
function irouteSaveSync(data) {
  if (!data || !data.sync_metadata) return;
  var sm = data.sync_metadata;
  pm.collectionVariables.set('content_hash', sm.content_hash || '');
  pm.collectionVariables.set('workflow_version', sm.workflow_version || '');
  try { pm.environment.set('content_hash', sm.content_hash || ''); } catch (e) {}
  try { pm.environment.set('workflow_version', sm.workflow_version || ''); } catch (e) {}
}
function irouteSavePodSync(data) {
  if (!data) return;
  pm.collectionVariables.set('pod_content_hash', data.content_hash || '');
  pm.collectionVariables.set('pod_workflow_version', data.workflow_version || '');
}
function irouteAssertToken() {
  var t = pm.variables.get('access_token') || '';
  if (!t || String(t).indexOf('{{') >= 0) throw new Error('Run 00 → 01 Login first.');
}
function irouteLogHint(hint, label) {
  hint = hint || {};
  console.log('=== ' + (label || 'HINT') + ' ===');
  console.log('action:', hint.action, '| code:', hint.action_code, '| screen:', hint.screen);
  console.log('reason:', hint.reason);
  console.log('capture_mode:', hint.capture_mode, '| job_closed:', hint.job_closed);
}
function irouteSaveDashboardJob(d) {
  d = d || {};
  var active = d.active_job || {};
  var current = d.current_job || {};
  if (active.job_id) {
    var jt = active.job_type || 'shipment';
    pm.collectionVariables.set('job_id', active.job_id);
    pm.collectionVariables.set('job_type', jt);
    try { pm.environment.set('job_id', active.job_id); pm.environment.set('job_type', jt); } catch (e) {}
    if (jt === 'booking') {
      pm.collectionVariables.set('booking_id', active.job_id);
      try { pm.environment.set('booking_id', active.job_id); } catch (e) {}
    }
    if (jt === 'shipment') {
      pm.collectionVariables.set('shipment_id', active.job_id);
      try { pm.environment.set('shipment_id', active.job_id); } catch (e) {}
    }
  }
  if (current.booking_id) pm.collectionVariables.set('booking_id', current.booking_id);
  if (active.job_no) {
    pm.collectionVariables.set('shipment_no', active.job_no);
    try { pm.environment.set('shipment_no', active.job_no); } catch (e) {}
  }
}
function irouteTransitionToShipment(d) {
  var active = (d || {}).active_job || {};
  if (active.job_type === 'shipment' && active.job_id) {
    pm.collectionVariables.set('job_id', active.job_id);
    pm.collectionVariables.set('job_type', 'shipment');
    pm.collectionVariables.set('shipment_id', active.job_id);
    pm.collectionVariables.set('shipment_born', 'true');
    try {
      pm.environment.set('job_id', active.job_id);
      pm.environment.set('job_type', 'shipment');
      pm.environment.set('shipment_id', active.job_id);
    } catch (e) {}
  }
}
function iroutePickNextAction(data) {
  data = data || {};
  var hint = data.next_action_hint || {};
  var wf = data.workflow || {};
  var allowed = wf.allowed_actions || [];
  var primary = wf.primary_action || wf.next_action || {};
  var row = {};
  if (hint.action_code) {
    var match = allowed.find(function (a) { return a.action_code === hint.action_code; }) || {};
    row = {
      action_code: hint.action_code,
      execution_label: match.execution_label || match.action_name || hint.action_code,
      execution_requirements: match.execution_requirements || {}
    };
  }
  if (!row.action_code && primary && primary.action_code) row = primary;
  if (!row.action_code && allowed.length) row = allowed[0];
  return row || {};
}
function irouteSyncJobDetail(data) {
  data = data || {};
  var job = data.job || {};
  var wf = data.workflow || {};
  var meta = wf.workflow_metadata || {};
  var allowed = wf.allowed_actions || [];
  irouteSaveSync(data);
  var pod = data.pod_cod || {};
  var hint = data.next_action_hint || {};
  var hard = pod.hard_pod_pending === true || ((pod.hard_copy_confirmation || {}).required === true);
  pm.collectionVariables.set('hard_pod_required', hard ? 'true' : 'false');
  pm.collectionVariables.set('pod_branch', hard ? 'hard_pod' : 'digital_only');
  pm.collectionVariables.set('workflow_context_label', meta.context_label || '');
  pm.collectionVariables.set('allowed_action_count', String(meta.allowed_action_count != null ? meta.allowed_action_count : allowed.length));
  if (job.job_id) {
    pm.collectionVariables.set('job_id', job.job_id);
    pm.collectionVariables.set('job_type', job.job_type || pm.collectionVariables.get('job_type') || 'shipment');
    if (job.job_type === 'booking') pm.collectionVariables.set('booking_id', job.job_id);
    if (job.job_type === 'shipment') pm.collectionVariables.set('shipment_id', job.job_id);
    if (job.job_no) pm.collectionVariables.set('shipment_no', job.job_no);
  }
  var row = iroutePickNextAction(data);
  var code = (row.action_code || '').trim();
  var req = row.execution_requirements || {};
  pm.collectionVariables.set('execute_action_code', code);
  pm.collectionVariables.set('execute_action_label', row.execution_label || row.action_name || code);
  pm.collectionVariables.set('execute_use_multipart', (req.auto_shipment_post || (req.photo && (req.photo_min_count || 0) >= 1)) ? 'true' : 'false');
  pm.collectionVariables.set('execute_use_cod', (job.order_type === 'COD' && req.auto_treasury_post) ? 'true' : 'false');
  pm.collectionVariables.set('needs_pod_capture', (hint.action === 'go_to_pod_capture' && hint.capture_mode === 'digital_evidence') ? 'true' : 'false');
  pm.collectionVariables.set('needs_hard_pod_confirm', (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation') ? 'true' : 'false');
  if (req.auto_pod_post || hint.action === 'go_to_pod_capture') {
    pm.collectionVariables.set('pod_upload_action_code', code || pm.collectionVariables.get('pod_upload_action_code') || '');
  }
  if (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation') {
    pm.collectionVariables.set('hard_copy_action_code', hint.action_code || code);
  }
  pm.collectionVariables.set('job_closed', hint.job_closed === true ? 'true' : 'false');
  pm.collectionVariables.set('execute_client_action_id', (code || 'act').toLowerCase().replace(/[^a-z0-9]+/g, '-') + '-' + pm.variables.replaceIn('{{$guid}}'));
  console.log('execute_action_code:', code || '(empty)');
  console.log('context:', meta.context_label || '(none)');
  console.log('allowed_action_count:', pm.collectionVariables.get('allowed_action_count'));
  irouteLogHint(hint, 'SYNC');
  return code;
}
function irouteAssertExecuteAction(data, optional) {
  var code = pm.variables.get('execute_action_code');
  var hint = (data || {}).next_action_hint || {};
  if (code || hint.job_closed === true) return;
  if (optional) return;
  var label = pm.variables.get('workflow_context_label') || '';
  var help = label.indexOf('no shipment') >= 0
    ? 'Booking has no preshipment actions. Portal: add Start Job + Pickup + Loading + Confirm Loaded (Auto Shipment ON), assign driver, booking Confirmed.'
    : 'API returned allowed_actions=[]. Check Action Master + job assignment.';
  pm.test('execute_action_code set — ' + help, function () {
    pm.expect(code, help + ' | context: ' + label).to.be.ok;
  });
}
function irouteNewClientActionId() {
  var code = (pm.variables.get('execute_action_code') || 'act').toLowerCase();
  return code.replace(/[^a-z0-9]+/g, '-') + '-' + pm.variables.replaceIn('{{$guid}}');
}
function irouteSkipIfNoAction() {
  if (!pm.variables.get('execute_action_code') || pm.variables.get('job_closed') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipUnless(flag) {
  if (pm.variables.get(flag) !== 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfDelegatedCapture() {
  if (pm.variables.get('needs_pod_capture') === 'true' || pm.variables.get('needs_hard_pod_confirm') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteBuildExecuteBody() {
  var body = {
    client_action_id: pm.variables.get('execute_client_action_id'),
    workflow_version: pm.variables.get('workflow_version'),
    content_hash: pm.variables.get('content_hash'),
    latitude: 21.3891,
    longitude: 39.8579,
    notes: 'Dynamic ' + pm.variables.get('execute_action_code') + ' — ' + pm.variables.get('shipment_no')
  };
  if (pm.variables.get('execute_use_cod') === 'true') {
    var amt = parseFloat(pm.variables.get('mobile_cod_amount') || '0');
    body.mobile_cod_amount = isNaN(amt) ? 0 : amt;
  }
  return JSON.stringify(body, null, 2);
}
"""


def auth_header():
    return [
        {"key": "Authorization", "value": "Bearer {{access_token}}"},
        {"key": "Accept-Language", "value": "{{accept_language}}"},
    ]


def dashboard_request(name: str, *, optional: bool = False):
    tests = [
        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
        "var d = pm.response.json().data || {};",
        "irouteSaveDashboardJob(d);",
        "irouteTransitionToShipment(d);",
    ]
    if not optional:
        tests.append(
            "pm.test('dashboard OK', function () { pm.expect(pm.response.code).to.eql(200); });"
        )
    return {
        "name": name,
        "request": {
            "method": "GET",
            "header": auth_header(),
            "url": "{{base_url}}/driver/dashboard/",
        },
        "event": [
            {
                "listen": "test",
                "script": {"type": "text/javascript", "exec": tests},
            }
        ],
    }


def job_detail_request(name: str, *, assert_action: bool = True, optional: bool = False):
    tests = [
        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
        "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
        "var data = (pm.response.json().data || {});",
        "irouteSyncJobDetail(data);",
        "pm.test('status success', function () { pm.expect(pm.response.json().status).to.eql(1); });",
    ]
    if assert_action:
        tests.append(
            f"irouteAssertExecuteAction(data, {'true' if optional else 'false'});"
        )
    return {
        "name": name,
        "request": {
            "method": "GET",
            "header": auth_header(),
            "url": "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
        },
        "event": [
            {
                "listen": "test",
                "script": {"type": "text/javascript", "exec": tests},
            }
        ],
    }


def execute_json(name: str):
    return {
        "name": name,
        "request": {
            "method": "POST",
            "header": auth_header(),
            "url": "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
            "body": {
                "mode": "raw",
                "raw": "{}",
                "options": {"raw": {"language": "json"}},
            },
        },
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                        "irouteAssertToken();",
                        "if (pm.variables.get('execute_use_multipart') === 'true') { if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest(); }",
                        "irouteSkipIfDelegatedCapture();",
                        "irouteSkipIfNoAction();",
                        "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                        "pm.request.body.raw = irouteBuildExecuteBody();",
                    ],
                },
            },
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                        "if (pm.response.code === 204 || !pm.response.text()) return;",
                        "var resp = pm.response.json();",
                        "if (resp.status === 1 && resp.data) {",
                        "  irouteSyncJobDetail(resp.data);",
                        "  irouteTransitionToShipment({active_job: resp.data.job});",
                        "}",
                        "pm.test('Execute OK or skipped', function () { pm.expect([200,201,204]).to.include(pm.response.code); });",
                    ],
                },
            },
        ],
    }


def execute_multipart(name: str):
    return {
        "name": name,
        "request": {
            "method": "POST",
            "header": auth_header(),
            "url": "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
            "body": {
                "mode": "formdata",
                "formdata": [
                    {"key": "client_action_id", "value": "{{execute_client_action_id}}", "type": "text"},
                    {"key": "workflow_version", "value": "{{workflow_version}}", "type": "text"},
                    {"key": "content_hash", "value": "{{content_hash}}", "type": "text"},
                    {"key": "latitude", "value": "21.4858", "type": "text"},
                    {"key": "longitude", "value": "39.1925", "type": "text"},
                    {"key": "notes", "value": "Dynamic multipart {{execute_action_code}}", "type": "text"},
                    {"key": "media[0][media_type]", "value": "photo", "type": "text"},
                    {"key": "media[0][file_ref]", "type": "file", "src": []},
                    {"key": "media[1][media_type]", "value": "photo", "type": "text"},
                    {"key": "media[1][file_ref]", "type": "file", "src": []},
                ],
            },
        },
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                        "irouteSkipUnless('execute_use_multipart');",
                        "irouteSkipIfDelegatedCapture();",
                        "irouteSkipIfNoAction();",
                        "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                    ],
                },
            },
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                        "if (pm.response.code === 204 || !pm.response.text()) return;",
                        "var resp = pm.response.json();",
                        "pm.test('Multipart execute OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
                        "if (resp.status === 1 && resp.data) { irouteSyncJobDetail(resp.data); irouteTransitionToShipment({active_job: resp.data.job}); }",
                    ],
                },
            },
        ],
    }


def cycle_folder(n: int):
    return {
        "name": f"Cycle {n:02d} — Job Detail + Execute",
        "item": [
            job_detail_request(f"{n:02d}a — Job Detail (sync next action)"),
            execute_multipart(f"{n:02d}b — Execute Next (multipart if required)"),
            execute_json(f"{n:02d}c — Execute Next (JSON)"),
            dashboard_request(f"{n:02d}d — Dashboard (pick shipment if born)", optional=True),
        ],
    }


def assign_postman_ids(node: dict | list) -> None:
    if isinstance(node, list):
        for item in node:
            assign_postman_ids(item)
        return
    if not isinstance(node, dict):
        return
    if "item" in node or "request" in node:
        node.setdefault("id", str(uuid.uuid4()))
    for key in ("item",):
        if key in node:
            assign_postman_ids(node[key])


def main() -> None:
    collection = {
        "info": {
            "_postman_id": COLLECTION_ID,
            "name": "IRoute — Dynamic Job + POD Flow (no hardcoded A1/A2)",
            "description": (
                "# Dynamic Job + POD Flow (v2)\n\n"
                "Uses `workflow.allowed_actions[0].action_code` — **no hardcoded A1/A2/OA codes**.\n\n"
                "## Before run (portal)\n"
                "1. Booking **Confirmed**, truck + driver assigned\n"
                "2. Action Master must include **preshipment** steps for booking:\n"
                "   Start Job → Pickup → Loading → Confirm Loaded (**Auto Shipment ON**)\n"
                "3. Set `driver_email`, `driver_password`, `mobile_cod_amount` (COD)\n"
                "4. Set `base_url` if not `http://127.0.0.1:8000/api/v1/mobile`\n\n"
                "## Run order\n"
                "Run folder **00** then **01** cycles in order (or Run Collection).\n"
                "Each cycle: **01a Job Detail** sets `execute_action_code` → **01b/01c Execute**.\n\n"
                "## If execute_action_code empty\n"
                "Check Tests tab on Job Detail — message explains `context_label` from API."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000/api/v1/mobile"},
            {"key": "_iroute_dynamic_helpers", "value": HELPERS.strip()},
            {"key": "driver_email", "value": ""},
            {"key": "driver_password", "value": ""},
            {"key": "access_token", "value": ""},
            {"key": "booking_id", "value": ""},
            {"key": "shipment_id", "value": ""},
            {"key": "job_id", "value": ""},
            {"key": "job_type", "value": "booking"},
            {"key": "shipment_no", "value": ""},
            {"key": "content_hash", "value": ""},
            {"key": "workflow_version", "value": ""},
            {"key": "execute_action_code", "value": ""},
            {"key": "execute_action_label", "value": ""},
            {"key": "execute_client_action_id", "value": ""},
            {"key": "execute_use_multipart", "value": "false"},
            {"key": "execute_use_cod", "value": "false"},
            {"key": "needs_pod_capture", "value": "false"},
            {"key": "needs_hard_pod_confirm", "value": "false"},
            {"key": "hard_pod_required", "value": "false"},
            {"key": "pod_upload_action_code", "value": ""},
            {"key": "hard_copy_action_code", "value": ""},
            {"key": "job_closed", "value": "false"},
            {"key": "workflow_context_label", "value": ""},
            {"key": "allowed_action_count", "value": "0"},
            {"key": "capture_bundle_id", "value": ""},
            {"key": "pod_content_hash", "value": ""},
            {"key": "pod_workflow_version", "value": ""},
            {"key": "pod_video_duration_seconds", "value": "8"},
            {"key": "hard_pod_confirmed_pages_json", "value": "[]"},
            {"key": "hard_pod_custody_submission_id", "value": ""},
            {"key": "hard_pod_client_submission_id", "value": ""},
            {"key": "hard_pod_receiver_name", "value": "Receiver Name"},
            {"key": "hard_pod_receiver_contact", "value": "0500000000"},
            {"key": "hard_pod_handoff_notes", "value": "Hard copy DN collected"},
            {"key": "mobile_cod_amount", "value": "100"},
            {"key": "accept_language", "value": "en"},
        ],
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');"
                    ],
                },
            }
        ],
        "item": [],
    }

    collection["item"].append(
        {
            "name": "00 — Login & Dashboard",
            "description": "Login → Dashboard picks active job → Job Detail syncs first action code.",
            "item": [
                {
                    "name": "01 — Login",
                    "request": {
                        "method": "POST",
                        "header": [{"key": "Accept-Language", "value": "{{accept_language}}"}],
                        "url": "{{base_url}}/driver/auth/login/",
                        "body": {
                            "mode": "raw",
                            "raw": json.dumps(
                                {"email": "{{driver_email}}", "password": "{{driver_password}}"}
                            ),
                            "options": {"raw": {"language": "json"}},
                        },
                    },
                    "event": [
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "var r = pm.response.json();",
                                    "pm.test('Login OK', function () { pm.expect(r.status).to.eql(1); });",
                                    "pm.collectionVariables.set('access_token', r.data.access_token);",
                                    "try { pm.environment.set('access_token', r.data.access_token); } catch (e) {}",
                                ],
                            },
                        }
                    ],
                },
                dashboard_request("02 — Dashboard"),
                job_detail_request("03 — Initial Job Detail (sets execute_action_code)"),
            ],
        }
    )

    collection["item"].append(
        {
            "name": "01 — Dynamic Workflow Cycles",
            "description": (
                "Always run **01a** before **01b/01c**. "
                "`execute_action_code` comes from `allowed_actions[0]`."
            ),
            "item": [cycle_folder(i) for i in range(1, 13)],
        }
    )

    collection["item"].append(
        {
            "name": "02 — POD Digital Capture",
            "item": [
                {
                    "name": "01 — POD Capture Sync",
                    "request": {
                        "method": "GET",
                        "header": auth_header(),
                        "url": "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
                    },
                    "event": [
                        {
                            "listen": "prerequest",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "irouteSkipUnless('needs_pod_capture');",
                                ],
                            },
                        },
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "if (pm.response.code === 204 || !pm.response.text()) return;",
                                    "irouteSavePodSync(pm.response.json().data || {});",
                                ],
                            },
                        },
                    ],
                },
                {
                    "name": "02 — POD Capture POST",
                    "request": {
                        "method": "POST",
                        "header": auth_header(),
                        "url": "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
                        "body": {
                            "mode": "formdata",
                            "formdata": [
                                {"key": "client_capture_id", "value": "pod-{{$guid}}", "type": "text"},
                                {"key": "content_hash", "value": "{{pod_content_hash}}", "type": "text"},
                                {"key": "workflow_version", "value": "{{pod_workflow_version}}", "type": "text"},
                                {"key": "pod_type", "value": "digital", "type": "text"},
                                {"key": "target_action_code", "value": "{{pod_upload_action_code}}", "type": "text"},
                                {"key": "latitude", "value": "21.3891", "type": "text"},
                                {"key": "longitude", "value": "39.8579", "type": "text"},
                                {"key": "media[0][media_type]", "value": "photo", "type": "text"},
                                {"key": "media[0][file_ref]", "type": "file", "src": []},
                                {"key": "media[1][media_type]", "value": "signature", "type": "text"},
                                {"key": "media[1][file_ref]", "type": "file", "src": []},
                                {"key": "media[2][media_type]", "value": "video", "type": "text"},
                                {"key": "media[2][duration_seconds]", "value": "{{pod_video_duration_seconds}}", "type": "text"},
                                {"key": "media[2][file_ref]", "type": "file", "src": []},
                            ],
                        },
                    },
                    "event": [
                        {
                            "listen": "prerequest",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "irouteSkipUnless('needs_pod_capture');",
                                ],
                            },
                        },
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "if (pm.response.code === 204 || !pm.response.text()) return;",
                                    "var d = pm.response.json().data || {};",
                                    "var id = (d.capture_bundle || {}).capture_bundle_id || d.capture_bundle_id || '';",
                                    "pm.collectionVariables.set('capture_bundle_id', id);",
                                ],
                            },
                        },
                    ],
                },
                {
                    "name": "03 — Execute POD upload (dynamic code)",
                    "request": {
                        "method": "POST",
                        "header": auth_header(),
                        "url": "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{pod_upload_action_code}}/execute/",
                        "body": {
                            "mode": "raw",
                            "raw": json.dumps(
                                {
                                    "client_action_id": "{{execute_client_action_id}}",
                                    "workflow_version": "{{workflow_version}}",
                                    "content_hash": "{{content_hash}}",
                                    "latitude": 21.3891,
                                    "longitude": 39.8579,
                                    "notes": "Dynamic POD upload",
                                    "capture_bundle_id": "{{capture_bundle_id}}",
                                },
                                indent=2,
                            ),
                            "options": {"raw": {"language": "json"}},
                        },
                    },
                    "event": [
                        {
                            "listen": "prerequest",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "irouteSkipUnless('needs_pod_capture');",
                                    "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                                ],
                            },
                        },
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "if (pm.response.code === 204 || !pm.response.text()) return;",
                                    "irouteSyncJobDetail((pm.response.json().data || {}));",
                                ],
                            },
                        },
                    ],
                },
            ],
        }
    )

    collection["item"].append(
        {
            "name": "03 — Hard POD Branch",
            "item": [
                {
                    "name": "01 — Hard POD Documents",
                    "request": {
                        "method": "GET",
                        "header": auth_header(),
                        "url": "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/hard-pod/documents/",
                    },
                    "event": [
                        {
                            "listen": "prerequest",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "irouteSkipUnless('hard_pod_required');",
                                ],
                            },
                        },
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "if (pm.response.code === 204 || !pm.response.text()) return;",
                                    "var pages = (pm.response.json().data || {}).pages || [];",
                                    "var confirmed = pages.map(function (p) { return { page_id: p.page_id, document_id: p.document_id, line_no: p.line_no || 1, confirmed: true }; });",
                                    "pm.collectionVariables.set('hard_pod_confirmed_pages_json', JSON.stringify(confirmed));",
                                    "pm.collectionVariables.set('hard_pod_client_submission_id', 'hard-' + Date.now());",
                                ],
                            },
                        },
                    ],
                },
                {
                    "name": "02 — Hard POD Submit",
                    "request": {
                        "method": "POST",
                        "header": auth_header(),
                        "url": "{{base_url}}/driver/hard-pod/submit/",
                        "body": {
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
                    },
                    "event": [
                        {
                            "listen": "prerequest",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "irouteSkipUnless('hard_pod_required');",
                                ],
                            },
                        },
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "if (pm.response.code === 204 || !pm.response.text()) return;",
                                    "var sub = (pm.response.json().data || {}).custody_submission || {};",
                                    "pm.collectionVariables.set('hard_pod_custody_submission_id', sub.submission_id || '');",
                                ],
                            },
                        },
                    ],
                },
                job_detail_request("03 — Job Detail (hard-copy action)", optional=True),
                {
                    "name": "04 — Execute Hard Copy (dynamic code)",
                    "request": {
                        "method": "POST",
                        "header": auth_header(),
                        "url": "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{hard_copy_action_code}}/execute/",
                        "body": {
                            "mode": "raw",
                            "raw": json.dumps(
                                {
                                    "client_action_id": "{{execute_client_action_id}}",
                                    "workflow_version": "{{workflow_version}}",
                                    "content_hash": "{{content_hash}}",
                                    "latitude": 21.3891,
                                    "longitude": 39.8579,
                                    "notes": "Hard copy confirmation",
                                    "custody_submission_id": "{{hard_pod_custody_submission_id}}",
                                    "client_submission_id": "{{hard_pod_client_submission_id}}",
                                },
                                indent=2,
                            ),
                            "options": {"raw": {"language": "json"}},
                        },
                    },
                    "event": [
                        {
                            "listen": "prerequest",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "irouteSkipUnless('hard_pod_required');",
                                    "if (!pm.variables.get('hard_copy_action_code')) pm.collectionVariables.set('hard_copy_action_code', pm.variables.get('execute_action_code'));",
                                    "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                                ],
                            },
                        },
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                                    "if (pm.response.code === 204 || !pm.response.text()) return;",
                                    "irouteSyncJobDetail((pm.response.json().data || {}));",
                                ],
                            },
                        },
                    ],
                },
            ],
        }
    )

    collection["item"].append(
        {"name": "04 — Closeout Cycles", "item": [cycle_folder(i) for i in range(13, 16)]}
    )

    final_detail = job_detail_request("Final Job Detail", assert_action=False)
    final_detail["event"] = [
        {
            "listen": "test",
            "script": {
                "type": "text/javascript",
                "exec": [
                    "eval(pm.collectionVariables.get('_iroute_dynamic_helpers') || '');",
                    "var data = pm.response.json().data || {};",
                    "irouteSyncJobDetail(data);",
                    "pm.test('job closed', function () { pm.expect((data.next_action_hint || {}).job_closed).to.eql(true); });",
                ],
            },
        }
    ]
    collection["item"].append(
        {"name": "05 — Verify Job Closed", "item": [final_detail]}
    )

    assign_postman_ids(collection)

    path = "postman/IRoute_Dynamic_Job_POD_Flow_Collection.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(collection, handle, indent=2, ensure_ascii=False)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
