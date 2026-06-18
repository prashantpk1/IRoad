/* Text inputs that must not contain numeric characters (e.g. cargo UOM). */
(function (window, document) {
  "use strict";

  var EXPLICIT_SELECTOR =
    "input.eal-no-digits, textarea.eal-no-digits, input[data-no-digits], textarea[data-no-digits]";

  var INPUT_TYPES = { text: 1, search: 1, tel: 1, "": 1 };

  var FIELD_NAME_PATTERNS = [/cargo_unit(?:_\d+)?$/];

  var DIGIT_RE = /\d/g;

  function sanitizeNoDigits(value) {
    return String(value || "").replace(DIGIT_RE, "");
  }

  function isAllowedText(value) {
    return !DIGIT_RE.test(String(value || ""));
  }

  function fieldNameMatches(name, id) {
    var normalized = String(name || id || "").toLowerCase();
    if (!normalized) return false;
    for (var i = 0; i < FIELD_NAME_PATTERNS.length; i++) {
      if (FIELD_NAME_PATTERNS[i].test(normalized)) return true;
    }
    return false;
  }

  function isNoDigitsInput(input) {
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
    return fieldNameMatches(input.name, input.id);
  }

  function decorateNoDigitsInput(input) {
    if (!input || input.readOnly || input.disabled) return;
    input.classList.add("eal-no-digits");
    input.setAttribute("data-no-digits", "1");
    input.setAttribute("autocomplete", input.getAttribute("autocomplete") || "off");
    var sanitized = sanitizeNoDigits(input.value);
    if (input.value !== sanitized) input.value = sanitized;
  }

  function discoverNoDigitsInputs(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var found = [];
    scope.querySelectorAll("input, textarea").forEach(function (input) {
      if (isNoDigitsInput(input)) found.push(input);
    });
    return found;
  }

  function initNoDigitsInputs(root) {
    discoverNoDigitsInputs(root).forEach(decorateNoDigitsInput);
    if (root && root.querySelectorAll) {
      root.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateNoDigitsInput);
    } else {
      document.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateNoDigitsInput);
    }
  }

  function boot() {
    initNoDigitsInputs(document);

    document.addEventListener(
      "beforeinput",
      function (event) {
        var input = event.target;
        if (!isNoDigitsInput(input)) return;
        decorateNoDigitsInput(input);
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
        if (!isNoDigitsInput(input)) return;
        decorateNoDigitsInput(input);
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
        if (!isNoDigitsInput(input)) return;
        var sanitized = sanitizeNoDigits(input.value);
        if (input.value !== sanitized) input.value = sanitized;
      },
      true
    );

    document.addEventListener(
      "paste",
      function (event) {
        var input = event.target;
        if (!isNoDigitsInput(input)) return;
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
        var sanitized = sanitizeNoDigits(merged);
        input.value = sanitized;
        var caret =
          (start == null ? current.length : start) +
          sanitizeNoDigits(pasted).length;
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
        if (!isNoDigitsInput(input)) return;
        var sanitized = sanitizeNoDigits(input.value);
        if (input.value !== sanitized) input.value = sanitized;
      },
      true
    );

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        discoverNoDigitsInputs(form).forEach(function (input) {
          input.value = sanitizeNoDigits(input.value);
        });
      },
      true
    );

    if (window.MutationObserver) {
      var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          mutation.addedNodes.forEach(function (node) {
            if (!node || node.nodeType !== 1) return;
            initNoDigitsInputs(node);
          });
        });
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  window.iroadNoDigitsInputs = {
    init: initNoDigitsInputs,
    sanitize: sanitizeNoDigits,
    isNoDigitsInput: isNoDigitsInput,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
