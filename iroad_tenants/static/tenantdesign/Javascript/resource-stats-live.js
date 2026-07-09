/* Live refresh — Plan & Resources Intelligence (tenant dashboard overview). */

window.iroadResourceStatsState = {
  meta: null,
  timerId: null,
  inFlight: false,
};

function iroadParseResourceStatsMeta() {
  var node = document.getElementById("resource-stats-meta");
  if (!node || !node.textContent) {
    return null;
  }
  try {
    return JSON.parse(node.textContent);
  } catch (err) {
    return null;
  }
}

function iroadOverviewShellVisible() {
  var shell = document.querySelector('.overview-shell[data-section="overview"]');
  if (!shell) return false;
  return shell.style.display !== "none";
}

function iroadApplyResourceStatsPayload(payload) {
  if (!payload) return;

  var planPanel = document.querySelector("[data-live-plan-panel]");
  if (planPanel) {
    var planName = planPanel.querySelector("[data-live-plan-name]");
    var planPrice = planPanel.querySelector("[data-live-plan-price]");
    var planCycle = planPanel.querySelector("[data-live-plan-cycle]");
    var planRenewal = planPanel.querySelector("[data-live-plan-renewal]");
    var planDriver = planPanel.querySelector("[data-live-plan-driver]");
    var planBackup = planPanel.querySelector("[data-live-plan-backup]");

    if (planName && payload.plan_name != null) {
      planName.textContent = payload.plan_name;
    }
    if (planPrice && payload.plan_price_line != null) {
      planPrice.textContent = payload.plan_price_line;
    }
    if (planCycle && payload.plan_cycle_label != null) {
      planCycle.textContent = payload.plan_cycle_label;
    }
    if (planRenewal && payload.plan_renewal_display != null) {
      planRenewal.textContent = payload.plan_renewal_display;
    }
    if (planDriver && payload.plan_driver_attr != null) {
      planDriver.textContent = payload.plan_driver_attr;
    }
    if (planBackup && payload.plan_backup_attr != null) {
      planBackup.textContent = payload.plan_backup_attr;
    }
  }

  (payload.resource_rows || []).forEach(function (row) {
    var item = document.querySelector(
      '[data-resource-key="' + row.key + '"]',
    );
    if (!item) return;

    var pctEl = item.querySelector("[data-resource-pct]");
    var currentEl = item.querySelector("[data-resource-current]");
    var totalEl = item.querySelector("[data-resource-total]");
    var barEl = item.querySelector("[data-resource-bar]");

    if (pctEl) pctEl.textContent = row.pct_label || "";
    if (currentEl) currentEl.textContent = row.current_display || "0";
    if (totalEl) totalEl.textContent = row.total_display || "0";
    if (barEl) barEl.style.width = (row.bar_width || 0) + "%";
  });

  if (Array.isArray(payload.donut_segments)) {
    var donutData = document.getElementById("quota-donut-data");
    if (donutData) {
      donutData.textContent = JSON.stringify(payload.donut_segments);
    }

    var donut = document.querySelector(
      '[data-quota-donut-chart][data-donut-json-id="quota-donut-data"] .quota-donut',
    );
    if (donut && payload.donut_style) {
      donut.setAttribute("style", payload.donut_style);
    }

    payload.donut_segments.forEach(function (seg) {
      document
        .querySelectorAll(
          '[data-quota-donut-legend][data-segment-key="' + seg.key + '"] .quota-legend-pct',
        )
        .forEach(function (el) {
          el.textContent = seg.pct_label || "";
        });
    });
  }
}

function iroadRefreshResourceStats() {
  var meta = window.iroadResourceStatsState.meta;
  if (!meta || !meta.refreshUrl || window.iroadResourceStatsState.inFlight) {
    return;
  }
  if (!iroadOverviewShellVisible()) {
    return;
  }

  window.iroadResourceStatsState.inFlight = true;
  fetch(meta.refreshUrl, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  })
    .then(function (res) {
      if (!res.ok) throw new Error("resource stats refresh failed");
      return res.json();
    })
    .then(function (payload) {
      iroadApplyResourceStatsPayload(payload);
    })
    .catch(function () {})
    .finally(function () {
      window.iroadResourceStatsState.inFlight = false;
    });
}

function iroadScheduleResourceStatsPolling() {
  var state = window.iroadResourceStatsState;
  if (state.timerId) {
    window.clearInterval(state.timerId);
    state.timerId = null;
  }

  var meta = state.meta || {};
  var interval = parseInt(meta.pollIntervalMs, 10);
  if (!meta.refreshUrl || !interval || interval < 5000) {
    return;
  }

  state.timerId = window.setInterval(iroadRefreshResourceStats, interval);
}

function iroadBootResourceStatsLive() {
  if (!document.querySelector("[data-live-resource-stats]")) {
    return;
  }

  window.iroadResourceStatsState.meta = iroadParseResourceStatsMeta();
  iroadScheduleResourceStatsPolling();

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      iroadRefreshResourceStats();
    }
  });

  var viewBtns = document.querySelectorAll(".view-toggle .vt-btn");
  viewBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.getAttribute("data-view") === "overview") {
        window.setTimeout(iroadRefreshResourceStats, 50);
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", iroadBootResourceStatsLive);
