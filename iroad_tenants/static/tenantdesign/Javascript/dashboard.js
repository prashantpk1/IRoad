/* ============================================
   iRoad Admin Dashboard — Dashboard Page Scripts
   ============================================ */

document.addEventListener("DOMContentLoaded", function () {
  initViewToggle();
  initOperationsHubTabs();
  initSurveillanceTabs();
  initLomTabs();
  initFinanceSalesHub();
  initFihTabs();
  initPurchaseIntelligenceHub();
  initVendorSettlementsTabs();
  initFiListHubTabs();
  initTruckHubSearch();
  initDriverHubSearch();
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

/* ── Fleet Integrity Hub: Truck search ── */
function initTruckHubSearch() {
  var input = document.querySelector("[data-truck-hub-search]");
  var rows = document.querySelectorAll("[data-truck-hub-row]");
  if (!input || !rows.length) return;

  function applyFilter() {
    var query = input.value.trim().toLowerCase();

    rows.forEach(function (row) {
      var rowText = row.textContent.toLowerCase().replace(/\s+/g, " ").trim();
      row.style.display = !query || rowText.indexOf(query) !== -1 ? "" : "none";
    });
  }

  input.addEventListener("input", applyFilter);
  applyFilter();
}

/* ── Fleet Integrity Hub: Driver search ── */
function initDriverHubSearch() {
  var input = document.querySelector("[data-driver-hub-search]");
  var rows = document.querySelectorAll("[data-driver-hub-row]");
  if (!input || !rows.length) return;

  function applyFilter() {
    var query = input.value.trim().toLowerCase();

    rows.forEach(function (row) {
      var rowText = row.textContent.toLowerCase().replace(/\s+/g, " ").trim();
      row.style.display = !query || rowText.indexOf(query) !== -1 ? "" : "none";
    });
  }

  input.addEventListener("input", applyFilter);
  applyFilter();
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
