/* ============================================
   iRoad Admin Dashboard — Dashboard Page Scripts
   ============================================ */

document.addEventListener("DOMContentLoaded", function () {
  initQuotaChartTooltips();
  initViewToggle();
  initOperationsHubTabs();
  initSurveillanceTabs();
  initLomTabs();
  initFinanceSalesHub();
  initFihTabs();
  initPurchaseIntelligenceHub();
  initVendorSettlementsTabs();
  initFiListHubTabs();
  initFleetHubDetailNavigation();
  initHubTableSearchEnter();
  initFleetTopSearchForms();
  initFiDriversHubTabs();
  initFihFleetMap();
  initSalesOperationsTabs();
  initPaymentsCashierTabs();
});

function applyView(view) {
  document.querySelectorAll("[data-section]").forEach(function (sec) {
    var sections = sec
      .getAttribute("data-section")
      .split(",")
      .map(function (v) {
        return v.trim();
      });
    sec.style.display = sections.indexOf(view) !== -1 ? "" : "none";
  });

  if (view === "fleet-integrity-hub" && window.fihFleetMapInstance) {
    window.setTimeout(function () {
      window.fihFleetMapInstance.invalidateSize();
    }, 150);
  }
}

/* ── Finance Sales Hub Tabs ── */
function initFinanceSalesHub() {
  var tabBtns = document.querySelectorAll("[data-fs-tab]");
  var panes = document.querySelectorAll("[data-fs-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-fs-tab") === tabKey,
      );
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-fs-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-fs-tab"));
    });
  });

  setTab("portfolio");
}

/* ── View Toggle ── */
function initViewToggle() {
  var btns = document.querySelectorAll(".view-toggle .vt-btn");
  if (!btns.length) return;

  var defaultBtn =
    document.querySelector('.view-toggle .vt-btn[data-view="overview"]') ||
    btns[0];

  btns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      btns.forEach(function (b) {
        b.classList.remove("active");
      });
      btn.classList.add("active");
      applyView(btn.getAttribute("data-view"));
    });
  });

  btns.forEach(function (b) {
    b.classList.remove("active");
  });
  defaultBtn.classList.add("active");
  applyView("overview");
}

/* ── Operations Hub Tabs ── */
function initOperationsHubTabs() {
  var tabBtns = document.querySelectorAll(".ops-tab-btn");
  var panes = document.querySelectorAll(".ops-pane");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-ops-tab") === tabKey,
      );
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-ops-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-ops-tab"));
    });
  });

  setTab("bookings");
}

/* ── Surveillance Tabs ── */
function initSurveillanceTabs() {
  var tabBtns = document.querySelectorAll(".surv-tab-btn");
  var panes = document.querySelectorAll(".surv-pane");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-surv-tab") === tabKey,
      );
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-surv-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-surv-tab"));
    });
  });

  setTab("live-map");
}

/* ── Live Operations Mgt Tabs ── */
function initLomTabs() {
  var tabBtns = document.querySelectorAll(".lom-tab");
  var panes = document.querySelectorAll(".lom-pane");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-lom-tab") === tabKey,
      );
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-lom-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-lom-tab"));
    });
  });

  setTab("live-trips");
}

/* ── Purchase Intelligence Hub ── */
function initPurchaseIntelligenceHub() {
  var kpiBtns = document.querySelectorAll("[data-pih-tab]");
  var kpiPanes = document.querySelectorAll("[data-pih-pane]");
  var viewBtns = document.querySelectorAll("[data-pih-view-tab]");
  var viewPanes = document.querySelectorAll("[data-pih-view-pane]");

  function bindTabs(btns, panes, btnAttr, paneAttr, defaultKey, aria) {
    if (!btns.length || !panes.length) return;

    function setTab(tabKey) {
      btns.forEach(function (btn) {
        var on = btn.getAttribute(btnAttr) === tabKey;
        btn.classList.toggle("active", on);
        if (aria) btn.setAttribute("aria-selected", on ? "true" : "false");
      });

      panes.forEach(function (pane) {
        pane.classList.toggle("active", pane.getAttribute(paneAttr) === tabKey);
      });
    }

    btns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setTab(btn.getAttribute(btnAttr));
      });
    });

    setTab(defaultKey);
  }

  bindTabs(kpiBtns, kpiPanes, "data-pih-tab", "data-pih-pane", "procurement");
  bindTabs(
    viewBtns,
    viewPanes,
    "data-pih-view-tab",
    "data-pih-view-pane",
    "analytics",
    true,
  );
}

