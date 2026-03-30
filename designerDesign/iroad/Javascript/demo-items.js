// ============================================
// Demo Items - shared data + localStorage store
// ============================================
//
// This is used by:
// - Demo-items-list.html
// - Demo-item-form.html
//
// Store is persisted only in the browser (localStorage) for demo purposes.

(function (global) {
  const STORAGE_KEY = "demo_items_store_v1";

  // Base dataset (used to seed localStorage on first load)
  const BASE_ITEMS = [
    {
      id: "D-001",
      name: "Shipment Prep Template",
      description:
        "Demo item used to store a reusable template for shipment preparation workflows.",
      category: "Operations",
      status: "Active",
      priority: 1,
      createdAt: "2026-01-08",
      updatedAt: "2026-01-28",
    },
    {
      id: "D-002",
      name: "Client Onboarding Checklist",
      description:
        "Checklist for client onboarding including required documents and verification steps.",
      category: "CRM",
      status: "Active",
      priority: 2,
      createdAt: "2026-01-12",
      updatedAt: "2026-01-29",
    },
    {
      id: "D-003",
      name: "Invoice Approval Rules",
      description:
        "Defines approval thresholds and escalation steps for invoices and billing documents.",
      category: "Finance",
      status: "Draft",
      priority: 4,
      createdAt: "2026-02-01",
      updatedAt: "2026-02-10",
    },
    {
      id: "D-004",
      name: "Tax Calculation Presets",
      description:
        "Demo preset pack for selecting tax codes and calculating rates based on scope.",
      category: "Finance",
      status: "Active",
      priority: 3,
      createdAt: "2026-01-23",
      updatedAt: "2026-01-30",
    },
    {
      id: "D-005",
      name: "Support SLA Escalation",
      description:
        "Escalation rules to handle urgent support requests and time-based reassignment.",
      category: "Support",
      status: "Active",
      priority: 2,
      createdAt: "2026-01-17",
      updatedAt: "2026-01-25",
    },
    {
      id: "D-006",
      name: "Roles & Permission Map",
      description:
        "Demo item describing roles, permissions, and access policies for admin users.",
      category: "Security",
      status: "Active",
      priority: 5,
      createdAt: "2026-02-05",
      updatedAt: "2026-02-11",
    },
    {
      id: "D-007",
      name: "Weekly Operations Report Spec",
      description:
        "A spec for weekly reporting format, sections, and KPI computations.",
      category: "Operations",
      status: "Draft",
      priority: 4,
      createdAt: "2026-02-12",
      updatedAt: "2026-02-12",
    },
    {
      id: "D-008",
      name: "Promo Rule: Free Upgrade",
      description:
        "Demo promo rule that grants a free plan upgrade for qualifying tenants.",
      category: "Subscriptions",
      status: "Active",
      priority: 3,
      createdAt: "2026-02-14",
      updatedAt: "2026-02-20",
    },
    {
      id: "D-009",
      name: "Gateway Routing Policy",
      description:
        "Routing policy for selecting payment gateway based on tenant configuration and currency.",
      category: "Payment",
      status: "Active",
      priority: 2,
      createdAt: "2026-01-29",
      updatedAt: "2026-02-02",
    },
    {
      id: "D-010",
      name: "Data Retention Policy",
      description:
        "Demo item defining retention windows for logs, sessions, and audit data.",
      category: "Security",
      status: "Archived",
      priority: 6,
      createdAt: "2025-12-15",
      updatedAt: "2026-01-05",
    },
    {
      id: "D-011",
      name: "Vendor Contract Checklist",
      description:
        "Checklist for vendor contracts including documents, approval steps, and expiry reminders.",
      category: "Operations",
      status: "Active",
      priority: 2,
      createdAt: "2026-01-19",
      updatedAt: "2026-02-01",
    },
    {
      id: "D-012",
      name: "FX Rate Change Display",
      description:
        "Demo spec to show FX rate changes with impact preview on transactions.",
      category: "Finance",
      status: "Inactive",
      priority: 3,
      createdAt: "2026-01-26",
      updatedAt: "2026-01-27",
    },
    {
      id: "D-013",
      name: "Client Contract Reminder",
      description:
        "Reminder automation rules for contract renewal deadlines and notifications.",
      category: "CRM",
      status: "Active",
      priority: 3,
      createdAt: "2026-02-03",
      updatedAt: "2026-02-15",
    },
    {
      id: "D-014",
      name: "Incident Response Playbook",
      description:
        "Demo playbook with incident severity levels, notifications, and rollback guidance.",
      category: "Security",
      status: "Draft",
      priority: 7,
      createdAt: "2026-02-16",
      updatedAt: "2026-02-16",
    },
    {
      id: "D-015",
      name: "Tenant Welcome Banner Text",
      description:
        "Demo template for tenant welcome banner copy and localization placeholders.",
      category: "Subscriptions",
      status: "Active",
      priority: 1,
      createdAt: "2026-01-30",
      updatedAt: "2026-02-18",
    },
    {
      id: "D-016",
      name: "Bank Account Validation Rules",
      description:
        "Demo rules to validate bank account formats and required fields per tenant.",
      category: "Payment",
      status: "Active",
      priority: 3,
      createdAt: "2026-02-04",
      updatedAt: "2026-02-07",
    },
    {
      id: "D-017",
      name: "Ticket Categorization Matrix",
      description:
        "Demo matrix that maps ticket types to routing and suggested responses.",
      category: "Support",
      status: "Inactive",
      priority: 4,
      createdAt: "2026-01-21",
      updatedAt: "2026-01-22",
    },
    {
      id: "D-018",
      name: "Route Master Sync Job",
      description:
        "Demo job configuration used to sync route masters from an external source.",
      category: "Operations",
      status: "Archived",
      priority: 5,
      createdAt: "2025-11-29",
      updatedAt: "2026-01-09",
    },
    {
      id: "D-019",
      name: "Tax Code Coverage Report",
      description:
        "Demo report spec showing which tax codes are used per scope and country.",
      category: "Finance",
      status: "Active",
      priority: 2,
      createdAt: "2026-02-09",
      updatedAt: "2026-02-25",
    },
    {
      id: "D-020",
      name: "Access Review Cadence",
      description:
        "Demo setting to schedule role access reviews and capture audit notes.",
      category: "Security",
      status: "Active",
      priority: 6,
      createdAt: "2026-02-13",
      updatedAt: "2026-02-24",
    },
  ];

  function _readStoredItems() {
    const raw = global.localStorage
      ? global.localStorage.getItem(STORAGE_KEY)
      : null;
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    } catch (e) {
      // ignore
    }
    return null;
  }

  function _writeStoredItems(items) {
    if (!global.localStorage) return;
    global.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  }

  function loadItems() {
    var stored = _readStoredItems();
    if (stored) return stored;
    return BASE_ITEMS.slice();
  }

  function getItemById(id) {
    var items = loadItems();
    return items.find(function (it) {
      return it.id === id;
    }) || null;
  }

  function upsertItem(item) {
    var items = loadItems();
    var idx = items.findIndex(function (it) {
      return it.id === item.id;
    });
    if (idx === -1) items.push(item);
    else items[idx] = item;
    _writeStoredItems(items);
    return item;
  }

  function deleteItem(id) {
    var items = loadItems();
    var next = items.filter(function (it) {
      return it.id !== id;
    });
    _writeStoredItems(next);
    return true;
  }

  function getAllCategories() {
    return Array.from(
      new Set(loadItems().map(function (it) {
        return it.category;
      })),
    ).sort();
  }

  function getStatusOptions() {
    // Must match the dataset values
    return ["Active", "Draft", "Inactive", "Archived"];
  }

  function generateNewId() {
    var items = loadItems();
    var prefix = "D-";
    var max = 0;
    items.forEach(function (it) {
      if (!it.id || typeof it.id !== "string") return;
      if (it.id.indexOf(prefix) !== 0) return;
      var num = parseInt(it.id.slice(prefix.length), 10);
      if (!Number.isNaN(num) && num > max) max = num;
    });
    var next = max + 1;
    return prefix + String(next).padStart(3, "0");
  }

  global.demoItems = {
    loadItems: loadItems,
    getItemById: getItemById,
    upsertItem: upsertItem,
    deleteItem: deleteItem,
    getAllCategories: getAllCategories,
    getStatusOptions: getStatusOptions,
    generateNewId: generateNewId,
  };
})(window);

