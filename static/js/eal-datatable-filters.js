/**
 * Client-side global search, per-column text filters, and A–Z / Z–A sort
 * for tables marked with [data-eal-filterable-table].
 */
(function (global) {
  "use strict";

  function normalizeText(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function getCellText(row, index) {
    if (!row || !row.cells || !row.cells[index]) return "";
    return row.cells[index].textContent.replace(/\s+/g, " ").trim();
  }

  function positionFloatingMenu(menu, button) {
    if (!menu || !button) return;
    var buttonRect = button.getBoundingClientRect();
    var margin = 8;
    menu.style.position = "fixed";
    menu.style.top = buttonRect.bottom + margin + "px";
    menu.style.left = Math.max(12, buttonRect.right - menu.offsetWidth) + "px";
    menu.style.right = "auto";
    menu.style.transform = "";
    menu.style.zIndex = "1080";
    var rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth - 12) {
      menu.style.left = Math.max(12, window.innerWidth - rect.width - 12) + "px";
    }
    if (rect.left < 12) {
      menu.style.left = "12px";
    }
  }

  function resetFloatingMenu(menu) {
    if (!menu) return;
    menu.style.position = "";
    menu.style.top = "";
    menu.style.left = "";
    menu.style.right = "";
    menu.style.transform = "";
    menu.style.zIndex = "";
  }

  function getHeaderLabelText(th) {
    if (!th) return "";
    var link = th.querySelector("a");
    if (link) {
      var clone = link.cloneNode(true);
      Array.prototype.forEach.call(clone.querySelectorAll("i, .sort-indicator, .tm-sort-indicator"), function (el) {
        el.parentNode.removeChild(el);
      });
      return clone.textContent.replace(/\s+/g, " ").trim();
    }
    return th.textContent.replace(/\s+/g, " ").trim();
  }

  function inferHeaderFilterType(th, label) {
    var explicit = (th.getAttribute("data-filter-type") || "").trim().toLowerCase();
    if (explicit === "number" || explicit === "date" || explicit === "text") {
      return explicit;
    }
    var text = String(label || "").toLowerCase();
    if (
      /(date|time|created|updated|expiry|expired|modified|timestamp|registered|logged|at\b)/.test(
        text
      )
    ) {
      return "date";
    }
    if (
      /(amount|balance|price|total|count|wallet|qty|quantity|rate|percent|distance|duration|km|mrr|ltv|#|no\.|number|sl\b|rank)/.test(
        text
      )
    ) {
      return "number";
    }
    return "text";
  }

  function sortLabelsForFilterType(filterType) {
    if (filterType === "number") {
      return { asc: "Lowest", desc: "Highest" };
    }
    if (filterType === "date") {
      return { asc: "Oldest", desc: "Newest" };
    }
    return { asc: "A to Z", desc: "Z to A" };
  }

  function filterPlaceholderFor(title, filterType) {
    var label = String(title || "").trim();
    var lower = label.toLowerCase();
    if (filterType === "number") {
      return "Filter by value…";
    }
    if (filterType === "date") {
      return "Filter by date…";
    }
    if (lower.indexOf("name") !== -1) {
      return "Filter by name…";
    }
    if (label) {
      return "Filter by " + label + "…";
    }
    return "Filter…";
  }

  function buildFilterHeaderMarkup(title, filterType, placeholder) {
    var sorts = sortLabelsForFilterType(filterType);
    var safeTitle = String(title || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
    var safePlaceholder = String(placeholder || "Filter…")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
    return (
      '<div class="eal-th-filter-head">' +
      '<span class="eal-th-filter-label">' +
      safeTitle +
      '<span class="sort-indicator">' +
      '<i class="bi bi-caret-up-fill"></i>' +
      '<i class="bi bi-caret-down-fill"></i>' +
      "</span>" +
      "</span>" +
      '<button type="button" class="eal-filter-menu-btn" aria-label="Filter ' +
      safeTitle +
      '">' +
      '<i class="bi bi-funnel"></i>' +
      "</button>" +
      "</div>" +
      '<div class="eal-filter-menu">' +
      '<div class="eal-filter-menu-title">' +
      safeTitle +
      "</div>" +
      '<input type="text" class="form-control eal-column-filter-input" placeholder="' +
      safePlaceholder +
      '" />' +
      '<div class="eal-filter-actions">' +
      '<button type="button" class="eal-filter-action" data-sort="asc">' +
      sorts.asc +
      "</button>" +
      '<button type="button" class="eal-filter-action" data-sort="desc">' +
      sorts.desc +
      "</button>" +
      '<button type="button" class="eal-filter-action" data-clear="true">Clear</button>' +
      "</div>" +
      "</div>"
    );
  }

  function shouldSkipFilterHeader(th) {
    if (!th || th.nodeName !== "TH") return true;
    if (th.classList.contains("eal-th-filter")) return true;
    if (th.classList.contains("eal-col-check")) return true;
    if (th.getAttribute("data-eal-skip-filter") === "1") return true;
    var label = getHeaderLabelText(th);
    if (!label) return true;
    return /^actions?$/i.test(label);
  }

  function ensureFilterHeaders(table) {
    var row = table.querySelector("thead tr");
    if (!row) return;
    Array.prototype.forEach.call(row.children, function (th, index) {
      if (shouldSkipFilterHeader(th)) return;
      var title = getHeaderLabelText(th);
      var filterType = inferHeaderFilterType(th, title);
      var columnIndex = th.getAttribute("data-column-index");
      if (columnIndex === null || columnIndex === "") {
        columnIndex = String(index);
      }
      th.className = "eal-th-filter";
      th.setAttribute("data-column-index", columnIndex);
      th.setAttribute("data-filter-type", filterType);
      th.innerHTML = buildFilterHeaderMarkup(
        title,
        filterType,
        filterPlaceholderFor(title, filterType)
      );
    });
  }

  function ensureGlobalSearchInput(root) {
    if (root.getAttribute("data-eal-global-search-added") === "1") return;
    if (root.querySelector("[data-eal-global-search]")) return;
    var toolbar = root.querySelector(".eal-toolbar");
    if (!toolbar) return;
    var existingSearch = toolbar.querySelector(
      'input[type="search"], input[type="text"][name="q"], .eal-search input'
    );
    if (existingSearch && !existingSearch.hasAttribute("data-eal-global-search")) {
      existingSearch.setAttribute("data-eal-global-search", "");
      if (existingSearch.type === "text") {
        existingSearch.type = "search";
      }
      root.setAttribute("data-eal-global-search-added", "1");
      return;
    }
    var toolbarLeft = toolbar.querySelector(".eal-toolbar-left") || toolbar;
    var searchWrap = document.createElement("div");
    searchWrap.className = "eal-search";
    searchWrap.style.flex = "1";
    searchWrap.style.minWidth = "220px";
    searchWrap.innerHTML =
      '<i class="bi bi-search"></i>' +
      '<input type="search" data-eal-global-search placeholder="Search…" aria-label="Search table" autocomplete="off" />' +
      '<button type="button" class="eal-search-clear-btn" title="Clear search" aria-label="Clear search" hidden>' +
      '<i class="bi bi-x-lg"></i>' +
      "</button>";
    toolbarLeft.insertBefore(searchWrap, toolbarLeft.firstChild);
    root.setAttribute("data-eal-global-search-added", "1");
  }

  function discoverFilterableRoots() {
    var roots = [];
    var seen = new Set();
    Array.prototype.forEach.call(document.querySelectorAll("[data-eal-filterable-table]"), function (root) {
      if (!seen.has(root)) {
        seen.add(root);
        roots.push(root);
      }
    });
    Array.prototype.forEach.call(document.querySelectorAll(".eal-table-card"), function (card) {
      if (card.getAttribute("data-eal-filterable") === "0") return;
      if (!card.querySelector("table.eal-table thead")) return;
      if (!card.hasAttribute("data-eal-filterable-table")) {
        card.setAttribute("data-eal-filterable-table", "");
      }
      if (!seen.has(card)) {
        seen.add(card);
        roots.push(card);
      }
    });
    return roots;
  }

  function initSelectAllCheckboxes(root) {
    if (root.getAttribute("data-eal-select-all-init") === "1") {
      return null;
    }
    if (root.getAttribute("data-eal-select-all") === "0") {
      return null;
    }

    var selectAll = root.querySelector("thead .eal-col-check .eal-custom-check");
    if (!selectAll || selectAll.disabled) {
      return null;
    }

    root.setAttribute("data-eal-select-all-init", "1");

    function getRowCheckboxes() {
      return Array.prototype.slice.call(
        root.querySelectorAll("tbody tr .eal-col-check .eal-custom-check")
      );
    }

    function isRowVisible(checkbox) {
      var row = checkbox.closest("tr");
      return row && row.style.display !== "none";
    }

    function syncSelectAll() {
      var visible = getRowCheckboxes().filter(isRowVisible);
      var total = visible.length;
      var checked = visible.filter(function (cb) {
        return cb.checked;
      }).length;
      selectAll.checked = total > 0 && checked === total;
      selectAll.indeterminate = checked > 0 && checked < total;
    }

    selectAll.addEventListener("change", function () {
      var on = selectAll.checked;
      getRowCheckboxes().forEach(function (cb) {
        if (!isRowVisible(cb)) return;
        cb.checked = on;
      });
      syncSelectAll();
    });

    getRowCheckboxes().forEach(function (cb) {
      cb.addEventListener("change", syncSelectAll);
    });

    syncSelectAll();
    return syncSelectAll;
  }

  function initFloatingActionDropdowns(root) {
    var scope = root || document;
    var actionDropdowns = Array.prototype.slice
      .call(scope.querySelectorAll(".eal-table .dropdown"))
      .filter(function (dd) {
        return dd.querySelector("[data-bs-toggle='dropdown']");
      });
    var floatingMenus = [];

    function positionActionMenu(button, menu) {
      if (!button || !menu) return;
      var buttonRect = button.getBoundingClientRect();
      var margin = 8;
      var menuWidth = menu.offsetWidth || 180;
      menu.style.position = "fixed";
      menu.style.top = buttonRect.bottom + margin + "px";
      menu.style.left = Math.max(12, buttonRect.right - menuWidth) + "px";
      menu.style.right = "auto";
      menu.style.transform = "";
      menu.style.zIndex = "2000";
      var rect = menu.getBoundingClientRect();
      if (rect.right > window.innerWidth - 12) {
        menu.style.left = Math.max(12, window.innerWidth - rect.width - 12) + "px";
      }
      if (rect.left < 12) {
        menu.style.left = "12px";
      }
    }

    function resetActionMenu(menu) {
      if (!menu) return;
      menu.style.position = "";
      menu.style.top = "";
      menu.style.left = "";
      menu.style.right = "";
      menu.style.transform = "";
      menu.style.zIndex = "";
    }

    actionDropdowns.forEach(function (dropdown) {
      if (dropdown.getAttribute("data-eal-action-float-init") === "1") return;
      dropdown.setAttribute("data-eal-action-float-init", "1");
      dropdown.removeAttribute("data-bs-display");
      dropdown.addEventListener("shown.bs.dropdown", function () {
        var button = dropdown.querySelector("[data-bs-toggle='dropdown']");
        var menu = dropdown.querySelector(".dropdown-menu");
        if (!button || !menu) return;
        if (!menu.__menuPlaceholder) {
          var placeholder = document.createComment("action-menu-placeholder");
          menu.__menuPlaceholder = placeholder;
          dropdown.insertBefore(placeholder, menu);
          document.body.appendChild(menu);
        }
        menu.classList.add("show");
        positionActionMenu(button, menu);
        floatingMenus = floatingMenus.filter(function (item) {
          return item.dropdown !== dropdown;
        });
        floatingMenus.push({ dropdown: dropdown, button: button, menu: menu });
      });

      dropdown.addEventListener("hidden.bs.dropdown", function () {
        var entry = null;
        for (var i = 0; i < floatingMenus.length; i++) {
          if (floatingMenus[i].dropdown === dropdown) {
            entry = floatingMenus[i];
            break;
          }
        }
        var menu = entry ? entry.menu : dropdown.querySelector(".dropdown-menu");
        if (!menu) return;
        menu.classList.remove("show");
        resetActionMenu(menu);
        if (menu.__menuPlaceholder && menu.__menuPlaceholder.parentNode) {
          menu.__menuPlaceholder.parentNode.insertBefore(menu, menu.__menuPlaceholder);
          menu.__menuPlaceholder.parentNode.removeChild(menu.__menuPlaceholder);
          menu.__menuPlaceholder = null;
        }
        floatingMenus = floatingMenus.filter(function (item) {
          return item.dropdown !== dropdown;
        });
      });
    });

    window.addEventListener("resize", function () {
      floatingMenus.forEach(function (item) {
        positionActionMenu(item.button, item.menu);
      });
    });
  }

  function navigateServerPaginatedSort(columnIndex, direction) {
    var url = new URL(window.location.href);
    url.searchParams.set("sort_col", String(columnIndex));
    url.searchParams.set("sort_dir", direction || "asc");
    url.searchParams.delete("page");
    window.location.assign(url.toString());
  }

  function clearServerPaginatedSort(columnIndex) {
    var url = new URL(window.location.href);
    var activeCol = url.searchParams.get("sort_col");
    if (!activeCol || Number(activeCol) === columnIndex) {
      url.searchParams.delete("sort_col");
      url.searchParams.delete("sort_dir");
    }
    url.searchParams.delete("page");
    window.location.assign(url.toString());
  }

  function navigateServerPaginatedFilter(columnIndex, value) {
    var url = new URL(window.location.href);
    var v = String(value || "").trim();
    if (v) {
      url.searchParams.set("filter_" + columnIndex, v);
    } else {
      url.searchParams.delete("filter_" + columnIndex);
    }
    url.searchParams.delete("page");
    window.location.assign(url.toString());
  }

  function clearServerPaginatedColumn(columnIndex) {
    var url = new URL(window.location.href);
    url.searchParams.delete("filter_" + String(columnIndex));
    var activeCol = url.searchParams.get("sort_col");
    if (activeCol && Number(activeCol) === columnIndex) {
      url.searchParams.delete("sort_col");
      url.searchParams.delete("sort_dir");
    }
    url.searchParams.delete("page");
    window.location.assign(url.toString());
  }

  function syncServerSortIndicators(filterHeaders) {
    var params;
    try {
      params = new URLSearchParams(window.location.search);
    } catch (e) {
      return;
    }
    var sortCol = params.get("sort_col");
    var sortDir = (params.get("sort_dir") || "").toLowerCase();
    filterHeaders.forEach(function (header) {
      var columnIndex = String(header.getAttribute("data-column-index") || "");
      var label = header.querySelector(".eal-th-filter-label");
      if (!label) return;
      label.classList.remove("sorted-asc", "sorted-desc");
      if (sortCol && columnIndex === sortCol && (sortDir === "asc" || sortDir === "desc")) {
        label.classList.add(sortDir === "asc" ? "sorted-asc" : "sorted-desc");
      }
    });
  }

  function syncServerFilterInputs(filterHeaders) {
    var params;
    try {
      params = new URLSearchParams(window.location.search);
    } catch (e) {
      return;
    }
    filterHeaders.forEach(function (header) {
      var columnIndex = Number(header.getAttribute("data-column-index"));
      var input = header.querySelector(".eal-column-filter-input");
      var menuButton = header.querySelector(".eal-filter-menu-btn");
      var val = params.get("filter_" + columnIndex) || "";
      if (input) input.value = val;
      if (menuButton) menuButton.classList.toggle("active", Boolean(val));
    });
  }

  function initFilterableTable(root) {
    if (!root || root.getAttribute("data-eal-filter-skip") === "1") return;

    var serverPaginated = root.getAttribute("data-eal-server-paginated") === "1";
    var table = root.querySelector("table.eal-table");
    if (!table) return;
    var tbody = table.querySelector("tbody");
    if (!tbody) return;

    ensureFilterHeaders(table);
    if (root.getAttribute("data-eal-global-search") !== "0") {
      ensureGlobalSearchInput(root);
    }

    function syncFilterMenuSortLabels(header) {
      var filterType = (header.getAttribute("data-filter-type") || "text").toLowerCase();
      var sorts = sortLabelsForFilterType(filterType);
      var ascBtn = header.querySelector('[data-sort="asc"]');
      var descBtn = header.querySelector('[data-sort="desc"]');
      if (ascBtn) ascBtn.textContent = sorts.asc;
      if (descBtn) descBtn.textContent = sorts.desc;
    }

    var globalSearchInput = root.querySelector("[data-eal-global-search]");
    var emptyColspan = parseInt(root.getAttribute("data-eal-empty-colspan") || "10", 10);
    var emptyMsg =
      root.getAttribute("data-eal-empty-filter-message") ||
      "No rows match the selected search/filter criteria.";

    var globalColsAttr = root.getAttribute("data-eal-global-search-columns");
    var globalSearchColumns = null;
    if (globalColsAttr && globalColsAttr.trim()) {
      globalSearchColumns = globalColsAttr
        .split(",")
        .map(function (s) {
          return parseInt(s.trim(), 10);
        })
        .filter(function (n) {
          return !isNaN(n);
        });
    }

    var filterHeaders = Array.prototype.slice.call(table.querySelectorAll(".eal-th-filter"));
    filterHeaders.forEach(syncFilterMenuSortLabels);
    if (!globalSearchColumns || globalSearchColumns.length === 0) {
      globalSearchColumns = filterHeaders.map(function (h) {
        return Number(h.getAttribute("data-column-index"));
      });
    }

    var emptyRow = document.createElement("tr");
    emptyRow.className = "eal-table-empty-row";
    emptyRow.style.display = "none";
    emptyRow.innerHTML =
      '<td colspan="' +
      emptyColspan +
      '" class="eal-table-empty eal-table-empty-filter-msg">' +
      emptyMsg +
      "</td>";
    tbody.appendChild(emptyRow);

    var chipGroup = root.querySelector("[data-eal-chip-group]");
    var chipColumnRaw = root.getAttribute("data-eal-chip-column");
    var chipColumn =
      chipColumnRaw != null && String(chipColumnRaw).trim() !== ""
        ? parseInt(String(chipColumnRaw).trim(), 10)
        : NaN;
    /** When set (e.g. data-eal-row-primary), chip filter uses row attribute instead of cell text. */
    var chipRowPrimaryAttr = (root.getAttribute("data-eal-chip-primary-attr") || "").trim();

    var state = {
      globalSearch: "",
      columnFilters: {},
      chipFilter: "all",
      sort: {
        columnIndex: null,
        direction: null,
      },
    };

    var chipButtons = chipGroup
      ? Array.prototype.slice.call(chipGroup.querySelectorAll("[data-eal-chip-value]"))
      : [];

    function hasActiveFilters() {
      if (state.globalSearch) return true;
      if (state.chipFilter !== "all") return true;
      return Object.keys(state.columnFilters).some(function (key) {
        return normalizeText(state.columnFilters[key]);
      });
    }

    function getServerEmptyRows() {
      return Array.prototype.slice
        .call(tbody.querySelectorAll("tr.eal-table-empty-row"))
        .filter(function (row) {
          return row !== emptyRow;
        });
    }

    function chipMatches(row) {
      if (state.chipFilter === "all") return true;
      if (chipRowPrimaryAttr) {
        var pv = String(row.getAttribute(chipRowPrimaryAttr) || "").trim();
        if (state.chipFilter === "primary") return pv === "1";
        if (state.chipFilter === "secondary") return pv === "0";
        return true;
      }
      if (!chipGroup || chipButtons.length === 0 || isNaN(chipColumn)) return true;
      var t = normalizeText(getCellText(row, chipColumn));
      if (state.chipFilter === "primary") return t.indexOf("primary") !== -1;
      if (state.chipFilter === "secondary") return t.indexOf("secondary") !== -1;
      return true;
    }

    function getRows() {
      return Array.prototype.slice
        .call(tbody.querySelectorAll("tr"))
        .filter(function (row) {
          return row !== emptyRow && !row.classList.contains("eal-table-empty-row");
        });
    }

    function serverPaginatedUrlFiltersActive() {
      try {
        var params = new URLSearchParams(window.location.search);
        if ((params.get("q") || "").trim()) {
          return true;
        }
        var active = false;
        params.forEach(function (val, key) {
          if (active) return;
          if (key.indexOf("filter_") === 0 && (val || "").trim()) {
            active = true;
          }
        });
        return active;
      } catch (e) {
        return false;
      }
    }

    function renumberSlColumn(rows, startAt) {
      var slCol = parseInt(root.getAttribute("data-eal-sl-column-index") || "0", 10);
      if (!slCol || isNaN(slCol)) return;
      var nextSl = startAt;
      if (isNaN(nextSl) || nextSl < 1) {
        nextSl = 1;
      }
      rows.forEach(function (row) {
        if (row.style.display === "none") return;
        var cell = row.querySelector(".eal-sl-cell");
        if (!cell && row.cells && row.cells[slCol]) {
          cell = row.cells[slCol];
        }
        if (!cell) return;
        cell.textContent = String(nextSl);
        nextSl += 1;
      });
    }

    function syncServerPaginatedSlColumn() {
      if (!serverPaginated || !root.getAttribute("data-eal-sl-column-index")) {
        return;
      }
      var slStart = 1;
      if (!serverPaginatedUrlFiltersActive()) {
        slStart = parseInt(
          root.getAttribute("data-eal-sl-page-start-original") ||
            root.getAttribute("data-eal-sl-page-start") ||
            "1",
          10
        );
      }
      renumberSlColumn(getRows(), slStart);
    }

    function applyTableState() {
      if (serverPaginated) {
        return;
      }

      var rows = getRows();
      rows.forEach(function (row) {
        var globalMatch = true;
        if (state.globalSearch && globalSearchColumns.length) {
          globalMatch = globalSearchColumns.some(function (colIdx) {
            return normalizeText(getCellText(row, colIdx)).indexOf(state.globalSearch) !== -1;
          });
        }

        var columnsMatch = Object.keys(state.columnFilters).every(function (key) {
          var filterValue = normalizeText(state.columnFilters[key]);
          if (!filterValue) return true;
          return normalizeText(getCellText(row, Number(key))).indexOf(filterValue) !== -1;
        });

        row.style.display =
          globalMatch && columnsMatch && chipMatches(row) ? "" : "none";
      });

      var visibleRows = rows.filter(function (row) {
        return row.style.display !== "none";
      });

      if (
        !serverPaginated &&
        state.sort.columnIndex !== null &&
        state.sort.direction &&
        visibleRows.length
      ) {
        var col = state.sort.columnIndex;
        var dir = state.sort.direction;
        var sorted = visibleRows.slice().sort(function (a, b) {
          var valueA = normalizeText(getCellText(a, col));
          var valueB = normalizeText(getCellText(b, col));
          var cmp = valueA.localeCompare(valueB, undefined, {
            numeric: true,
            sensitivity: "base",
          });
          return dir === "desc" ? -cmp : cmp;
        });
        var hiddenRows = rows.filter(function (row) {
          return visibleRows.indexOf(row) === -1;
        });
        var frag = document.createDocumentFragment();
        sorted.forEach(function (row) {
          frag.appendChild(row);
        });
        hiddenRows.forEach(function (row) {
          frag.appendChild(row);
        });
        tbody.insertBefore(frag, emptyRow);
      }

      var dataRows = rows;
      var filtersActive = hasActiveFilters();
      var showServerEmpty = dataRows.length === 0 && !filtersActive;
      getServerEmptyRows().forEach(function (row) {
        row.style.display = showServerEmpty ? "" : "none";
      });
      emptyRow.style.display =
        visibleRows.length === 0 && (dataRows.length > 0 || filtersActive) ? "" : "none";

      if (root.getAttribute("data-eal-sl-column-index")) {
        renumberSlColumn(rows, 1);
      }

      if (syncSelectAllCheckboxes) {
        syncSelectAllCheckboxes();
      }
    }

    var syncSelectAllCheckboxes = initSelectAllCheckboxes(root);

    var searchClearBtn =
      globalSearchInput && globalSearchInput.parentElement
        ? globalSearchInput.parentElement.querySelector(".eal-search-clear-btn")
        : null;

    function syncGlobalSearchClearBtn() {
      if (!searchClearBtn || !globalSearchInput) return;
      var value = (globalSearchInput.value || "").trim();
      if (serverPaginated) {
        try {
          var activeQ = new URLSearchParams(window.location.search).get("q") || "";
          searchClearBtn.hidden = !(value || activeQ);
        } catch (e) {
          searchClearBtn.hidden = !value;
        }
        return;
      }
      searchClearBtn.hidden = !value;
    }

    if (globalSearchInput) {
      if (serverPaginated) {
        var globalSearchDebounce;
        globalSearchInput.addEventListener("input", function () {
          syncGlobalSearchClearBtn();
          clearTimeout(globalSearchDebounce);
          globalSearchDebounce = setTimeout(function () {
            var url = new URL(window.location.href);
            var v = (globalSearchInput.value || "").trim();
            var cur = url.searchParams.get("q") || "";
            if (v === cur) return;
            if (v) url.searchParams.set("q", v);
            else url.searchParams.delete("q");
            url.searchParams.delete("page");
            window.location.replace(url.toString());
          }, 450);
        });
      } else {
        globalSearchInput.addEventListener("input", function () {
          state.globalSearch = normalizeText(globalSearchInput.value);
          syncGlobalSearchClearBtn();
          applyTableState();
        });
      }
      syncGlobalSearchClearBtn();
    }

    if (searchClearBtn && globalSearchInput) {
      searchClearBtn.addEventListener("click", function () {
        globalSearchInput.value = "";
        globalSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
        syncGlobalSearchClearBtn();
        globalSearchInput.focus();
      });
    }

    if (chipGroup && (chipRowPrimaryAttr || !isNaN(chipColumn))) {
      if (root.getAttribute("data-eal-chip-listener") !== "1") {
        root.setAttribute("data-eal-chip-listener", "1");
        root.addEventListener(
          "click",
          function (e) {
            var t = e.target;
            if (t && t.nodeType !== 1) {
              t = t.parentElement;
            }
            if (!t || typeof t.closest !== "function") return;
            var chipBtn = t.closest("[data-eal-chip-value]");
            if (!chipBtn || !chipGroup.contains(chipBtn)) return;
            e.preventDefault();
            e.stopPropagation();
            var v = String(chipBtn.getAttribute("data-eal-chip-value") || "all")
              .toLowerCase()
              .trim();
            if (v === "primary") state.chipFilter = "primary";
            else if (v === "secondary") state.chipFilter = "secondary";
            else state.chipFilter = "all";
            Array.prototype.forEach.call(
              chipGroup.querySelectorAll("[data-eal-chip-value]"),
              function (b) {
                b.classList.toggle("active", b === chipBtn);
              },
            );
            applyTableState();
          },
          true,
        );
      }
    }

    filterHeaders.forEach(function (header) {
      var menuButton = header.querySelector(".eal-filter-menu-btn");
      var menu = header.querySelector(".eal-filter-menu");
      var input = header.querySelector(".eal-column-filter-input");
      var columnIndex = Number(header.getAttribute("data-column-index"));

      if (!menuButton || !menu) return;

      menuButton.addEventListener("click", function (event) {
        event.stopPropagation();
        filterHeaders.forEach(function (otherHeader) {
          if (otherHeader !== header) {
            var otherMenu = otherHeader.querySelector(".eal-filter-menu");
            var otherButton = otherHeader.querySelector(".eal-filter-menu-btn");
            if (otherMenu) {
              otherMenu.classList.remove("open");
              resetFloatingMenu(otherMenu);
            }
            if (otherButton) otherButton.classList.remove("active");
          }
        });
        menu.classList.toggle("open");
        menuButton.classList.toggle("active", menu.classList.contains("open"));
        if (menu.classList.contains("open")) {
          positionFloatingMenu(menu, menuButton);
        } else {
          resetFloatingMenu(menu);
        }
      });

      if (input) {
        if (serverPaginated) {
          var filterDebounce;
          var params;
          try {
            params = new URLSearchParams(window.location.search);
          } catch (e) {
            params = null;
          }
          if (params) {
            var initialVal = params.get("filter_" + columnIndex) || "";
            if (initialVal) input.value = initialVal;
          }
          input.addEventListener("input", function () {
            clearTimeout(filterDebounce);
            filterDebounce = setTimeout(function () {
              var urlVal = "";
              try {
                urlVal =
                  new URLSearchParams(window.location.search).get(
                    "filter_" + columnIndex
                  ) || "";
              } catch (e) {
                urlVal = "";
              }
              var nextVal = (input.value || "").trim();
              if (nextVal === urlVal) return;
              navigateServerPaginatedFilter(columnIndex, nextVal);
            }, 450);
          });
        } else {
          input.addEventListener("input", function () {
            state.columnFilters[columnIndex] = input.value;
            applyTableState();
          });
        }
      }

      Array.prototype.slice.call(menu.querySelectorAll("[data-sort]")).forEach(function (button) {
        button.addEventListener("click", function () {
          var direction = button.getAttribute("data-sort");
          if (serverPaginated) {
            navigateServerPaginatedSort(columnIndex, direction);
            return;
          }
          state.sort.columnIndex = columnIndex;
          state.sort.direction = direction;
          applyTableState();
          menu.classList.remove("open");
          resetFloatingMenu(menu);
          menuButton.classList.remove("active");
        });
      });

      Array.prototype.slice.call(menu.querySelectorAll("[data-clear]")).forEach(function (button) {
        button.addEventListener("click", function () {
          if (serverPaginated) {
            clearServerPaginatedColumn(columnIndex);
            return;
          }
          if (input) input.value = "";
          delete state.columnFilters[columnIndex];
          if (state.sort.columnIndex === columnIndex) {
            state.sort.columnIndex = null;
            state.sort.direction = null;
          }
          applyTableState();
          menu.classList.remove("open");
          resetFloatingMenu(menu);
          menuButton.classList.remove("active");
        });
      });
    });

    document.addEventListener("click", function (event) {
      if (event.target.closest(".eal-th-filter")) return;
      filterHeaders.forEach(function (header) {
        var menu = header.querySelector(".eal-filter-menu");
        var button = header.querySelector(".eal-filter-menu-btn");
        if (menu) {
          menu.classList.remove("open");
          resetFloatingMenu(menu);
        }
        if (button) button.classList.remove("active");
      });
    });

    window.addEventListener("resize", function () {
      filterHeaders.forEach(function (header) {
        var menu = header.querySelector(".eal-filter-menu.open");
        var button = header.querySelector(".eal-filter-menu-btn");
        if (menu && button) {
          positionFloatingMenu(menu, button);
        }
      });
    });

    if (root.getAttribute("data-eal-action-dropdowns") !== "0") {
      initFloatingActionDropdowns(root);
    }

    if (root.getAttribute("data-eal-sl-column-index")) {
      root.setAttribute(
        "data-eal-sl-page-start-original",
        root.getAttribute("data-eal-sl-page-start") || "1"
      );
    }

    if (serverPaginated) {
      syncServerFilterInputs(filterHeaders);
      syncServerSortIndicators(filterHeaders);
    } else {
      applyTableState();
    }
  }

  function autoInit() {
    discoverFilterableRoots().forEach(function (root) {
      if (root.getAttribute("data-eal-filter-initialized") === "1") return;
      root.setAttribute("data-eal-filter-initialized", "1");
      initFilterableTable(root);
    });
    initFloatingActionDropdowns(document);
  }

  global.EalDataTableFilters = {
    init: initFilterableTable,
    autoInit: autoInit,
    initActionDropdowns: initFloatingActionDropdowns,
    ensureFilterHeaders: ensureFilterHeaders,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }
})(typeof window !== "undefined" ? window : this);