/* ── Fleet Integrity Hub Tabs ── */
function initFihTabs() {
  var tabBtns = document.querySelectorAll("[data-fih-tab]");
  var panes = document.querySelectorAll("[data-fih-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-fih-tab") === tabKey,
      );
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-fih-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-fih-tab"));
    });
  });

  setTab("truck-assets");
}

/* ── Fleet Integrity Hub: Recent / Ext / Truck Att. lists ── */
function initFiListHubTabs() {
  var card = document.querySelector(".fih-hub-list-card");
  if (!card) return;

  var tabBtns = card.querySelectorAll("[data-fi-list-tab]");
  var panes = card.querySelectorAll("[data-fi-list-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      var on = btn.getAttribute("data-fi-list-tab") === tabKey;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-fi-list-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-fi-list-tab"));
    });
  });

  setTab("recent");
}

/* ── Fleet hub tables: filter locally; Enter opens scoped search results ── */
function initHubTableSearchEnter() {
  document.querySelectorAll("[data-hub-table-filter]").forEach(function (input) {
    var kind = input.getAttribute("data-hub-table-filter") || "";
    var table =
      kind === "truck"
        ? document.querySelector("[data-truck-hub-table]")
        : document.querySelector("[data-driver-hub-table]");
    if (!table) return;

    var rowSelector =
      kind === "truck" ? "tr[data-truck-hub-row]" : "tr[data-driver-hub-row]";
    var rows = table.querySelectorAll(rowSelector);

    function applyFilter() {
      var query = input.value.trim().toLowerCase();
      rows.forEach(function (row) {
        var rowText = row.textContent.toLowerCase().replace(/\s+/g, " ").trim();
        row.style.display = !query || rowText.indexOf(query) !== -1 ? "" : "none";
      });
    }

    input.addEventListener("input", applyFilter);

    input.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      var q = input.value.trim();
      if (!q) return;
      e.preventDefault();
      var scope = input.getAttribute("data-hub-search-submit-scope") || "all";
      if (window.iroadTenantSearch && window.iroadTenantSearch.go) {
        window.iroadTenantSearch.go(q, scope);
        return;
      }
      var form = input.closest("form");
      if (form) form.submit();
    });

    applyFilter();
  });
}

/* ── Fleet top search bars (above Trucks/Driver hub): Enter → results page ── */
function initFleetTopSearchForms() {
  document.querySelectorAll("[data-fleet-top-search-form]").forEach(function (form) {
    var input = form.querySelector("[data-fleet-top-search]");
    if (!input) return;

    form.addEventListener("submit", function (e) {
      var q = input.value.trim();
      if (!q) {
        e.preventDefault();
        return;
      }
      var scopeInput = form.querySelector('input[name="scope"]');
      var scope = scopeInput ? scopeInput.value : "all";
      if (window.iroadTenantSearch && window.iroadTenantSearch.go) {
        e.preventDefault();
        window.iroadTenantSearch.go(q, scope);
      }
    });
  });
}

/* ── Fleet hub rows: click row (except links) → detail page ── */
function initFleetHubDetailNavigation() {
  document
    .querySelectorAll(
      "tr[data-truck-hub-row][data-detail-url], tr[data-driver-hub-row][data-detail-url]",
    )
    .forEach(function (row) {
      function goToDetail() {
        var url = (row.getAttribute("data-detail-url") || "").trim();
        if (url && url !== "#") {
          window.location.href = url;
        }
      }

      row.addEventListener("click", function (e) {
        if (e.target.closest("a, button, input, select, textarea, label")) {
          return;
        }
        goToDetail();
      });

      row.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" && e.key !== " ") return;
        if (e.target.closest("a, button, input, select, textarea")) return;
        e.preventDefault();
        goToDetail();
      });
    });
}

/* ── Fleet Integrity Hub: Recent Drivers / Driver Att. ── */
function initFiDriversHubTabs() {
  var card = document.querySelector(".fih-drivers-hub-card");
  if (!card) return;

  var tabBtns = card.querySelectorAll("[data-fi-drv-tab]");
  var panes = card.querySelectorAll("[data-fi-drv-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      var on = btn.getAttribute("data-fi-drv-tab") === tabKey;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-fi-drv-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-fi-drv-tab"));
    });
  });

  setTab("recent-drivers");
}

