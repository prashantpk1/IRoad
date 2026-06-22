"""Generate dynamic Auto Shipment + POD Branching Postman collection + environment."""
from __future__ import annotations

import json
import uuid

COLLECTION_ID = "f4e8d1c2-7a3b-4e5f-9c0d-1e2f3a4b5c6d"
ENV_ID = "e5f9e2d3-8b4c-5f6a-0d1e-2f3a4b5c6d7e"

HELPERS = r"""
function irouteEnvSet(key, val) {
  pm.collectionVariables.set(key, val);
  try { pm.environment.set(key, val); } catch (e) {}
}
function irouteSaveSync(data) {
  if (!data || !data.sync_metadata) return;
  var sm = data.sync_metadata;
  irouteEnvSet('content_hash', sm.content_hash || '');
  irouteEnvSet('workflow_version', sm.workflow_version || '');
}
function irouteSavePodSync(data) {
  if (!data) return;
  irouteEnvSet('pod_content_hash', data.content_hash || '');
  irouteEnvSet('pod_workflow_version', data.workflow_version || '');
}
function irouteSaveJobIds(data) {
  var job = data.job || {};
  var sid = job.job_id || data.shipment_id || '';
  if (sid) {
    irouteEnvSet('shipment_id', sid);
    irouteEnvSet('job_id', sid);
    irouteEnvSet('job_type', job.job_type || 'shipment');
  }
  if (job.job_no) irouteEnvSet('shipment_no', job.job_no);
}
function irouteSaveBranchState(data) {
  var pod = data.pod_cod || {};
  var hint = data.next_action_hint || {};
  var hard = pod.hard_pod_pending === true || ((pod.hard_copy_confirmation || {}).required === true);
  irouteEnvSet('hard_pod_required', hard ? 'true' : 'false');
  irouteEnvSet('pod_branch', hard ? 'hard_pod' : 'digital_only');
  irouteEnvSet('next_action_code', String(hint.action_code || ''));
}
function irouteAssertToken() {
  var t = pm.variables.get('access_token') || '';
  if (!t || String(t).indexOf('{{') >= 0) throw new Error('Run Login first.');
}
function irouteLogHint(hint, label) {
  hint = hint || {};
  console.log('=== ' + (label || 'HINT') + ' ===');
  console.log('action:', hint.action, '| code:', hint.action_code, '| screen:', hint.screen);
  console.log('capture_mode:', hint.capture_mode, '| ui_mode:', hint.ui_mode);
  console.log('reason:', hint.reason, '| job_closed:', hint.job_closed);
}
function irouteSaveDashboardJob(d) {
  d = d || {};
  var active = d.active_job || {};
  var current = d.current_job || {};
  if (active.job_id) {
    var jt = active.job_type || 'shipment';
    irouteEnvSet('job_id', active.job_id);
    irouteEnvSet('job_type', jt);
    if (jt === 'booking') irouteEnvSet('booking_id', active.job_id);
    if (jt === 'shipment') irouteEnvSet('shipment_id', active.job_id);
  }
  if (current.booking_id) irouteEnvSet('booking_id', current.booking_id);
  if (active.job_no) irouteEnvSet('shipment_no', active.job_no);
}
function irouteTransitionToShipment(d) {
  var active = (d || {}).active_job || {};
  if (active.job_type === 'shipment' && active.job_id) {
    irouteEnvSet('job_id', active.job_id);
    irouteEnvSet('job_type', 'shipment');
    irouteEnvSet('shipment_id', active.job_id);
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
  var ship = ((d || {}).current_job || {}).active_shipment || {};
  if (ship.shipment_id) irouteEnvSet('shipment_id', ship.shipment_id);
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
function irouteFindActionByFlag(allowed, flag) {
  allowed = allowed || [];
  for (var i = 0; i < allowed.length; i++) {
    var req = allowed[i].execution_requirements || {};
    if (req[flag] === true) return allowed[i];
  }
  return null;
}
function irouteSyncJobDetail(data) {
  data = data || {};
  var job = data.job || {};
  var wf = data.workflow || {};
  var meta = wf.workflow_metadata || {};
  var allowed = wf.allowed_actions || [];
  var hint = data.next_action_hint || {};
  var pod = data.pod_cod || {};
  irouteSaveSync(data);
  irouteSaveBranchState(data);
  irouteSyncWorkflowStage(data);
  irouteEnvSet('workflow_context_label', meta.context_label || '');
  irouteEnvSet('allowed_action_count', String(meta.allowed_action_count != null ? meta.allowed_action_count : allowed.length));
  if (job.job_id) {
    irouteEnvSet('job_id', job.job_id);
    irouteEnvSet('job_type', job.job_type || pm.variables.get('job_type') || 'shipment');
    if (job.job_type === 'booking') irouteEnvSet('booking_id', job.job_id);
    if (job.job_type === 'shipment') irouteEnvSet('shipment_id', job.job_id);
    if (job.job_no) irouteEnvSet('shipment_no', job.job_no);
  }
  var row = iroutePickNextAction(data);
  var code = (row.action_code || '').trim();
  var req = row.execution_requirements || {};
  irouteEnvSet('execute_action_code', code);
  irouteEnvSet('execute_action_label', row.execution_label || row.action_name || code);
  irouteEnvSet('execute_use_multipart', (req.auto_shipment_post || (req.photo && (req.photo_min_count || 0) >= 1)) ? 'true' : 'false');
  irouteEnvSet('execute_use_cod', (job.order_type === 'COD' && req.auto_treasury_post) ? 'true' : 'false');
  irouteEnvSet('execute_is_pod_action', (req.auto_pod_post === true) ? 'true' : 'false');
  irouteEnvSet('needs_pod_capture', (hint.action === 'go_to_pod_capture' && hint.capture_mode === 'digital_evidence') ? 'true' : 'false');
  irouteEnvSet('needs_hard_pod_confirm', (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation') ? 'true' : 'false');
  var podRow = irouteFindActionByFlag(allowed, 'auto_pod_post');
  if (podRow && podRow.action_code) {
    irouteEnvSet('pod_upload_action_code', podRow.action_code);
    irouteEnvSet('ready_for_pod', 'true');
  } else if (req.auto_pod_post || hint.action === 'go_to_pod_capture') {
    irouteEnvSet('pod_upload_action_code', code || pm.variables.get('pod_upload_action_code') || '');
    irouteEnvSet('ready_for_pod', 'true');
  }
  var hardRow = irouteFindActionByFlag(allowed, 'hard_copy_collection');
  if (hardRow && hardRow.action_code) irouteEnvSet('hard_copy_action_code', hardRow.action_code);
  if (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation' || (pod.hard_copy_confirmation || {}).required) {
    irouteEnvSet('hard_copy_action_code', hint.action_code || code);
  }
  if (row.hard_copy_collection || req.hard_copy_collection) {
    irouteEnvSet('hard_copy_action_code', code);
  }
  if (job.job_type === 'shipment' && job.job_id) irouteEnvSet('auto_shipment_a4_done', 'true');
  irouteEnvSet('job_closed', hint.job_closed === true ? 'true' : 'false');
  console.log('execute_action_code:', code || '(empty)', '| context:', meta.context_label || '');
  console.log('workflow_path:', pm.variables.get('workflow_path') || '(unset)', '| ready_for_pod:', pm.variables.get('ready_for_pod'));
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
    ? 'Add preshipment actions in Action Master: Start Job, Pickup, Loading, Confirm Loaded (Auto Shipment ON).'
    : 'allowed_actions is empty — check Action Master and driver assignment.';
  pm.test('execute_action_code required — ' + help, function () {
    pm.expect(code, help + ' | ' + label).to.be.ok;
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
function irouteSkipIfHardPod() {
  if (pm.variables.get('hard_pod_required') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfDigitalOnly() {
  if (pm.variables.get('hard_pod_required') !== 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSyncWorkflowStage(data) {
  data = data || {};
  var wf = data.workflow || {};
  var meta = wf.workflow_metadata || {};
  var stage = (wf.current_stage || meta.operational_stage || '').trim();
  irouteEnvSet('current_stage', stage);
  var hint = data.next_action_hint || {};
  irouteEnvSet('next_screen', hint.screen || '');
  console.log('MOBILE UI stage:', stage || '(unknown)',
    '| execute:', pm.variables.get('execute_action_code') || hint.action_code || '(none)');
}
function irouteRouteAfterBookingDetail(data) {
  data = data || {};
  var allowed = (data.workflow || {}).allowed_actions || [];
  var job = data.job || {};
  if (job.job_type === 'shipment' || pm.variables.get('auto_shipment_a4_done') === 'true') {
    irouteEnvSet('workflow_path', 'shipment_phase');
    return;
  }
  if (!allowed.length) {
    irouteEnvSet('workflow_path', 'shipment_only');
    irouteEnvSet('skip_preshipment', 'true');
    console.warn('>>> No preship actions on booking — use folder 00B (shipment already exists) or add Start Job/Pickup/Loading/Confirm Loaded.');
  } else {
    irouteEnvSet('workflow_path', 'full_preship');
    irouteEnvSet('skip_preshipment', 'false');
  }
}
function irouteSkipIfShipmentOnlyPath() {
  if (pm.variables.get('workflow_path') === 'shipment_only') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfShipmentBorn() {
  if (pm.variables.get('auto_shipment_a4_done') === 'true' || pm.variables.get('job_type') === 'shipment') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfReadyForPod() {
  if (pm.variables.get('ready_for_pod') === 'true' || pm.variables.get('needs_pod_capture') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfExecuteIsPod() {
  if (pm.variables.get('execute_is_pod_action') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipOptionalPostPod() {
  if (!pm.variables.get('execute_action_code') || pm.variables.get('job_closed') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfNotHardPod() {
  if (pm.variables.get('hard_pod_required') !== 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfDelegatedCapture() {
  if (pm.variables.get('needs_pod_capture') === 'true' || pm.variables.get('needs_hard_pod_confirm') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfPreshipDoneOnBooking() {
  if (pm.variables.get('auto_shipment_a4_done') === 'true' && pm.variables.get('job_type') === 'booking') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfSkipPreshipment() {
  if (pm.variables.get('skip_preshipment') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfNotPodReady() {
  var ready = pm.variables.get('ready_for_pod') === 'true' || pm.variables.get('needs_pod_capture') === 'true';
  var code = pm.variables.get('pod_upload_action_code') || '';
  if (!ready && !code) {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function iroutePrintSyncSummary() {
  console.log('--- SYNC VARS ---');
  console.log('execute_action_code:', pm.variables.get('execute_action_code') || '(empty)');
  console.log('pod_upload_action_code:', pm.variables.get('pod_upload_action_code') || '(empty)');
  console.log('hard_copy_action_code:', pm.variables.get('hard_copy_action_code') || '(empty)');
  console.log('job_type:', pm.variables.get('job_type'), '| job_id:', pm.variables.get('job_id'));
  console.log('multipart:', pm.variables.get('execute_use_multipart'), '| cod:', pm.variables.get('execute_use_cod'));
  console.log('execute_is_pod_action:', pm.variables.get('execute_is_pod_action'), '| workflow_path:', pm.variables.get('workflow_path'));
  console.log('current_stage (mobile UI):', pm.variables.get('current_stage') || '(unknown)');
  console.log('hard_pod_required:', pm.variables.get('hard_pod_required'), '| ready_for_pod:', pm.variables.get('ready_for_pod'));
}
function irouteBuildExecuteBody(extra) {
  extra = extra || {};
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
  if (extra.capture_bundle_id) body.capture_bundle_id = extra.capture_bundle_id;
  if (extra.custody_submission_id) body.custody_submission_id = extra.custody_submission_id;
  if (extra.client_submission_id) body.client_submission_id = extra.client_submission_id;
  return JSON.stringify(body, null, 2);
}
function irouteAssertAutoShipmentEnabled() {
  if (pm.variables.get('auto_shipment_enabled') !== 'true') {
    console.warn('auto_shipment_enabled is not true');
  }
}
"""


