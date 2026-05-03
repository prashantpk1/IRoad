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

  function initFilterableTable(root) {
    if (!root || root.getAttribute("data-eal-filter-skip") === "1") return;

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

    var state = {
      globalSearch: "",
      columnFilters: {},
      sort: {
        columnIndex: null,
        direction: null,
      },
    };

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

        row.style.display = globalMatch && columnsMatch ? "" : "none";
      });

      var visibleRows = rows.filter(function (row) {
        return row.style.display !== "none";
      });

      if (state.sort.columnIndex !== null && state.sort.direction) {
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
        sorted.forEach(function (row) {
          tbody.appendChild(row);
        });
      }

      emptyRow.style.display = visibleRows.length ? "none" : "";
    }

    if (globalSearchInput) {
      globalSearchInput.addEventListener("input", function () {
        state.globalSearch = normalizeText(globalSearchInput.value);
        applyTableState();
      });
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
          state.sort.columnIndex = columnIndex;
          state.sort.direction = button.getAttribute("data-sort");
          applyTableState();
          menu.classList.remove("open");
          resetFloatingMenu(menu);
          menuButton.classList.remove("active");
        });
      });

      Array.prototype.slice.call(menu.querySelectorAll("[data-clear]")).forEach(function (button) {
        button.addEventListener("click", function () {
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