/* ── Fleet Integrity Hub: OpenStreetMap via Leaflet ── */
function initFihFleetMap() {
  var el = document.getElementById("fihFleetMap");
  if (!el || typeof L === "undefined") return;
  if (el._leaflet_id) return;

  var map = L.map(el, {
    scrollWheelZoom: true,
    zoomControl: true,
  }).setView([24.5, 44.5], 6);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  function addUnit(lat, lng, color, title) {
    L.circleMarker([lat, lng], {
      radius: 8,
      color: color,
      fillColor: color,
      fillOpacity: 0.9,
      weight: 2,
    })
      .addTo(map)
      .bindPopup(title);
  }

  addUnit(24.7136, 46.6753, "#5051f9", "<strong>Internal</strong><br>J H A 9921 · Riyadh");
  addUnit(21.4858, 39.1925, "#5051f9", "<strong>Internal</strong><br>R R M 4410 · Jeddah");
  addUnit(26.4207, 50.0888, "#8b5cf6", "<strong>External</strong><br>A B C 7711 · Dammam");
  addUnit(18.2164, 42.5044, "#8b5cf6", "<strong>External</strong><br>N X T 9022 · Abha");
  addUnit(24.4681, 39.6142, "#5051f9", "<strong>Internal</strong><br>K S A 2201 · Madinah");

  function addDriver(lat, lng, title) {
    L.circleMarker([lat, lng], {
      radius: 7,
      color: "#14b8a6",
      fillColor: "#14b8a6",
      fillOpacity: 0.9,
      weight: 2,
    })
      .addTo(map)
      .bindPopup(title);
  }

  addDriver(
    21.4858,
    39.1925,
    "<strong>Driver</strong><br>Ahmed Mansour · Jeddah",
  );
  addDriver(
    26.4207,
    50.0888,
    "<strong>Driver</strong><br>Sami Al-Otaibi · Dammam",
  );
  addDriver(24.0892, 38.0618, "<strong>Driver</strong><br>Omar Muhammad · Yanbu");
  addDriver(
    24.7136,
    46.6753,
    "<strong>Driver</strong><br>Fahad Al-Anzi · Riyadh",
  );
  addDriver(18.2164, 42.5053, "<strong>Driver</strong><br>Yousef Sharif · Abha");

  window.fihFleetMapInstance = map;
}

/* ── Vendor Settlements Tabs ── */
function initVendorSettlementsTabs() {
  var tabBtns = document.querySelectorAll("[data-vs-tab]");
  var panes = document.querySelectorAll("[data-vs-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      var on = btn.getAttribute("data-vs-tab") === tabKey;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-vs-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-vs-tab"));
    });
  });
}

/* ── Sales Operations Tabs (Finance Sales Hub) ── */
function initSalesOperationsTabs() {
  var tabBtns = document.querySelectorAll("[data-fso-tab]");
  var panes = document.querySelectorAll("[data-fso-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      var on = btn.getAttribute("data-fso-tab") === tabKey;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-fso-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-fso-tab"));
    });
  });

  setTab("invoices");
}

/* ── Payments & Cashier Tabs (Finance Sales Hub) ── */
function initPaymentsCashierTabs() {
  var tabBtns = document.querySelectorAll("[data-pcs-tab]");
  var panes = document.querySelectorAll("[data-pcs-pane]");
  if (!tabBtns.length || !panes.length) return;

  function setTab(tabKey) {
    tabBtns.forEach(function (btn) {
      var on = btn.getAttribute("data-pcs-tab") === tabKey;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });

    panes.forEach(function (pane) {
      pane.classList.toggle(
        "active",
        pane.getAttribute("data-pcs-pane") === tabKey,
      );
    });
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.getAttribute("data-pcs-tab"));
    });
  });

  setTab("statistics");
}

