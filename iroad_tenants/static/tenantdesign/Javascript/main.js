/* ============================================
   iRoad Admin Dashboard - Main JavaScript
   Version: 1.0
   ============================================ */

document.addEventListener("DOMContentLoaded", function () {
  ensureUnifiedSidebar().then(function () {
    [
      initSidebar,
      initSidebarActiveState,
      initSidebarCollapse,
      initTimeValidation,
      initFormValidation,
      initFormSubmitGuard,
      initArabicTextInputs,
      initUserProfile,
      initNotificationPanel,
      initHeaderDateTime,
      initSalesOrderLines,
      initPurchaseOrderLines,
      initShipmentDocumentLines,
      initDocumentHandoverVerificationLines,
      initBookingLinesRoute,
      initOperationActionLogMedia,
      initTenantGlobalSearch,
    ].forEach(function (fn) {
      try {
        fn();
      } catch (err) {
        console.error("iRoad UI init:", fn.name || "anonymous", err);
      }
    });
  });
});

/* ── Navbar global search (shipments, clients, addresses) ── */
function initTenantGlobalSearch() {
  var input = document.querySelector("[data-tenant-global-search]");
  if (!input) return;

  var apiUrl = input.getAttribute("data-search-api") || "";
  var pending = null;

  var form = input.closest("[data-tenant-global-search-form]");

  function runSearch() {
    var q = input.value.trim();
    if (!q) return;

    var scope = input.getAttribute("data-search-scope") || "navbar";
    if (window.iroadTenantSearch && window.iroadTenantSearch.go) {
      window.iroadTenantSearch.go(q, scope);
      return;
    }

    if (form) {
      form.submit();
      return;
    }

    if (!apiUrl) return;

    if (pending) pending.abort();
    pending = new AbortController();

    fetch(
      apiUrl +
        "?q=" +
        encodeURIComponent(q) +
        "&scope=" +
        encodeURIComponent(scope),
      {
        signal: pending.signal,
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      }
    )
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (data && data.redirect) {
          window.location.href = data.redirect;
        }
      })
      .catch(function () {});
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      var q = input.value.trim();
      if (!q) {
        e.preventDefault();
        return;
      }
      if (window.iroadTenantSearch && window.iroadTenantSearch.go) {
        e.preventDefault();
        runSearch();
      }
    });
  }

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      runSearch();
    }
  });
}

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
  const docRefInput = document.getElementById("documentRefNo");
  const pageCountInput = document.getElementById("pageCount");
  const isDeliveryNoteInput = document.getElementById("isDeliveryNote");
  const documentTypeInput = document.getElementById("documentType");
  const physicalLocationSelect = document.getElementById("physicalLocation");

  // Only run on Shipment-documents.html (or pages with same markup)
  if (!tbody || !addBtn) return;

  const DEFAULT_PHYSICAL_LOCATIONS = [
    "Not Collected",
    "With Driver",
    "In Company",
    "Submitted to Receiver",
    "Submitted to Client",
  ];

  function readPhysicalLocationOptions() {
    const optionsEl = document.getElementById("shipment-document-physical-locations");
    if (!optionsEl || !optionsEl.textContent) return DEFAULT_PHYSICAL_LOCATIONS.slice();
    try {
      const parsed = JSON.parse(optionsEl.textContent);
      return Array.isArray(parsed) && parsed.length ? parsed : DEFAULT_PHYSICAL_LOCATIONS.slice();
    } catch (e) {
      return DEFAULT_PHYSICAL_LOCATIONS.slice();
    }
  }

  const physicalLocationOptions = readPhysicalLocationOptions();

  function normalizePhysicalLocation(value) {
    const safeValue = String(value || "").trim();
    if (safeValue === "With Client") return "Submitted to Client";
    return safeValue;
  }

  function buildPhysicalLocationSelectMarkup(selectedValue) {
    const normalized = normalizePhysicalLocation(selectedValue);
    let html =
      '<option value="" disabled' +
      (normalized ? "" : " selected") +
      '>-Select custody-</option>';
    physicalLocationOptions.forEach(function (optionValue) {
      html +=
        '<option value="' +
        optionValue +
        '"' +
        (normalized === optionValue ? " selected" : "") +
        ">" +
        optionValue +
        "</option>";
    });
    if (normalized && physicalLocationOptions.indexOf(normalized) === -1) {
      html +=
        '<option value="' +
        normalized +
        '" selected>' +
        normalized +
        "</option>";
    }
    return html;
  }

  function getHeaderPhysicalLocation() {
    if (!physicalLocationSelect) return "";
    const selectedValue = String(physicalLocationSelect.value || "").trim();
    if (selectedValue) return selectedValue;
    const selectedOption =
      physicalLocationSelect.options[physicalLocationSelect.selectedIndex];
    return selectedOption ? String(selectedOption.value || "").trim() : "";
  }

  function syncLinePhysicalLocations(value) {
    const normalized = normalizePhysicalLocation(
      value !== undefined ? value : getHeaderPhysicalLocation()
    );
    if (!normalized) return;
    getRows().forEach(function (tr) {
      setFieldValue(tr, '[name="line_physical_location[]"]', normalized);
    });
  }

  window.syncShipmentDocumentLinePhysicalLocations = syncLinePhysicalLocations;

  function getRows() {
    return Array.from(tbody.querySelectorAll("tr[data-sd-line]"));
  }

  function syncDocRefsToLines() {
    const docRefNo = getHeaderDocRefNo();
    tbody.querySelectorAll('[data-field="docRefNo"]').forEach((field) => {
      field.value = docRefNo;
      field.placeholder = docRefNo ? "" : "Same as header Document Ref No";
    });
  }

  function renumberRowsOnly() {
    getRows().forEach((tr, idx) => {
      const snEl = tr.querySelector("[data-sn]");
      if (snEl) snEl.textContent = String(idx + 1);
      const pageNoInput = tr.querySelector('[data-field="pageNo"]');
      if (pageNoInput && pageNoInput.getAttribute("data-auto-page") !== "false") {
        pageNoInput.value = String(idx + 1);
        pageNoInput.setAttribute("data-auto-page", "true");
      }
      const attachmentInput = tr.querySelector('[data-field="attachment"]');
      if (attachmentInput) attachmentInput.name = "line_attachment_" + idx;
    });
    if (pageCountInput) {
      pageCountInput.value = String(Math.max(getRows().length, 1));
    }
  }

  function updateSN() {
    renumberRowsOnly();
    syncDocRefsToLines();
  }

  function getHeaderDocRefNo() {
    return docRefInput ? String(docRefInput.value || "").trim() : "";
  }

  function isDeliveryNoteEnabled() {
    if (isDeliveryNoteInput && !isDeliveryNoteInput.disabled) {
      return isDeliveryNoteInput.checked;
    }
    if (isDeliveryNoteInput && isDeliveryNoteInput.checked) return true;
    if (documentTypeInput) {
      const docType = String(documentTypeInput.value || "").trim();
      if (docType === "Delivery Note") return true;
    }
    return false;
  }

  function syncDocumentTypeWithDeliveryNoteFlag() {
    if (!documentTypeInput || !isDeliveryNoteInput || isDeliveryNoteInput.disabled) return;
    const docType = String(documentTypeInput.value || "").trim();
    if (docType === "Delivery Note") {
      isDeliveryNoteInput.checked = true;
    } else if (docType && isDeliveryNoteInput.checked) {
      isDeliveryNoteInput.checked = false;
    }
  }

  function shouldAutoPopulateLinesFromPodCount() {
    if (!shipmentSelect || !shipmentSelect.value) return false;
    if (isDeliveryNoteEnabled()) return true;
    if (!isCreateDeliveryNoteForm) return false;
    const opt =
      shipmentSelect.selectedIndex >= 0
        ? shipmentSelect.options[shipmentSelect.selectedIndex]
        : null;
    const raw = opt ? parseInt(opt.getAttribute("data-pod-doc-count") || "0", 10) : 0;
    return Number.isFinite(raw) && raw > 0;
  }

  function selectedShipmentPodType() {
    const shipmentSelectEl = document.getElementById("shipmentRef");
    if (!shipmentSelectEl || shipmentSelectEl.selectedIndex < 0) return "";
    const opt = shipmentSelectEl.options[shipmentSelectEl.selectedIndex];
    return opt ? String(opt.getAttribute("data-pod-type") || "").trim() : "";
  }

  function isDigitalPodShipment() {
    const podType = selectedShipmentPodType().toLowerCase();
    return podType === "digital" || podType === "digital evidence";
  }

  const SD_NON_DN_SINGLE_LINE_MSG =
    "When Delivery Note is off, only one subform line can be added.";

  function maxSubformRows() {
    if (isDeliveryNoteEnabled()) {
      const shipmentSelectEl = document.getElementById("shipmentRef");
      const opt =
        shipmentSelectEl && shipmentSelectEl.selectedIndex >= 0
          ? shipmentSelectEl.options[shipmentSelectEl.selectedIndex]
          : null;
      const raw = opt ? parseInt(opt.getAttribute("data-pod-doc-count") || "0", 10) : 0;
      if (Number.isFinite(raw) && raw > 1) return Math.min(raw, MAX_SD_PAGE_ROWS);
      return MAX_SD_PAGE_ROWS;
    }
    return 1;
  }

  function subformRowLimitMessage() {
    if (!isDeliveryNoteEnabled()) return SD_NON_DN_SINGLE_LINE_MSG;
    return "Maximum subform pages reached for this document type.";
  }

  function getSdAddLineLimitErrorEl() {
    return document.getElementById("sdAddLineLimitError");
  }

  function showSdAddLineLimitError(message) {
    const errorEl = getSdAddLineLimitErrorEl();
    if (!errorEl) return;
    errorEl.textContent = message || subformRowLimitMessage();
    errorEl.classList.remove("d-none");
    errorEl.classList.add("d-block");
    if (addBtn) addBtn.classList.add("btn-outline-danger");
  }

  function clearSdAddLineLimitError() {
    const errorEl = getSdAddLineLimitErrorEl();
    if (errorEl) {
      errorEl.textContent = "";
      errorEl.classList.add("d-none");
      errorEl.classList.remove("d-block");
    }
    if (addBtn) addBtn.classList.remove("btn-outline-danger");
  }

  function enforceSubformRowLimit() {
    const maxRows = maxSubformRows();
    const rows = getRows();
    while (rows.length > maxRows) {
      rows[rows.length - 1].remove();
    }
    if (getRows().length < maxRows) {
      clearSdAddLineLimitError();
    }
    if (addBtn) {
      addBtn.title = getRows().length >= maxRows ? subformRowLimitMessage() : "";
    }
    renumberRowsOnly();
  }

  function syncSubformRowLimitFromRules() {
    if (!isDeliveryNoteEnabled() && getRows().length === 0) {
      createLineRow();
      return;
    }
    enforceSubformRowLimit();
    syncDocRefsToLines();
  }

  function syncToggleLabel() {
    if (!isDeliveryNoteInput) return;
    const toggle = isDeliveryNoteInput.closest(".setting-toggle");
    const label = toggle ? toggle.querySelector(".toggle-label") : null;
    if (label) label.textContent = isDeliveryNoteInput.checked ? "Yes" : "No";
  }

  function syncDerivedFields() {
    syncDocumentTypeWithDeliveryNoteFlag();
    const deliveryNoteEnabled = isDeliveryNoteEnabled();
    syncDocRefsToLines();
    tbody.querySelectorAll("[data-status-cell]").forEach((cell) => {
      cell.hidden = !deliveryNoteEnabled;
    });
    tbody.querySelectorAll('[data-field="status"]').forEach((field) => {
      field.disabled = !deliveryNoteEnabled;
      if (deliveryNoteEnabled && !field.value) {
        field.value = "Not Completed";
      }
    });
    const statusHeader = document.querySelector("[data-sd-status-header]");
    if (statusHeader) statusHeader.hidden = !deliveryNoteEnabled;
    syncToggleLabel();
  }

  function syncHeaderToSubformLines() {
    syncDerivedFields();
    syncSubformRowLimitFromRules();
    const headerLoc = getHeaderPhysicalLocation();
    if (headerLoc) {
      syncLinePhysicalLocations(headerLoc);
    }
  }

  window.syncShipmentDocumentDeliveryNoteUi = syncDerivedFields;
  window.syncShipmentDocumentHeaderToLines = syncHeaderToSubformLines;
  window.__sdSyncDocRefToLines = syncDocRefsToLines;

  function attachRowEvents(tr) {
    const delBtn = tr.querySelector('[data-action="delete"]');
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        tr.remove();
        updateSN();
        syncSubformRowLimitFromRules();
      });
    }
    const pageNoInput = tr.querySelector('[data-field="pageNo"]');
    if (pageNoInput) {
      pageNoInput.addEventListener("input", function () {
        pageNoInput.setAttribute("data-auto-page", "false");
      });
    }
  }

  function setFieldValue(tr, selector, value) {
    const field = tr.querySelector(selector);
    if (!field) return;
    const safeValue = value || "";
    if (field.tagName === "SELECT" && safeValue) {
      const hasOption = Array.from(field.options).some((option) => option.value === safeValue);
      if (!hasOption) {
        const option = document.createElement("option");
        option.value = safeValue;
        option.textContent = safeValue;
        field.appendChild(option);
      }
    }
    field.value = safeValue;
  }

  function applyRowFieldErrors(tr, fieldErrors) {
    if (!fieldErrors || typeof fieldErrors !== "object") return;
    const selectorMap = {
      page_no: '[data-field="pageNo"]',
      physical_location: '[data-field="physicalLocation"]',
      status: '[data-field="status"]',
      attachment: '[data-field="attachment"]',
      extra_ref: '[data-field="extraRef"]',
    };
    Object.keys(fieldErrors).forEach(function (fieldName) {
      const selector = selectorMap[fieldName];
      const message = fieldErrors[fieldName];
      if (!selector || !message) return;
      const field = tr.querySelector(selector);
      if (field) {
        field.classList.add("is-invalid");
      }
      const hostCell = field ? field.closest("td") : null;
      if (!hostCell || hostCell.querySelector("[data-sd-line-error]")) return;
      const feedback = document.createElement("div");
      feedback.className = "invalid-feedback d-block";
      feedback.setAttribute("data-sd-line-error", fieldName);
      feedback.textContent = String(message);
      hostCell.appendChild(feedback);
    });
  }

  function createLineRow(lineData) {
    const data = lineData || {};
    if (!data.physical_location) {
      const headerLocation = getHeaderPhysicalLocation();
      if (headerLocation) {
        data.physical_location = headerLocation;
      }
    }
    const tr = document.createElement("tr");
    tr.setAttribute("data-sd-line", "true");
    tr.innerHTML = `
      <td data-label="SN"><span data-sn></span></td>
      <td data-label="Doc Ref No">
        <input type="text" class="form-control form-control-sm" name="line_doc_ref_no[]" data-field="docRefNo" placeholder="Same as header Document Ref No" readonly />
      </td>
      <td data-label="Extra Ref">
        <input type="text" class="form-control form-control-sm" name="line_extra_ref[]" data-field="extraRef" placeholder="Extra Ref..." />
      </td>
      <td data-label="Page No">
        <input type="number" class="form-control form-control-sm" name="line_page_no[]" data-field="pageNo" min="1" placeholder="Page No" required />
      </td>
      <td data-label="Completion" data-status-cell>
        <select class="form-select form-select-sm" name="line_status[]" data-field="status">
          <option value="Not Completed" selected>Not Completed</option>
          <option value="Completed">Completed</option>
        </select>
      </td>
      <td data-label="Physical Location">
        <select class="form-select form-select-sm" name="line_physical_location[]" data-field="physicalLocation" required>
          ${buildPhysicalLocationSelectMarkup(data.physical_location)}
        </select>
      </td>
      <td data-label="Attachment">
        <input type="file" class="form-control form-control-sm" name="line_attachment[]" data-field="attachment" accept="image/*,.pdf" />
        <input type="hidden" name="line_existing_attachment_label[]" data-field="existingAttachment" />
        <div class="text-muted small mt-1" data-existing-attachment></div>
      </td>
      <td data-col="actions" data-label="Actions">
        <button type="button" class="eal-row-btn danger" data-action="delete" title="Delete">
          <i class="bi bi-trash3"></i>
        </button>
      </td>
    `;

    tbody.appendChild(tr);
    setFieldValue(tr, '[name="line_doc_ref_no[]"]', data.doc_ref_no || getHeaderDocRefNo());
    setFieldValue(tr, '[name="line_extra_ref[]"]', data.extra_ref);
    setFieldValue(tr, '[name="line_page_no[]"]', data.page_no);
    const pageNoInput = tr.querySelector('[data-field="pageNo"]');
    if (pageNoInput) {
      pageNoInput.setAttribute("data-auto-page", data.page_no ? "false" : "true");
    }
    setFieldValue(tr, '[name="line_status[]"]', data.status || "Not Completed");
    setFieldValue(
      tr,
      '[name="line_physical_location[]"]',
      normalizePhysicalLocation(data.physical_location)
    );
    setFieldValue(
      tr,
      '[name="line_existing_attachment_label[]"]',
      data.attachment_storage_path || data.attachment_label || ""
    );
    const attachmentLabel = tr.querySelector("[data-existing-attachment]");
    if (attachmentLabel) {
      if (data.attachment_url) {
        attachmentLabel.innerHTML =
          '<a href="' +
          data.attachment_url +
          '" target="_blank" rel="noopener">Reference: ' +
          (data.attachment_label || "file") +
          "</a>";
      } else if (data.attachment_label) {
        attachmentLabel.textContent = "Current: " + data.attachment_label;
      }
    }
    const attachmentInput = tr.querySelector('[data-field="attachment"]');
    if (attachmentInput) {
      attachmentInput.required = false;
    }
    applyRowFieldErrors(tr, data._field_errors || data.field_errors || null);
    attachRowEvents(tr);
    updateSN();
  }

  addBtn.addEventListener("click", function () {
    if (getRows().length >= maxSubformRows()) {
      showSdAddLineLimitError(subformRowLimitMessage());
      return;
    }
    clearSdAddLineLimitError();
    createLineRow();
  });

  let initialLines = [];
  const initialLinesEl = document.getElementById("shipment-document-line-rows");
  if (initialLinesEl && initialLinesEl.textContent) {
    try {
      initialLines = JSON.parse(initialLinesEl.textContent) || [];
    } catch (e) {
      initialLines = [];
    }
  }

  const shipmentSelect = document.getElementById("shipmentRef");
  const formEl = document.getElementById("shipmentDocumentForm");
  const isEditForm = formEl && formEl.getAttribute("data-sd-is-edit") === "true";
  const isCreateDeliveryNoteForm =
    formEl && formEl.getAttribute("data-sd-create-delivery-note") === "true";
  const hasServerInitialLines = isEditForm && initialLines.length > 0;

  function expectedPageCountFromShipmentOption(opt) {
    if (!opt || !opt.value) return 1;
    const raw = parseInt(opt.getAttribute("data-pod-doc-count") || "0", 10);
    return Math.max(Number.isFinite(raw) ? raw : 0, 1);
  }

  const MAX_SD_PAGE_ROWS = 50;
  let pageCountSyncLock = false;

  function populateSdLinesFromPageCount(count) {
    let target = Math.max(parseInt(String(count), 10) || 1, 1);
    if (target > MAX_SD_PAGE_ROWS) {
      target = MAX_SD_PAGE_ROWS;
    }
    getRows().forEach(function (tr) {
      tr.remove();
    });
    for (let i = 0; i < target; i += 1) {
      createLineRow();
    }
    syncDerivedFields();
    syncLinePhysicalLocations();
  }

  function syncPageCountFromShipment() {
    if (pageCountSyncLock || isEditForm || hasServerInitialLines || !shipmentSelect) return;
    if (!shouldAutoPopulateLinesFromPodCount()) return;
    const opt = shipmentSelect.options[shipmentSelect.selectedIndex];
    if (!opt || !opt.value) return;
    pageCountSyncLock = true;
    try {
      populateSdLinesFromPageCount(expectedPageCountFromShipmentOption(opt));
    } finally {
      pageCountSyncLock = false;
    }
  }

  window.syncShipmentDocumentPageCount = syncPageCountFromShipment;

  if (initialLines.length) {
    initialLines.forEach(function (lineData) {
      createLineRow(lineData);
    });
  } else if (shipmentSelect && shipmentSelect.value) {
    syncPageCountFromShipment();
  } else {
    createLineRow();
  }

  if (docRefInput) {
    ["input", "change", "keyup", "paste"].forEach(function (eventName) {
      docRefInput.addEventListener(eventName, syncHeaderToSubformLines);
    });
  }

  if (isDeliveryNoteInput) {
    isDeliveryNoteInput.addEventListener("change", function () {
      if (isDeliveryNoteInput.checked && documentTypeInput) {
        documentTypeInput.value = "Delivery Note";
      } else if (
        !isDeliveryNoteInput.checked &&
        documentTypeInput &&
        documentTypeInput.value === "Delivery Note"
      ) {
        documentTypeInput.value = "";
      }
      syncDerivedFields();
      syncSubformRowLimitFromRules();
      if (shouldAutoPopulateLinesFromPodCount() && shipmentSelect && shipmentSelect.value) {
        syncPageCountFromShipment();
      }
    });
  }

  if (physicalLocationSelect) {
    physicalLocationSelect.addEventListener("change", syncHeaderToSubformLines);
  }

  if (documentTypeInput && isDeliveryNoteInput) {
    documentTypeInput.addEventListener("change", function () {
      syncDerivedFields();
      syncSubformRowLimitFromRules();
      if (shouldAutoPopulateLinesFromPodCount() && shipmentSelect && shipmentSelect.value) {
        syncPageCountFromShipment();
      } else if (
        !shouldAutoPopulateLinesFromPodCount() &&
        getRows().length === 0
      ) {
        createLineRow();
      }
    });
  }

  syncDocumentTypeWithDeliveryNoteFlag();
  if (isCreateDeliveryNoteForm && documentTypeInput && !documentTypeInput.value) {
    documentTypeInput.value = "Delivery Note";
  }
  if (isCreateDeliveryNoteForm && isDeliveryNoteInput && !isDeliveryNoteInput.disabled) {
    isDeliveryNoteInput.checked = true;
  }
  syncHeaderToSubformLines();
  window.syncShipmentDocumentSubformLimits = syncSubformRowLimitFromRules;
}

