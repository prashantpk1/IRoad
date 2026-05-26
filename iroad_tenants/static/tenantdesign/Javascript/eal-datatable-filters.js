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

  function initFilterableTable(root) {
    if (!root || root.getAttribute("data-eal-filter-skip") === "1") return;

    var serverPaginated = root.getAttribute("data-eal-server-paginated") === "1";
    var table = root.querySelector("table.eal-table");
    if (!table) return;
    var tbody = table.querySelector("tbody");
    if (!tbody) return;

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

    function applyTableState() {
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
    }

    if (globalSearchInput) {
      globalSearchInput.addEventListener("input", function () {
        state.globalSearch = normalizeText(globalSearchInput.value);
        applyTableState();
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
        input.addEventListener("input", function () {
          state.columnFilters[columnIndex] = input.value;
          applyTableState();
        });
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
            clearServerPaginatedSort(columnIndex);
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

    applyTableState();
  }

  function autoInit() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-eal-filterable-table]"), function (
      root
    ) {
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
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }
})(typeof window !== "undefined" ? window : this);
