/* Fleet GPS Surveillance — Google Maps embed iframes (tenant dashboard). */

window.iroadFleetGpsState = {
  data: null,
  meta: null,
  booted: false,
};

var IROAD_FLEET_GPS_DEFAULT = { lat: 24.7136, lng: 46.6753 };

function iroadParseJsonNode(id, fallback) {
  var node = document.getElementById(id);
  if (!node || !node.textContent) return fallback;
  try {
    return JSON.parse(node.textContent);
  } catch (err) {
    return fallback;
  }
}

function iroadElementDisplayed(el) {
  if (!el) return false;
  if (el.style.display === "none") return false;
  var cs = window.getComputedStyle(el);
  return cs.display !== "none" && cs.visibility !== "hidden";
}

function iroadFleetGpsHubVisible() {
  return iroadElementDisplayed(document.querySelector(".operations-hub-shell"));
}

function iroadActiveSurvTab() {
  var pane = document.querySelector(".surv-pane.active");
  return pane ? pane.getAttribute("data-surv-pane") || "" : "";
}

function iroadCoordPoint(raw) {
  if (!raw) return null;
  var lat = Number(raw.lat);
  var lng = Number(raw.lng);
  if (!isFinite(lat) || !isFinite(lng)) return null;
  return { lat: lat, lng: lng };
}

function iroadEmbedPointUrl(point, zoom) {
  var p = iroadCoordPoint(point);
  if (!p) return "";
  return (
    "https://maps.google.com/maps?q=" +
    encodeURIComponent(p.lat + "," + p.lng) +
    "&z=" +
    (zoom || 14) +
    "&hl=en&output=embed"
  );
}

function iroadEmbedRouteUrl(start, end) {
  var a = iroadCoordPoint(start);
  var b = iroadCoordPoint(end);
  if (!a || !b) return "";
  return (
    "https://maps.google.com/maps?saddr=" +
    encodeURIComponent(a.lat + "," + a.lng) +
    "&daddr=" +
    encodeURIComponent(b.lat + "," + b.lng) +
    "&hl=en&output=embed"
  );
}

function iroadTrailPoints(path) {
  return (path || [])
    .map(function (p) {
      return iroadCoordPoint(p);
    })
    .filter(Boolean);
}

function iroadSetMapFrame(frameId, url) {
  var frame = document.getElementById(frameId);
  if (!frame || !url) return;
  if (frame.getAttribute("src") !== url) {
    frame.setAttribute("src", url);
  }
}

function iroadRenderLiveMap(data) {
  if (iroadActiveSurvTab() !== "live-map") return;

  var center = data.default_center || IROAD_FLEET_GPS_DEFAULT;
  var markers = data.live_markers || [];
  var points = markers.map(iroadCoordPoint).filter(Boolean);
  var target = points.length ? points[0] : center;
  var zoom = points.length ? 14 : 6;

  iroadSetMapFrame("fleet-live-map", iroadEmbedPointUrl(target, zoom));

  var emptyEl = document.getElementById("fleet-live-empty");
  if (emptyEl) {
    emptyEl.classList.toggle("d-none", points.length > 0);
  }

  var openMaps = document.getElementById("fleet-live-open-maps");
  if (openMaps && target) {
    openMaps.href =
      "https://maps.google.com/?q=" + target.lat + "," + target.lng;
  }
}

function iroadRenderDetailMap(data) {
  if (iroadActiveSurvTab() !== "detailed-tracking") return;

  var center = data.default_center || IROAD_FLEET_GPS_DEFAULT;
  var track = data.featured_track;
  var emptyEl = document.getElementById("fleet-detail-empty");
  var popup = document.getElementById("fleet-detail-popup");
  var path = iroadTrailPoints(track && track.trail ? track.trail : []);
  var current = track && track.current ? iroadCoordPoint(track.current) : null;
  var embedUrl = "";

  if (path.length >= 2) {
    embedUrl = iroadEmbedRouteUrl(path[0], path[path.length - 1]);
  } else if (path.length === 1) {
    embedUrl = iroadEmbedPointUrl(path[0], 14);
  } else if (current) {
    embedUrl = iroadEmbedPointUrl(current, 14);
  } else if (track) {
    embedUrl = iroadEmbedPointUrl(center, 6);
  }

  if (embedUrl) {
    iroadSetMapFrame("fleet-detail-map", embedUrl);
  }

  if (emptyEl) {
    emptyEl.classList.toggle("d-none", !!(track && (path.length || current)));
  }

  if (popup) {
    if (track && (current || path.length)) {
      popup.classList.remove("d-none");
      var speedEl = document.getElementById("fleet-detail-speed");
      var headingEl = document.getElementById("fleet-detail-heading");
      if (speedEl) speedEl.innerHTML = "LIVE <span>GPS</span>";
      if (headingEl) {
        headingEl.innerHTML = (track.shipment_status || "IN TRANSIT").replace(
          " ",
          "<br />",
        );
      }
    } else {
      popup.classList.add("d-none");
    }
  }
}

