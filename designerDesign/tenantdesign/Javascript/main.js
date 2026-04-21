/* ============================================
   iRoad Admin Dashboard - Main JavaScript
   Version: 1.0
   ============================================ */

document.addEventListener("DOMContentLoaded", function () {
  ensureUnifiedSidebar().then(function () {
    // Initialize all components after sidebar is unified
    initSidebar();
    initSidebarActiveState();
    initSidebarCollapse();
    initTimeValidation();
    initFormValidation();
    initUserProfile();
    initNotificationPanel();
    initHeaderDateTime();
    initSalesOrderLines();
    initPurchaseOrderLines();
    initShipmentDocumentLines();
    initDocumentHandoverVerificationLines();
    initBookingLinesRoute();
    initOperationActionLogMedia();
  });
});

/* ============================================
   Sales Order - Order Lines (sub-table)
   ============================================ */
function initSalesOrderLines() {
  const tbody = document.getElementById("soLinesTbody");
  const addBtn = document.getElementById("addOrderLineBtn");
  const subtotalInput = document.getElementById("subtotal");
  const taxRateInput = document.getElementById("taxRate");
  const taxAmountInput = document.getElementById("taxAmount");
  const grandTotalInput = document.getElementById("grandTotal");

  // Only run on Sales-order.html (or pages with same markup)
  if (!tbody || !addBtn) return;

  function toNumber(v) {
    const n = Number.parseFloat(String(v ?? "").trim());
    return Number.isFinite(n) ? n : 0;
  }

  function money(n) {
    const x = Number.isFinite(n) ? n : 0;
    return Math.round(x * 100) / 100;
  }

  function getRows() {
    return Array.from(tbody.querySelectorAll("tr[data-so-line]"));
  }

  function isTripRow(tr) {
    const st = tr.querySelector('[data-field="serviceType"]');
    return (st?.value || "") === "Trip";
  }

  function updateTripOnlyColumnVisibility() {
    const anyTrip = getRows().some((tr) => isTripRow(tr));
    const tripOnlyHeaders = document.querySelectorAll("th.so-trip-only");
    const tripOnlyCells = document.querySelectorAll("td.so-trip-only");
    [...tripOnlyHeaders, ...tripOnlyCells].forEach((el) => {
      el.classList.toggle("d-none", !anyTrip);
    });
  }

  function updateSN() {
    getRows().forEach((tr, idx) => {
      const snEl = tr.querySelector("[data-sn]");
      if (snEl) snEl.textContent = String(idx + 1);
    });
  }

  function updateLineCalculations(tr) {
    const isTrip = isTripRow(tr);
    const qty = toNumber(tr.querySelector('[data-field="qty"]')?.value);
    const unitPrice = toNumber(
      tr.querySelector('[data-field="unitPrice"]')?.value,
    );

    const tripType =
      tr.querySelector('[data-field="tripType"]')?.value || "Outbound";
    const tripCount = isTrip ? (tripType === "Round" ? qty * 2 : qty) : 0;

    const tripCountEl = tr.querySelector('[data-field="tripCount"]');
    if (tripCountEl) tripCountEl.value = isTrip ? String(tripCount) : "";

    const lineSubtotal = money(unitPrice * qty);
    const subtotalEl = tr.querySelector('[data-field="subtotal"]');
    if (subtotalEl) subtotalEl.value = String(lineSubtotal);

    // Trip-only fields: enable/disable + clear when not Trip
    const routeEl = tr.querySelector('[data-field="route"]');
    const tripTypeEl = tr.querySelector('[data-field="tripType"]');

    if (!isTrip) {
      if (routeEl) routeEl.value = "";
      if (tripTypeEl) tripTypeEl.value = "Outbound";
    }

    if (routeEl) routeEl.disabled = !isTrip;
    if (tripTypeEl) tripTypeEl.disabled = !isTrip;
    if (tripCountEl) tripCountEl.disabled = true;
  }

  function updateHeaderTotals() {
    const subtotal = money(
      getRows().reduce((sum, tr) => {
        const v = toNumber(tr.querySelector('[data-field="subtotal"]')?.value);
        return sum + v;
      }, 0),
    );

    const taxRate = toNumber(taxRateInput?.value);
    const taxAmount = money(subtotal * (taxRate / 100));
    const grandTotal = money(subtotal + taxAmount);

    if (subtotalInput) subtotalInput.value = String(subtotal);
    if (taxAmountInput) taxAmountInput.value = String(taxAmount);
    if (grandTotalInput) grandTotalInput.value = String(grandTotal);
  }

  function attachRowEvents(tr) {
    tr.addEventListener("input", function (e) {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      if (t.matches('[data-field="unitPrice"], [data-field="qty"]')) {
        updateLineCalculations(tr);
        updateHeaderTotals();
      }
    });

    tr.addEventListener("change", function (e) {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;

      if (t.matches('[data-field="serviceType"]')) {
        updateLineCalculations(tr);
        updateTripOnlyColumnVisibility();
        updateHeaderTotals();
      }

      if (t.matches('[data-field="tripType"]')) {
        updateLineCalculations(tr);
        updateHeaderTotals();
      }
    });

    const delBtn = tr.querySelector('[data-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        tr.remove();
        updateSN();
        updateTripOnlyColumnVisibility();
        updateHeaderTotals();
      });
    }
  }

  function createLineRow() {
    const tr = document.createElement("tr");
    tr.setAttribute("data-so-line", "true");
    tr.innerHTML = `
      <td data-label="SN"><span data-sn></span></td>
      <td data-label="Service Type">
        <select class="form-select form-select-sm" data-field="serviceType">
          <option value="Trip" selected>Trip</option>
          <option value="Handling">Handling</option>
          <option value="Storage">Storage</option>
        </select>
      </td>
      <td data-label="Service Item">
        <select class="form-select form-select-sm" data-field="serviceItem">
          <option value="" selected disabled>-Select-</option>
          <option value="Trip Service">Trip Service</option>
          <option value="Loading">Loading</option>
          <option value="Unloading">Unloading</option>
          <option value="Warehousing">Warehousing</option>
        </select>
      </td>
      <td class="so-trip-only" data-label="Route">
        <select class="form-select form-select-sm" data-field="route">
          <option value="" selected disabled>-Select-</option>
          <option value="JED-YAN">JED–YAN</option>
          <option value="RUH-JED">RUH–JED</option>
          <option value="DMM-RUH">DMM–RUH</option>
        </select>
      </td>
      <td class="so-trip-only" data-label="Trip Type">
        <select class="form-select form-select-sm" data-field="tripType">
          <option value="Outbound" selected>Outbound</option>
          <option value="Inbound">Inbound</option>
          <option value="Round">Round</option>
        </select>
      </td>
      <td data-label="Unit">
        <select class="form-select form-select-sm" data-field="unit">
          <option value="Trip" selected>Trip</option>
          <option value="Shipment">Shipment</option>
          <option value="Hour">Hour</option>
        </select>
      </td>
      <td data-label="Unit Price">
        <input type="number" min="0" step="0.01" class="form-control form-control-sm" data-field="unitPrice" placeholder="0.00" />
      </td>
      <td data-label="QTY">
        <input type="number" min="0" step="1" class="form-control form-control-sm" data-field="qty" placeholder="0" />
      </td>
      <td class="so-trip-only" data-label="Trip Count">
        <input type="text" class="form-control form-control-sm" data-field="tripCount" readonly />
      </td>
      <td data-label="Subtotal">
        <input type="text" class="form-control form-control-sm" data-field="subtotal" readonly />
      </td>
      <td data-col="actions" data-label="Actions">
        <button type="button" class="eal-row-btn danger" data-action="delete" title="Delete">
          <i class="bi bi-trash3"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
    attachRowEvents(tr);
    updateSN();
    updateLineCalculations(tr);
    updateTripOnlyColumnVisibility();
    updateHeaderTotals();
  }

  addBtn.addEventListener("click", function () {
    createLineRow();
  });

  if (taxRateInput) {
    taxRateInput.addEventListener("input", function () {
      updateHeaderTotals();
    });
  }

  // Start with one blank line
  createLineRow();
}

/* ============================================
   Ensure Unified Sidebar (load from index.html)
   ============================================ */
function ensureUnifiedSidebar() {
  // Navigation sidebar is now hardcoded directly in the HTML files instead of dynamically loaded
  return Promise.resolve();
}

/* ============================================
   Purchase Order - Order Lines (sub-table)
   ============================================ */
function initPurchaseOrderLines() {
  const tbody = document.getElementById("poLinesTbody");
  const addBtn = document.getElementById("addPoLineBtn");
  const subtotalInput = document.getElementById("subtotal");
  const taxRateInput = document.getElementById("taxRate");
  const taxAmountInput = document.getElementById("taxAmount");
  const grandTotalInput = document.getElementById("grandTotal");

  // Only run on Purchase-order.html (or pages with same markup)
  if (!tbody || !addBtn) return;

  function toNumber(v) {
    const n = Number.parseFloat(String(v ?? "").trim());
    return Number.isFinite(n) ? n : 0;
  }

  function money(n) {
    const x = Number.isFinite(n) ? n : 0;
    return Math.round(x * 100) / 100;
  }

  function getRows() {
    return Array.from(tbody.querySelectorAll("tr[data-po-line]"));
  }

  function isTripRow(tr) {
    const st = tr.querySelector('[data-field="serviceType"]');
    return (st?.value || "") === "Trip";
  }

  function updateTripOnlyColumnVisibility() {
    const anyTrip = getRows().some((tr) => isTripRow(tr));
    const tripOnlyHeaders = document.querySelectorAll("th.po-trip-only");
    const tripOnlyCells = document.querySelectorAll("td.po-trip-only");
    [...tripOnlyHeaders, ...tripOnlyCells].forEach((el) => {
      el.classList.toggle("d-none", !anyTrip);
    });
  }

  function updateSN() {
    getRows().forEach((tr, idx) => {
      const snEl = tr.querySelector("[data-sn]");
      if (snEl) snEl.textContent = String(idx + 1);
    });
  }

  function updateLineCalculations(tr) {
    const isTrip = isTripRow(tr);
    const qty = toNumber(tr.querySelector('[data-field="qty"]')?.value);
    const unitPrice = toNumber(
      tr.querySelector('[data-field="unitPrice"]')?.value,
    );

    const tripType =
      tr.querySelector('[data-field="tripType"]')?.value || "Outbound";
    const tripCount = isTrip ? (tripType === "Round" ? qty * 2 : qty) : 0;

    const tripCountEl = tr.querySelector('[data-field="tripCount"]');
    if (tripCountEl) tripCountEl.value = isTrip ? String(tripCount) : "";

    const lineSubtotal = money(unitPrice * qty);
    const subtotalEl = tr.querySelector('[data-field="subtotal"]');
    if (subtotalEl) subtotalEl.value = String(lineSubtotal);

    const routeEl = tr.querySelector('[data-field="route"]');
    const tripTypeEl = tr.querySelector('[data-field="tripType"]');

    if (!isTrip) {
      if (routeEl) routeEl.value = "";
      if (tripTypeEl) tripTypeEl.value = "Outbound";
    }

    if (routeEl) routeEl.disabled = !isTrip;
    if (tripTypeEl) tripTypeEl.disabled = !isTrip;
    if (tripCountEl) tripCountEl.disabled = true;
  }

  function updateHeaderTotals() {
    const subtotal = money(
      getRows().reduce((sum, tr) => {
        const v = toNumber(tr.querySelector('[data-field="subtotal"]')?.value);
        return sum + v;
      }, 0),
    );

    const taxRate = toNumber(taxRateInput?.value);
    const taxAmount = money(subtotal * (taxRate / 100));
    const grandTotal = money(subtotal + taxAmount);

    if (subtotalInput) subtotalInput.value = String(subtotal);
    if (taxAmountInput) taxAmountInput.value = String(taxAmount);
    if (grandTotalInput) grandTotalInput.value = String(grandTotal);
  }

  function attachRowEvents(tr) {
    tr.addEventListener("input", function (e) {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      if (t.matches('[data-field="unitPrice"], [data-field="qty"]')) {
        updateLineCalculations(tr);
        updateHeaderTotals();
      }
    });

    tr.addEventListener("change", function (e) {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;

      if (t.matches('[data-field="serviceType"]')) {
        updateLineCalculations(tr);
        updateTripOnlyColumnVisibility();
        updateHeaderTotals();
      }

      if (t.matches('[data-field="tripType"]')) {
        updateLineCalculations(tr);
        updateHeaderTotals();
      }
    });

    const delBtn = tr.querySelector('[data-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        tr.remove();
        updateSN();
        updateTripOnlyColumnVisibility();
        updateHeaderTotals();
      });
    }
  }

  function createLineRow() {
    const tr = document.createElement("tr");
    tr.setAttribute("data-po-line", "true");
    tr.innerHTML = `
      <td data-label="SN"><span data-sn></span></td>
      <td data-label="Sales Order No">
        <select class="form-select form-select-sm" data-field="salesOrderNo">
          <option value="" selected disabled>-Select-</option>
          <option value="SO-001">SO-001</option>
          <option value="SO-002">SO-002</option>
          <option value="SO-003">SO-003</option>
        </select>
      </td>
      <td data-label="Sales Order Item">
        <select class="form-select form-select-sm" data-field="salesOrderItem">
          <option value="" selected disabled>-Select-</option>
          <option value="Line 1">Line 1</option>
          <option value="Line 2">Line 2</option>
          <option value="Line 3">Line 3</option>
        </select>
      </td>
      <td data-label="Service Type">
        <select class="form-select form-select-sm" data-field="serviceType">
          <option value="Trip" selected>Trip</option>
          <option value="Handling">Handling</option>
          <option value="Storage">Storage</option>
        </select>
      </td>
      <td data-label="Service Item">
        <select class="form-select form-select-sm" data-field="serviceItem">
          <option value="" selected disabled>-Select-</option>
          <option value="Trip Service">Trip Service</option>
          <option value="Loading">Loading</option>
          <option value="Unloading">Unloading</option>
          <option value="Warehousing">Warehousing</option>
        </select>
      </td>
      <td class="po-trip-only" data-label="Route">
        <select class="form-select form-select-sm" data-field="route">
          <option value="" selected disabled>-Select-</option>
          <option value="JED-YAN">JED–YAN</option>
          <option value="RUH-JED">RUH–JED</option>
          <option value="DMM-RUH">DMM–RUH</option>
        </select>
      </td>
      <td class="po-trip-only" data-label="Trip Type">
        <select class="form-select form-select-sm" data-field="tripType">
          <option value="Outbound" selected>Outbound</option>
          <option value="Inbound">Inbound</option>
          <option value="Round">Round</option>
        </select>
      </td>
      <td data-label="Unit">
        <select class="form-select form-select-sm" data-field="unit">
          <option value="Trip" selected>Trip</option>
          <option value="Shipment">Shipment</option>
          <option value="Hour">Hour</option>
        </select>
      </td>
      <td data-label="Unit Price (Buy)">
        <input type="number" min="0" step="0.01" class="form-control form-control-sm" data-field="unitPrice" placeholder="0.00" />
      </td>
      <td data-label="QTY">
        <input type="number" min="0" step="1" class="form-control form-control-sm" data-field="qty" placeholder="0" />
      </td>
      <td class="po-trip-only" data-label="Trip Count">
        <input type="text" class="form-control form-control-sm" data-field="tripCount" readonly />
      </td>
      <td data-label="Subtotal">
        <input type="text" class="form-control form-control-sm" data-field="subtotal" readonly />
      </td>
      <td data-col="actions" data-label="Actions">
        <button type="button" class="eal-row-btn danger" data-action="delete" title="Delete">
          <i class="bi bi-trash3"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
    attachRowEvents(tr);
    updateSN();
    updateLineCalculations(tr);
    updateTripOnlyColumnVisibility();
    updateHeaderTotals();
  }

  addBtn.addEventListener("click", function () {
    createLineRow();
  });

  if (taxRateInput) {
    taxRateInput.addEventListener("input", function () {
      updateHeaderTotals();
    });
  }

  // Start with one blank line
  createLineRow();
}

