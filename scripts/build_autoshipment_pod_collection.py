"""Build IRoute Auto Shipment + POD Branching Postman collection."""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "postman" / "IRoute_POD_Branching_Flow_Collection.json"
OUT = ROOT / "postman" / "IRoute_AutoShipment_POD_Branching_Flow_Collection.json"

with SRC.open(encoding="utf-8") as f:
    coll = json.load(f)

coll["info"]["_postman_id"] = str(uuid.uuid4())
coll["info"]["name"] = "IRoute — Auto Shipment + POD Branching Flow"
coll["info"]["description"] = (
    "# IRoute Auto Shipment + POD Branching Flow\n\n"
    "Full clone of POD Branching Flow with **Auto Shipment ON** preamble.\n\n"
    "## Precondition (portal)\n"
    "1. Action Master **A4 Confirm Loaded** has **Auto Shipment Post = Enabled**\n"
    "2. Create **Booking** and **assign truck + driver** (no manual shipment row)\n"
    "3. Set `auto_shipment_enabled=true` in environment (default)\n\n"
    "## Run order\n"
    "1. **00 Auto Shipment ON** — Login → Dashboard (booking job) → Booking Job Detail "
    "→ A1–A4 on booking → A4 births shipment → Dashboard + Shipment Job Detail\n"
    "2. **01 Setup** — Refresh sync (optional if 00 completed)\n"
    "3. **02 Workflow → A6** — A5–A6 (skip A1–A4 if `auto_shipment_a4_done=true`)\n"
    "4. **03–06** — Digital POD, branch check, 05A/05B, COD close\n\n"
    "## Branching (after A7)\n"
    "| Shipment type | Next |\n|---------------|------|\n"
    "| Digital / Soft POD | 05A → A8 |\n| Hard POD + DN | 05B → A7H → A8 |\n"
)

extra_helpers = r"""
function irouteSaveDashboardJob(d) {
  var active = (d || {}).active_job || {};
  var current = (d || {}).current_job || {};
  if (active.job_id) {
    var jt = active.job_type || 'shipment';
    pm.collectionVariables.set('job_id', active.job_id);
    pm.collectionVariables.set('job_type', jt);
    pm.environment.set('job_id', active.job_id);
    pm.environment.set('job_type', jt);
    if (jt === 'booking') {
      pm.collectionVariables.set('booking_id', active.job_id);
      pm.environment.set('booking_id', active.job_id);
    } else if (jt === 'shipment') {
      pm.collectionVariables.set('shipment_id', active.job_id);
      pm.environment.set('shipment_id', active.job_id);
    }
  }
  if (current.booking_id) {
    pm.collectionVariables.set('booking_id', current.booking_id);
    pm.environment.set('booking_id', current.booking_id);
  }
  if (active.job_no) {
    pm.collectionVariables.set('shipment_no', active.job_no);
    pm.environment.set('shipment_no', active.job_no);
  }
}
function irouteTransitionToShipment(d) {
  var active = (d || {}).active_job || {};
  pm.test('job_type is shipment after auto shipment birth', function () {
    pm.expect(active.job_type).to.eql('shipment');
  });
  if (active.job_id) {
    pm.collectionVariables.set('job_id', active.job_id);
    pm.collectionVariables.set('job_type', 'shipment');
    pm.collectionVariables.set('shipment_id', active.job_id);
    pm.environment.set('job_id', active.job_id);
    pm.environment.set('job_type', 'shipment');
    pm.environment.set('shipment_id', active.job_id);
  }
  if (active.job_no) {
    pm.collectionVariables.set('shipment_no', active.job_no);
    pm.environment.set('shipment_no', active.job_no);
  }
  pm.collectionVariables.set('auto_shipment_a4_done', 'true');
  pm.environment.set('auto_shipment_a4_done', 'true');
}
function irouteAssertAutoShipmentEnabled() {
  if (pm.variables.get('auto_shipment_enabled') !== 'true') {
    console.warn('auto_shipment_enabled is not true — folder 00 may not apply');
  }
}
"""
for var in coll["variable"]:
    if var["key"] == "_iroute_helpers":
        var["value"] = var["value"].rstrip() + extra_helpers
        break
