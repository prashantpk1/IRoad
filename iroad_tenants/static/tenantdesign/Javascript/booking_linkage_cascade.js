/**
 * PCS §8.1 — Booking → Booking Item → Shipment → Doc Record cascading select filters.
 */
(function (global) {
  function readAttr(option, name) {
    return String(option.getAttribute(name) || "").trim();
  }

  function selectedOption(selectEl) {
    if (!selectEl || selectEl.selectedIndex < 0) return null;
    return selectEl.options[selectEl.selectedIndex];
  }

  function ensureSelectOption(selectEl, value, label, attrs) {
    if (!selectEl || !value) return;
    const exists = Array.prototype.some.call(selectEl.options, function (option) {
      return option.value === value;
    });
    if (!exists) {
      const option = new Option(label || value, value);
      if (attrs) {
        Object.keys(attrs).forEach(function (key) {
          option.setAttribute(key, attrs[key]);
        });
      }
      selectEl.add(option);
    }
  }

  function matchesBooking(option, bookingId, bookingNo) {
    if (!bookingId && !bookingNo) return false;
    const optionBookingId = readAttr(option, "data-booking-id");
    const optionBookingNo = readAttr(option, "data-booking-no");
    if (bookingId && optionBookingId === bookingId) return true;
    if (bookingNo && optionBookingNo === bookingNo) return true;
    return false;
  }

  function filterSelectByPredicate(selectEl, predicate, options) {
    const opts = options || {};
    const autoSelectSingle = opts.autoSelectSingle !== false;
    const clearInvalidSelection = opts.clearInvalidSelection !== false;
    if (!selectEl) return [];

    const matched = [];
    Array.prototype.forEach.call(selectEl.options, function (option, index) {
      if (index === 0) {
        option.hidden = false;
        option.disabled = false;
        return;
      }
      const isMatch = predicate(option);
      option.hidden = !isMatch;
      option.disabled = !isMatch;
      if (isMatch) matched.push(option);
    });

    const current = selectedOption(selectEl);
    if (clearInvalidSelection && current && (current.disabled || current.hidden)) {
      selectEl.value = "";
    }
    if (autoSelectSingle && !selectEl.value && matched.length === 1) {
      selectEl.value = matched[0].value;
    }
    return matched;
  }

  function filterBookingItems(bookingItemSelect, bookingId, bookingNo) {
    return filterSelectByPredicate(bookingItemSelect, function (option) {
      return matchesBooking(option, bookingId, bookingNo);
    });
  }

  function filterShipments(shipmentSelect, bookingId, bookingNo, bookingItem) {
    const normalizedItem = String(bookingItem || "").trim();
    return filterSelectByPredicate(shipmentSelect, function (option) {
      if (!normalizedItem) return false;
      return (
        matchesBooking(option, bookingId, bookingNo) &&
        readAttr(option, "data-booking-item") === normalizedItem
      );
    });
  }

  function filterRecordsForShipment(selectEl, shipmentId, bookingItem) {
    const normalizedShipmentId = String(shipmentId || "").trim();
    const normalizedItem = String(bookingItem || "").trim();
    return filterSelectByPredicate(selectEl, function (option) {
      if (!normalizedShipmentId) return false;
      const shipmentMatch = readAttr(option, "data-shipment-id") === normalizedShipmentId;
      const optionItem = readAttr(option, "data-booking-item");
      const itemMatch = !normalizedItem || !optionItem || optionItem === normalizedItem;
      return shipmentMatch && itemMatch;
    });
  }

  /**
   * Run the full Booking → Item → Shipment → record cascade.
   * Returns { bookingItemValue, shipmentIdValue, matchedShipments, matchedRecords }.
   */
  function runLinkageCascade(config) {
    const cfg = config || {};
    const bookingId = String(cfg.bookingId || "").trim();
    const bookingNo = String(cfg.bookingNo || "").trim();
    const bookingItemSelect = cfg.bookingItemSelect || null;
    const shipmentSelect = cfg.shipmentSelect || null;
    const recordSelects = cfg.recordSelects || [];
    const preserveBookingItem = cfg.preserveBookingItem === true;
    const preserveShipment = cfg.preserveShipment === true;
    const autoSelectSingleShipment = cfg.autoSelectSingleShipment !== false;

    filterBookingItems(bookingItemSelect, bookingId, bookingNo);

    let bookingItemValue = "";
    if (bookingItemSelect) {
      const currentItem = selectedOption(bookingItemSelect);
      if (currentItem && currentItem.value && !currentItem.disabled) {
        if (preserveBookingItem || bookingItemSelect.value) {
          bookingItemValue = bookingItemSelect.value;
        }
      }
      if (!bookingItemValue) {
        bookingItemSelect.value = "";
        const autoItem = selectedOption(bookingItemSelect);
        if (autoItem && autoItem.value && !autoItem.disabled) {
          bookingItemValue = autoItem.value;
        }
      }
    }

    const matchedShipments = filterShipments(
      shipmentSelect,
      bookingId,
      bookingNo,
      bookingItemValue,
    );

    let shipmentIdValue = "";
    if (shipmentSelect) {
      const currentShipment = selectedOption(shipmentSelect);
      if (
        preserveShipment &&
        currentShipment &&
        !currentShipment.disabled &&
        currentShipment.value
      ) {
        shipmentIdValue = shipmentSelect.value;
      } else if (
        shipmentSelect.value &&
        matchedShipments.some(function (option) {
          return option.value === shipmentSelect.value;
        })
      ) {
        shipmentIdValue = shipmentSelect.value;
      } else if (autoSelectSingleShipment && matchedShipments.length) {
        shipmentSelect.value = matchedShipments[0].value;
        shipmentIdValue = shipmentSelect.value;
      } else {
        shipmentSelect.value = "";
      }
    }

    const matchedRecords = [];
    recordSelects.forEach(function (selectEl) {
      if (!selectEl) return;
      matchedRecords.push(
        filterRecordsForShipment(selectEl, shipmentIdValue, bookingItemValue),
      );
    });

    return {
      bookingItemValue: bookingItemValue,
      shipmentIdValue: shipmentIdValue,
      matchedShipments: matchedShipments,
      matchedRecords: matchedRecords,
    };
  }

  global.IRoadBookingLinkage = {
    readAttr: readAttr,
    selectedOption: selectedOption,
    ensureSelectOption: ensureSelectOption,
    matchesBooking: matchesBooking,
    filterBookingItems: filterBookingItems,
    filterShipments: filterShipments,
    filterRecordsForShipment: filterRecordsForShipment,
    runLinkageCascade: runLinkageCascade,
  };
})(window);