/* ============================================
   Shipment Documents - Subform Line Fields (sub-table)
   ============================================ */
function initShipmentDocumentLines() {
  const tbody = document.getElementById("sdLinesTbody");
  const addBtn = document.getElementById("addSdLineBtn");

  // Only run on Shipment-documents.html (or pages with same markup)
  if (!tbody || !addBtn) return;

  function getRows() {
    return Array.from(tbody.querySelectorAll("tr[data-sd-line]"));
  }

  function updateSN() {
    getRows().forEach((tr, idx) => {
      const snEl = tr.querySelector("[data-sn]");
      if (snEl) snEl.textContent = String(idx + 1);
    });
  }

  function attachRowEvents(tr) {
    const delBtn = tr.querySelector('[data-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        tr.remove();
        updateSN();
      });
    }
  }

  function createLineRow() {
    const tr = document.createElement("tr");
    tr.setAttribute("data-sd-line", "true");
    tr.innerHTML = `
      <td data-label="SN"><span data-sn></span></td>
      <td data-label="Doc Ref No">
        <input type="text" class="form-control form-control-sm" data-field="docRefNo" placeholder="Ref No..." />
      </td>
      <td data-label="Extra Ref">
        <input type="text" class="form-control form-control-sm" data-field="extraRef" placeholder="Extra Ref..." />
      </td>
      <td data-label="Page No">
        <input type="number" class="form-control form-control-sm" data-field="pageNo" min="1" placeholder="Page No" />
      </td>
      <td data-label="Status">
        <select class="form-select form-select-sm" data-field="status">
          <option value="pending" selected>Pending</option>
          <option value="uploaded">Uploaded</option>
          <option value="approved">Approved</option>
        </select>
      </td>
      <td data-label="Physical Location">
        <select class="form-select form-select-sm" data-field="physicalLocation">
          <option value="" selected disabled>-Select location-</option>
          <option value="not_collected">Not Collected</option>
          <option value="submitted_to_receiver">Submitted to Receiver</option>
          <option value="with_driver">With Driver</option>
          <option value="submitted_to_office">Submitted to Office</option>
          <option value="submitted_to_client">Submitted to Client</option>
        </select>
      </td>
      <td data-label="Attachment">
        <input type="file" class="form-control form-control-sm" data-field="attachment" />
      </td>
      <td data-col="actions" data-label="Actions">
        <button type="button" class="eal-row-btn danger" data-action="delete" title="Delete">
          <i class="bi bi-trash3"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
    attachRowEvents(tr);
    updateSN();
  }

  addBtn.addEventListener("click", function () {
    createLineRow();
  });

  // Start with one blank line
  createLineRow();
}

/* ============================================
   Document Handover - Pages Verification (sub-table)
   ============================================ */
function initDocumentHandoverVerificationLines() {
  const tbody = document.getElementById("dhLinesTbody");
  const addBtn = document.getElementById("addDhLineBtn");

  // Only run on Document-handover.html (or pages with same markup)
  if (!tbody || !addBtn) return;

  function getRows() {
    return Array.from(tbody.querySelectorAll("tr[data-dh-line]"));
  }

  function updateSN() {
    getRows().forEach((tr, idx) => {
      const snEl = tr.querySelector("[data-sn]");
      if (snEl) snEl.textContent = String(idx + 1);
      const seqEl = tr.querySelector('[data-field="sequence"]');
      if (seqEl && !seqEl.value) seqEl.value = String(idx + 1);
    });
  }

  function attachRowEvents(tr) {
    const delBtn = tr.querySelector('[data-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        tr.remove();
        updateSN();
      });
    }
  }

  function createLineRow() {
    const tr = document.createElement("tr");
    tr.setAttribute("data-dh-line", "true");
    tr.innerHTML = `
      <td data-label="SN"><span data-sn></span></td>
      <td data-label="Doc Page (list)">
        <select class="form-select form-select-sm" data-field="docPage">
          <option value="" selected disabled>-Select doc page-</option>
          <option value="page1">Page-1</option>
          <option value="page2">Page-2</option>
        </select>
      </td>
      <td data-label="Page Status (list)">
        <select class="form-select form-select-sm" data-field="pageStatus">
          <option value="" selected disabled>-Select page status-</option>
          <option value="verified">Verified</option>
          <option value="pending">Pending</option>
          <option value="mismatch">Mismatch</option>
        </select>
      </td>
      <td data-label="Physical Location">
        <select class="form-select form-select-sm" data-field="physicalLocation">
          <option value="" selected disabled>-Select location-</option>
          <option value="with_driver">With Driver</option>
          <option value="with_admin">With Admin</option>
          <option value="with_client">With Client</option>
        </select>
      </td>
      <td data-label="Note">
        <input type="text" class="form-control form-control-sm" data-field="note" placeholder="Enter note" />
      </td>
      <td data-col="actions" data-label="Actions">
        <button type="button" class="eal-row-btn danger" data-action="delete" title="Delete">
          <i class="bi bi-trash3"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
    attachRowEvents(tr);
    updateSN();
  }

  addBtn.addEventListener("click", function () {
    createLineRow();
  });

  // Start with one blank line
  createLineRow();
}