else:
    raise RuntimeError("_iroute_helpers variable not found in source collection")

new_vars = [
    ("auto_shipment_enabled", "true"),
    ("booking_id", ""),
    ("auto_shipment_a4_done", "false"),
    ("accept_language", "en"),
]
existing_keys = {v["key"] for v in coll["variable"]}
for key, value in new_vars:
    if key not in existing_keys:
        coll["variable"].append({"key": key, "value": value})

common_pre = [
    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
    "irouteAssertToken();",
    "irouteAssertAutoShipmentEnabled();",
]


def make_req(name, method, url_path, *, tests=None, prerequest=None, body=None, desc=""):
    req_item = {
        "name": name,
        "request": {
            "method": method,
            "header": [
                {"key": "Authorization", "value": "Bearer {{access_token}}"},
                {"key": "Accept-Language", "value": "{{accept_language}}"},
            ],
            "url": "{{base_url}}" + url_path,
        },
    }
    if desc:
        req_item["request"]["description"] = desc
    if body:
        req_item["request"]["body"] = body
    events = []
    if prerequest:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": prerequest}})
    if tests:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": tests}})
    if events:
        req_item["event"] = events
    return req_item


auto_folder = {
    "name": "00 — Auto Shipment ON (booking assigned → A4 births shipment)",
    "description": (
        "Run when Action Master A4 has auto_shipment_post enabled and portal booking "
        "is assigned to driver (no shipment row yet). Set auto_shipment_enabled=true."
    ),
    "item": [
        make_req(
            "01 — Login (Email)",
            "POST",
            "/driver/auth/login/",
            body={
                "mode": "raw",
                "raw": '{\n  "email": "{{driver_email}}",\n  "password": "{{driver_password}}"\n}',
                "options": {"raw": {"language": "json"}},
            },
            tests=[
                "var r = pm.response.json();",
                "if (r.status === 1 && r.data && r.data.access_token) {",
                "  pm.collectionVariables.set('access_token', r.data.access_token);",
                "  pm.environment.set('access_token', r.data.access_token);",
                "  pm.test('Login OK', function () { pm.expect(r.status).to.eql(1); });",
                '} else { pm.test("Login failed", function () { pm.expect.fail(r.message); }); }',
            ],
        ),
        make_req(
            "02 — Dashboard (expect booking job)",
            "GET",
            "/driver/dashboard/",
            prerequest=common_pre,
            tests=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                "var d = (pm.response.json().data || {});",
                "irouteSaveDashboardJob(d);",
                "pm.test('active_job present', function () { pm.expect((d.active_job || {}).job_id || '').to.not.eql(''); });",
                "pm.test('job_type is booking (no shipment yet)', function () { pm.expect((d.active_job || {}).job_type).to.eql('booking'); });",
                "pm.test('current_job has booking_id', function () { pm.expect((d.current_job || {}).booking_id || (d.active_job || {}).job_id).to.be.ok; });",
                "pm.test('workflow has allowed actions', function () { pm.expect(((d.workflow || {}).allowed_actions || []).length).to.be.at.least(1); });",
                "console.log('Booking job:', (d.active_job || {}).job_no || (d.active_job || {}).job_id);",
            ],
        ),
        make_req(
            "03 — Booking Job Detail",
            "GET",
            "/driver/jobs/booking/{{booking_id}}/",
            prerequest=common_pre
            + [
                "var bid = pm.variables.get('booking_id') || pm.variables.get('job_id') || '';",
                "if (!bid) throw new Error('No booking_id from dashboard');",
            ],
            tests=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                "var data = pm.response.json().data || {};",
                "irouteSaveJobIds(data);",
                "irouteSaveSync(data);",
                "pm.test('job_type booking in detail', function () { pm.expect((data.job || {}).job_type).to.eql('booking'); });",
                "pm.test('workflow present', function () { pm.expect(data.workflow).to.be.an('object'); });",
                'irouteLogHint(data.next_action_hint, "BOOKING JOB DETAIL");',
                "var allowed = (data.workflow.allowed_actions || []).map(function (a) { return a.action_code; });",
                "console.log('allowed_actions:', allowed.join(', '));",
            ],
        ),
    ],
}