/* ============================================
   Document Handover - Pages Verification (sub-table)
   ============================================ */
function initDocumentHandoverVerificationLines() {
  const tbody = document.getElementById("dhLinesTbody");
  const addBtn = document.getElementById("addDhLineBtn");

  // Tenant portal form ships its own inline line-table logic.
  if (document.getElementById("documentHandoverForm")) return;

  // Only run on designer/static Document-handover.html (or pages with same markup)
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

  // Operation-action-log.html manages its own media rows (save + layout).
  if (!tbody || !addBtn || document.getElementById("oalDeleteButtonTemplate")) return;

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

  const configEl = document.getElementById("tenant-system-config");
  const cfg = configEl
    ? JSON.parse(configEl.textContent || "{}")
    : {};
  const locale = cfg.js_locale || "en-US";
  const timeZone = cfg.timezone || undefined;

  function updateDateTime() {
    const now = new Date();

    const dateOptions = {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: timeZone,
    };
    const timeOptions = {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: timeZone,
    };

    dateElement.textContent = now.toLocaleDateString(locale, dateOptions);
    timeElement.textContent = now.toLocaleTimeString(locale, timeOptions);
  }

  // Update immediately and then every minute
  updateDateTime();
  setInterval(updateDateTime, 60000);
}

/* ============================================
   Sidebar Active State Management
   ============================================ */
