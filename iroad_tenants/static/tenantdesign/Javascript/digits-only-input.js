/* Digits-only text inputs — document-level blocking for numeric registration fields. */
(function (window, document) {
  "use strict";

  var EXPLICIT_SELECTOR =
    "input.eal-digits, input[data-digits-only], textarea.eal-digits, textarea[data-digits-only]";

  var INPUT_TYPES = { text: 1, search: 1, tel: 1, number: 1, "": 1 };

  var FIELD_NAME_PATTERNS = [
    /commercial_registration_no$/,
    /tax_registration_no$/,
  ];

  var DIGITS_LABEL_RE = /(numbers only|digits only|أرقام فقط)/i;

  var DISALLOWED_RE = /[^\d]/g;

  function sanitizeDigitsOnly(value) {
    return String(value || "").replace(DISALLOWED_RE, "");
  }

  function isAllowedText(value) {
    return sanitizeDigitsOnly(value) === String(value || "");
  }

  function fieldNameMatches(name, id) {
    var normalized = String(name || id || "").toLowerCase();
    if (!normalized) return false;
    for (var i = 0; i < FIELD_NAME_PATTERNS.length; i++) {
      if (FIELD_NAME_PATTERNS[i].test(normalized)) return true;
    }
    return false;
  }

  function hintMatches(input) {
    var field = input.closest(".field");
    if (!field) return false;
    var hint = field.querySelector(".field-hint");
    if (hint && DIGITS_LABEL_RE.test(hint.textContent || "")) return true;
    return false;
  }

  function labelMatches(input) {
    var labels = input.labels || [];
    for (var i = 0; i < labels.length; i++) {
      if (DIGITS_LABEL_RE.test(labels[i].textContent || "")) return true;
    }
    return false;
  }

  function isDigitsOnlyInput(input) {
    if (!input) return false;
    if (
      !(input instanceof HTMLInputElement) &&
      !(input instanceof HTMLTextAreaElement)
    ) {
      return false;
    }
    if (input.readOnly || input.disabled) return false;
    if (input.matches(EXPLICIT_SELECTOR)) return true;
    var type = (input.type || "text").toLowerCase();
    if (!INPUT_TYPES[type]) return false;
    return (
      fieldNameMatches(input.name, input.id) ||
      hintMatches(input) ||
      labelMatches(input)
    );
  }

  function decorateDigitsInput(input) {
    if (!input || input.readOnly || input.disabled) return;
    input.classList.add("eal-digits");
    input.setAttribute("data-digits-only", "1");
    input.setAttribute("inputmode", "numeric");
    input.setAttribute("pattern", "[0-9]*");
    input.setAttribute("autocomplete", input.getAttribute("autocomplete") || "off");
    var sanitized = sanitizeDigitsOnly(input.value);
    if (input.value !== sanitized) input.value = sanitized;
  }

  function discoverDigitsOnlyInputs(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var found = [];
    scope.querySelectorAll("input, textarea").forEach(function (input) {
      if (isDigitsOnlyInput(input)) found.push(input);
    });
    return found;
  }

  function initDigitsOnlyInputs(root) {
    discoverDigitsOnlyInputs(root).forEach(decorateDigitsInput);
    if (root && root.querySelectorAll) {
      root.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateDigitsInput);
    } else {
      document.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateDigitsInput);
    }
  }

  function boot() {
    initDigitsOnlyInputs(document);

    document.addEventListener(
      "beforeinput",
      function (event) {
        var input = event.target;
        if (!isDigitsOnlyInput(input)) return;
        decorateDigitsInput(input);
        if (event.isComposing) return;
        var data = event.data;
        if (data == null || data === "") return;
        if (!isAllowedText(data)) event.preventDefault();
      },
      true
    );

    document.addEventListener(
      "keydown",
      function (event) {
        var input = event.target;
        if (!isDigitsOnlyInput(input)) return;
        decorateDigitsInput(input);
        if (event.isComposing || event.key === "Dead") return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (
          event.key === "Backspace" ||
          event.key === "Delete" ||
          event.key === "Tab" ||
          event.key === "Enter" ||
          event.key === "Escape" ||
          event.key.startsWith("Arrow") ||
          event.key === "Home" ||
          event.key === "End"
        ) {
          return;
        }
        if (event.key.length === 1 && !isAllowedText(event.key)) {
          event.preventDefault();
        }
      },
      true
    );

    document.addEventListener(
      "input",
      function (event) {
        var input = event.target;
        if (!isDigitsOnlyInput(input)) return;
        var sanitized = sanitizeDigitsOnly(input.value);
        if (input.value !== sanitized) {
          input.value = sanitized;
        }
      },
      true
    );

    document.addEventListener(
      "paste",
      function (event) {
        var input = event.target;
        if (!isDigitsOnlyInput(input)) return;
        event.preventDefault();
        var pasted = "";
        if (event.clipboardData) {
          pasted = event.clipboardData.getData("text");
        } else if (window.clipboardData) {
          pasted = window.clipboardData.getData("Text");
        }
        var start = input.selectionStart;
        var end = input.selectionEnd;
        var current = input.value || "";
        var merged =
          start == null || end == null
            ? current + pasted
            : current.slice(0, start) + pasted + current.slice(end);
        var sanitized = sanitizeDigitsOnly(merged);
        input.value = sanitized;
        var caret =
          (start == null ? current.length : start) +
          sanitizeDigitsOnly(pasted).length;
        if (typeof input.setSelectionRange === "function") {
          input.setSelectionRange(caret, caret);
        }
        input.dispatchEvent(new Event("input", { bubbles: true }));
      },
      true
    );

    document.addEventListener(
      "compositionend",
      function (event) {
        var input = event.target;
        if (!isDigitsOnlyInput(input)) return;
        var sanitized = sanitizeDigitsOnly(input.value);
        if (input.value !== sanitized) input.value = sanitized;
      },
      true
    );

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        discoverDigitsOnlyInputs(form).forEach(function (input) {
          input.value = sanitizeDigitsOnly(input.value);
        });
      },
      true
    );

    if (window.MutationObserver) {
      var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          mutation.addedNodes.forEach(function (node) {
            if (!node || node.nodeType !== 1) return;
            initDigitsOnlyInputs(node);
          });
        });
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  window.iroadDigitsOnlyInputs = {
    init: initDigitsOnlyInputs,
    sanitize: sanitizeDigitsOnly,
    isDigitsOnlyInput: isDigitsOnlyInput,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