for code, label, desc in [
    ("A1", "04 — Execute A1 (booking)", "Start job on booking context"),
    ("A2", "05 — Execute A2 (booking)", "Pickup arrival"),
    ("A3", "06 — Execute A3 (booking)", "Start loading"),
]:
    auto_folder["item"].append(
        make_req(
            label,
            "POST",
            f"/driver/jobs/booking/{{{{booking_id}}}}/actions/{code}/execute/",
            desc=desc,
            prerequest=common_pre,
            body={
                "mode": "raw",
                "raw": (
                    "{\n"
                    f'  "client_action_id": "{code.lower()}-{{{{$guid}}}}",\n'
                    '  "workflow_version": "{{workflow_version}}",\n'
                    '  "content_hash": "{{content_hash}}",\n'
                    '  "latitude": 21.3891,\n'
                    '  "longitude": 39.8579,\n'
                    f'  "notes": "{code} — {{{{shipment_no}}}} (booking)"\n'
                    "}"
                ),
                "options": {"raw": {"language": "json"}},
            },
            tests=[
                "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                "var resp = pm.response.json();",
                'pm.test("HTTP OK", function () { pm.expect([200, 201]).to.include(pm.response.code); });',
                "if (resp.status === 1 && resp.data) { irouteSaveSync(resp.data); }",
                "var hint = (resp.data || {}).next_action_hint;",
                f'if (hint) {{ irouteLogHint(hint, "{code} booking"); }}',
            ],
        )
    )

auto_folder["item"].append(
    {
        "name": "07 — Execute A4 (booking, 2 photos — auto shipment birth)",
        "request": {
            "method": "POST",
            "header": [
                {"key": "Authorization", "value": "Bearer {{access_token}}"},
                {"key": "Accept-Language", "value": "{{accept_language}}"},
            ],
            "url": "{{base_url}}/driver/jobs/booking/{{booking_id}}/actions/A4/execute/",
            "body": {
                "mode": "formdata",
                "formdata": [
                    {"key": "client_action_id", "value": "a4-{{$guid}}", "type": "text"},
                    {"key": "workflow_version", "value": "{{workflow_version}}", "type": "text"},
                    {"key": "content_hash", "value": "{{content_hash}}", "type": "text"},
                    {"key": "latitude", "value": "21.4858", "type": "text"},
                    {"key": "longitude", "value": "39.1925", "type": "text"},
                    {"key": "notes", "value": "Confirm loaded — auto shipment birth", "type": "text"},
                    {"key": "media[0][media_type]", "value": "photo", "type": "text"},
                    {"key": "media[0][file_ref]", "type": "file", "src": []},
                    {"key": "media[1][media_type]", "value": "photo", "type": "text"},
                    {"key": "media[1][file_ref]", "type": "file", "src": []},
                ],
            },
            "description": "A4 on booking context. Auto Shipment Post creates shipment row. Attach 2 JPG/PNG.",
        },
        "event": [
            {"listen": "prerequest", "script": {"type": "text/javascript", "exec": common_pre}},
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                        "var resp = pm.response.json();",
                        'pm.test("A4 OK", function () { pm.expect([200, 201]).to.include(pm.response.code); });',
                        "if (resp.status === 1 && resp.data) { irouteSaveSync(resp.data); }",
                        "var hint = (resp.data || {}).next_action_hint;",
                        'if (hint) { irouteLogHint(hint, "A4 booking — shipment birth"); }',
                        "pm.collectionVariables.set('auto_shipment_a4_done', 'true');",
                        "pm.environment.set('auto_shipment_a4_done', 'true');",
                    ],
                },
            },
        ],
    }
)

auto_folder["item"].append(
    make_req(
        "08 — Dashboard (expect shipment job after A4)",
        "GET",
        "/driver/dashboard/",
        prerequest=common_pre,
        tests=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
            "var d = (pm.response.json().data || {});",
            "irouteTransitionToShipment(d);",
            "irouteSaveDashboardJob(d);",
            "var ship = ((d.current_job || {}).active_shipment || {});",
            "if (ship.shipment_id) { pm.collectionVariables.set('shipment_id', ship.shipment_id); pm.environment.set('shipment_id', ship.shipment_id); }",
            "console.log('Shipment job:', (d.active_job || {}).job_no);",
        ],
    )
)

