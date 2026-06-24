var irouteEnvSet = function(key, val) {
  pm.collectionVariables.set(key, val);
  try { pm.environment.set(key, val); } catch (e) {}
}
var irouteSaveSync = function(data) {
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
var irouteGetTimeline = function(data) {
  data = data || {};
  var wf = data.workflow || {};
  var tl = data.timeline || {};
  return wf.timeline_preview || tl.timeline_preview || [];
}
var irouteFindTimelinePending = function(timeline, matcher) {
  timeline = timeline || [];
  for (var i = 0; i < timeline.length; i++) {
    var row = timeline[i];
    if (row.is_performed === true) continue;
    if (matcher(row)) return row;
  }
  return null;
}
var irouteFindActionByFlag = function(allowed, flag) {
  allowed = allowed || [];
  for (var i = 0; i < allowed.length; i++) {
    var req = allowed[i].execution_requirements || {};
    if (req[flag] === true) return allowed[i];
    if (allowed[i][flag] === true) return allowed[i];
  }
  return null;
}
var irouteFindActionByFlags = function(allowed, flags) {
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
var irouteResolveActionCodeByImpact = function(data, flag) {
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
var irouteResolvePodActionCode = function(data) {
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
var irouteResolveHardCopyActionCode = function(data) {
  data = data || {};
  var hint = data.next_action_hint || {};
  var pod = data.pod_cod || {};
  var code = irouteResolveActionCodeByImpact(data, 'hard_copy_collection');
  if (code) return code;
  if (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation') {
    return hint.action_code || pm.variables.get('hard_copy_action_code') || '';
  }
  if ((pod.hard_copy_confirmation || {}).required && hint.action_code) return hint.action_code;
  return pm.variables.get('hard_copy_action_code') || '';
}
var irouteDetectShipmentBirth = function(data) {
  data = data || {};
  var sm = data.sync_metadata || {};
  var ev = (sm.entity_versions || {});
  if (ev.shipment) return true;
  if ((data.job || {}).job_type === 'shipment') return true;
  return pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('auto_shipment_a4_done') === 'true';
}
var irouteMarkShipmentBirth = function(data) {
  if (irouteDetectShipmentBirth(data)) {
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
}
var irouteNeedsMultipart = function(req, hint) {
  req = req || {};
  hint = hint || {};
  if (req.auto_shipment_post === true) return true;
  if (req.photo === true && (req.photo_min_count || 0) >= 1) return true;
  if (hint.capture_mode === 'photo_evidence' || hint.capture_mode === 'loading_photos') return true;
  return false;
}
var irouteSavePodSync = function(data) {
  if (!data) return;
  irouteEnvSet('pod_content_hash', data.content_hash || '');
  irouteEnvSet('pod_workflow_version', data.workflow_version || '');
}
var irouteSaveJobIds = function(data) {
  var job = data.job || {};
  var sid = job.job_id || data.shipment_id || '';
  if (sid) {
    irouteEnvSet('shipment_id', sid);
    irouteEnvSet('job_id', sid);
    irouteEnvSet('job_type', job.job_type || 'shipment');
  }
  if (job.job_no) irouteEnvSet('shipment_no', job.job_no);
}
var irouteSaveBranchState = function(data) {
  var pod = data.pod_cod || {};
  var hint = data.next_action_hint || {};
  var hard = pod.hard_pod_pending === true || ((pod.hard_copy_confirmation || {}).required === true);
  irouteEnvSet('hard_pod_required', hard ? 'true' : 'false');
  irouteEnvSet('pod_branch', hard ? 'hard_pod' : 'digital_only');
  irouteEnvSet('next_action_code', String(hint.action_code || ''));
}
var irouteAssertToken = function() {
  var t = pm.variables.get('access_token') || '';
  if (!t || String(t).indexOf('{{') >= 0) throw new Error('Run Login first.');
}
var irouteLogHint = function(hint, label) {
  hint = hint || {};
  console.log('=== ' + (label || 'HINT') + ' ===');
  console.log('action:', hint.action, '| code:', hint.action_code, '| screen:', hint.screen);
  console.log('capture_mode:', hint.capture_mode, '| ui_mode:', hint.ui_mode);
  console.log('reason:', hint.reason, '| job_closed:', hint.job_closed);
}
var irouteSaveDashboardJob = function(d) {
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
var irouteTransitionToShipment = function(d) {
  var active = (d || {}).active_job || {};
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
var iroutePickNextAction = function(data) {
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
var irouteSyncJobDetail = function(data) {
  data = data || {};
  var job = data.job || {};
  var wf = data.workflow || {};
  var meta = wf.workflow_metadata || {};
  var allowed = wf.allowed_actions || [];
  var hint = data.next_action_hint || {};
  var pod = data.pod_cod || {};
  irouteSaveSync(data);
  irouteSaveBranchState(data);
  irouteMarkShipmentBirth(data);
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
  irouteEnvSet('execute_use_multipart', irouteNeedsMultipart(req, hint) ? 'true' : 'false');
  irouteEnvSet('execute_use_cod', (job.order_type === 'COD' && req.auto_treasury_post) ? 'true' : 'false');
  irouteEnvSet('execute_is_pod_action', (req.auto_pod_post === true) ? 'true' : 'false');
  irouteEnvSet('needs_pod_capture', (hint.action === 'go_to_pod_capture' && hint.capture_mode === 'digital_evidence') ? 'true' : 'false');
  irouteEnvSet('needs_hard_pod_confirm', (hint.capture_mode === 'hard_copy_confirmation' || hint.ui_mode === 'hard_pod_collection_confirmation') ? 'true' : 'false');
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
  if (job.job_type === 'shipment' && job.job_id) {
    irouteEnvSet('auto_shipment_birth_done', 'true');
    irouteEnvSet('auto_shipment_a4_done', 'true');
  }
  irouteEnvSet('job_closed', hint.job_closed === true ? 'true' : 'false');
  console.log('execute_action_code:', code || '(empty)', '| context:', meta.context_label || '');
  console.log('workflow_path:', pm.variables.get('workflow_path') || '(unset)', '| ready_for_pod:', pm.variables.get('ready_for_pod'));
  irouteLogHint(hint, 'SYNC');
  return code;
}
var irouteAssertExecuteAction = function(data, optional) {
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
var irouteNewClientActionId = function() {
  var code = (pm.variables.get('execute_action_code') || 'act').toLowerCase();
  return code.replace(/[^a-z0-9]+/g, '-') + '-' + pm.variables.replaceIn('{{$guid}}');
}
var irouteSkipIfNoAction = function() {
  if (!pm.variables.get('execute_action_code') || pm.variables.get('job_closed') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipUnless = function(flag) {
  if (pm.variables.get(flag) !== 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfHardPod = function() {
  if (pm.variables.get('hard_pod_required') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfDigitalOnly = function() {
  if (pm.variables.get('hard_pod_required') !== 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSyncWorkflowStage = function(data) {
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
var irouteRouteAfterBookingDetail = function(data) {
  data = data || {};
  var allowed = (data.workflow || {}).allowed_actions || [];
  var job = data.job || {};
  if (job.job_type === 'shipment' || irouteDetectShipmentBirth(data)) {
    irouteEnvSet('workflow_path', 'shipment_phase');
    return;
  }
  if (!allowed.length) {
    irouteEnvSet('workflow_path', 'shipment_only');
    irouteEnvSet('skip_preshipment', 'true');
    console.warn('>>> No allowed actions on booking — configure Operation Actions in Action Master and assign driver.');
  } else {
    irouteEnvSet('workflow_path', 'full_preship');
    irouteEnvSet('skip_preshipment', 'false');
  }
}
var irouteSkipIfShipmentOnlyPath = function() {
  if (pm.variables.get('workflow_path') === 'shipment_only') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfShipmentBorn = function() {
  if (pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('auto_shipment_a4_done') === 'true' || pm.variables.get('job_type') === 'shipment') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfReadyForPod = function() {
  if (pm.variables.get('ready_for_pod') === 'true' || pm.variables.get('needs_pod_capture') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfExecuteIsPod = function() {
  if (pm.variables.get('execute_is_pod_action') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipOptionalPostPod = function() {
  if (!pm.variables.get('execute_action_code') || pm.variables.get('job_closed') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfNotHardPod = function() {
  if (pm.variables.get('hard_pod_required') !== 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfDelegatedCapture = function() {
  if (pm.variables.get('needs_pod_capture') === 'true' || pm.variables.get('needs_hard_pod_confirm') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfPreshipDoneOnBooking = function() {
  if ((pm.variables.get('auto_shipment_birth_done') === 'true' || pm.variables.get('auto_shipment_a4_done') === 'true') && pm.variables.get('job_type') === 'booking') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfSkipPreshipment = function() {
  if (pm.variables.get('skip_preshipment') === 'true') {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var irouteSkipIfNotPodReady = function() {
  var ready = pm.variables.get('ready_for_pod') === 'true' || pm.variables.get('needs_pod_capture') === 'true';
  var code = pm.variables.get('pod_upload_action_code') || '';
  if (!ready && !code) {
    if (pm.execution && pm.execution.skipRequest) pm.execution.skipRequest();
  }
}
var iroutePrintSyncSummary = function() {
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
var irouteBuildExecuteBody = function(extra) {
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
var irouteAssertAutoShipmentEnabled = function() {
  if (pm.variables.get('auto_shipment_enabled') !== 'true') {
    console.warn('auto_shipment_enabled is not true');
  }
}
var irouteResetWorkflowLoop = function() {
  irouteEnvSet('workflow_loop_count', '0');
}
var irouteWorkflowLoopContinue = function(detailStepName, mode) {
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
    stop = readyPod || jobClosed || !code;
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