function iroadRenderVisibleFleetMaps(data) {
  if (!data) return;
  iroadRenderLiveMap(data);
  iroadRenderDetailMap(data);
}

function iroadUpdateDetailSidebar(track) {
  var setText = function (id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value || "—";
  };

  if (!track) {
    setText("fleet-detail-shipment-no", "—");
    setText("fleet-detail-departure", "—");
    setText("fleet-detail-departure-time", "—");
    setText("fleet-detail-arrival", "—");
    setText("fleet-detail-arrival-time", "—");
    setText("fleet-detail-driver-name", "—");
    setText("fleet-detail-driver-initials", "—");
    setText("fleet-detail-driver-plate", "PLATE: —");
    var search = document.getElementById("fleet-detail-search");
    if (search) search.value = "No shipment";
    var statuses = document.getElementById("fleet-detail-statuses");
    if (statuses) {
      statuses.innerHTML =
        '<span class="badge-status pending">NO ACTIVE TRACK</span>';
    }
    var history = document.getElementById("fleet-detail-history");
    if (history) {
      history.innerHTML =
        '<div class="text-muted small">Execute a driver action with GPS from the mobile app to start live tracking.</div>';
    }
    return;
  }

  setText("fleet-detail-shipment-no", "#" + track.shipment_no);
  setText("fleet-detail-departure", track.departure_label);
  setText("fleet-detail-departure-time", track.departure_time);
  setText("fleet-detail-arrival", track.arrival_label);
  setText("fleet-detail-arrival-time", track.arrival_time);
  setText("fleet-detail-driver-name", track.driver_name);
  setText("fleet-detail-driver-initials", track.driver_initials);
  setText("fleet-detail-driver-plate", "PLATE: " + track.driver_plate);
  var searchInput = document.getElementById("fleet-detail-search");
  if (searchInput) searchInput.value = track.shipment_no;

  var statusWrap = document.getElementById("fleet-detail-statuses");
  if (statusWrap) {
    var html =
      '<span class="badge-status in-transit">' +
      (track.shipment_status || "IN TRANSIT") +
      "</span>";
    if (track.on_time) {
      html += '<span class="badge-status on-time">ON TIME</span>';
    }
    statusWrap.innerHTML = html;
  }

  var historyEl = document.getElementById("fleet-detail-history");
  if (historyEl) {
    var rows = track.history || [];
    if (!rows.length) {
      historyEl.innerHTML =
        '<div class="text-muted small">No action history with GPS yet.</div>';
    } else {
      historyEl.innerHTML = rows
        .map(function (item) {
          var cls = item.state === "current" ? "current" : "completed";
          var icon =
            item.state === "current"
              ? '<i class="bi bi-truck"></i>'
              : '<i class="bi bi-check2"></i>';
          return (
            '<div class="timeline-item ' +
            cls +
            '"><div class="tl-icon">' +
            icon +
            '</div><div class="tl-content"><div class="tl-head"><span class="tl-name">' +
            item.title +
            '</span><span class="tl-time">' +
            item.time +
            '</span></div><div class="tl-desc">' +
            item.description +
            "</div></div></div>"
          );
        })
        .join("");
    }
  }
}

function iroadApplyFleetGpsData(data) {
  window.iroadFleetGpsState.data = data;
  iroadUpdateDetailSidebar(data.featured_track);
  iroadRenderVisibleFleetMaps(data);
}