/* ============================================
   Booking - Booking Lines (auto-generated, read-only)
   ============================================ */
function initBookingLinesRoute() {
  const table = document.getElementById("bookingLinesTable");
  const soLineSelect = document.getElementById("salesOrderLine");
  const routeDisplay = document.getElementById("routeDisplay");
  const tripTypeDisplay = document.getElementById("tripTypeDisplay");
  const swapBtn = document.getElementById("swapRoundTripOriginBtn");

  if (!table) return;
  // Allow pages to keep static/default rows without auto-overwrite.
  if (table.hasAttribute("data-static-view")) return;
  const tbody = table.querySelector("tbody");
  if (!tbody) return;

  let isRoundOriginSwapped = false;
  const COLS = 5;

  function normalizeRouteText(s) {
    return String(s || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parseRoute(routeText) {
    // Accept formats like "Jeddah - Yanbu", "Jeddah – Yanbu", "JED–YAN"
    const t = normalizeRouteText(routeText);
    if (!t) return { from: "—", to: "—" };

    const parts = t.split(/–|-|→|>/).map((p) => p.trim()).filter(Boolean);
    if (parts.length >= 2) return { from: parts[0], to: parts[1] };
    return { from: t, to: "—" };
  }

  function routePillHTML(from, to) {
    return `
      <div class="pl-route-chip" title="${from} ↔ ${to}">
        <span>${from}</span>
        <span class="pl-route-arrow" aria-hidden="true">
          <i class="bi bi-arrow-left-right"></i>
        </span>
        <span>${to}</span>
      </div>
    `;
  }

  function renderDemoRow() {
    tbody.innerHTML = `
      <tr>
        <td>1</td>
        <td>Outbound</td>
        <td><span class="status-badge pending">Draft</span></td>
        <td>${routePillHTML("Jeddah", "Yanbu")}</td>
        <td></td>
      </tr>
    `;
  }

  function getTripType() {
    const t = normalizeRouteText(tripTypeDisplay?.value);
    if (!t) return "";
    const v = t.toLowerCase();
    if (v.includes("round")) return "round";
    if (v.includes("inbound")) return "inbound";
    if (v.includes("outbound") || v.includes("one")) return "outbound";
    return v;
  }

  function updateSwapButtonVisibility(tt, hasSelection) {
    if (!swapBtn) return;
    const show = tt === "round" && !!hasSelection;
    swapBtn.classList.toggle("d-none", !show);
    swapBtn.setAttribute("aria-hidden", show ? "false" : "true");
  }

  function actionButtonHTML(tt) {
    if (tt !== "round") return "";
    return `
      <button
        type="button"
        class="btn btn-outline-secondary btn-sm"
        data-action="swap-round-origin"
        title="Swap Round Trip Origin"
      >
        <i class="bi bi-arrow-left-right"></i>
      </button>
    `;
  }

  function renderLines() {
    const selected = soLineSelect?.value;
    if (!selected) {
      // Demo data row when nothing is selected (requested by client)
      renderDemoRow();
      updateSwapButtonVisibility(getTripType(), false);
      isRoundOriginSwapped = false;
      return;
    }

    const rText =
      normalizeRouteText(routeDisplay?.value) ||
      normalizeRouteText(
        soLineSelect?.options?.[soLineSelect.selectedIndex]?.textContent,
      );
    const { from, to } = parseRoute(rText);
    const tt = getTripType();
    updateSwapButtonVisibility(tt, true);

    const rows = [];

    // Default behavior:
    // - Outbound / One-way: 1 line (Outbound)
    // - Round: 2 lines (Outbound + Backload)
    if (tt === "round") {
      const firstFrom = isRoundOriginSwapped ? to : from;
      const firstTo = isRoundOriginSwapped ? from : to;
      const secondFrom = firstTo;
      const secondTo = firstFrom;

      rows.push({
        lineNo: 1,
        type: "Outbound",
        status: "Draft",
        routeHtml: routePillHTML(firstFrom, firstTo),
        actionsHtml: actionButtonHTML(tt),
      });
      rows.push({
        lineNo: 2,
        type: "Inbound",
        status: "Draft",
        routeHtml: routePillHTML(secondFrom, secondTo),
        actionsHtml: "",
      });
    } else {
      isRoundOriginSwapped = false;
      rows.push({
        lineNo: 1,
        type: "Outbound",
        status: "Draft",
        routeHtml: routePillHTML(from, to),
        actionsHtml: "",
      });
    }

    tbody.innerHTML = rows
      .map(
        (r) => `
        <tr>
          <td>${r.lineNo}</td>
          <td>${r.type}</td>
          <td><span class="status-badge pending">${r.status}</span></td>
          <td>${r.routeHtml}</td>
          <td>${r.actionsHtml || ""}</td>
        </tr>
      `,
      )
      .join("");
  }

  // Initial state
  renderLines();

  // Re-render when SO line changes, and when route/trip fields are updated by page scripts.
  if (soLineSelect) soLineSelect.addEventListener("change", renderLines);
  if (routeDisplay) routeDisplay.addEventListener("input", renderLines);
  if (tripTypeDisplay) tripTypeDisplay.addEventListener("input", renderLines);

  if (swapBtn) {
    swapBtn.addEventListener("click", function () {
      isRoundOriginSwapped = !isRoundOriginSwapped;
      renderLines();
    });
  }

  tbody.addEventListener("click", function (e) {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const btn = t.closest('[data-action="swap-round-origin"]');
    if (!btn) return;
    isRoundOriginSwapped = !isRoundOriginSwapped;
    renderLines();
  });
}

/* ============================================
   Operation Actions - Action Log Media sub-table
   ============================================ */
function initOperationActionLogMedia() {
  const tbody = document.getElementById("oalMediaTbody");
  const addBtn = document.getElementById("addOalMediaBtn");

  // Only run on Operation-action-log.html
  if (!tbody || !addBtn) return;

  function getRows() {
    return Array.from(tbody.querySelectorAll("tr[data-oal-media]"));
  }

  function updateSN() {
    getRows().forEach((tr, idx) => {
      const snEl = tr.querySelector("[data-sn]");
      if (snEl) snEl.textContent = String(idx + 1);
    });
  }

  function attachRowEvents(tr) {
    const delBtn = tr.querySelector('[data-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        tr.remove();
        updateSN();
      });
    }
  }

  function createMediaRow() {
    const tr = document.createElement("tr");
    tr.setAttribute("data-oal-media", "true");
    tr.innerHTML = `
      <td data-label="SN"><span data-sn></span></td>
      <td data-label="Media Type">
        <select class="form-select form-select-sm" data-field="mediaType" required>
          <option value="" selected disabled>-Select type-</option>
          <option value="photo">Photo</option>
          <option value="video">Video</option>
        </select>
      </td>
      <td data-label="Timestamp">
        <input type="datetime-local" class="form-control form-control-sm" data-field="timestamp" />
      </td>
      <td data-label="File">
        <input type="file" class="form-control form-control-sm" data-field="file" accept="image/*,video/*" />
      </td>
      <td data-label="Description">
        <input type="text" class="form-control form-control-sm" data-field="description" placeholder="Brief description" />
      </td>
      <td data-col="actions" data-label="Actions">
        <button type="button" class="eal-row-btn danger" data-action="delete" title="Delete">
          <i class="bi bi-trash3"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
    attachRowEvents(tr);
    updateSN();
  }

  addBtn.addEventListener("click", function () {
    createMediaRow();
  });

  // Start with one row for demo
  createMediaRow();
}

/* ============================================
   Sidebar Collapse Toggle
   ============================================ */
function initSidebarCollapse() {
  const sidebar = document.getElementById("appSidebar");
  const collapseBtn = document.getElementById("sidebarCollapseBtn");
  const overlay = document.querySelector(".sidebar-overlay");
  const mainContent = document.querySelector(".main-content");

  if (!sidebar || !collapseBtn) return;

  // Restore saved state (desktop only)
  if (window.innerWidth > 992) {
    const isCollapsed = localStorage.getItem("sidebarCollapsed") === "true";
    if (isCollapsed) {
      sidebar.classList.add("collapsed");
    }
  }

  // Toggle collapse on button click — responsive behavior
  collapseBtn.addEventListener("click", function () {
    if (window.innerWidth <= 992) {
      // Mobile: toggle sidebar overlay (slide in/out)
      sidebar.classList.toggle("active");
      if (overlay) overlay.classList.toggle("active");
      document.body.style.overflow = sidebar.classList.contains("active")
        ? "hidden"
        : "";
    } else {
      // Desktop: toggle collapsed state
      sidebar.classList.toggle("collapsed");

      // Save state
      localStorage.setItem(
        "sidebarCollapsed",
        sidebar.classList.contains("collapsed"),
      );

      // Close all open submenus when collapsing
      if (sidebar.classList.contains("collapsed")) {
        sidebar.querySelectorAll(".nav-item.open").forEach(function (item) {
          item.classList.remove("open");
        });
        sidebar
          .querySelectorAll(".submenu-item.has-submenu.open")
          .forEach(function (item) {
            item.classList.remove("open");
          });
      }
    }
  });
}

/* ============================================
   Header Date Time
   ============================================ */
function initHeaderDateTime() {
  const dateElement = document.getElementById("headerDate");
  const timeElement = document.getElementById("headerTime");

  if (!dateElement || !timeElement) return;

  function updateDateTime() {
    const now = new Date();

    // Format date: Tuesday, 28 January 2026
    const options = {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    };
    const formattedDate = now.toLocaleDateString("en-US", options);

    // Format time: 3:52 PM
    const timeOptions = { hour: "numeric", minute: "2-digit", hour12: true };
    const formattedTime = now.toLocaleTimeString("en-US", timeOptions);

    dateElement.textContent = formattedDate;
    timeElement.textContent = formattedTime;
  }

  // Update immediately and then every minute
  updateDateTime();
  setInterval(updateDateTime, 60000);
}

/* ============================================
   Sidebar Active State Management
   ============================================ */
function initSidebarActiveState() {
  const currentPage = window.location.pathname.split("/").pop() || "index.html";

  // Remove all active classes first
  document.querySelectorAll(".nav-link.active").forEach((link) => {
    link.classList.remove("active");
  });
  document.querySelectorAll(".submenu-link.active").forEach((link) => {
    link.classList.remove("active");
  });
  document.querySelectorAll(".nav-item.open").forEach((item) => {
    item.classList.remove("open");
  });

  // Find and activate the matching link
  const allLinks = document.querySelectorAll(".nav-link, .submenu-link");

  allLinks.forEach((link) => {
    const href = link.getAttribute("href");
    if (href && href !== "#") {
      const linkPage = href.split("/").pop();

      if (linkPage === currentPage) {
        link.classList.add("active");

        // If it's a submenu link, open the parent menu
        const parentSubmenu = link.closest(".submenu");
        if (parentSubmenu) {
          const parentNavItem = parentSubmenu.closest(".nav-item.has-submenu");
          if (parentNavItem) {
            parentNavItem.classList.add("open");
          }
        }
      }
    }
  });

  // Special case: if no link is active, default to dashboard for index.html
  const hasActiveLink = document.querySelector(
    ".nav-link.active, .submenu-link.active",
  );
  if (!hasActiveLink && (currentPage === "" || currentPage === "index.html")) {
    const dashboardLink = document.querySelector(
      '.nav-link[href="index.html"]',
    );
    if (dashboardLink) {
      dashboardLink.classList.add("active");
    }
  }
}

/* ============================================
   Sidebar Functionality
   ============================================ */
function initSidebar() {
  const sidebar = document.querySelector(".sidebar");
  const mobileToggle = document.querySelector(".mobile-menu-toggle");
  const overlay = document.querySelector(".sidebar-overlay");
  const navItems = document.querySelectorAll(".nav-item.has-submenu");
  const sidebarNav = document.querySelector(".sidebar-nav");

  // Restore sidebar scroll position
  if (sidebarNav) {
    const savedScrollPos = sessionStorage.getItem("sidebarScrollPos");
    if (savedScrollPos) {
      sidebarNav.scrollTop = parseInt(savedScrollPos, 10);
    }

    // Save scroll position on scroll
    sidebarNav.addEventListener("scroll", function () {
      sessionStorage.setItem("sidebarScrollPos", sidebarNav.scrollTop);
    });
  }

  // Set data-menu-title on each submenu for collapsed flyout headers
  navItems.forEach(function (item) {
    const link = item.querySelector(":scope > .nav-link");
    const submenu = item.querySelector(":scope > .submenu");
    if (link && submenu) {
      const tooltip =
        link.getAttribute("data-tooltip") ||
        link.querySelector(".nav-text")?.textContent ||
        "";
      submenu.setAttribute("data-menu-title", tooltip);
    }
  });

  // Mobile menu toggle
  if (mobileToggle) {
    mobileToggle.addEventListener("click", function () {
      sidebar.classList.toggle("active");
      overlay.classList.toggle("active");
      document.body.style.overflow = sidebar.classList.contains("active")
        ? "hidden"
        : "";
    });
  }

  // Close sidebar when clicking overlay
  if (overlay) {
    overlay.addEventListener("click", function () {
      sidebar.classList.remove("active");
      overlay.classList.remove("active");
      document.body.style.overflow = "";
    });
  }

  // Sidebar dropdown toggles
  navItems.forEach(function (item) {
    const link = item.querySelector(".nav-link");

    link.addEventListener("click", function (e) {
      e.preventDefault();

      // Skip click-toggle when sidebar is collapsed AND NOT hovered
      if (
        sidebar &&
        sidebar.classList.contains("collapsed") &&
        !sidebar.classList.contains("is-hovered")
      ) {
        return;
      }

      // Close other open submenus
      navItems.forEach(function (otherItem) {
        if (otherItem !== item && otherItem.classList.contains("open")) {
          otherItem.classList.remove("open");
        }
      });

      // Toggle current submenu
      item.classList.toggle("open");
    });
  });

  // Hover expansion logic for collapsed sidebar with debounce
  let hoverTimeout;
  const hoverDelay = 200; // Delay in ms before opening
  const leaveDelay = 150; // Delay before closing

  if (sidebar) {
    sidebar.addEventListener("mouseenter", function () {
      if (sidebar.classList.contains("collapsed")) {
        clearTimeout(hoverTimeout);
        hoverTimeout = setTimeout(() => {
          sidebar.classList.remove("is-collapsing");
          sidebar.classList.add("is-hovered");
        }, hoverDelay);
      }
    });

    sidebar.addEventListener("mouseleave", function () {
      clearTimeout(hoverTimeout);
      hoverTimeout = setTimeout(() => {
        sidebar.classList.remove("is-hovered");
        // Add is-collapsing class to prevent flyout render glitch while sidebar shrinks
        sidebar.classList.add("is-collapsing");
        setTimeout(() => {
          sidebar.classList.remove("is-collapsing");
        }, 300); // 300ms matches --sidebar-transition in CSS
      }, leaveDelay);
    });
  }

  // Nested submenu toggle (e.g., Config: Sales Setting)
  const nestedSubmenuItems = document.querySelectorAll(
    ".submenu-item.has-submenu",
  );
  nestedSubmenuItems.forEach(function (item) {
    const link = item.querySelector(":scope > .submenu-link");

    if (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();

        // Close other nested submenus at the same level
        const siblings = item.parentElement.querySelectorAll(
          ":scope > .submenu-item.has-submenu",
        );
        siblings.forEach(function (sibling) {
          if (sibling !== item && sibling.classList.contains("open")) {
            sibling.classList.remove("open");
          }
        });

        // Toggle current nested submenu
        item.classList.toggle("open");
      });
    }
  });

  // Close sidebar on window resize (if open on mobile)
  window.addEventListener("resize", function () {
    if (window.innerWidth > 992) {
      sidebar.classList.remove("active");
      overlay.classList.remove("active");
      document.body.style.overflow = "";
    }
  });
}

/* ============================================
   Time Picker Validation
   ============================================ */
function initTimeValidation() {
  const timeInputs = document.querySelectorAll('input[type="time"]');

  timeInputs.forEach(function (input) {
    input.addEventListener("change", function () {
      validateTimeInput(this);
    });
  });
}

function validateTimeInput(input) {
  const value = input.value;

  if (value) {
    // Time is valid (browser handles basic validation)
    input.classList.remove("is-invalid");
    input.classList.add("is-valid");
  } else {
    input.classList.remove("is-valid");
  }
}

// Validate time range (From should be before To)
function validateTimeRange() {
  const fromInput = document.getElementById("workingTimeFrom");
  const toInput = document.getElementById("workingTimeTo");

  if (fromInput && toInput && fromInput.value && toInput.value) {
    if (fromInput.value >= toInput.value) {
      toInput.setCustomValidity("End time must be after start time");
      return false;
    } else {
      toInput.setCustomValidity("");
      return true;
    }
  }
  return true;
}

/* ============================================
   Form Validation
   ============================================ */
function initFormValidation() {
  const form = document.getElementById("addressForm");

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();

      // Validate time range
      if (!validateTimeRange()) {
        showAlert("End time must be after start time", "error");
        return;
      }

      // Validate required fields
      const requiredFields = form.querySelectorAll("[required]");
      let isValid = true;

      requiredFields.forEach(function (field) {
        if (!field.value.trim()) {
          field.classList.add("is-invalid");
          isValid = false;
        } else {
          field.classList.remove("is-invalid");
        }
      });

      if (isValid) {
        // Form is valid - you can submit or process data
        showAlert("Form submitted successfully!", "success");
        // form.submit(); // Uncomment to actually submit
      } else {
        showAlert("Please fill in all required fields", "error");
      }
    });

    // Remove invalid class on input
    form
      .querySelectorAll(".form-control, .form-select")
      .forEach(function (input) {
        input.addEventListener("input", function () {
          this.classList.remove("is-invalid");
        });
      });
  }
}

/* ============================================
   Map Link Validation
   ============================================ */
function validateMapLink(input) {
  const value = input.value.trim();

  if (value && !value.startsWith("https://")) {
    input.classList.add("is-invalid");
    return false;
  }

  input.classList.remove("is-invalid");
  return true;
}

/* ============================================
   Phone Number Formatting
   ============================================ */
function formatPhoneNumber(input) {
  // Remove non-numeric characters
  let value = input.value.replace(/\D/g, "");

  // Limit length
  if (value.length > 15) {
    value = value.substring(0, 15);
  }

  input.value = value;
}

/* ============================================
   Alert/Notification Helper
   ============================================ */
function showAlert(message, type) {
  // Remove existing alerts
  const existingAlert = document.querySelector(".custom-alert");
  if (existingAlert) {
    existingAlert.remove();
  }

  // Create alert element
  const alert = document.createElement("div");
  alert.className = `custom-alert alert-${type}`;
  alert.innerHTML = `
        <span>${message}</span>
        <button type="button" class="alert-close">&times;</button>
    `;

  // Add styles
  alert.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 16px 20px;
        border-radius: 8px;
        background: ${type === "success" ? "#10b981" : "#ef4444"};
        color: white;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 9999;
        animation: slideIn 0.3s ease;
    `;

  // Add animation keyframes if not present
  if (!document.querySelector("#alertStyles")) {
    const style = document.createElement("style");
    style.id = "alertStyles";
    style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
    document.head.appendChild(style);
  }

  // Add to page
  document.body.appendChild(alert);

  // Close button functionality
  const closeBtn = alert.querySelector(".alert-close");
  closeBtn.style.cssText = `
        background: none;
        border: none;
        color: white;
        font-size: 20px;
        cursor: pointer;
        padding: 0;
        line-height: 1;
    `;

  closeBtn.addEventListener("click", function () {
    alert.style.animation = "slideOut 0.3s ease forwards";
    setTimeout(() => alert.remove(), 300);
  });

  // Auto remove after 5 seconds
  setTimeout(function () {
    if (alert.parentElement) {
      alert.style.animation = "slideOut 0.3s ease forwards";
      setTimeout(() => alert.remove(), 300);
    }
  }, 5000);
}

/* ============================================
   Numeric Input Validation
   ============================================ */
function validateNumericInput(input) {
  input.value = input.value.replace(/[^0-9]/g, "");
}

/* ============================================
   Email Validation
   ============================================ */
function validateEmail(input) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const value = input.value.trim();

  if (value && !emailRegex.test(value)) {
    input.classList.add("is-invalid");
    return false;
  }

  input.classList.remove("is-invalid");
  return true;
}

