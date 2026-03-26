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
  });
});

/* ============================================
   Ensure Unified Sidebar (load from index.html)
   ============================================ */
function ensureUnifiedSidebar() {
  // Navigation sidebar is now hardcoded directly in the HTML files instead of dynamically loaded
  return Promise.resolve();
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
        !sidebar.matches(":hover")
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
   Working Days Checkbox Logic
   ============================================ */
function toggleAllWorkingDays(selectAll) {
  const checkboxes = document.querySelectorAll(".working-day-checkbox");
  checkboxes.forEach(function (checkbox) {
    checkbox.checked = selectAll;
  });
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