auto_folder["item"].append(
    make_req(
        "09 — Shipment Job Detail (sync for POD flow)",
        "GET",
        "/driver/jobs/shipment/{{shipment_id}}/",
        prerequest=common_pre,
        tests=[
            "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
            "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
            "var data = pm.response.json().data || {};",
            "irouteSaveJobIds(data);",
            "irouteSaveSync(data);",
            "irouteSaveBranchState(data);",
            'irouteLogHint(data.next_action_hint, "SHIPMENT JOB DETAIL");',
            "pm.test('job_type shipment', function () { pm.expect((data.job || {}).job_type).to.eql('shipment'); });",
            "var codes = (data.workflow.allowed_actions || []).map(function (a) { return a.action_code; });",
            "pm.test('A5 allowed after auto shipment', function () { pm.expect(codes).to.include('A5'); });",
        ],
    )
)

coll["item"].insert(0, auto_folder)

rename_map = {
    "00 — Setup": "01 — Setup (refresh / shipment_id preset)",
    "01 — Workflow → A6": "02 — Workflow → A6",
    "02 — Digital POD (photo + signature + video → A7)": "03 — Digital POD (photo + signature + video → A7)",
    "03 — After A7 Branch Check": "04 — After A7 Branch Check",
    "04A — Digital POD only → A8 (skip if hard_pod_required=true)": "05A — Digital POD only → A8 (skip if hard_pod_required=true)",
    "04B — Hard POD + DN → A7H confirmation → A8": "05B — Hard POD + DN → A7H confirmation → A8",
    "05 — COD Close (A9 → A10)": "06 — COD Close (A9 → A10)",
}
for item in coll["item"]:
    if item.get("name") in rename_map:
        item["name"] = rename_map[item["name"]]

for item in coll["item"]:
    if "Setup" in item.get("name", ""):
        item["description"] = "Optional refresh when shipment_id is preset or after folder 00. Updates sync metadata."
        for sub in item.get("item", []):
            if sub.get("name") == "02 — Dashboard":
                sub["event"][1]["script"]["exec"] = [
                    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
                    "pm.test('HTTP 200', function () { pm.response.to.have.status(200); });",
                    "var d = (pm.response.json().data || {});",
                    "irouteSaveDashboardJob(d);",
                    "var job = d.active_job || {};",
                    'if (job && job.job_id) { console.log("Active job:", job.job_no || job.job_id, "type:", job.job_type); }',
                ]
            if sub.get("name") == "03 — Job Detail":
                sub["request"]["url"] = "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/"
                exec_lines = sub["event"][1]["script"]["exec"]
                exec_lines.insert(
                    5,
                    "pm.test('job detail OK', function () { pm.expect((pm.response.json().data || {}).job).to.be.an('object'); });",
                )

skip_pre = [
    "eval(pm.collectionVariables.get('_iroute_helpers') || '');",
    "if (pm.variables.get('auto_shipment_a4_done') === 'true') { console.warn('SKIP — A1-A4 done in folder 00'); }",
]
for item in coll["item"]:
    if item.get("name", "").startswith("02 — Workflow"):
        for sub in item.get("item", []):
            name = sub.get("name", "")
            if any(
                name.startswith(p)
                for p in [
                    "04 — Execute A1",
                    "05 — Execute A2",
                    "06 — Execute A3",
                    "07 — Execute A4",
                ]
            ):
                if "event" not in sub:
                    sub["event"] = []
                sub["event"].insert(
                    0,
                    {"listen": "prerequest", "script": {"type": "text/javascript", "exec": skip_pre}},
                )
            url = sub.get("request", {}).get("url", "")
            if "/driver/jobs/shipment/{shipment_id}/actions/" in url:
                code = url.split("/actions/")[1].replace("/execute/", "")
                sub["request"]["url"] = (
                    "{{base_url}}/driver/jobs/{{job_type}}/{{job_id}}/actions/" + code + "/execute/"
                )

with OUT.open("w", encoding="utf-8") as f:
    json.dump(coll, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUT} ({len(coll['item'])} top-level folders)")