/* ============================================
   User Profile Dropdown
   ============================================ */
function initUserProfile() {
  const headerUserToggle = document.getElementById("headerUserToggle");
  const headerUserDropdown = document.getElementById("headerUserDropdown");

  if (headerUserToggle && headerUserDropdown) {
    // Toggle dropdown on click
    headerUserToggle.addEventListener("click", function (e) {
      e.stopPropagation();
      headerUserDropdown.classList.toggle("active");

      // Rotate chevron
      const chevron = headerUserToggle.querySelector(".header-user-chevron");
      if (chevron) {
        chevron.style.transform = headerUserDropdown.classList.contains(
          "active",
        )
          ? "rotate(180deg)"
          : "rotate(0deg)";
      }
    });

    // Close dropdown when clicking outside
    document.addEventListener("click", function (e) {
      if (
        !headerUserDropdown.contains(e.target) &&
        !headerUserToggle.contains(e.target)
      ) {
        headerUserDropdown.classList.remove("active");
        const chevron = headerUserToggle.querySelector(".header-user-chevron");
        if (chevron) {
          chevron.style.transform = "rotate(0deg)";
        }
      }
    });

    // Close dropdown when pressing Escape
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        headerUserDropdown.classList.remove("active");
        const chevron = headerUserToggle.querySelector(".header-user-chevron");
        if (chevron) {
          chevron.style.transform = "rotate(0deg)";
        }
      }
    });
  }
}