function initSidebarActiveState() {
  // Tenant portal: active/open classes come from Django (resolver_match).
  // Do not strip them — pathname "last segment" matching breaks UUID routes.
  const tenantSidebar = document.querySelector("#appSidebar[data-server-nav-state]");
  if (
    tenantSidebar &&
    tenantSidebar.getAttribute("data-server-nav-state") === "1"
  ) {
    return;
  }

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
var FORM_REQUIRED_FIELDS_MESSAGE = "Please fill in all required fields";

function validateRequiredFields(form) {
  const requiredFields = form.querySelectorAll("[required]:not([disabled])");
  let isValid = true;

  requiredFields.forEach(function (field) {
    const value = (field.value || "").trim();
    if (!value) {
      field.classList.add("is-invalid");
      isValid = false;
    } else {
      field.classList.remove("is-invalid");
    }
  });

  return isValid;
}

function validateUserRoleSelection(form) {
  const roleBoxes = form.querySelectorAll(".role-checkbox:not(:disabled)");
  const roleTrigger = form.querySelector("#roleOptionsDropdown");
  if (!roleBoxes.length) {
    if (roleTrigger) roleTrigger.classList.remove("is-invalid");
    return true;
  }

  const anyChecked = Array.from(roleBoxes).some(function (cb) {
    return cb.checked;
  });
  if (roleTrigger) {
    roleTrigger.classList.toggle("is-invalid", !anyChecked);
  }
  return anyChecked;
}

function attachFormSubmitValidation(form, options) {
  if (!form) return;
  options = options || {};

  form.addEventListener("submit", function (e) {
    if (options.validateTimeRange && !validateTimeRange()) {
      e.preventDefault();
      showTenantFormBanner("End time must be after start time", "error");
      return;
    }

    let isValid = validateRequiredFields(form);
    if (options.validateRoles) {
      isValid = validateUserRoleSelection(form) && isValid;
    }

    if (!isValid) {
      e.preventDefault();
      showTenantFormBanner(FORM_REQUIRED_FIELDS_MESSAGE, "error");
      return;
    }

    // Allow native POST to Django (server validates & redirects)
  });

  form
    .querySelectorAll(".form-control, .form-select")
    .forEach(function (input) {
      input.addEventListener("input", function () {
        this.classList.remove("is-invalid");
      });
    });

  form.querySelectorAll(".role-checkbox").forEach(function (cb) {
    cb.addEventListener("change", function () {
      validateUserRoleSelection(form);
    });
  });
}

function initFormValidation() {
  attachFormSubmitValidation(document.getElementById("addressForm"), {
    validateTimeRange: true,
  });
  attachFormSubmitValidation(document.getElementById("userCreationForm"), {
    validateRoles: true,
  });
}

/* ============================================
   Prevent duplicate form submissions (double-click)
   ============================================ */
function initFormSubmitGuard() {
  document
    .querySelectorAll('form[method="post"], form[method="POST"]')
    .forEach(function (form) {
      if (form.dataset.submitGuardBound === "1") return;
      if (form.hasAttribute("data-no-submit-guard")) return;
      if (form.hasAttribute("data-tenant-global-search-form")) return;

      form.dataset.submitGuardBound = "1";

      var submitting = false;

      function lockSubmitControls() {
        form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(
          function (btn) {
            if (btn.disabled) return;
            if (btn.tagName === "BUTTON" && !btn.dataset.submitGuardOriginalHtml) {
              btn.dataset.submitGuardOriginalHtml = btn.innerHTML;
              var label = btn.dataset.submittingLabel || "Saving...";
              btn.innerHTML =
                '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> ' +
                label;
            }
            btn.disabled = true;
          },
        );
      }

      form.addEventListener("submit", function (e) {
        if (submitting) {
          e.preventDefault();
          return;
        }
        if (e.defaultPrevented) return;

        submitting = true;
        form.dataset.submitting = "1";
        lockSubmitControls();
      });

      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(
        function (btn) {
          btn.addEventListener("click", function (e) {
            if (!submitting) return;
            e.preventDefault();
            e.stopPropagation();
          });
        },
      );
    });
}

/* ============================================
   Arabic-only text inputs
   ============================================ */
var ARABIC_TEXT_INPUT_SELECTOR =
  'input.eal-arabic, textarea.eal-arabic, input[data-arabic-only], textarea[data-arabic-only], input.arabic-input, textarea.arabic-input';

var ARABIC_TEXT_DISALLOWED_RE =
  /[^\s\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/g;

function sanitizeArabicTextInput(value) {
  return String(value || "").replace(ARABIC_TEXT_DISALLOWED_RE, "");
}

function bindArabicTextInput(input) {
  if (!input || input.dataset.arabicBound === "1") return;
  input.dataset.arabicBound = "1";
  if (!input.getAttribute("dir")) input.setAttribute("dir", "rtl");
  if (!input.getAttribute("lang")) input.setAttribute("lang", "ar");

  function applySanitizedValue(nextValue) {
    if (input.value !== nextValue) {
      input.value = nextValue;
    }
  }

  input.addEventListener("input", function () {
    applySanitizedValue(sanitizeArabicTextInput(input.value));
  });

  input.addEventListener("paste", function (event) {
    event.preventDefault();
    var pasted = "";
    if (event.clipboardData) {
      pasted = event.clipboardData.getData("text");
    } else if (window.clipboardData) {
      pasted = window.clipboardData.getData("Text");
    }
    var start = input.selectionStart;
    var end = input.selectionEnd;
    if (start == null || end == null) {
      applySanitizedValue(sanitizeArabicTextInput((input.value || "") + pasted));
      return;
    }
    var merged =
      (input.value || "").slice(0, start) +
      pasted +
      (input.value || "").slice(end);
    applySanitizedValue(sanitizeArabicTextInput(merged));
    var caret = start + sanitizeArabicTextInput(pasted).length;
    if (typeof input.setSelectionRange === "function") {
      input.setSelectionRange(caret, caret);
    }
  });
}

function initArabicTextInputs(root) {
  if (window.iroadArabicTextInputs && window.iroadArabicTextInputs.init) {
    window.iroadArabicTextInputs.init(root);
    return;
  }
  var scope = root && root.querySelectorAll ? root : document;
  scope.querySelectorAll(ARABIC_TEXT_INPUT_SELECTOR).forEach(bindArabicTextInput);
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
   Form feedback banner (Bootstrap, same as Django messages in base.html)
   ============================================ */
function ensureTenantFormBannerHost() {
  var host = document.getElementById("tenantFormBannerHost");
  if (host) return host;

  host = document.createElement("div");
  host.id = "tenantFormBannerHost";
  host.className = "page-content px-3 pt-2";

  var main = document.querySelector("main.main-content");
  if (!main) return null;

  var messageBlocks = main.querySelectorAll(".page-content.px-3.pt-2");
  if (messageBlocks.length > 0) {
    messageBlocks[messageBlocks.length - 1].insertAdjacentElement("afterend", host);
  } else {
    var header = main.querySelector(".top-header");
    if (header) {
      header.insertAdjacentElement("afterend", host);
    } else {
      main.prepend(host);
    }
  }
  return host;
}

function showTenantFormBanner(message, type) {
  var host = ensureTenantFormBannerHost();
  if (!host || !message) return;

  var alertType = "danger";
  if (type === "success") alertType = "success";
  else if (type === "warning") alertType = "warning";
  else if (type === "info") alertType = "info";

  host.querySelectorAll(".alert").forEach(function (el) {
    el.remove();
  });

  var alert = document.createElement("div");
  alert.className = "alert alert-" + alertType + " alert-dismissible fade show mb-2";
  alert.setAttribute("role", "alert");

  var text = document.createElement("span");
  text.textContent = message;
  alert.appendChild(text);

  var closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "btn-close";
  closeBtn.setAttribute("data-bs-dismiss", "alert");
  closeBtn.setAttribute("aria-label", "Close");
  alert.appendChild(closeBtn);

  host.appendChild(alert);
  host.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/** @deprecated Use showTenantFormBanner — kept for older inline scripts */
function showAlert(message, type) {
  showTenantFormBanner(message, type);
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

    initTenantNotificationActions();
  }
}

function getCsrfToken() {
  var match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function updateNotificationBadge(count) {
  var badge = document.querySelector("[data-notification-count]");
  if (!badge) return;
  var n = parseInt(count, 10) || 0;
  badge.textContent = String(n);
  if (n > 0) {
    badge.classList.remove("d-none");
  } else {
    badge.classList.add("d-none");
  }
}

function initTenantNotificationActions() {
  var list = document.getElementById("tenantNotificationList");
  if (!list) return;

  list.addEventListener("click", function (e) {
    var card = e.target.closest("[data-mark-read-url]");
    if (!card) return;
    var url = card.getAttribute("data-mark-read-url");
    if (!url) return;
    fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCsrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data && data.ok) {
          card.classList.remove("is-unread");
          if (typeof data.unread_count !== "undefined") {
            updateNotificationBadge(data.unread_count);
          }
        }
      })
      .catch(function () {});
  });

  var markAllBtn = document.getElementById("tenantNotificationMarkAllRead");
  if (markAllBtn) {
    markAllBtn.addEventListener("click", function () {
      var url = markAllBtn.getAttribute("data-mark-all-url");
      if (!url) return;
      fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (data && data.ok) {
            list.querySelectorAll(".notification-card").forEach(function (c) {
              c.classList.remove("is-unread");
            });
            updateNotificationBadge(0);
          }
        })
        .catch(function () {});
    });
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
