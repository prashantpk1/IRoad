/**
 * Run booking_linkage_cascade.js against mock DOM (PCS §8.1).
 * Usage: node scripts/verify_booking_cascade_8_1.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class MockOption {
  constructor(value, label, attrs = {}) {
    this.value = value;
    this.label = label;
    this.text = label;
    this.hidden = false;
    this.disabled = false;
    this._attrs = { ...attrs };
  }
  getAttribute(name) {
    return this._attrs[name] ?? "";
  }
  setAttribute(name, val) {
    this._attrs[name] = val;
  }
}

class MockSelect {
  constructor(options = []) {
    this.options = options;
    this.selectedIndex = 0;
    this._value = "";
  }
  get value() {
    return this._value;
  }
  set value(v) {
    this._value = v;
    const idx = this.options.findIndex((o) => o.value === v);
    this.selectedIndex = idx >= 0 ? idx : 0;
  }
  add(option) {
    this.options.push(option);
  }
}

function loadLinkage() {
  const jsPath = path.join(
    __dirname,
    "..",
    "iroad_tenants",
    "static",
    "tenantdesign",
    "Javascript",
    "booking_linkage_cascade.js"
  );
  const code = fs.readFileSync(jsPath, "utf8");
  const sandbox = { global: {}, window: {} };
  sandbox.global = sandbox.window;
  vm.runInNewContext(code, sandbox);
  return sandbox.global.IRoadBookingLinkage;
}

function buildFixture() {
  const bookingItem = new MockSelect([
    new MockOption("", "-Select booking item-", {}),
    new MockOption("SV-0004 - RT-0001 — Jeddah — Makkah", "Item A", {
      "data-booking-id": "b1",
      "data-booking-no": "BK-0052",
    }),
    new MockOption("SV-0005 - RT-0002 — Riyadh — Dammam", "Item B", {
      "data-booking-id": "b1",
      "data-booking-no": "BK-0052",
    }),
    new MockOption("Other booking item", "Other", {
      "data-booking-id": "b2",
      "data-booking-no": "BK-0099",
    }),
  ]);

  const shipment = new MockSelect([
    new MockOption("", "-Select shipment-", {}),
    new MockOption("s1", "SH-0068 - BK-0052", {
      "data-booking-id": "b1",
      "data-booking-no": "BK-0052",
      "data-booking-item": "SV-0004 - RT-0001 — Jeddah — Makkah",
    }),
    new MockOption("s2", "SH-0069 - BK-0052", {
      "data-booking-id": "b1",
      "data-booking-no": "BK-0052",
      "data-booking-item": "SV-0005 - RT-0002 — Riyadh — Dammam",
    }),
    new MockOption("s3", "SH-0100 - BK-0099", {
      "data-booking-id": "b2",
      "data-booking-no": "BK-0099",
      "data-booking-item": "Other booking item",
    }),
  ]);

  const docRecord = new MockSelect([
    new MockOption("", "-Select doc record-", {}),
    new MockOption("d1", "REC-0079 - SH-0068", {
      "data-shipment-id": "s1",
      "data-booking-item": "SV-0004 - RT-0001 — Jeddah — Makkah",
    }),
    new MockOption("d2", "REC-0080 - SH-0069", {
      "data-shipment-id": "s2",
      "data-booking-item": "SV-0005 - RT-0002 — Riyadh — Dammam",
    }),
    new MockOption("d3", "REC-0100 - SH-0100", {
      "data-shipment-id": "s3",
      "data-booking-item": "Other booking item",
    }),
  ]);

  return { bookingItem, shipment, docRecord };
}

function visibleOptions(select) {
  return select.options.slice(1).filter((o) => !o.disabled && !o.hidden);
}

function main() {
  const linkage = loadLinkage();
  const { bookingItem, shipment, docRecord } = buildFixture();

  // Step 1: filter booking items for BK-0052
  linkage.filterBookingItems(bookingItem, "b1", "BK-0052");
  const items = visibleOptions(bookingItem);
  console.log("Step 1 — Booking items for BK-0052:", items.map((o) => o.value));
  const step1 =
    items.length === 2 &&
    items.every((o) => o.getAttribute("data-booking-no") === "BK-0052");

  // Step 2: select first item, filter shipments
  bookingItem.value = items[0].value;
  linkage.filterShipments(shipment, "b1", "BK-0052", bookingItem.value);
  const ships = visibleOptions(shipment);
  console.log("Step 2 — Shipments for item:", ships.map((o) => o.label));
  const step2 =
    ships.length === 1 &&
    ships[0].value === "s1" &&
    ships[0].getAttribute("data-booking-item") === bookingItem.value;

  // Step 3: filter doc records for shipment
  shipment.value = ships[0].value;
  linkage.filterRecordsForShipment(docRecord, shipment.value, bookingItem.value);
  const docs = visibleOptions(docRecord);
  console.log("Step 3 — Doc records for SH-0068:", docs.map((o) => o.label));
  const step3 = docs.length === 1 && docs[0].value === "d1";

  // Full cascade after user selects booking item (matches screenshot flow)
  const { bookingItem: bi2, shipment: sh2, docRecord: dr2 } = buildFixture();
  bi2.value = "SV-0004 - RT-0001 — Jeddah — Makkah";
  const result = linkage.runLinkageCascade({
    bookingId: "b1",
    bookingNo: "BK-0052",
    bookingItemSelect: bi2,
    shipmentSelect: sh2,
    recordSelects: [dr2],
    preserveBookingItem: true,
  });
  console.log("Full cascade result:", result);
  const stepAll =
    result.bookingItemValue === "SV-0004 - RT-0001 — Jeddah — Makkah" &&
    result.shipmentIdValue === "s1" &&
    result.matchedRecords[0].length === 1;

  const passed = step1 && step2 && step3 && stepAll;
  console.log("\nJS cascade:", passed ? "PASS" : "FAIL");
  process.exit(passed ? 0 : 1);
}

main();
