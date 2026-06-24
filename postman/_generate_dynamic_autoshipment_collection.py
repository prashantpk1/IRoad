"""Generate dynamic Auto Shipment + POD Branching Postman collection + environment (v6)."""
from __future__ import annotations

import json
import re
import uuid

COLLECTION_ID = "f4e8d1c2-7a3b-4e5f-9c0d-1e2f3a4b5c6d"
AUTO_SHIPMENT_COLLECTION_ID = "d36aba66-e025-4cf7-878e-244a2bb6cff3"
ENV_ID = "e5f9e2d3-8b4c-5f6a-0d1e-2f3a4b5c6d7e"
AUTO_SHIPMENT_ENV_ID = "b8e2f1a4-6c3d-4e9f-a1b2-3c4d5e6f7081"

WF_DETAIL = "01a - Job Detail (sync action code)"
WF_MULTIPART = "01b - Execute (multipart if required)"
WF_JSON = "01c - Execute (JSON)"
WF_DASH = "01d - Dashboard refresh"


def workflow_step_names(prefix: str) -> tuple[str, str, str, str]:
    return (
        f"{prefix}a - Job Detail (sync action code)",
        f"{prefix}b - Execute (multipart if required)",
        f"{prefix}c - Execute (JSON)",
        f"{prefix}d - Dashboard refresh",
    )

DYNAMIC_COLLECTION_DESCRIPTION = (
    "# Dynamic Auto Shipment + POD Branching\n\n"
    "## Golden rule\n"
    "Always run **01a Job Detail** before execute. Pick the next action **only from `allowed_actions`** "
    "(ignore timeline green checks). Use **01c JSON** when `requires_multipart: false`, **01b multipart** when true.\n\n"
    "## Round-trip (outbound + backload)\n"
    "Each leg starts at **OA-0001 Start Job** on the **booking** job, then OA-0002→0003→0004 (auto shipment birth), "
    "then **shipment** workflow until POD/close. Folder **01** auto-loops through both legs.\n\n"
    "## Future-proof — no regeneration when Action Master changes\n"
    "Action codes and operation impacts are read live from Job Detail on every request. "
    "Change codes, resequence steps, or toggle impacts in the portal — **re-run the collection only**.\n\n"
    "| Operation impact | Collection variable |\n"
    "|---|---|\n"
    "| (next allowed) | execute_action_code |\n"
    "| auto_shipment_post | execute_use_multipart |\n"
    "| auto_pod_post | pod_upload_action_code |\n"
    "| hard_copy_collection | hard_copy_action_code |\n"
    "| auto_treasury_post + COD | execute_use_cod |\n\n"
    "## Run order\n"
    "**00** Login & sync -> **01** auto-loop workflow until POD -> **02-05** POD, branch, close.\n"
    "Folder **01** loops via postman.setNextRequest until ready_for_pod=true (max workflow_loop_max, default 30).\n"
    "If `workflow_stuck=true` (empty allowed_actions), stop — redeploy backend or use a fresh booking.\n"
)