/* ── Quota charts: floating tooltips on bar + donut hover ── */
function initQuotaChartTooltips() {
  var bars = document.querySelectorAll("[data-quota-bar-tip]");
  var donutCharts = document.querySelectorAll("[data-quota-donut-chart]");
  if (!bars.length && !donutCharts.length) {
    return;
  }

  var tip = document.querySelector(".quota-chart-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "quota-chart-tooltip";
    tip.setAttribute("role", "tooltip");
    document.body.appendChild(tip);
  }

  function loadDonutSegments(jsonId) {
    var el = document.getElementById(jsonId || "quota-donut-data");
    if (!el || !el.textContent) {
      return [];
    }
    try {
      var parsed = JSON.parse(el.textContent);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return [];
    }
  }

  function buildDonutArcs(segments) {
    var arcs = [];
    var total = 0;
    segments.forEach(function (seg) {
      total += Math.max(0, parseFloat(seg.weight) || 0);
    });
    if (total <= 0) {
      return arcs;
    }
    var cursor = 0;
    segments.forEach(function (seg) {
      var w = Math.max(0, parseFloat(seg.weight) || 0);
      if (w <= 0) {
        return;
      }
      var span = (w / total) * 360;
      arcs.push({
        seg: seg,
        start: cursor,
        end: cursor + span,
      });
      cursor += span;
    });
    return arcs;
  }

  function formatCount(raw) {
    var n = parseInt(String(raw || "0"), 10);
    return Number.isNaN(n) ? "0" : n.toLocaleString();
  }

  function positionTip(clientX, clientY) {
    tip.style.left = clientX + "px";
    tip.style.top = clientY - 14 + "px";
  }

  var activeLegendScope = null;

  function hideTip() {
    tip.classList.remove("is-visible");
    if (activeLegendScope) {
      activeLegendScope
        .querySelectorAll("[data-quota-donut-legend].is-active")
        .forEach(function (el) {
          el.classList.remove("is-active");
        });
      activeLegendScope = null;
    }
  }

  function showDonutSegmentTip(seg, clientX, clientY, legendEl, tipKind, legendScope) {
    if (!seg) {
      return;
    }
    var label = seg.label || "";
    var used = seg.used_display != null ? String(seg.used_display) : formatCount(seg.used);
    var total = seg.total_display != null ? String(seg.total_display) : "0";
    var pct = seg.pct_label || "";
    var dotStyle = seg.color ? ' style="background:' + seg.color + '"' : "";
    var countLine =
      tipKind === "fleet"
        ? "Trucks: <b>" + used + "</b> / " + total
        : "Used: <b>" + used + "</b> / " + total;
    var pctLine =
      tipKind === "fleet"
        ? "Share: <b>" + pct + "</b> of fleet"
        : "Quota: <b>" + pct + "</b>";
    tip.innerHTML =
      "<strong>" +
      label +
      "</strong>" +
      '<div class="tip-line"><span class="tip-dot"' +
      dotStyle +
      "></span>" +
      countLine +
      "</div>" +
      (pct ? '<div class="tip-line">' + pctLine + "</div>" : "");
    tip.classList.add("is-visible");
    positionTip(clientX, clientY);
    if (legendScope) {
      legendScope
        .querySelectorAll("[data-quota-donut-legend].is-active")
        .forEach(function (el) {
          el.classList.remove("is-active");
        });
      activeLegendScope = legendScope;
      if (legendEl) {
        legendEl.classList.add("is-active");
      } else if (seg.key) {
        legendScope
          .querySelectorAll('[data-quota-donut-legend][data-segment-key="' + seg.key + '"]')
          .forEach(function (el) {
            el.classList.add("is-active");
          });
      }
    }
  }

  function showBarTip(bar, clientX, clientY) {
    var month = bar.getAttribute("data-month") || "";
    var seriesLabel = bar.getAttribute("data-series-label") || "Count";
    var count = formatCount(bar.getAttribute("data-count"));
    var series = bar.getAttribute("data-series") || "";
    tip.innerHTML =
      "<strong>" +
      month +
      "</strong>" +
      '<div class="tip-line"><span class="tip-dot ' +
      series +
      '"></span>' +
      seriesLabel +
      ": <b>" +
      count +
      "</b></div>";
    tip.classList.add("is-visible");
    positionTip(clientX, clientY);
  }

  function showMonthTip(group, clientX, clientY) {
    var monthLabel = "";
    var trucks = 0;
    var drivers = 0;
    group.querySelectorAll("[data-quota-bar-tip]").forEach(function (bar) {
      if (!monthLabel) {
        monthLabel = bar.getAttribute("data-month") || "";
      }
      var c = parseInt(bar.getAttribute("data-count") || "0", 10);
      if (bar.getAttribute("data-series") === "truck") {
        trucks = c;
      }
      if (bar.getAttribute("data-series") === "driver") {
        drivers = c;
      }
    });
    tip.innerHTML =
      "<strong>" +
      monthLabel +
      "</strong>" +
      '<div class="tip-line"><span class="tip-dot truck"></span>Total Trucks: <b>' +
      formatCount(trucks) +
      "</b></div>" +
      '<div class="tip-line"><span class="tip-dot driver"></span>Active Drivers: <b>' +
      formatCount(drivers) +
      "</b></div>";
    tip.classList.add("is-visible");
    positionTip(clientX, clientY);
  }

  function segmentAtAngle(deg, arcs) {
    if (!arcs.length) {
      return null;
    }
    var a = ((deg % 360) + 360) % 360;
    for (var i = 0; i < arcs.length; i++) {
      var arc = arcs[i];
      if (a >= arc.start && a < arc.end) {
        return arc.seg;
      }
    }
    return arcs[arcs.length - 1].seg;
  }

  function donutHitSegment(wrap, clientX, clientY, arcs) {
    var donut = wrap.querySelector(".quota-donut");
    if (!donut) {
      return null;
    }
    var rect = donut.getBoundingClientRect();
    var cx = rect.left + rect.width / 2;
    var cy = rect.top + rect.height / 2;
    var dx = clientX - cx;
    var dy = clientY - cy;
    var dist = Math.sqrt(dx * dx + dy * dy);
    var outerR = rect.width / 2;
    var innerR = outerR * 0.68;
    if (dist < innerR || dist > outerR) {
      return null;
    }
    var deg = (Math.atan2(dx, -dy) * 180) / Math.PI;
    return segmentAtAngle(deg, arcs);
  }

  bars.forEach(function (bar) {
    bar.addEventListener("mouseenter", function (e) {
      showBarTip(bar, e.clientX, e.clientY);
    });
    bar.addEventListener("mousemove", function (e) {
      if (tip.classList.contains("is-visible")) {
        positionTip(e.clientX, e.clientY);
      }
    });
    bar.addEventListener("mouseleave", hideTip);
    bar.addEventListener("focus", function (e) {
      showBarTip(bar, e.clientX, e.clientY);
    });
    bar.addEventListener("blur", hideTip);
  });

  document.querySelectorAll(".quota-month-group").forEach(function (group) {
    group.addEventListener("mouseenter", function (e) {
      if (e.target.closest("[data-quota-bar-tip]")) {
        return;
      }
      showMonthTip(group, e.clientX, e.clientY);
    });
    group.addEventListener("mousemove", function (e) {
      if (tip.classList.contains("is-visible") && !e.target.closest("[data-quota-bar-tip]")) {
        positionTip(e.clientX, e.clientY);
      }
    });
    group.addEventListener("mouseleave", hideTip);
  });

  donutCharts.forEach(function (wrap) {
    var jsonId = wrap.getAttribute("data-donut-json-id") || "quota-donut-data";
    var tipKind = wrap.getAttribute("data-donut-tip-kind") || "quota";
    var segments = loadDonutSegments(jsonId);
    var arcs = buildDonutArcs(segments);
    var segmentByKey = {};
    segments.forEach(function (seg) {
      if (seg && seg.key) {
        segmentByKey[seg.key] = seg;
      }
    });
    var legendScope =
      document.querySelector('[data-donut-legend-for="' + jsonId + '"]') || wrap.parentElement;

    wrap.addEventListener("mousemove", function (e) {
      var seg = donutHitSegment(wrap, e.clientX, e.clientY, arcs);
      if (!seg) {
        hideTip();
        return;
      }
      showDonutSegmentTip(seg, e.clientX, e.clientY, null, tipKind, legendScope);
    });
    wrap.addEventListener("mouseleave", hideTip);

    if (!legendScope) {
      return;
    }

    legendScope.querySelectorAll("[data-quota-donut-legend]").forEach(function (item) {
      var key = item.getAttribute("data-segment-key");
      var seg = key ? segmentByKey[key] : null;
      if (!seg) {
        return;
      }

      function onLegendHover(e) {
        showDonutSegmentTip(seg, e.clientX, e.clientY, item, tipKind, legendScope);
      }

      item.addEventListener("mouseenter", onLegendHover);
      item.addEventListener("mousemove", function (e) {
        if (tip.classList.contains("is-visible")) {
          positionTip(e.clientX, e.clientY);
        }
      });
      item.addEventListener("mouseleave", hideTip);
      item.addEventListener("focus", onLegendHover);
      item.addEventListener("blur", hideTip);
    });
  });
}