def auth_header():
    return [
        {"key": "Authorization", "value": "Bearer {{access_token}}"},
        {"key": "Accept-Language", "value": "{{accept_language}}"},
    ]


def assign_ids(node, seen: set[str] | None = None):
    if seen is None:
        seen = set()

    if isinstance(node, list):
        for item in node:
            assign_ids(item, seen)
        return

    if not isinstance(node, dict):
        return

    if "item" in node or "request" in node:
        new_id = str(uuid.uuid4())
        while new_id in seen:
            new_id = str(uuid.uuid4())
        seen.add(new_id)
        node["id"] = new_id

    if "item" in node:
        assign_ids(node["item"], seen)


def req_item(name, method, url, *, body=None, description="", prerequest=None, test=None):
    item = {
        "name": name,
        "request": {"method": method, "header": auth_header(), "url": url},
        "event": [],
    }
    if description:
        item["request"]["description"] = description
    if body:
        item["request"]["body"] = body
    if prerequest:
        item["event"].append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": prerequest}})
    if test:
        item["event"].append({"listen": "test", "script": {"type": "text/javascript", "exec": test}})
    return item


def job_detail(name, url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/", *, assert_action=True, optional=False, extra_test=None, prerequest=None):
    tests = [
        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
        "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
        "var data = pm.response.json().data || {};",
        "irouteSyncJobDetail(data);",
        f"irouteAssertExecuteAction(data, {'true' if optional else 'false'});",
        "iroutePrintSyncSummary();",
    ]
    if extra_test:
        tests.extend(extra_test)
    pre = ["eval(pm.collectionVariables.get('_iroute_helpers') || '');"]
    if prerequest:
        pre.extend(prerequest)
    return req_item(name, "GET", url, prerequest=pre if prerequest else None, test=tests)


def execute_dynamic(name, *, skip_preship=False, extra_body_keys=None, use_hard_copy_code=False):
    code_var = "{{hard_copy_action_code}}" if use_hard_copy_code else "{{execute_action_code}}"
    prerequest = [
        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
        "irouteAssertToken();",
    ]
    if skip_preship:
        prerequest.append("irouteSkipIfPreshipDoneOnBooking();")
    prerequest.extend([
        "if (pm.variables.get('execute_use_multipart') === 'true') { if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest(); }",
        "irouteSkipIfDelegatedCapture();",
        "irouteSkipIfNoAction();",
        "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
    ])
    extra = extra_body_keys or {}
    build_lines = ["var extra = " + json.dumps(extra) + ";"]
    if "capture_bundle_id" in extra:
        build_lines = ["var extra = { capture_bundle_id: pm.variables.get('capture_bundle_id') };"]
    elif use_hard_copy_code:
        build_lines = [
            "var extra = {",
            "  custody_submission_id: pm.variables.get('hard_pod_custody_submission_id'),",
            "  client_submission_id: pm.variables.get('hard_pod_client_submission_id')",
            "};",
        ]
    prerequest.append("pm.request.body.raw = irouteBuildExecuteBody(extra);")

    tests = [
        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
        "if (pm.response.code === 204 || !pm.response.text()) return;",
        "var resp = pm.response.json();",
        "pm.test('Execute OK', function () { pm.expect([200,201,204]).to.include(pm.response.code); });",
        "if (resp.status === 1 && resp.data) {",
        "  irouteSyncJobDetail(resp.data);",
        "  irouteSaveJobIds(resp.data);",
        "  irouteTransitionToShipment({active_job: resp.data.job});",
        "  if ((resp.data.job || {}).job_type === 'shipment') irouteEnvSet('auto_shipment_a4_done', 'true');",
        "}",
        "irouteLogHint((resp.data || {}).next_action_hint, '" + name + "');",
    ]
    url = f"{{{{base_url}}}}/driver/jobs/{{{{job_type}}}}/{{{{job_id}}}}/actions/{code_var}/execute/"
    return req_item(
        name,
        "POST",
        url,
        body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
        prerequest=prerequest,
        test=tests,
    )


def execute_multipart(name, *, skip_preship=False):
    prerequest = [
        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
        "irouteAssertToken();",
    ]
    if skip_preship:
        prerequest.append("irouteSkipIfPreshipDoneOnBooking();")
    prerequest.extend([
        "irouteSkipUnless('execute_use_multipart');",
        "irouteSkipIfDelegatedCapture();",
        "irouteSkipIfNoAction();",
        "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
    ])
    tests = [
        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
        "if (pm.response.code === 204 || !pm.response.text()) return;",
        "var resp = pm.response.json();",
        "pm.test('Multipart OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
        "if (resp.status === 1 && resp.data) {",
        "  irouteSyncJobDetail(resp.data);",
        "  irouteTransitionToShipment({active_job: resp.data.job});",
        "  irouteEnvSet('auto_shipment_a4_done', 'true');",
        "}",
    ]
    return req_item(
        name,
        "POST",
        "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
        body={
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
        description="Attach 2 photos when auto_shipment_post or photo required.",
        prerequest=prerequest,
        test=tests,
    )


def dynamic_cycle(n: int, label: str, *, booking_url: bool = False, skip_preship: bool = False, shipment_phase: bool = False):
    detail_url = "{{base_url}}/driver/jobs/booking/{{booking_id}}/" if booking_url else "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/"
    detail_pre = []
    exec_pre_extra = []
    if skip_preship:
        detail_pre = ["irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"]
        exec_pre_extra = ["irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"]
    if shipment_phase:
        exec_pre_extra.extend(["irouteSkipIfReadyForPod();", "irouteSkipIfExecuteIsPod();"])
    dash_pre = ["eval(pm.collectionVariables.get('_iroute_helpers') || '');"]
    if skip_preship:
        dash_pre.extend(["irouteSkipIfSkipPreshipment();", "irouteSkipIfPreshipDoneOnBooking();", "irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"])
    multipart = execute_multipart(f"{n:02d}b - Execute (multipart if required)", skip_preship=skip_preship)
    multipart["event"][0]["script"]["exec"].extend(exec_pre_extra)
    json_exec = execute_dynamic(f"{n:02d}c - Execute (JSON)", skip_preship=skip_preship)
    json_exec["event"][0]["script"]["exec"].extend(exec_pre_extra)
    return {
        "name": f"Cycle {n:02d} - {label}",
        "item": [
            job_detail(
                f"{n:02d}a - Job Detail (sync action code)",
                url=detail_url,
                optional=True,
                prerequest=detail_pre or None,
            ),
            multipart,
            json_exec,
            req_item(
                f"{n:02d}d - Dashboard refresh",
                "GET",
                "{{base_url}}/driver/dashboard/",
                prerequest=dash_pre,
                test=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "var d = pm.response.json().data || {};",
                    "irouteSaveDashboardJob(d);",
                    "irouteTransitionToShipment(d);",
                ],
            ),
        ],
    }


def preship_cycle(n: int, label: str):
    return dynamic_cycle(n, f"Preship {label}", booking_url=True, skip_preship=True)


def mobile_workflow_cycle(n: int, milestone_label: str):
    """Unified mobile stepper cycle — uses active job_type/job_id (booking then shipment)."""
    return dynamic_cycle(n, milestone_label, booking_url=False, skip_preship=False, shipment_phase=True)


def workflow_cycle(n: int, label: str):
    return mobile_workflow_cycle(n, label)


def collection_variables():
    return [
        {"key": "base_url", "value": "http://127.0.0.1:8001/api/v1/mobile"},
        {"key": "_iroute_helpers", "value": HELPERS.strip()},
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
        {"key": "pod_branch", "value": ""},
        {"key": "pod_upload_action_code", "value": ""},
        {"key": "hard_copy_action_code", "value": ""},
        {"key": "next_action_code", "value": ""},
        {"key": "workflow_context_label", "value": ""},
        {"key": "current_stage", "value": ""},
        {"key": "next_screen", "value": ""},
        {"key": "allowed_action_count", "value": "0"},
        {"key": "job_closed", "value": "false"},
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
        {"key": "auto_shipment_enabled", "value": "true"},
        {"key": "auto_shipment_a4_done", "value": "false"},
        {"key": "skip_preshipment", "value": "false"},
        {"key": "workflow_path", "value": ""},
        {"key": "execute_is_pod_action", "value": "false"},
        {"key": "ready_for_pod", "value": "false"},
        {"key": "accept_language", "value": "en"},
    ]


def make_login():
    return req_item(
        "01 - Login (Email)",
        "POST",
        "{{base_url}}/driver/auth/login/",
        body={
            "mode": "raw",
            "raw": '{\n  "email": "{{driver_email}}",\n  "password": "{{driver_password}}"\n}',
            "options": {"raw": {"language": "json"}},
        },
        test=[
            "var r = pm.response.json();",
            "if (r.status === 1 && r.data && r.data.access_token) {",
            "  pm.collectionVariables.set('access_token', r.data.access_token);",
            "  try { pm.environment.set('access_token', r.data.access_token); } catch (e) {}",
            "  pm.test('Login OK', function () { pm.expect(r.status).to.eql(1); });",
            "} else { pm.test('Login failed', function () { pm.expect.fail(r.message); }); }",
        ],
    )


def build_collection():
    dashboard_booking = req_item(
        "02 - Dashboard (expect booking job)",
        "GET",
        "{{base_url}}/driver/dashboard/",
        prerequest=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "irouteAssertToken();",
            "irouteAssertAutoShipmentEnabled();",
        ],
        test=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
            "var d = pm.response.json().data || {};",
            "irouteSaveDashboardJob(d);",
            "pm.test('active_job present', function () { pm.expect((d.active_job || {}).job_id).to.be.ok; });",
            "var codes = ((d.workflow || {}).allowed_actions || []).map(function (a) { return a.action_code; });",
            "console.log('dashboard allowed_actions:', codes.join(', ') || '(none)');",
        ],
    )

    booking_detail = job_detail(
        "03 - Booking Job Detail",
        url="{{base_url}}/driver/jobs/booking/{{booking_id}}/",
        optional=True,
        extra_test=[
            "pm.test('job_type booking', function () { pm.expect((data.job || {}).job_type).to.eql('booking'); });",
            "irouteRouteAfterBookingDetail(data);",
            "var codes = (data.workflow.allowed_actions || []).map(function (a) { return a.action_code; });",
            "console.log('allowed_actions:', codes.join(', ') || '(none)');",
            "if (pm.variables.get('workflow_path') === 'shipment_only') {",
            "  console.warn('Preship cycles 04-07 will SKIP — run folder 00B then 02.');",
            "}",
        ],
    )

    dashboard_shipment = req_item(
        "08 - Dashboard (expect shipment after auto birth)",
        "GET",
        "{{base_url}}/driver/dashboard/",
        prerequest=["eval(pm.collectionVariables.get('_iroute_helpers') || '');", "irouteAssertToken();"],
        test=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "var d = pm.response.json().data || {};",
            "irouteTransitionToShipment(d);",
            "irouteSaveDashboardJob(d);",
            "pm.test('job_type shipment', function () { pm.expect((d.active_job || {}).job_type).to.eql('shipment'); });",
        ],
    )

    shipment_detail = job_detail(
        "09 - Shipment Job Detail (sync for POD flow)",
        url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
        extra_test=[
            "pm.test('job_type shipment', function () { pm.expect((data.job || {}).job_type).to.eql('shipment'); });",
            "irouteSaveJobIds(data);",
        ],
    )

    folder_00 = {
        "name": "00 - Auto Shipment ON (Pickup + Loading milestones → shipment birth)",
        "description": (
            "Maps to mobile UI Pickup + Loading steps (doc A2–A4). Requires Start Job (A1) plus "
            "Pickup, Loading, Confirm Loaded with Auto Shipment ON on Confirm Loaded only. "
            "If booking has no allowed_actions, cycles skip — use folder 00B."
        ),
        "item": [
            make_login(),
            dashboard_booking,
            booking_detail,
            preship_cycle(4, "Start Job (doc A1)"),
            preship_cycle(5, "Pickup milestone (doc A2)"),
            preship_cycle(6, "Loading milestone (doc A3)"),
            preship_cycle(7, "Loading complete + shipment birth (doc A4)"),
            dashboard_shipment,
            shipment_detail,
        ],
    }

    folder_00b = {
        "name": "00B - Shipment phase start (OA-0003+ no preshipment)",
        "description": (
            "Use when only shipment-phase actions exist (OA-0003 In Transit through OA-0006 POD). "
            "Shipment must already exist in portal. Sets skip_preshipment=true and workflow_path=shipment_only."
        ),
        "item": [
            make_login(),
            req_item(
                "02 - Dashboard (pick shipment job)",
                "GET",
                "{{base_url}}/driver/dashboard/",
                test=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "irouteEnvSet('skip_preshipment', 'true');",
                    "irouteEnvSet('workflow_path', 'shipment_only');",
                    "irouteEnvSet('auto_shipment_a4_done', 'true');",
                    "var d = pm.response.json().data || {};",
                    "irouteSaveDashboardJob(d);",
                    "irouteTransitionToShipment(d);",
                    "if (!pm.variables.get('shipment_id')) {",
                    "  var sid = pm.environment.get('shipment_id') || '';",
                    "  if (sid) { irouteEnvSet('shipment_id', sid); irouteEnvSet('job_id', sid); irouteEnvSet('job_type', 'shipment'); }",
                    "}",
                ],
            ),
            job_detail(
                "03 - Shipment Job Detail (expect OA-0003)",
                url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                optional=True,
                extra_test=[
                    "irouteSaveJobIds(data);",
                    "pm.test('shipment job', function () { pm.expect((data.job || {}).job_type).to.eql('shipment'); });",
                    "var codes = (data.workflow.allowed_actions || []).map(function (a) { return a.action_code; });",
                    "console.log('allowed_actions:', codes.join(', ') || '(none)');",
                ],
            ),
        ],
    }

    folder_01 = {
        "name": "01 - Setup (refresh / shipment_id preset)",
        "item": [
            make_login(),
            req_item(
                "02 - Dashboard",
                "GET",
                "{{base_url}}/driver/dashboard/",
                test=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "irouteSaveDashboardJob(pm.response.json().data || {});",
                ],
            ),
            job_detail("03 - Job Detail", optional=True),
        ],
    }

    folder_02 = {
        "name": "02 - Mobile Job Workflow (Pickup → Delivery, dynamic)",
        "description": (
            "Mirrors mobile app stepper: Pickup → Loading → In Transit → Delivery → (POD in folder 03). "
            "Each cycle runs the next allowed_action from Job Detail. Works on booking (early milestones) "
            "or shipment job after auto birth. Stops before POD when ready_for_pod=true."
        ),
        "item": [
            mobile_workflow_cycle(1, "Pickup milestone"),
            mobile_workflow_cycle(2, "Loading milestone"),
            mobile_workflow_cycle(3, "In Transit milestone"),
            mobile_workflow_cycle(4, "Delivery milestone"),
            mobile_workflow_cycle(5, "Pre-POD buffer"),
            mobile_workflow_cycle(6, "Pre-POD buffer"),
            mobile_workflow_cycle(7, "Pre-POD buffer"),
        ],
    }

    pod_prerequest_skip = [
        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
        "irouteSkipIfNotPodReady();",
    ]

    pod_capture_sync = req_item(
        "10a - POD Capture Sync",
        "GET",
        "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
        prerequest=pod_prerequest_skip,
        test=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
            "irouteSavePodSync(pm.response.json().data || {});",
            "var d = pm.response.json().data || {};",
            "pm.test('digital_evidence', function () { pm.expect(d.capture_mode).to.eql('digital_evidence'); });",
        ],
    )

    pod_capture_post = req_item(
        "10 - POD Capture POST (photo + signature + video)",
        "POST",
        "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
        prerequest=pod_prerequest_skip,
        body={
            "mode": "formdata",
            "formdata": [
                {"key": "client_capture_id", "value": "pod-{{$guid}}", "type": "text"},
                {"key": "content_hash", "value": "{{pod_content_hash}}", "type": "text"},
                {"key": "workflow_version", "value": "{{pod_workflow_version}}", "type": "text"},
                {"key": "pod_type", "value": "digital", "type": "text"},
                {"key": "target_action_code", "value": "{{pod_upload_action_code}}", "type": "text"},
                {"key": "latitude", "value": "21.3891", "type": "text"},
                {"key": "longitude", "value": "39.8579", "type": "text"},
                {"key": "notes", "value": "Digital POD evidence", "type": "text"},
                {"key": "media[0][media_type]", "value": "photo", "type": "text"},
                {"key": "media[0][file_ref]", "type": "file", "src": []},
                {"key": "media[1][media_type]", "value": "signature", "type": "text"},
                {"key": "media[1][file_ref]", "type": "file", "src": []},
                {"key": "media[2][media_type]", "value": "video", "type": "text"},
                {"key": "media[2][duration_seconds]", "value": "{{pod_video_duration_seconds}}", "type": "text"},
                {"key": "media[2][file_ref]", "type": "file", "src": []},
            ],
        },
        test=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "var d = pm.response.json().data || {};",
            "var id = (d.capture_bundle || {}).capture_bundle_id || d.capture_bundle_id || '';",
            "irouteEnvSet('capture_bundle_id', id);",
        ],
    )

    pod_job_detail = job_detail(
        "10.5 - Job Detail (refresh before POD upload)",
        url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
        optional=True,
        extra_test=[
            "if (!pm.variables.get('pod_upload_action_code')) irouteEnvSet('pod_upload_action_code', pm.variables.get('execute_action_code'));",
        ],
    )

    pod_execute = req_item(
        "11 - Execute POD upload (dynamic code)",
        "POST",
        "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{pod_upload_action_code}}/execute/",
        body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
        prerequest=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
            "pm.request.body.raw = irouteBuildExecuteBody({ capture_bundle_id: pm.variables.get('capture_bundle_id') });",
        ],
        test=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "pm.test('POD upload OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
            "var data = pm.response.json().data || {};",
            "irouteSyncJobDetail(data);",
            "irouteSaveBranchState(data);",
            "var hint = data.next_action_hint || {};",
            "irouteLogHint(hint, 'AFTER POD UPLOAD');",
            "if (pm.variables.get('hard_pod_required') === 'true') {",
            "  console.log('>>> RUN FOLDER 05B Hard POD');",
            "} else {",
            "  console.log('>>> RUN FOLDER 05A Digital only');",
            "}",
        ],
    )

    folder_03 = {
        "name": "03 - Digital POD capture + OA-0006 upload",
        "description": "Runs when ready_for_pod=true. Sets hard_pod_required for folder 04/05B branching.",
        "item": [pod_capture_sync, pod_capture_post, pod_job_detail, pod_execute],
    }

    branch_check = job_detail(
        "12 - Job Detail (branch decision)",
        url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
        optional=True,
        extra_test=[
            "irouteSaveBranchState(data);",
            "console.log('pod_branch=', pm.variables.get('pod_branch'));",
        ],
    )

    folder_04 = {
        "name": "04 - After POD Branch Check",
        "description": "Sets pod_branch = hard_pod | digital_only",
        "item": [branch_check],
    }

    folder_05a = {
        "name": "05A - Digital POD only (optional post-POD action)",
        "description": "Skipped when hard_pod_required=true. Unload step optional — OA-0005 may already run in folder 02.",
        "item": [
            req_item(
                "13A - Job Detail (optional post-POD)",
                "GET",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
                prerequest=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "irouteSkipIfHardPod();",
                ],
                test=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "irouteSyncJobDetail(pm.response.json().data || {});",
                    "if (!pm.variables.get('execute_action_code')) console.log('No post-POD action — skip 14A (unload already done in 02).');",
                ],
            ),
            req_item(
                "14A - Execute post-POD action (dynamic, optional)",
                "POST",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{execute_action_code}}/execute/",
                body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
                prerequest=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "irouteSkipIfHardPod();",
                    "irouteSkipOptionalPostPod();",
                    "irouteSkipIfExecuteIsPod();",
                    "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                    "pm.request.body.raw = irouteBuildExecuteBody({});",
                ],
                test=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "var resp = pm.response.json();",
                    "pm.test('Post-POD execute OK', function () { pm.expect([200,201,204]).to.include(pm.response.code); });",
                    "if (resp.status === 1 && resp.data) irouteSaveSync(resp.data);",
                ],
            ),
        ],
    }

    hard_pod_items = [
        req_item(
            "13B - POD Capture GET (hard copy unlocked)",
            "GET",
            "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
            prerequest=["eval(pm.collectionVariables.get('_iroute_helpers') || '');", "irouteSkipIfNotHardPod();"],
            test=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "var d = pm.response.json().data || {};",
                "pm.test('hard_copy_confirmation', function () { pm.expect(d.capture_mode).to.eql('hard_copy_confirmation'); });",
            ],
        ),
        req_item(
            "13C - Hard copy confirmation UI",
            "GET",
            "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/?step=hard_copy_confirmation",
            prerequest=["eval(pm.collectionVariables.get('_iroute_helpers') || '');", "irouteSkipIfNotHardPod();"],
            test=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "var d = pm.response.json().data || {};",
                "pm.test('confirmation UI', function () { pm.expect(d.ui_mode).to.eql('hard_pod_collection_confirmation'); });",
                "if (d.target_action_code) irouteEnvSet('hard_copy_action_code', d.target_action_code);",
            ],
        ),
        req_item(
            "14B - Hard POD Documents GET",
            "GET",
            "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/hard-pod/documents/",
            prerequest=["eval(pm.collectionVariables.get('_iroute_helpers') || '');", "irouteSkipIfNotHardPod();"],
            test=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "var pages = (pm.response.json().data || {}).pages || [];",
                "var confirmed = pages.map(function (p) { return { page_id: p.page_id, document_id: p.document_id, line_no: p.line_no || 1, confirmed: true }; });",
                "irouteEnvSet('hard_pod_confirmed_pages_json', JSON.stringify(confirmed));",
                "irouteEnvSet('hard_pod_client_submission_id', 'hard-' + Date.now());",
            ],
        ),
        req_item(
            "15B - Hard POD Submit",
            "POST",
            "{{base_url}}/driver/hard-pod/submit/",
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
            prerequest=["eval(pm.collectionVariables.get('_iroute_helpers') || '');", "irouteSkipIfNotHardPod();"],
            test=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "var sub = (pm.response.json().data || {}).custody_submission || {};",
                "irouteEnvSet('hard_pod_custody_submission_id', sub.submission_id || '');",
            ],
        ),
        job_detail(
            "15.5B - Job Detail refresh (before hard copy execute)",
            url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/",
            optional=True,
            prerequest=["eval(pm.collectionVariables.get('_iroute_helpers') || '');", "irouteSkipIfNotHardPod();"],
            extra_test=[
                "irouteSyncJobDetail(data);",
                "if (!pm.variables.get('hard_copy_action_code')) irouteEnvSet('hard_copy_action_code', pm.variables.get('execute_action_code') || pm.variables.get('pod_upload_action_code'));",
                "console.log('hard_copy_action_code:', pm.variables.get('hard_copy_action_code'));",
            ],
        ),
        execute_dynamic("16B - Execute Hard Copy (dynamic)", use_hard_copy_code=True),
        req_item(
            "17B - Execute optional post-Hard-POD action (dynamic)",
            "POST",
            "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{execute_action_code}}/execute/",
            body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
            prerequest=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "irouteSkipIfNotHardPod();",
                "irouteSkipOptionalPostPod();",
                "irouteSkipIfExecuteIsPod();",
                "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                "pm.request.body.raw = irouteBuildExecuteBody({});",
            ],
            test=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "var resp = pm.response.json();",
                "pm.test('Post-Hard-POD execute OK', function () { pm.expect([200,201,204]).to.include(pm.response.code); });",
                "if (resp.status === 1 && resp.data) { irouteSyncJobDetail(resp.data); irouteSaveSync(resp.data); }",
            ],
        ),
    ]
    # Add skip to hard copy execute
    hard_pod_items[5]["event"][0]["script"]["exec"].insert(1, "irouteSkipIfNotHardPod();")

    folder_05b = {
        "name": "05B - Hard POD (digital POD then DN hard copy confirm)",
        "description": (
            "Run when hard_pod_required=true after folder 03 POD upload. "
            "Hard copy uses hard_copy_action_code (OA-0006 or separate A7H row). "
            "Post-Hard-POD execute (17B) is optional if unload already done in folder 02."
        ),
        "item": hard_pod_items,
    }

    cod_cycle_1 = {
        "name": "COD step 1",
        "item": [
            job_detail("18a - Job Detail (COD collect)", url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/", optional=True),
            req_item(
                "18b - Execute COD (dynamic)",
                "POST",
                "{{base_url}}/driver/jobs/shipment/{{shipment_id}}/actions/{{execute_action_code}}/execute/",
                body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
                prerequest=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "if (pm.variables.get('execute_use_cod') !== 'true') { if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest(); }",
                    "irouteSkipIfNoAction();",
                    "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                    "pm.request.body.raw = irouteBuildExecuteBody({});",
                ],
                test=[
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "var resp = pm.response.json();",
                    "if (resp.status === 1 && resp.data) irouteSaveSync(resp.data);",
                ],
            ),
        ],
    }

    cod_cycle_2 = {
        "name": "Close step",
        "item": [
            job_detail("19 - Job Detail (expect close)", url="{{base_url}}/driver/jobs/shipment/{{shipment_id}}/", optional=True),
            execute_dynamic("20 - Execute Job Close (dynamic)"),
        ],
    }

    folder_06 = {
        "name": "06 - COD Close (dynamic)",
        "description": "COD collect skipped automatically when order is Credit.",
        "item": cod_cycle_1["item"] + cod_cycle_2["item"],
    }

    collection = {
        "info": {
            "_postman_id": COLLECTION_ID,
            "name": "IRoute - Dynamic Auto Shipment + POD Branching Flow",
            "description": (
                "# Dynamic Auto Shipment + POD Branching (v5)\n\n"
                "## Mobile app workflow (matches Job Detail stepper)\n"
                "**Pickup → Loading → In Transit → Delivery → POD**\n\n"
                "Postman executes `allowed_actions` dynamically — action codes (OA-xxxx or A1-A10) "
                "come from your Action Master.\n\n"
                "## Document mapping (IRoute_Operational_Logic.html §2.4)\n"
                "| Mobile UI | Backend actions |\n"
                "| Pickup | A2 Pickup Arrival |\n"
                "| Loading | A3 Start Loading + A4 Confirm Loaded (Auto Shipment ON) |\n"
                "| In Transit | A5 Depart In Transit |\n"
                "| Delivery | A6 Delivery Arrival |\n"
                "| POD | A7 Upload POD (+ A7H Hard Copy if Hard POD) |\n\n"
                "## Run order\n"
                "1. **00** full preship (if actions exist) OR **00B** if shipment already exists\n"
                "2. **02** mobile workflow cycles until `ready_for_pod=true`\n"
                "3. **03** POD capture + upload → **04** branch → **05B/05A** → **06** close\n"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": collection_variables(),
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": ["eval(pm.collectionVariables.get('_iroute_helpers') || '');"],
                },
            }
        ],
        "item": [folder_00, folder_00b, folder_01, folder_02, folder_03, folder_04, folder_05a, folder_05b, folder_06],
    }

    assign_ids(collection)
    return collection