/* ============================================
   Notification Panel
   ============================================ */
function initNotificationPanel() {
  const sidebarNotificationBtn = document.querySelector(".notification-btn");
  const headerNotificationBtn = document.querySelector(
    '.header-icon-btn[title="Notifications"]',
  );
  const notificationPanel = document.getElementById("notificationPanel");
  const notificationClose = document.getElementById("notificationClose");
  const notificationOverlay = document.getElementById("notificationOverlay");
  const settingsBtn = document.getElementById("notificationSettingsBtn");
  const preferencesPopup = document.getElementById("preferencesPopup");
  const preferencesDone = document.getElementById("preferencesDone");

  function openNotificationPanel(e) {
    e.stopPropagation();
    notificationPanel.classList.add("active");
    notificationOverlay.classList.add("active");
    document.body.style.overflow = "hidden";
  }

  if (notificationPanel) {
    // Open notification panel from sidebar button
    if (sidebarNotificationBtn) {
      sidebarNotificationBtn.addEventListener("click", openNotificationPanel);
    }

    // Open notification panel from header button
    if (headerNotificationBtn) {
      headerNotificationBtn.addEventListener("click", openNotificationPanel);
    }

    // Close notification panel
    function closeNotificationPanel() {
      notificationPanel.classList.remove("active");
      notificationOverlay.classList.remove("active");
      preferencesPopup.classList.remove("active");
      document.body.style.overflow = "";
    }

    notificationClose.addEventListener("click", closeNotificationPanel);
    notificationOverlay.addEventListener("click", closeNotificationPanel);

    // Close on Escape key
    document.addEventListener("keydown", function (e) {
      if (
        e.key === "Escape" &&
        notificationPanel.classList.contains("active")
      ) {
        closeNotificationPanel();
      }
    });

    // Toggle preferences popup
    if (settingsBtn && preferencesPopup) {
      settingsBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        preferencesPopup.classList.toggle("active");
      });

      // Close preferences when clicking Done
      preferencesDone.addEventListener("click", function () {
        preferencesPopup.classList.remove("active");
      });

      // Close preferences when clicking outside
      notificationPanel.addEventListener("click", function (e) {
        if (
          !preferencesPopup.contains(e.target) &&
          !settingsBtn.contains(e.target)
        ) {
          preferencesPopup.classList.remove("active");
        }
      });
    }
  }
}