function iroadFocusFeaturedShipment(shipmentId) {
  var tabBtn = document.querySelector(
    '.surv-tab-btn[data-surv-tab="detailed-tracking"]',
  );
  if (tabBtn) tabBtn.click();
  var meta = window.iroadFleetGpsState.meta || {};
  if (!meta.refreshUrl || !shipmentId) return;
  fetch(meta.refreshUrl + "?shipment_id=" + encodeURIComponent(shipmentId), {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  })
    .then(function (res) {
      return res.json();
    })
    .then(function (payload) {
      iroadApplyFleetGpsData(payload);
    })
    .catch(function () {});
}

function iroadOnSurveillanceTabChange() {
  if (window.iroadFleetGpsState.data) {
    window.setTimeout(function () {
      iroadRenderVisibleFleetMaps(window.iroadFleetGpsState.data);
    }, 50);
  }
}
window.iroadOnSurveillanceTabChange = iroadOnSurveillanceTabChange;

function iroadScheduleFleetGpsBoot() {
  [0, 100, 350, 700].forEach(function (delay) {
    window.setTimeout(function () {
      if (!iroadFleetGpsHubVisible()) return;
      iroadTryBootFleetGpsMaps();
    }, delay);
  });
}
window.iroadScheduleFleetGpsBoot = iroadScheduleFleetGpsBoot;

function iroadOnOperationsHubShown() {
  iroadScheduleFleetGpsBoot();
}
window.iroadOnOperationsHubShown = iroadOnOperationsHubShown;

function iroadResizeFleetGpsMaps() {
  if (!iroadFleetGpsHubVisible()) return;
  if (window.iroadFleetGpsState.data) {
    iroadRenderVisibleFleetMaps(window.iroadFleetGpsState.data);
  } else {
    iroadTryBootFleetGpsMaps();
  }
}
window.iroadResizeFleetGpsMaps = iroadResizeFleetGpsMaps;

function iroadHardResetFleetGpsMaps() {
  window.iroadFleetGpsState.booted = false;
}
window.iroadHardResetFleetGpsMaps = iroadHardResetFleetGpsMaps;

function iroadBindFleetGpsRefresh() {
  var meta = window.iroadFleetGpsState.meta || {};
  var btn = document.querySelector(".refresh-ops-btn");
  if (!btn || !meta.refreshUrl || btn.dataset.fleetGpsBound === "1") return;
  btn.dataset.fleetGpsBound = "1";

  btn.addEventListener("click", function () {
    btn.disabled = true;
    fetch(meta.refreshUrl, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("refresh failed");
        return res.json();
      })
      .then(function (payload) {
        iroadApplyFleetGpsData(payload);
      })
      .catch(function () {})
      .finally(function () {
        btn.disabled = false;
      });
  });
}

function iroadTryBootFleetGpsMaps() {
  if (!iroadFleetGpsHubVisible()) return;

  var data =
    window.iroadFleetGpsState.data ||
    iroadParseJsonNode("fleet-gps-data", {
      default_center: IROAD_FLEET_GPS_DEFAULT,
      live_markers: [],
      featured_track: null,
    });

  if (!window.iroadFleetGpsState.meta) {
    window.iroadFleetGpsState.meta = iroadParseJsonNode("fleet-gps-meta", {});
  }

  iroadApplyFleetGpsData(data);
  iroadBindFleetGpsRefresh();
  window.iroadFleetGpsState.booted = true;
}
window.iroadTryBootFleetGpsMaps = iroadTryBootFleetGpsMaps;

window.iroadBootFleetGpsMaps = function iroadBootFleetGpsMaps() {
  window.iroadFleetGpsState.data = iroadParseJsonNode("fleet-gps-data", {
    default_center: IROAD_FLEET_GPS_DEFAULT,
    live_markers: [],
    featured_track: null,
  });
  window.iroadFleetGpsState.meta = iroadParseJsonNode("fleet-gps-meta", {});
  iroadUpdateDetailSidebar(window.iroadFleetGpsState.data.featured_track);
  if (iroadFleetGpsHubVisible()) {
    iroadScheduleFleetGpsBoot();
  }
};

window.iroadInitFleetGpsMaps = window.iroadBootFleetGpsMaps;

document.addEventListener("DOMContentLoaded", function () {
  if (
    !window.iroadFleetGpsState.meta &&
    document.getElementById("fleet-gps-meta")
  ) {
    window.iroadFleetGpsState.meta = iroadParseJsonNode("fleet-gps-meta", {});
  }
  window.iroadBootFleetGpsMaps();
});