def build_environment():
    return {
        "id": ENV_ID,
        "name": "IRoute Dynamic Auto Shipment POD Branching Flow",
        "values": [
            {"key": "base_url", "value": "http://127.0.0.1:8001/api/v1/mobile", "type": "default", "enabled": True},
            {"key": "auto_shipment_enabled", "value": "true", "type": "default", "enabled": True},
            {"key": "driver_email", "value": "", "type": "default", "enabled": True},
            {"key": "driver_password", "value": "", "type": "secret", "enabled": True},
            {"key": "access_token", "value": "", "type": "secret", "enabled": True},
            {"key": "booking_id", "value": "", "type": "default", "enabled": True},
            {"key": "shipment_id", "value": "", "type": "default", "enabled": True},
            {"key": "job_id", "value": "", "type": "default", "enabled": True},
            {"key": "job_type", "value": "booking", "type": "default", "enabled": True},
            {"key": "auto_shipment_a4_done", "value": "false", "type": "default", "enabled": True},
            {"key": "skip_preshipment", "value": "false", "type": "default", "enabled": True},
            {"key": "workflow_path", "value": "", "type": "default", "enabled": True},
            {"key": "current_stage", "value": "", "type": "default", "enabled": True},
            {"key": "next_screen", "value": "", "type": "default", "enabled": True},
            {"key": "execute_is_pod_action", "value": "false", "type": "default", "enabled": True},
            {"key": "ready_for_pod", "value": "false", "type": "default", "enabled": True},
            {"key": "shipment_no", "value": "", "type": "default", "enabled": True},
            {"key": "content_hash", "value": "", "type": "default", "enabled": True},
            {"key": "workflow_version", "value": "", "type": "default", "enabled": True},
            {"key": "execute_action_code", "value": "", "type": "default", "enabled": True},
            {"key": "pod_upload_action_code", "value": "", "type": "default", "enabled": True},
            {"key": "hard_copy_action_code", "value": "", "type": "default", "enabled": True},
            {"key": "pod_content_hash", "value": "", "type": "default", "enabled": True},
            {"key": "pod_workflow_version", "value": "", "type": "default", "enabled": True},
            {"key": "capture_bundle_id", "value": "", "type": "default", "enabled": True},
            {"key": "pod_video_duration_seconds", "value": "8", "type": "default", "enabled": True},
            {"key": "hard_pod_required", "value": "false", "type": "default", "enabled": True},
            {"key": "pod_branch", "value": "", "type": "default", "enabled": True},
            {"key": "next_action_code", "value": "", "type": "default", "enabled": True},
            {"key": "mobile_cod_amount", "value": "100", "type": "default", "enabled": True},
            {"key": "hard_pod_confirmed_pages_json", "value": "[]", "type": "default", "enabled": True},
            {"key": "hard_pod_custody_submission_id", "value": "", "type": "default", "enabled": True},
            {"key": "hard_pod_client_submission_id", "value": "", "type": "default", "enabled": True},
            {"key": "hard_pod_receiver_name", "value": "Receiver Name", "type": "default", "enabled": True},
            {"key": "hard_pod_receiver_contact", "value": "0500000000", "type": "default", "enabled": True},
            {"key": "hard_pod_handoff_notes", "value": "Hard copy DN collected", "type": "default", "enabled": True},
            {"key": "accept_language", "value": "en", "type": "default", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": "2026-06-22T12:00:00.000Z",
        "_postman_exported_using": "Cursor",
    }


def main():
    coll_path = "postman/IRoute_Dynamic_AutoShipment_POD_Branching_Flow_Collection.json"
    env_path = "postman/IRoute-Dynamic-AutoShipment-POD-Branching-Flow.postman_environment.json"
    with open(coll_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(build_collection(), f, indent=2, ensure_ascii=True)
    with open(env_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(build_environment(), f, indent=2, ensure_ascii=True)
    print(f"Wrote {coll_path}")
    print(f"Wrote {env_path}")


if __name__ == "__main__":
    main()
