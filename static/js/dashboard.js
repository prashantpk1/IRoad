/* ============================================
   iRoad Admin Dashboard — Dashboard Page Scripts
   ============================================ */

document.addEventListener("DOMContentLoaded", function () {
  initCountUp();
  initSparklines();
  initDashboardCharts();
  initTableSearch();
  initFilterChips();
  initViewToggle();
});

/* ── Count-Up Animation ── */
function initCountUp() {
  document.querySelectorAll(".count-up").forEach(function (el) {
    var target = el.getAttribute("data-target");
    if (!target) return;
    var isFloat = target.indexOf(".") !== -1;
    var hasPercent = target.indexOf("%") !== -1;
    var prefix = "";
    if (target.indexOf("SAR ") === 0) prefix = "SAR ";
    else if (target.charAt(0) === "$" || target.charAt(0) === "€") prefix = target.charAt(0);
    var suffix = hasPercent ? "%" : "";
    var numStr = target.replace(/[SAR$€%,M\s]/g, "");
    var hasSuffix = target.indexOf("M") !== -1 ? "M" : "";
    var end = parseFloat(numStr);
    var duration = 1200;
    var start = performance.now();

    function tick(now) {
      var elapsed = now - start;
      var progress = Math.min(elapsed / duration, 1);
      var ease = 1 - Math.pow(1 - progress, 3);
      var current = ease * end;
      if (isFloat) {
        el.textContent = prefix + current.toFixed(1) + hasSuffix + suffix;
      } else {
        el.textContent = prefix + Math.floor(current).toLocaleString() + hasSuffix + suffix;
      }
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = target;
    }
    requestAnimationFrame(tick);
  });
}

/* ── Sparkline Charts ── */
function initSparklines() {
  document.querySelectorAll(".kpi-sparkline").forEach(function (canvas) {
    var ctx = canvas.getContext("2d");
    var raw = canvas.getAttribute("data-values");
    var data = [];
    try { data = JSON.parse(raw || "[]"); } catch (e) { return; }
    if (!data.length) return;

    var dpr = window.devicePixelRatio || 1;
    var w = canvas.offsetWidth;
    var h = canvas.offsetHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    var max = Math.max.apply(null, data);
    var min = Math.min.apply(null, data);
    var range = max - min || 1;
    var step = w / (data.length - 1);
    var color = canvas.getAttribute("data-color") || "#5051f9";

    ctx.beginPath();
    for (var i = 0; i < data.length; i++) {
      var x = i * step;
      var y = h - ((data[i] - min) / range) * (h * 0.8) - h * 0.1;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    var lastX = (data.length - 1) * step;
    var lastY = h - ((data[data.length - 1] - min) / range) * (h * 0.8) - h * 0.1;
    ctx.beginPath();
    ctx.moveTo(lastX, lastY);
    for (var j = data.length - 1; j >= 0; j--) {
      var xj = j * step;
      var yj = h - ((data[j] - min) / range) * (h * 0.8) - h * 0.1;
      ctx.lineTo(xj, yj);
    }
    ctx.lineTo(0, h);
    ctx.lineTo(lastX, h);
    ctx.closePath();
    var grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, color + "30");
    grad.addColorStop(1, color + "05");
    ctx.fillStyle = grad;
    ctx.fill();
  });
}

/* ── Chart.js Instances ── */
var dbCharts = {};

function initDashboardCharts() {
  if (typeof Chart === "undefined") return;
  Chart.defaults.font.family = "'Inter', sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.color = "#64748b";

  buildLoginHeatmapChart();
  buildRoleDistributionChart();
}