/**
 * Quick actions row: fits as many actions as the toolbar width allows; the rest go under a "More" dropdown.
 * Use on any page with matching markup (see Vendor-details.html).
 *
 * Markup:
 * - Toolbar: id from options.toolbarId (default vendorQuickActionsToolbar), contains [data-ch-visible-slot] and [data-ch-more-wrap] > button + [data-ch-overflow-menu] ul
 * - Source: id from options.sourceId (default chActionsSource), contains action elements with data-ch-action
 */
function initQuickActionsOverflowToolbar(options) {
  const opts = options || {};
  const toolbarId = opts.toolbarId || "vendorQuickActionsToolbar";
  const sourceId = opts.sourceId || "chActionsSource";

  const toolbar = document.getElementById(toolbarId);
  const source = document.getElementById(sourceId);
  if (!toolbar || !source) return;

  const visibleSlot = toolbar.querySelector("[data-ch-visible-slot]");
  const moreWrap = toolbar.querySelector("[data-ch-more-wrap]");
  const overflowMenu = toolbar.querySelector("[data-ch-overflow-menu]");
  if (!visibleSlot || !moreWrap || !overflowMenu) return;

  const gap = typeof opts.gap === "number" ? opts.gap : 12;
  const actionElements = Array.from(source.querySelectorAll("[data-ch-action]"));
  if (actionElements.length === 0) return;

  let widths = [];

  function measureWidths() {
    const measureRow = document.createElement("div");
    measureRow.style.cssText =
      "position:absolute;left:-9999px;top:0;display:flex;gap:" +
      gap +
      "px;white-space:nowrap;visibility:hidden;pointer-events:none;";
    document.body.appendChild(measureRow);
    actionElements.forEach(function (el) {
      measureRow.appendChild(el);
    });
    widths = actionElements.map(function (el) {
      return el.getBoundingClientRect().width;
    });
    measureRow.remove();
  }

  function getMoreWidth() {
    moreWrap.hidden = false;
    moreWrap.style.visibility = "hidden";
    moreWrap.style.position = "absolute";
    moreWrap.style.left = "-9999px";
    const w = moreWrap.offsetWidth;
    moreWrap.style.visibility = "";
    moreWrap.style.position = "";
    moreWrap.style.left = "";
    moreWrap.hidden = true;
    return w;
  }

  function setVisibleMode(el) {
    el.classList.remove(
      "dropdown-item",
      "d-flex",
      "align-items-center",
      "gap-2",
      "py-2",
      "border-0",
      "bg-transparent",
      "w-100",
      "text-start",
    );
    el.classList.add("ch-action-btn");
  }

  function setOverflowMode(el) {
    el.classList.remove("ch-action-btn");
    el.classList.add(
      "dropdown-item",
      "d-flex",
      "align-items-center",
      "gap-2",
      "py-2",
      "border-0",
      "bg-transparent",
      "w-100",
      "text-start",
    );
  }

  function fitCount(toolbarW) {
    if (toolbarW <= 0) return 0;
    const n = widths.length;
    const moreW = getMoreWidth();

    for (let k = n; k >= 0; k--) {
      let sum = 0;
      for (let i = 0; i < k; i++) {
        sum += widths[i] + (i > 0 ? gap : 0);
      }
      const overflow = k < n;
      const need =
        sum + (overflow ? (sum > 0 ? gap : 0) + moreW : 0);
      if (need <= toolbarW) return k;
    }
    return 0;
  }

  function layout() {
    const tw = toolbar.clientWidth;
    const k = fitCount(tw);
    const n = actionElements.length;

    visibleSlot.innerHTML = "";
    overflowMenu.innerHTML = "";

    actionElements.forEach(function (el) {
      if (el.parentNode) el.parentNode.removeChild(el);
    });

    for (let i = 0; i < k; i++) {
      setVisibleMode(actionElements[i]);
      visibleSlot.appendChild(actionElements[i]);
    }

    for (let j = k; j < n; j++) {
      setOverflowMode(actionElements[j]);
      const li = document.createElement("li");
      li.className = "px-1";
      li.appendChild(actionElements[j]);
      overflowMenu.appendChild(li);
    }

    moreWrap.hidden = k >= n;
  }

  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(function () {
      layout();
    });
    ro.observe(toolbar);
  } else {
    window.addEventListener("resize", layout);
  }

  measureWidths();
  layout();

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      measureWidths();
      layout();
    });
  }
}