AUTO_SHIPMENT_COLLECTION_DESCRIPTION = (
    "# IRoute Auto Shipment + POD Branching Flow\n\n"
    "## Golden rule\n"
    "Always run **01a Job Detail** before execute. Trust **`allowed_actions` only** — never execute from timeline or "
    "`next_action_hint` when the code is not in allowed_actions.\n\n"
    "## Future-proof — Action Master drives everything at runtime\n"
    "No hardcoded action codes. No Python regen when you rename actions or change operation impacts. "
    "Job Detail sets execute_action_code from allowed_actions / next_action_hint on every step.\n\n"
    "| Operation impact | Collection variable |\n"
    "|---|---|\n"
    "| (next allowed) | execute_action_code |\n"
    "| auto_shipment_post | execute_use_multipart (shipment birth) |\n"
    "| auto_pod_post | pod_upload_action_code |\n"
    "| hard_copy_collection | hard_copy_action_code |\n"
    "| auto_treasury_post + COD order | execute_use_cod |\n\n"
    "1. Booking **Confirmed**, truck + driver assigned\n"
    "2. Set driver_email, driver_password, mobile_cod_amount (COD)\n\n"
    "## Run order\n"
    "Run folders **00 -> 01 -> 02 -> 03 -> 04A or 04B -> 05** (or Run Collection).\n"
    "Folder **01** auto-loops until POD ready — any number of workflow steps.\n\n"
    "## Golden rule\n"
    "Job Detail before Execute. Console shows execute_action_code each loop.\n"
)

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
  var ev = sm.entity_versions || {};
  if (ev.shipment) {
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
}
function irouteGetTimeline(data) {
  data = data || {};
  var wf = data.workflow || {};
  var tl = data.timeline || {};
  return wf.timeline_preview || tl.timeline_preview || [];
}
function irouteFindTimelinePending(timeline, matcher) {
  timeline = timeline || [];
  for (var i = 0; i < timeline.length; i++) {
    var row = timeline[i];
    if (row.is_performed === true) continue;
    if (matcher(row)) return row;
  }
  return null;
}
function irouteFindActionByFlag(allowed, flag) {
  allowed = allowed || [];
  for (var i = 0; i < allowed.length; i++) {
    var req = allowed[i].execution_requirements || {};
    if (req[flag] === true) return allowed[i];
    if (allowed[i][flag] === true) return allowed[i];
  }
  return null;
}
function irouteFindActionByFlags(allowed, flags) {
  allowed = allowed || [];
  flags = flags || [];
  for (var i = 0; i < allowed.length; i++) {
    var req = allowed[i].execution_requirements || {};
    for (var j = 0; j < flags.length; j++) {
      if (req[flags[j]] === true || allowed[i][flags[j]] === true) return allowed[i];
    }
  }
  return null;
}
function irouteResolveActionCodeByImpact(data, flag) {
  data = data || {};
  var allowed = (data.workflow || {}).allowed_actions || [];
  var hint = data.next_action_hint || {};
  var row = irouteFindActionByFlag(allowed, flag);
  if (row && row.action_code) return row.action_code;
  if (hint.action_code) {
    var match = allowed.find(function (a) { return a.action_code === hint.action_code; }) || {};
    var req = match.execution_requirements || {};
    if (req[flag] === true || match[flag] === true) return hint.action_code;
  }
  return '';
}
function irouteResolvePodActionCode(data) {
  data = data || {};
  var hint = data.next_action_hint || {};
  var code = irouteResolveActionCodeByImpact(data, 'auto_pod_post');
  if (code) return code;
  if (hint.action === 'go_to_pod_capture' && hint.action_code) return hint.action_code;
  var timeline = irouteGetTimeline(data);
  var pending = irouteFindTimelinePending(timeline, function (row) {
    var label = (row.action_label || '').toLowerCase();
    return label.indexOf('pod') >= 0 || label.indexOf('proof of delivery') >= 0;
  });
  return (pending && pending.action_code) ? pending.action_code : (pm.variables.get('pod_upload_action_code') || '');
}
function irouteResolveHardCopyActionCode(data) {
  data = data || {};
  var hint = data.next_action_hint || {};
  var pod = data.pod_cod || {};
  var wf = data.workflow || {};
  var primary = wf.primary_action || {};
  var block = pod.hard_copy_confirmation || {};
  var code = irouteResolveActionCodeByImpact(data, 'hard_copy_collection');
  if (code) return code;
  code = String(block.execute_action_code || block.action_code || '').trim();
  if (code) return code;
  if (primary.capture_mode === 'hard_copy_confirmation' && primary.action_code) {
    return String(primary.action_code).trim();
  }
  if (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation') {
    return hint.action_code || pm.variables.get('hard_copy_action_code') || '';
  }
  if (block.required && hint.action_code && hint.action === 'go_to_pod_capture') return hint.action_code;
  return pm.variables.get('hard_copy_action_code') || '';
}
function irouteResolveCollectPaymentActionCode(data) {
  data = data || {};
  var hint = data.next_action_hint || {};
  var code = irouteResolveActionCodeByImpact(data, 'auto_treasury_post');
  if (code) return code;
  if (hint.action === 'go_to_payment_collection' && hint.action_code) return hint.action_code;
  return '';
}
function irouteIsDelegatedNavigation(row) {
  row = row || {};
  var action = row.action || '';
  return action === 'go_to_pod_capture' || action === 'go_to_payment_collection';
}
function irouteIsHardCopyNavigation(hint, primary) {
  hint = hint || {};
  primary = primary || {};
  return (
    hint.capture_mode === 'hard_copy_confirmation' ||
    hint.active_step === 'hard_copy_confirmation' ||
    hint.ui_mode === 'hard_pod_collection_confirmation' ||
    primary.capture_mode === 'hard_copy_confirmation' ||
    primary.ui_mode === 'hard_pod_collection_confirmation'
  );
}
function irouteApplyScreenRouting(data, row, hint, pod) {
  data = data || {};
  row = row || {};
  hint = hint || {};
  pod = pod || {};
  var wf = data.workflow || {};
  var primary = wf.primary_action || {};
  if (hint.action === 'go_to_payment_collection') {
    var payCode = irouteResolveCollectPaymentActionCode(data);
    if (payCode) {
      irouteEnvSet('execute_action_code', payCode);
      irouteEnvSet('execute_action_label', hint.screen_title || row.execution_label || 'Collect Payment');
      irouteEnvSet('execute_use_cod', 'true');
      irouteEnvSet('needs_hard_pod_confirm', 'false');
      irouteEnvSet('needs_pod_capture', 'false');
      irouteEnvSet('next_screen', 'collect_payment');
    }
    return;
  }
  if (hint.action === 'go_to_pod_capture' && irouteIsHardCopyNavigation(hint, primary)) {
    if (pod.hard_pod_pending !== true) {
      return;
    }
    var hc = irouteResolveHardCopyActionCode(data);
    if (hc) {
      irouteEnvSet('hard_copy_action_code', hc);
      irouteEnvSet('execute_action_code', hc);
      irouteEnvSet('execute_action_label', hint.screen_title || primary.execution_label || 'Hard POD Collection Confirmation');
      irouteEnvSet('execute_use_cod', 'false');
      irouteEnvSet('needs_hard_pod_confirm', 'true');
      irouteEnvSet('needs_pod_capture', 'false');
      irouteEnvSet('next_screen', 'pod_capture');
    }
    return;
  }
  if (hint.action === 'go_to_pod_capture') {
    var digitalFirst = hint.active_step === 'digital_evidence' || hint.capture_mode === 'digital_evidence';
    if (digitalFirst) {
      irouteEnvSet('needs_pod_capture', 'true');
      irouteEnvSet('needs_hard_pod_confirm', 'false');
      irouteEnvSet('next_screen', 'pod_capture');
    }
    return;
  }
  if (pod.hard_pod_pending === true && pod.pod_pending !== true) {
    var pendingHard = irouteResolveHardCopyActionCode(data);
    if (pendingHard) {
      irouteEnvSet('hard_copy_action_code', pendingHard);
      irouteEnvSet('needs_hard_pod_confirm', 'true');
      irouteEnvSet('next_screen', 'pod_capture');
    }
  }
}
function irouteDetectShipmentBirth(data) {
  data = data || {};
  var sm = data.sync_metadata || {};
  var ev = (sm.entity_versions || {});
  if (ev.shipment) return true;
  if ((data.job || {}).job_type === 'shipment') return true;
  return pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('auto_shipment_a4_done') === 'true';
}
function irouteMarkShipmentBirth(data) {
  if (irouteDetectShipmentBirth(data)) {
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
}
function irouteNeedsMultipart(req, hint) {
  req = req || {};
  hint = hint || {};
  if (req.auto_shipment_post === true) return true;
  if (req.photo === true && (req.photo_min_count || 0) >= 1) return true;
  if (hint.capture_mode === 'photo_evidence' || hint.capture_mode === 'loading_photos') return true;
  return false;
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
  console.log('requires_multipart:', hint.requires_multipart);
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
function irouteSyncFromDashboard(d) {
  d = d || {};
  irouteSaveDashboardJob(d);
  if (d.sync_metadata) irouteSaveSync({ sync_metadata: d.sync_metadata });
  var current = d.current_job || {};
  if ((d.active_job || {}).job_type === 'booking' && current.open_job) {
    irouteApplyOpenJob({ open_job: current.open_job });
  }
  var wf = d.workflow || {};
  var row = iroutePickNextAction({ workflow: wf, next_action_hint: d.next_action_hint || {} });
  var code = (row.action_code || '').trim();
  var req = row.execution_requirements || {};
  var stuck = irouteHandleWorkflowStuck({ workflow: wf, next_action_hint: d.next_action_hint || {}, job: (d.active_job || {}) });
  if (stuck) {
    irouteEnvSet('execute_action_code', '');
    return '';
  }
  irouteEnvSet('execute_action_code', code);
  irouteEnvSet('execute_action_label', row.execution_label || row.action_name || code);
  irouteEnvSet('execute_use_multipart', irouteNeedsMultipart(req, {}) ? 'true' : 'false');
  irouteEnvSet('execute_photo_min_count', String(req.photo_min_count != null ? req.photo_min_count : (req.photo ? 1 : 0)));
  irouteEnvSet('execute_auto_shipment_post', req.auto_shipment_post === true ? 'true' : 'false');
  irouteEnvSet('workflow_context_label', ((wf.workflow_metadata || {}).context_label) || '');
  console.log('[IRoute] dashboard sync → execute_action_code:', code || '(empty)', '| multipart:', pm.variables.get('execute_use_multipart'));
  irouteLogExecutePlan();
  return code;
}
function irouteApplyOpenJob(hint) {
  hint = hint || {};
  var open = hint.open_job || hint;
  if (!open.job_id) return false;
  var jt = open.job_type || 'booking';
  irouteEnvSet('job_id', open.job_id);
  irouteEnvSet('job_type', jt);
  if (jt === 'booking') {
    irouteEnvSet('booking_id', open.job_id);
    irouteEnvSet('auto_shipment_birth_done', 'false');
    irouteEnvSet('auto_shipment_a4_done', 'false');
    irouteEnvSet('ready_for_pod', 'false');
    irouteEnvSet('needs_pod_capture', 'false');
    irouteEnvSet('execute_is_pod_action', 'false');
    irouteEnvSet('job_closed', 'false');
    irouteEnvSet('skip_preshipment', 'false');
    irouteEnvSet('workflow_path', 'full_preship');
  }
  if (jt === 'shipment') {
    irouteEnvSet('shipment_id', open.job_id);
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
  if (open.job_no) irouteEnvSet('shipment_no', open.job_no);
  console.log('[IRoute] open_job →', jt, open.job_id, open.booking_item_type || '');
  return true;
}
function irouteTransitionToShipment(d) {
  d = d || {};
  var active = d.active_job || {};
  var current = d.current_job || {};
  if (active.job_type === 'booking' && active.job_id) {
    var open = current.open_job;
    if (open && open.job_id) {
      irouteApplyOpenJob({ open_job: open });
    } else {
      irouteEnvSet('job_id', active.job_id);
      irouteEnvSet('job_type', 'booking');
      irouteEnvSet('booking_id', active.job_id);
      if (active.job_no) irouteEnvSet('shipment_no', active.job_no);
    }
    return;
  }
  if (active.job_type === 'shipment' && active.job_id) {
    irouteEnvSet('job_id', active.job_id);
    irouteEnvSet('job_type', 'shipment');
    irouteEnvSet('shipment_id', active.job_id);
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
  var ship = ((d || {}).current_job || {}).active_shipment || {};
  if (ship.shipment_id) irouteEnvSet('shipment_id', ship.shipment_id);
}
function iroutePickNextAction(data) {
  data = data || {};
  var wf = data.workflow || {};
  var allowed = wf.allowed_actions || [];
  if (!allowed.length) return {};

  var hint = data.next_action_hint || {};
  var primary = wf.primary_action || wf.next_action || {};
  if (primary && primary.action_code) {
    for (var i = 0; i < allowed.length; i++) {
      if (allowed[i].action_code === primary.action_code) return allowed[i];
    }
    // A7H / hard_copy rows are stripped from allowed_actions — trust overlay primary.
    if (irouteIsDelegatedNavigation(primary)) return primary;
  }

  if (hint.action === 'go_to_pod_capture' && hint.action_code) {
    for (var h = 0; h < allowed.length; h++) {
      if (allowed[h].action_code === hint.action_code) return allowed[h];
    }
    return hint;
  }
  if (hint.action === 'go_to_payment_collection' && hint.action_code) {
    for (var p = 0; p < allowed.length; p++) {
      if (allowed[p].action_code === hint.action_code) return allowed[p];
    }
    return hint;
  }

  if (hint.action === 'execute_action' && hint.action_code) {
    for (var j = 0; j < allowed.length; j++) {
      if (allowed[j].action_code === hint.action_code) return allowed[j];
    }
  }

  return allowed[0];
}
function irouteHandleWorkflowStuck(data) {
  data = data || {};
  var allowed = (data.workflow || {}).allowed_actions || [];
  var hint = data.next_action_hint || {};
  if (allowed.length > 0) {
    irouteEnvSet('workflow_stuck', 'false');
    return false;
  }
  irouteEnvSet('workflow_stuck', 'true');
  irouteEnvSet('execute_action_code', '');
  irouteEnvSet('execute_use_multipart', 'false');
  console.error('>>> WORKFLOW STUCK: allowed_actions is empty — do NOT run Execute.');
  console.error('>>> Trust allowed_actions only (ignore timeline green checks).');
  if (hint.action === 'refresh_job_detail') {
    console.warn('>>> API returned refresh_job_detail only — redeploy backend or use a fresh booking.');
  }
  var job = data.job || {};
  if (job.backload_bootstrap_pending === true) {
    console.warn('>>> Backload bootstrap: run OA-0001 Start Job first (outbound preshipment logs must not count).');
  }
  return true;
}
function irouteSkipIfWorkflowStuck() {
  if (pm.variables.get('workflow_stuck') === 'true') {
    console.error('[IRoute] SKIP', pm.info.requestName, '— workflow_stuck (allowed_actions empty)');
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSyncJobDetail(data) {
  data = data || {};
  var job = data.job || {};
  var exec = data.execution || {};
  if (!job.job_id && exec.job_id) {
    job = {
      job_id: exec.job_id,
      job_type: exec.job_type || 'shipment',
      job_no: exec.job_no || pm.variables.get('shipment_no') || ''
    };
  }
  var wf = data.workflow || {};
  var meta = wf.workflow_metadata || {};
  var allowed = wf.allowed_actions || [];
  var hint = data.next_action_hint || {};
  var pod = data.pod_cod || {};
  irouteSaveSync(data);
  irouteSaveBranchState(data);
  irouteMarkShipmentBirth(data);
  irouteSyncWorkflowStage(data);
  if (job.backload_bootstrap_pending === true) {
    irouteEnvSet('backload_bootstrap_pending', 'true');
    irouteEnvSet('booking_item_type', job.booking_item_type || 'Backload');
    console.log('[IRoute] backload bootstrap — each leg starts OA-0001 Start Job');
  } else {
    irouteEnvSet('backload_bootstrap_pending', 'false');
  }
  if (irouteHandleWorkflowStuck(data)) {
    iroutePrintSyncSummary();
    return '';
  }
  if (hint.job_closed && hint.open_job && hint.booking_continues) {
    irouteApplyOpenJob(hint);
    irouteEnvSet('execute_action_code', '');
    irouteEnvSet('ready_for_pod', 'false');
    irouteEnvSet('needs_pod_capture', 'false');
    irouteEnvSet('needs_hard_pod_confirm', 'false');
    irouteEnvSet('execute_is_pod_action', 'false');
    irouteLogHint(hint, 'LEG_COMPLETE');
    console.log('[IRoute] outbound leg closed — switched to backload booking; re-sync from Job Detail or Dashboard.');
    return '';
  }
  if (hint.job_closed === true || hint.action === 'go_to_dashboard') {
    irouteEnvSet('execute_action_code', '');
    irouteEnvSet('needs_hard_pod_confirm', 'false');
    irouteEnvSet('needs_pod_capture', 'false');
    irouteEnvSet('ready_for_pod', 'false');
    irouteEnvSet('job_closed', 'true');
    irouteLogHint(hint, 'JOB_CLOSED');
    return '';
  }
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
  irouteEnvSet('execute_use_multipart', irouteNeedsMultipart(req, hint) ? 'true' : 'false');
  if (hint.requires_multipart === true || hint.requires_multipart === false) {
    irouteEnvSet('execute_use_multipart', hint.requires_multipart ? 'true' : 'false');
  }
  irouteEnvSet('execute_photo_min_count', String(req.photo_min_count != null ? req.photo_min_count : (req.photo ? 1 : 0)));
  irouteEnvSet('execute_auto_shipment_post', req.auto_shipment_post === true ? 'true' : 'false');
  irouteEnvSet('execute_use_cod', (job.order_type === 'COD' && req.auto_treasury_post) ? 'true' : 'false');
  irouteEnvSet('execute_is_pod_action', (req.auto_pod_post === true) ? 'true' : 'false');
  var primary = wf.primary_action || wf.next_action || {};
  var steps = hint.pod_capture_steps || primary.pod_capture_steps || [];
  var hardPodSteps = steps.indexOf('hard_copy_confirmation') >= 0;
  var hardFromPod = pod.hard_pod_pending === true;
  irouteEnvSet('hard_pod_required', (hardFromPod || hint.hard_pod === true || hardPodSteps) ? 'true' : 'false');
  var digitalFirst = hint.active_step === 'digital_evidence' || hint.capture_mode === 'digital_evidence' || steps[0] === 'digital_evidence' || steps[0] === 'digital';
  irouteEnvSet('needs_pod_capture', 'false');
  irouteEnvSet('needs_hard_pod_confirm', 'false');
  var podCode = irouteResolvePodActionCode(data);
  if (podCode) {
    irouteEnvSet('pod_upload_action_code', podCode);
    if (req.auto_pod_post || hint.action === 'go_to_pod_capture' || irouteFindActionByFlag(allowed, 'auto_pod_post')) {
      irouteEnvSet('ready_for_pod', 'true');
    }
  } else if (req.auto_pod_post || hint.action === 'go_to_pod_capture') {
    irouteEnvSet('pod_upload_action_code', code || pm.variables.get('pod_upload_action_code') || '');
    irouteEnvSet('ready_for_pod', 'true');
  }
  var hardCode = irouteResolveHardCopyActionCode(data);
  if (hardCode) irouteEnvSet('hard_copy_action_code', hardCode);
  else if (row.hard_copy_collection || req.hard_copy_collection) irouteEnvSet('hard_copy_action_code', code);
  irouteApplyScreenRouting(data, row, hint, pod);
  code = (pm.variables.get('execute_action_code') || code || '').trim();
  if (job.job_type === 'shipment' && job.job_id) {
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
  irouteEnvSet('job_closed', hint.job_closed === true ? 'true' : 'false');
  console.log('execute_action_code:', code || '(empty)', '| context:', meta.context_label || '');
  console.log('workflow_path:', pm.variables.get('workflow_path') || '(unset)', '| ready_for_pod:', pm.variables.get('ready_for_pod'));
  irouteLogHint(hint, 'SYNC');
  irouteLogExecutePlan();
  return code;
}
function irouteLogExecutePlan() {
  var code = pm.variables.get('execute_action_code') || '(empty)';
  var label = pm.variables.get('execute_action_label') || code;
  var mp = pm.variables.get('execute_use_multipart');
  var photos = pm.variables.get('execute_photo_min_count') || '0';
  var autoShip = pm.variables.get('execute_auto_shipment_post');
  console.log('=== EXECUTE PLAN ===');
  console.log('action:', code, '|', label);
  console.log('multipart:', mp, '| auto_shipment_post:', autoShip, '| photo_min:', photos);
  console.log('hint.requires_multipart:', pm.variables.get('execute_use_multipart'));
  if (mp === 'true') {
    console.log('NEXT: 01b multipart — attach JPG/PNG to media[0][file_ref] (and media[1] if photo_min >= 2). Keys must be media_type + file_ref, NOT type/file.');
  } else {
    console.log('NEXT: 01c JSON only — skip 01b (Start Job, Pickup, GPS steps use direct_execute).');
  }
}
function irouteAssertExecuteReady(requireMultipart) {
  var code = pm.variables.get('execute_action_code');
  if (!code) {
    throw new Error('execute_action_code empty — run 01a Job Detail first, then execute.');
  }
  if (!pm.variables.get('workflow_version') || !pm.variables.get('content_hash')) {
    throw new Error('workflow_version/content_hash empty — run 01a Job Detail sync before execute.');
  }
  if (requireMultipart && pm.variables.get('execute_use_multipart') !== 'true') {
    throw new Error('Wrong step for ' + code + ': execute_use_multipart is not true — use 01c Execute (JSON), not 01b.');
  }
}
function irouteAssertExecuteAction(data, optional) {
  if (pm.variables.get('workflow_stuck') === 'true') {
    if (optional) return;
    pm.test('workflow stuck — allowed_actions empty', function () {
      pm.expect.fail('Trust allowed_actions only. Redeploy backend or use a fresh booking — do not execute from timeline.');
    });
    return;
  }
  var code = pm.variables.get('execute_action_code');
  var hint = (data || {}).next_action_hint || {};
  if (code || hint.job_closed === true) return;
  if (optional) return;
  var label = pm.variables.get('workflow_context_label') || '';
  var help = label.indexOf('no shipment') >= 0
    ? 'Configure Operation Actions on booking in Action Master (include Auto Shipment Post on confirm-loaded step).'
    : 'allowed_actions is empty — check Action Master operation impacts and driver assignment.';
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
    console.log('[IRoute] SKIP', pm.info.requestName, '— no execute_action_code or job_closed');
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipUnless(flag) {
  if (pm.variables.get(flag) !== 'true') {
    var code = pm.variables.get('execute_action_code') || '(none)';
    console.log('[IRoute] SKIP', pm.info.requestName, '—', flag, 'is not true', '| action:', code, '| → use 01c Execute (JSON) for direct_execute actions');
    irouteEnvSet('last_step_skipped', pm.info.requestName || 'step');
    irouteEnvSet('last_step_skip_reason', flag + ' !== true');
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
  if (job.job_type === 'shipment' || irouteDetectShipmentBirth(data)) {
    irouteEnvSet('workflow_path', 'shipment_phase');
    return;
  }
  if (!allowed.length) {
    if (job.backload_bootstrap_pending === true || pm.variables.get('workflow_stuck') === 'true') {
      console.warn('>>> No allowed actions — workflow_stuck (outbound logs must not count on backload).');
      return;
    }
    irouteEnvSet('workflow_path', 'shipment_only');
    irouteEnvSet('skip_preshipment', 'true');
    console.warn('>>> No allowed actions on booking — configure Operation Actions in Action Master and assign driver.');
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
  if (pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('auto_shipment_a4_done') === 'true' || pm.variables.get('job_type') === 'shipment') {
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
  if (pm.variables.get('needs_pod_capture') === 'true') {
    console.log('[IRoute] SKIP', pm.info.requestName, '— needs_pod_capture (use folder 02 POD capture)');
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfHardPodDelegated() {
  if (pm.variables.get('needs_hard_pod_confirm') === 'true') {
    console.log('[IRoute] SKIP', pm.info.requestName, '— needs_hard_pod_confirm (use folder 04B/05B Hard POD)');
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
function irouteSkipIfPreshipDoneOnBooking() {
  if ((pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('auto_shipment_a4_done') === 'true') && pm.variables.get('job_type') === 'booking') {
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
  console.log('needs_hard_pod_confirm:', pm.variables.get('needs_hard_pod_confirm'), '| next_screen:', pm.variables.get('next_screen') || '(unset)');
  console.log('workflow_stuck:', pm.variables.get('workflow_stuck'), '| backload_bootstrap:', pm.variables.get('backload_bootstrap_pending'));
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
function irouteResetWorkflowLoop() {
  irouteEnvSet('workflow_loop_count', '0');
}
function irouteWorkflowLoopContinue(detailStepName, mode) {
  mode = mode || 'pod';
  var n = parseInt(pm.variables.get('workflow_loop_count') || '0', 10) + 1;
  irouteEnvSet('workflow_loop_count', String(n));
  var max = parseInt(pm.variables.get('workflow_loop_max') || '30', 10);
  var code = pm.variables.get('execute_action_code') || '';
  var readyPod = pm.variables.get('ready_for_pod') === 'true' || pm.variables.get('needs_pod_capture') === 'true';
  var jobClosed = pm.variables.get('job_closed') === 'true';
  var shipmentBorn = pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('job_type') === 'shipment';
  var stop = false;
  if (mode === 'pod') {
    stop = readyPod || jobClosed;
    if (!code && !readyPod) stop = true;
    if (pm.variables.get('workflow_stuck') === 'true') stop = true;
    // Keep looping on booking while preship actions remain (outbound + backload legs).
  } else if (mode === 'shipment_birth') {
    stop = shipmentBorn || jobClosed || !code;
  } else if (mode === 'closed') {
    stop = jobClosed || !code;
  }
  if (n >= max) {
    console.warn('workflow_loop_max (' + max + ') reached at iteration ' + n + ' — advancing to next folder.');
    stop = true;
  }
  if (stop) {
    irouteEnvSet('workflow_loop_count', '0');
    postman.setNextRequest(null);
    return;
  }
  console.log('Workflow loop', n + '/' + max, '->', detailStepName, '| next:', code);
  postman.setNextRequest(detailStepName);
}
"""


HELPERS_EVAL_LINES = [
    "if (typeof irouteAssertToken !== 'function') {",
    "  var _irouteSrc = (pm.collectionVariables.get('_iroute_h1')||'')",
    "    + (pm.collectionVariables.get('_iroute_h2')||'')",
    "    + (pm.collectionVariables.get('_iroute_h3')||'')",
    "    + (pm.collectionVariables.get('_iroute_h4')||'');",
    "  if (!_irouteSrc) { throw new Error('IRoute helpers missing. Re-import collection JSON (_iroute_h1/_h2/_h3).'); }",
    "  eval(_irouteSrc);",
    "  if (typeof irouteAssertToken !== 'function') { throw new Error('IRoute helpers failed to load — check Postman Console.'); }",
    "}",
]


def helpers_eval_source() -> str:
    """Use var assignments so eval() exposes helpers in Postman request script scope."""
    text = HELPERS.strip()
    return re.sub(r"(?m)^function (iroute\w+)\s*\(", r"var \1 = function(", text)


def helpers_variable_chunks(max_chunk: int = 9000) -> list[dict]:
    """Split helper JS at function boundaries (safe concat + eval)."""
    text = helpers_eval_source()
    parts = re.split(r"(?=var iroute\w+ = function)", text)
    parts = [part for part in parts if part.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) > max_chunk and current:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)
    keys = ("_iroute_h1", "_iroute_h2", "_iroute_h3", "_iroute_h4")
    return [{"key": keys[i], "value": chunk} for i, chunk in enumerate(chunks)]


def with_helpers(script_lines: list[str] | None) -> list[str] | None:
    if not script_lines:
        return None
    return [*HELPERS_EVAL_LINES, *script_lines]


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

    if "request" in node:
        new_id = str(uuid.uuid4())
        while new_id in seen:
            new_id = str(uuid.uuid4())
        seen.add(new_id)
        node["id"] = new_id

    if "item" in node:
        assign_ids(node["item"], seen)


def req_item(name, method, url, *, body=None, description="", prerequest=None, test=None, auth=True):
    headers = auth_header() if auth else [{"key": "Accept-Language", "value": "{{accept_language}}"}]
    item = {
        "name": name,
        "request": {"method": method, "header": headers, "url": url},
        "event": [],
    }
    if description:
        item["request"]["description"] = description
    if body:
        item["request"]["body"] = body
    if prerequest:
        item["event"].append(
            {"listen": "prerequest", "script": {"type": "text/javascript", "exec": with_helpers(prerequest)}}
        )
    if test:
        item["event"].append(
            {"listen": "test", "script": {"type": "text/javascript", "exec": with_helpers(test)}}
        )
    return item


def job_detail(name, url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/", *, assert_action=True, optional=False, extra_test=None, prerequest=None):
    tests = [
        "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
        "var data = pm.response.json().data || {};",
        "irouteSyncJobDetail(data);",
        f"irouteAssertExecuteAction(data, {'true' if optional else 'false'});",
        "iroutePrintSyncSummary();",
    ]
    if extra_test:
        tests.extend(extra_test)
    pre = []
    if prerequest:
        pre.extend(prerequest)
    return req_item(name, "GET", url, prerequest=pre if prerequest else None, test=tests)


def execute_dynamic(name, *, skip_preship=False, extra_body_keys=None, use_hard_copy_code=False):
    code_var = "{{hard_copy_action_code}}" if use_hard_copy_code else "{{execute_action_code}}"
    prerequest = [
        "irouteAssertToken();",
    ]
    if skip_preship:
        prerequest.append("irouteSkipIfPreshipDoneOnBooking();")
    prerequest.extend([
        "if (pm.variables.get('execute_use_multipart') === 'true') {",
        "  console.log('[IRoute] SKIP', pm.info.requestName, '— multipart path (use 01b)');",
        "  if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();",
        "}",
    ])
    if use_hard_copy_code:
        prerequest.extend([
            "irouteSkipIfNotHardPod();",
            "if (!pm.variables.get('hard_copy_action_code')) {",
            "  throw new Error('hard_copy_action_code empty — run 15.5B Job Detail or 13C POD capture first.');",
            "}",
            "irouteEnvSet('execute_action_code', pm.variables.get('hard_copy_action_code'));",
        ])
    else:
        prerequest.extend([
            "irouteSkipIfDelegatedCapture();",
            "irouteSkipIfHardPodDelegated();",
        ])
    prerequest.extend([
        "irouteSkipIfWorkflowStuck();",
        "irouteSkipIfNoAction();",
        "irouteAssertExecuteReady(false);",
        "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
        "irouteLogExecutePlan();",
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
    prerequest.extend(build_lines)
    prerequest.append("pm.request.body.raw = irouteBuildExecuteBody(extra);")

    tests = [
        "if (pm.response.code === 204 || !pm.response.text()) {",
        "  var code = pm.variables.get('execute_action_code') || '(empty)';",
        "  var closed = pm.variables.get('job_closed');",
        "  var multipart = pm.variables.get('execute_use_multipart');",
        "  if (multipart === 'true') {",
        "    console.log('[IRoute]', pm.info.requestName, 'skipped — use multipart step for', code);",
        "  } else {",
        "    console.error('[IRoute]', pm.info.requestName, 'skipped unexpectedly! action:', code, '| job_closed:', closed, '| Run Job Detail (01a) first.');",
        "    pm.test('JSON execute must run when multipart step skipped', function () {",
        "      pm.expect.fail(pm.info.requestName + ' skipped — run 01a to sync execute_action_code (current: ' + code + ', job_closed: ' + closed + ')');",
        "    });",
        "  }",
        "  return;",
        "}",
        "var resp = pm.response.json();",
        "pm.test('Execute OK', function () { pm.expect([200,201,204]).to.include(pm.response.code); });",
        "pm.test('Execute status success', function () { pm.expect(resp.status).to.eql(1); });",
        "if (resp.status === 1 && resp.data) {",
        "  irouteSyncJobDetail(resp.data);",
        "  irouteSaveJobIds(resp.data);",
        "  irouteTransitionToShipment({active_job: resp.data.job});",
        "  irouteMarkShipmentBirth(resp.data);",
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
        "irouteAssertToken();",
    ]
    if skip_preship:
        prerequest.append("irouteSkipIfPreshipDoneOnBooking();")
    prerequest.extend([
        "irouteSkipUnless('execute_use_multipart');",
        "irouteSkipIfDelegatedCapture();",
        "irouteSkipIfHardPodDelegated();",
        "irouteSkipIfWorkflowStuck();",
        "irouteSkipIfNoAction();",
        "irouteAssertExecuteReady(true);",
        "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
        "irouteLogExecutePlan();",
    ])
    tests = [
        "if (pm.response.code === 204 || !pm.response.text()) {",
        "  console.log('[IRoute]', pm.info.requestName, 'had no HTTP response — SKIPPED (normal when execute_use_multipart is not true). Run the JSON execute step next.');",
        "  pm.test('multipart step skipped — JSON execute handles direct_execute', function () {",
        "    pm.expect(pm.variables.get('execute_use_multipart')).to.not.eql('true');",
        "  });",
        "  return;",
        "}",
        "var resp = pm.response.json();",
        "pm.test('Multipart OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
        "if (resp.status === 1 && resp.data) {",
        "  irouteSyncJobDetail(resp.data);",
        "  irouteTransitionToShipment({active_job: resp.data.job});",
        "  irouteMarkShipmentBirth(resp.data);",
        "}",
    ]
    return req_item(
        name,
        "POST",
        "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
        description=(
            "Multipart execute ONLY when execute_use_multipart=true (auto_shipment_post or photo required). "
            "Start Job / Pickup / GPS → skip this step and use 01c JSON instead. "
            "Form keys MUST be media[n][media_type] + media[n][file_ref] (not type/file). "
            "Attach JPG/PNG to both file_ref rows when photo_min_count >= 2."
        ),
        body={
            "mode": "formdata",
            "formdata": [
                {"key": "client_action_id", "value": "{{execute_client_action_id}}", "type": "text"},
                {"key": "workflow_version", "value": "{{workflow_version}}", "type": "text"},
                {"key": "content_hash", "value": "{{content_hash}}", "type": "text"},
                {"key": "latitude", "value": "21.4858", "type": "text"},
                {"key": "longitude", "value": "39.1925", "type": "text"},
                {"key": "notes", "value": "Dynamic multipart {{execute_action_code}}", "type": "text"},
                {"key": "media[0][media_type]", "value": "photo", "type": "text", "description": "Required key name — do not rename to type"},
                {"key": "media[0][file_ref]", "type": "file", "src": [], "description": "Attach JPG/PNG — do not rename to file"},
                {"key": "media[1][media_type]", "value": "photo", "type": "text", "description": "Second photo when photo_min_count >= 2"},
                {"key": "media[1][file_ref]", "type": "file", "src": [], "description": "Attach JPG/PNG"},
            ],
        },
        prerequest=prerequest,
        test=tests,
    )


def loopable_workflow_folder(
    folder_name: str,
    folder_description: str,
    *,
    detail_url: str = "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
    step_prefix: str = "01",
    skip_preship: bool = False,
    shipment_phase: bool = True,
    loop_mode: str = "pod",
):
    """Single workflow cycle that loops via postman.setNextRequest until stop condition."""
    detail_step, multipart_step, json_step, dash_step = workflow_step_names(step_prefix)
    detail_pre = ["irouteResetWorkflowLoop();"]
    exec_pre_extra = []
    if skip_preship:
        detail_pre.extend(["irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"])
        exec_pre_extra = ["irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"]
    if shipment_phase:
        exec_pre_extra.extend(["irouteSkipIfReadyForPod();", "irouteSkipIfExecuteIsPod();"])
    dash_pre = []
    if skip_preship:
        dash_pre.extend(
            [
                "irouteSkipIfSkipPreshipment();",
                "irouteSkipIfPreshipDoneOnBooking();",
                "irouteSkipIfShipmentOnlyPath();",
                "irouteSkipIfShipmentBorn();",
            ]
        )

    multipart = execute_multipart(multipart_step, skip_preship=skip_preship)
    multipart["event"][0]["script"]["exec"].extend(exec_pre_extra)
    json_exec = execute_dynamic(json_step, skip_preship=skip_preship)
    json_exec["event"][0]["script"]["exec"].extend(exec_pre_extra)

    loop_line = f"irouteWorkflowLoopContinue('{detail_step}', '{loop_mode}');"
    dash_test = [
        "var d = pm.response.json().data || {};",
        "irouteSyncFromDashboard(d);",
        "irouteTransitionToShipment(d);",
        "var wf = d.workflow || {};",
        "console.log('[IRoute] dashboard next:', (wf.next_action || {}).action_code || '(none)', '| timeline:', (d.timeline_summary || {}).recent_count);",
        loop_line,
    ]

    return {
        "name": folder_name,
        "description": folder_description,
        "item": [
            job_detail(
                detail_step,
                url=detail_url,
                optional=True,
                prerequest=detail_pre,
            ),
            multipart,
            json_exec,
            req_item(
                dash_step,
                "GET",
                "{{base_url}}/driver/dashboard/",
                prerequest=dash_pre or None,
                test=dash_test,
            ),
        ],
    }


def dynamic_cycle(n: int, label: str, *, booking_url: bool = False, skip_preship: bool = False, shipment_phase: bool = False):
    detail_url = "{{base_url}}/driver/jobs/booking/{{booking_id}}/" if booking_url else "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/"
    detail_pre = []
    exec_pre_extra = []
    if skip_preship:
        detail_pre = ["irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"]
        exec_pre_extra = ["irouteSkipIfShipmentOnlyPath();", "irouteSkipIfShipmentBorn();"]
    if shipment_phase:
        exec_pre_extra.extend(["irouteSkipIfReadyForPod();", "irouteSkipIfExecuteIsPod();"])
    dash_pre = []
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
                    "var d = pm.response.json().data || {};",
                    "irouteSyncFromDashboard(d);",
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
        *helpers_variable_chunks(),
        {"key": "base_url", "value": "http://127.0.0.1:8001/api/v1/mobile"},
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
        {"key": "execute_photo_min_count", "value": "0"},
        {"key": "execute_auto_shipment_post", "value": "false"},
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
        {"key": "auto_shipment_birth_done", "value": "false"},
        {"key": "skip_preshipment", "value": "false"},
        {"key": "workflow_path", "value": ""},
        {"key": "execute_is_pod_action", "value": "false"},
        {"key": "ready_for_pod", "value": "false"},
        {"key": "workflow_loop_count", "value": "0"},
        {"key": "workflow_loop_max", "value": "30"},
        {"key": "workflow_stuck", "value": "false"},
        {"key": "backload_bootstrap_pending", "value": "false"},
        {"key": "booking_item_type", "value": ""},
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
        auth=False,
        test=[
            "var r = pm.response.json();",
            "if (r.status === 1 && r.data && r.data.access_token) {",
            "  pm.collectionVariables.set('access_token', r.data.access_token);",
            "  try { pm.environment.set('access_token', r.data.access_token); } catch (e) {}",
            "  pm.test('Login OK', function () { pm.expect(r.status).to.eql(1); });",
            "} else { pm.test('Login failed', function () { pm.expect.fail(r.message); }); }",
        ],
    )


def build_collection(*, postman_id: str, name: str, description: str, simple: bool = False):
    dashboard_booking = req_item(
        "02 - Dashboard (expect booking job)",
        "GET",
        "{{base_url}}/driver/dashboard/",
        prerequest=[
            "irouteAssertToken();",
            "irouteAssertAutoShipmentEnabled();",
        ],
        test=[
            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
            "var d = pm.response.json().data || {};",
            "irouteSyncFromDashboard(d);",
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
        prerequest=["irouteAssertToken();"],
        test=[
            "var d = pm.response.json().data || {};",
            "irouteTransitionToShipment(d);",
            "irouteSyncFromDashboard(d);",
            "pm.test('job_type shipment', function () { pm.expect((d.active_job || {}).job_type).to.eql('shipment'); });",
        ],
    )

    shipment_detail = job_detail(
        "09 - Shipment Job Detail (sync for POD flow)",
        url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
        extra_test=[
            "pm.test('job_type shipment', function () { pm.expect((data.job || {}).job_type).to.eql('shipment'); });",
            "irouteSaveJobIds(data);",
        ],
    )

    preship_loop = loopable_workflow_folder(
        "04 - Preship auto-loop (until shipment birth)",
        "Loops booking allowed_actions until auto_shipment_post creates shipment. Codes from Action Master only.",
        detail_url="{{base_url}}/driver/jobs/booking/{{booking_id}}/",
        step_prefix="04",
        skip_preship=True,
        shipment_phase=False,
        loop_mode="shipment_birth",
    )

    folder_00 = {
        "name": "00 - Preshipment + Auto Shipment birth (dynamic codes)",
        "description": (
            "Runs booking-scope actions until Auto Shipment Post creates the shipment. "
            "Auto-loops from Job Detail — no fixed step count. Use folder 00B if shipment already exists."
        ),
        "item": [
            make_login(),
            dashboard_booking,
            booking_detail,
            *preship_loop["item"],
            dashboard_shipment,
            shipment_detail,
        ],
    }

    folder_00b = {
        "name": "00B - Shipment phase only (skip preshipment)",
        "description": (
            "Use when preshipment is already done or shipment was created in portal. "
            "Sets skip_preshipment=true. Next actions resolved from allowed_actions dynamically."
        ),
        "item": [
            make_login(),
            req_item(
                "02 - Dashboard (pick shipment job)",
                "GET",
                "{{base_url}}/driver/dashboard/",
                test=[
                    "irouteEnvSet('skip_preshipment', 'true');",
                    "irouteEnvSet('workflow_path', 'shipment_only');",
                    "irouteEnvSet('auto_shipment_a4_done', 'true');",
                    "var d = pm.response.json().data || {};",
                    "irouteSyncFromDashboard(d);",
                    "irouteTransitionToShipment(d);",
                    "if (!pm.variables.get('shipment_id')) {",
                    "  var sid = pm.environment.get('shipment_id') || '';",
                    "  if (sid) { irouteEnvSet('shipment_id', sid); irouteEnvSet('job_id', sid); irouteEnvSet('job_type', 'shipment'); }",
                    "}",
                ],
            ),
            job_detail(
                "03 - Shipment Job Detail (sync first allowed action)",
                url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
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
                    "irouteSyncFromDashboard(pm.response.json().data || {});",
                ],
            ),
            job_detail("03 - Job Detail", optional=True),
        ],
    }

    folder_02 = loopable_workflow_folder(
        "02 - Mobile Job Workflow (auto-loop until POD)",
        (
            "Auto-loops Job Detail -> execute -> dashboard until ready_for_pod=true. "
            "Works on booking or shipment job. Adapts to any Action Master sequence length."
        ),
        step_prefix="02",
        loop_mode="pod",
    )

    pod_prerequest_skip = [
        "irouteSkipIfNotPodReady();",
    ]

    pod_capture_sync = req_item(
        "10a - POD Capture Sync",
        "GET",
        "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/",
        prerequest=pod_prerequest_skip,
        test=[
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
            "var d = pm.response.json().data || {};",
            "var id = (d.capture_bundle || {}).capture_bundle_id || d.capture_bundle_id || '';",
            "irouteEnvSet('capture_bundle_id', id);",
        ],
    )

    pod_job_detail = job_detail(
        "10.5 - Job Detail (refresh before POD upload)",
        url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
        optional=True,
        extra_test=[
            "var podCode = irouteResolvePodActionCode(data);",
            "if (podCode) irouteEnvSet('pod_upload_action_code', podCode);",
            "else if (!pm.variables.get('pod_upload_action_code')) irouteEnvSet('pod_upload_action_code', pm.variables.get('execute_action_code'));",
        ],
    )

    pod_execute = req_item(
        "11 - Execute POD upload (auto_pod_post action)",
        "POST",
        "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{pod_upload_action_code}}/execute/",
        body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
        prerequest=[
            "var podCode = pm.variables.get('pod_upload_action_code') || pm.variables.get('execute_action_code');",
            "if (!podCode) { if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest(); }",
            "irouteEnvSet('pod_upload_action_code', podCode);",
            "irouteEnvSet('execute_action_code', podCode);",
            "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
            "pm.request.body.raw = irouteBuildExecuteBody({ capture_bundle_id: pm.variables.get('capture_bundle_id') });",
        ],
        test=[
            "pm.test('POD upload OK', function () { pm.expect([200,201]).to.include(pm.response.code); });",
            "var data = pm.response.json().data || {};",
            "irouteSyncJobDetail(data);",
            "irouteSaveBranchState(data);",
            "var hint = data.next_action_hint || {};",
            "irouteLogHint(hint, 'AFTER POD UPLOAD');",
            "if (pm.variables.get('hard_pod_required') === 'true') {",
            "  console.log('>>> RUN FOLDER 04B Hard POD');",
            "} else {",
            "  console.log('>>> RUN FOLDER 04A Digital only');",
            "}",
        ],
    )

    folder_03 = {
        "name": "03 - Digital POD capture + upload (auto_pod_post)",
        "description": "POD action code resolved from auto_pod_post flag or next_action_hint — not hardcoded.",
        "item": [pod_capture_sync, pod_capture_post, pod_job_detail, pod_execute],
    }

    branch_check = job_detail(
        "12 - Job Detail (branch decision)",
        url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
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
        "description": "Skipped when hard_pod_required=true. Runs any remaining allowed action after POD.",
        "item": [
            req_item(
                "13A - Job Detail (optional post-POD)",
                "GET",
                "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
                prerequest=[
                    "irouteSkipIfHardPod();",
                ],
                test=[
                    "irouteSyncJobDetail(pm.response.json().data || {});",
                    "if (!pm.variables.get('execute_action_code')) console.log('No post-POD action — skip 14A (unload already done in 02).');",
                ],
            ),
            req_item(
                "14A - Execute post-POD action (dynamic, optional)",
                "POST",
                "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
                body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
                prerequest=[
                    "irouteSkipIfHardPod();",
                    "irouteSkipOptionalPostPod();",
                    "irouteSkipIfExecuteIsPod();",
                    "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                    "pm.request.body.raw = irouteBuildExecuteBody({});",
                ],
                test=[
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
            prerequest=["irouteSkipIfNotHardPod();"],
            test=[
                "var d = pm.response.json().data || {};",
                "pm.test('hard_copy_confirmation', function () { pm.expect(d.capture_mode).to.eql('hard_copy_confirmation'); });",
            ],
        ),
        req_item(
            "13C - Hard copy confirmation UI",
            "GET",
            "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/pod/capture/?step=hard_copy_confirmation",
            prerequest=["irouteSkipIfNotHardPod();"],
            test=[
                "var d = pm.response.json().data || {};",
                "pm.test('confirmation UI', function () { pm.expect(d.ui_mode).to.eql('hard_pod_collection_confirmation'); });",
                "if (d.target_action_code) irouteEnvSet('hard_copy_action_code', d.target_action_code);",
            ],
        ),
        req_item(
            "14B - Hard POD Documents GET",
            "GET",
            "{{base_url}}/driver/jobs/shipments/{{shipment_id}}/hard-pod/documents/",
            prerequest=["irouteSkipIfNotHardPod();"],
            test=[
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
            prerequest=["irouteSkipIfNotHardPod();"],
            test=[
                "var sub = (pm.response.json().data || {}).custody_submission || {};",
                "irouteEnvSet('hard_pod_custody_submission_id', sub.submission_id || '');",
            ],
        ),
        job_detail(
            "15.5B - Job Detail refresh (before hard copy execute)",
            url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
            optional=True,
            prerequest=["irouteSkipIfNotHardPod();"],
            extra_test=[
                "irouteSyncJobDetail(data);",
                "var hardCode = irouteResolveHardCopyActionCode(data);",
                "if (hardCode) irouteEnvSet('hard_copy_action_code', hardCode);",
                "else if (!pm.variables.get('hard_copy_action_code')) irouteEnvSet('hard_copy_action_code', pm.variables.get('execute_action_code') || pm.variables.get('pod_upload_action_code'));",
                "console.log('hard_copy_action_code:', pm.variables.get('hard_copy_action_code'));",
            ],
        ),
        execute_dynamic("16B - Execute Hard Copy (dynamic)", use_hard_copy_code=True),
        req_item(
            "17B - Execute optional post-Hard-POD action (dynamic)",
            "POST",
            "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
            body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
            prerequest=[
                "irouteSkipIfNotHardPod();",
                "irouteSkipOptionalPostPod();",
                "irouteSkipIfExecuteIsPod();",
                "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                "pm.request.body.raw = irouteBuildExecuteBody({});",
            ],
            test=[
                "var resp = pm.response.json();",
                "pm.test('Post-Hard-POD execute OK', function () { pm.expect([200,201,204]).to.include(pm.response.code); });",
                "if (resp.status === 1 && resp.data) { irouteSyncJobDetail(resp.data); irouteSaveSync(resp.data); }",
            ],
        ),
    ]
    # Add skip to hard copy execute
    hard_pod_items[5]["event"][0]["script"]["exec"].insert(1, "irouteSkipIfNotHardPod();")

    folder_05b = {
        "name": "05B - Hard POD (digital POD then hard_copy_collection confirm)",
        "description": (
            "Run when hard_pod_required=true after folder 03. "
            "Hard copy action resolved from hard_copy_collection flag or capture API target_action_code."
        ),
        "item": hard_pod_items,
    }

    cod_cycle_1 = {
        "name": "COD step 1",
        "item": [
            job_detail("18a - Job Detail (COD collect)", url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/", optional=True),
            req_item(
                "18b - Execute COD (auto_treasury_post)",
                "POST",
                "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/{{execute_action_code}}/execute/",
                body={"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}},
                prerequest=[
                    "if (pm.variables.get('execute_use_cod') !== 'true') { if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest(); }",
                    "irouteSkipIfWorkflowStuck();",
                    "irouteSkipIfNoAction();",
                    "pm.collectionVariables.set('execute_client_action_id', irouteNewClientActionId());",
                    "pm.request.body.raw = irouteBuildExecuteBody({});",
                ],
                test=[
                    "var resp = pm.response.json();",
                    "if (resp.status === 1 && resp.data) irouteSaveSync(resp.data);",
                ],
            ),
        ],
    }

    cod_cycle_2 = {
        "name": "Close step",
        "item": [
            job_detail("19 - Job Detail (expect close)", url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/", optional=True),
            execute_dynamic("20 - Execute Job Close (dynamic)"),
        ],
    }

    folder_06 = {
        "name": "06 - COD Close (dynamic)",
        "description": "COD collect skipped automatically when order is Credit.",
        "item": cod_cycle_1["item"] + cod_cycle_2["item"],
    }

    if simple:
        folder_start = {
            "name": "00 - Login & Job Sync (dynamic)",
            "description": (
                "Login, pick active job from dashboard, sync first allowed_action from Job Detail. "
                "Works on booking (before shipment birth) or shipment job."
            ),
            "item": [
                make_login(),
                req_item(
                    "02 - Dashboard (active job)",
                    "GET",
                    "{{base_url}}/driver/dashboard/",
                    prerequest=[
                        "irouteAssertToken();",
                        "irouteAssertAutoShipmentEnabled();",
                    ],
                    test=[
                        "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                        "var d = pm.response.json().data || {};",
                        "irouteSyncFromDashboard(d);",
                        "irouteTransitionToShipment(d);",
                        "pm.test('active_job present', function () { pm.expect((d.active_job || {}).job_id).to.be.ok; });",
                        "var codes = ((d.workflow || {}).allowed_actions || []).map(function (a) { return a.action_code; });",
                        "console.log('dashboard allowed_actions:', codes.join(', ') || '(none)');",
                    ],
                ),
                job_detail(
                    "03 - Job Detail (sync allowed_actions)",
                    url="{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/",
                    optional=True,
                    extra_test=[
                        "irouteRouteAfterBookingDetail(data);",
                        "var codes = (data.workflow.allowed_actions || []).map(function (a) { return a.action_code; });",
                        "console.log('allowed_actions:', codes.join(', ') || '(none)');",
                        "console.log('execute_action_code:', pm.variables.get('execute_action_code') || '(empty)');",
                    ],
                ),
            ],
        }
        folder_workflow = loopable_workflow_folder(
            "01 - Job Workflow (auto-loop until POD)",
            (
                "Auto-loops Job Detail -> multipart/JSON execute -> dashboard until ready_for_pod=true. "
                "Runs outbound preship (booking OA-0001..0004), shipment phase, then backload preship on the same booking. "
                "Stops when workflow_stuck=true (empty allowed_actions)."
            ),
            step_prefix="01",
            loop_mode="pod",
        )
        folder_03["name"] = "02 - Digital POD capture + upload (auto_pod_post)"
        folder_04["name"] = "03 - After POD Branch Check"
        folder_05a["name"] = "04A - Digital POD only (optional post-POD action)"
        folder_05b["name"] = "04B - Hard POD (hard_copy_collection confirm)"
        folder_05b["description"] = (
            "Run when hard_pod_required=true after folder 02. "
            "Hard copy action resolved from hard_copy_collection flag or capture API target_action_code."
        )
        folder_06["name"] = "05 - COD Close (dynamic)"
        top_items = [folder_start, folder_workflow, folder_03, folder_04, folder_05a, folder_05b, folder_06]
    else:
        top_items = [folder_00, folder_00b, folder_01, folder_02, folder_03, folder_04, folder_05a, folder_05b, folder_06]

    collection = {
        "info": {
            "_postman_id": postman_id,
            "name": name,
            "description": description,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": collection_variables(),
        "item": top_items,
    }

    assign_ids(collection)
    collection["info"]["_postman_id"] = postman_id
    return collection


def build_environment(*, env_id: str, name: str, base_url: str = "http://127.0.0.1:8001/api/v1/mobile"):
    return {
        "id": env_id,
        "name": name,
        "values": [
            {"key": "base_url", "value": base_url, "type": "default", "enabled": True},
            {"key": "auto_shipment_enabled", "value": "true", "type": "default", "enabled": True},
            {"key": "driver_email", "value": "", "type": "default", "enabled": True},
            {"key": "driver_password", "value": "", "type": "secret", "enabled": True},
            {"key": "access_token", "value": "", "type": "secret", "enabled": True},
            {"key": "booking_id", "value": "", "type": "default", "enabled": True},
            {"key": "shipment_id", "value": "", "type": "default", "enabled": True},
            {"key": "job_id", "value": "", "type": "default", "enabled": True},
            {"key": "job_type", "value": "booking", "type": "default", "enabled": True},
            {"key": "auto_shipment_a4_done", "value": "false", "type": "default", "enabled": True},
            {"key": "auto_shipment_birth_done", "value": "false", "type": "default", "enabled": True},
            {"key": "skip_preshipment", "value": "false", "type": "default", "enabled": True},
            {"key": "workflow_path", "value": "", "type": "default", "enabled": True},
            {"key": "current_stage", "value": "", "type": "default", "enabled": True},
            {"key": "next_screen", "value": "", "type": "default", "enabled": True},
            {"key": "execute_is_pod_action", "value": "false", "type": "default", "enabled": True},
            {"key": "ready_for_pod", "value": "false", "type": "default", "enabled": True},
            {"key": "workflow_loop_count", "value": "0", "type": "default", "enabled": True},
            {"key": "workflow_loop_max", "value": "30", "type": "default", "enabled": True},
            {"key": "workflow_stuck", "value": "false", "type": "default", "enabled": True},
            {"key": "backload_bootstrap_pending", "value": "false", "type": "default", "enabled": True},
            {"key": "booking_item_type", "value": "", "type": "default", "enabled": True},
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
    outputs = [
        {
            "coll_path": "postman/IRoute_Dynamic_AutoShipment_POD_Branching_Flow_Collection.json",
            "env_path": "postman/IRoute-Dynamic-AutoShipment-POD-Branching-Flow.postman_environment.json",
            "postman_id": COLLECTION_ID,
            "name": "IRoute - Dynamic Auto Shipment + POD Branching Flow",
            "description": DYNAMIC_COLLECTION_DESCRIPTION,
            "env_id": ENV_ID,
            "env_name": "IRoute Dynamic Auto Shipment POD Branching Flow",
            "base_url": "http://127.0.0.1:8001/api/v1/mobile",
            "simple": True,
        },
        {
            "coll_path": "postman/IRoute_AutoShipment_POD_Branching_Flow_Collection.json",
            "env_path": "postman/IRoute-AutoShipment-POD-Branching-Flow.postman_environment.json",
            "postman_id": AUTO_SHIPMENT_COLLECTION_ID,
            "name": "IRoute - Auto Shipment + POD Branching Flow",
            "description": AUTO_SHIPMENT_COLLECTION_DESCRIPTION,
            "env_id": AUTO_SHIPMENT_ENV_ID,
            "env_name": "IRoute Auto Shipment POD Branching Flow",
            "base_url": "http://127.0.0.1:8001/api/v1/mobile",
            "simple": True,
        },
    ]
    for spec in outputs:
        with open(spec["coll_path"], "w", encoding="utf-8", newline="\n") as f:
            json.dump(
                build_collection(
                    postman_id=spec["postman_id"],
                    name=spec["name"],
                    description=spec["description"],
                    simple=spec.get("simple", False),
                ),
                f,
                indent=2,
                ensure_ascii=True,
            )
        with open(spec["env_path"], "w", encoding="utf-8", newline="\n") as f:
            json.dump(
                build_environment(
                    env_id=spec["env_id"],
                    name=spec["env_name"],
                    base_url=spec["base_url"],
                ),
                f,
                indent=2,
                ensure_ascii=True,
            )
        print(f"Wrote {spec['coll_path']}")
        print(f"Wrote {spec['env_path']}")


if __name__ == "__main__":
    main()