function buildLoginHeatmapChart() {
  const grid = document.getElementById("loginHeatmapGrid");
  if (!grid) return;
  
  grid.innerHTML = "";
  const dayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const colors = ["#f1f5f9", "#cbd5e1", "#818cf8", "#6366f1", "#4338ca"];

  // Prefer server-provided real data when available.
  const heatmapRaw = document.getElementById("heatmap-data");
  let heatmapData = null;
  if (heatmapRaw) {
    try {
      heatmapData = JSON.parse(heatmapRaw.textContent || "[]");
    } catch (e) {
      heatmapData = null;
    }
  }

  // Fallback for pages that do not provide real data.
  if (!Array.isArray(heatmapData) || heatmapData.length !== 7) {
    heatmapData = [];
    for (let d = 0; d < 7; d++) {
      const dayArr = [];
      for (let h = 0; h < 24; h++) {
        let activity = Math.floor(Math.random() * 20);
        if (d < 5 && h >= 8 && h <= 18) activity += Math.floor(Math.random() * 80);
        else if (h >= 10 && h <= 22) activity += Math.floor(Math.random() * 40);
        dayArr.push(activity);
      }
      heatmapData.push(dayArr);
    }
  }

  const nonZeroValues = heatmapData.flat().filter((v) => Number(v) > 0).sort((a, b) => a - b);
  const pickQuantile = (arr, q) => {
    if (!arr.length) return 0;
    const idx = Math.floor((arr.length - 1) * q);
    return arr[idx];
  };
  const q1 = pickQuantile(nonZeroValues, 0.25);
  const q2 = pickQuantile(nonZeroValues, 0.5);
  const q3 = pickQuantile(nonZeroValues, 0.75);
  const q4 = pickQuantile(nonZeroValues, 0.95);
  const getIntensity = (count) => {
    if (count <= 0 || !nonZeroValues.length) return 0;
    if (count <= q1) return 1;
    if (count <= q2) return 2;
    if (count <= q3) return 3;
    if (count <= q4) return 4;
    return 4;
  };

  // Build Monday..Sunday date labels for tooltip display.
  const now = new Date();
  const monday = new Date(now);
  const weekdayFromMonday = (now.getDay() + 6) % 7; // Mon=0...Sun=6
  monday.setDate(now.getDate() - weekdayFromMonday);
  monday.setHours(0, 0, 0, 0);
  const dayDates = Array.from({ length: 7 }, (_, idx) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + idx);
    return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
  });
  
  // Create 7 rows x 24 columns
  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";

      const activity = Number(heatmapData[d]?.[h] || 0);
      const intensity = getIntensity(activity);
      cell.style.backgroundColor = colors[intensity];

      const hourFmt = h.toString().padStart(2, "0") + ":00";
      cell.setAttribute(
        "data-tooltip",
        `${dayLabels[d]}, ${dayDates[d]} ${hourFmt} - ${activity} login(s)`
      );
      grid.appendChild(cell);
    }
  }
}

function buildRoleDistributionChart() {
  var ctx = document.getElementById("roleDistributionChart");
  if (!ctx) return;
  dbCharts.donut = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Super Admins", "Sales", "Support Actions", "Operations"],
      datasets: [{
        data: [15, 62, 55, 24],
        backgroundColor: ["#5051f9", "#10b981", "#f59e0b", "#8b5cf6"],
        borderWidth: 3,
        borderColor: "#ffffff",
        hoverOffset: 4,
        hoverBorderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: "75%",
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#1e293b",
          padding: 12,
          cornerRadius: 8,
          bodyFont: { size: 12 },
          titleFont: { weight: "600" },
          callbacks: {
            label: function(c) {
              var total = c.dataset.data.reduce(function(a, b) { return a + b; }, 0);
              var pct = ((c.raw / total) * 100).toFixed(1);
              return " " + c.label + ": " + c.raw + " (" + pct + "%)";
            }
          }
        }
      }
    }
  });
}

/* ── Table Search ── */
function initTableSearch() {
  var input = document.getElementById("dbTableSearch");
  if (!input) return;
  input.addEventListener("input", function () {
    var q = input.value.toLowerCase();
    document.querySelectorAll(".db-table tbody tr").forEach(function (row) {
      row.style.display = row.textContent.toLowerCase().indexOf(q) !== -1 ? "" : "none";
    });
  });
}

/* ── Filter Chips ── */
function initFilterChips() {
  document.querySelectorAll(".filter-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      chip.parentElement.querySelectorAll(".filter-chip").forEach(function (c) { c.classList.remove("active"); });
      chip.classList.add("active");
      var filter = chip.getAttribute("data-filter");
      document.querySelectorAll(".db-table tbody tr").forEach(function (row) {
        if (filter === "all") { row.style.display = ""; return; }
        row.style.display = row.getAttribute("data-status") === filter ? "" : "none";
      });
    });
  });
}

/* ── View Toggle ── */
function initViewToggle() {
  var btns = document.querySelectorAll(".view-toggle .vt-btn");
  btns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      btns.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var view = btn.getAttribute("data-view");
      document.querySelectorAll("[data-section]").forEach(function (sec) {
        var sections = sec.getAttribute("data-section").split(",");
        if (view === "all") { sec.style.display = ""; return; }
        sec.style.display = sections.indexOf(view) !== -1 ? "" : "none";
      });
    });
  });
}
