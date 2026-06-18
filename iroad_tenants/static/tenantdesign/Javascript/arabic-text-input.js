/* Arabic-only text inputs — document-level blocking for all Arabic fields. */
(function (window, document) {
  "use strict";

  var EXPLICIT_SELECTOR =
    "input.eal-arabic, textarea.eal-arabic, input[data-arabic-only], textarea[data-arabic-only], input.arabic-input, textarea.arabic-input";

  var INPUT_TYPES = { text: 1, search: 1, tel: 1, url: 1, "": 1 };
  var SKIP_FIELD_NAMES = { content_ar: 1 };

  var DISALLOWED_RE =
    /[^\s\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/g;

  var ARABIC_LABEL_RE = /(arabic|عربي|العربية)/i;

  function sanitizeArabicText(value) {
    return String(value || "").replace(DISALLOWED_RE, "");
  }

  function isAllowedText(value) {
    return sanitizeArabicText(value) === String(value || "");
  }

  function fieldNameMatches(name, id) {
    var normalized = String(name || id || "").toLowerCase();
    if (!normalized || SKIP_FIELD_NAMES[normalized]) return false;
    if (normalized.indexOf("arabic") >= 0) return true;
    return /_ar$/.test(normalized);
  }

  function labelMatches(input) {
    var labels = input.labels || [];
    for (var i = 0; i < labels.length; i++) {
      if (ARABIC_LABEL_RE.test(labels[i].textContent || "")) return true;
    }
    var labelledBy = input.getAttribute("aria-labelledby");
    if (labelledBy) {
      var labelNode = document.getElementById(labelledBy);
      if (labelNode && ARABIC_LABEL_RE.test(labelNode.textContent || "")) {
        return true;
      }
    }
    return false;
  }

  function isArabicTextInput(input) {
    if (!input) return false;
    if (
      !(input instanceof HTMLInputElement) &&
      !(input instanceof HTMLTextAreaElement)
    ) {
      return false;
    }
    if (input.readOnly || input.disabled) return false;
    if (input.closest(".ck-editor, .django-ckeditor, .tox-tinymce")) {
      return false;
    }
    if (input.matches(EXPLICIT_SELECTOR)) return true;
    if (input.tagName === "TEXTAREA") {
      return fieldNameMatches(input.name, input.id) || labelMatches(input);
    }
    var type = (input.type || "text").toLowerCase();
    if (!INPUT_TYPES[type]) return false;
    return fieldNameMatches(input.name, input.id) || labelMatches(input);
  }

  function decorateArabicInput(input) {
    if (!input || input.readOnly || input.disabled) return;
    input.classList.add("eal-arabic");
    input.setAttribute("data-arabic-only", "1");
    if (!input.getAttribute("dir")) input.setAttribute("dir", "rtl");
    if (!input.getAttribute("lang")) input.setAttribute("lang", "ar");
    input.setAttribute("inputmode", "text");
    input.setAttribute("autocomplete", input.getAttribute("autocomplete") || "off");
    var sanitized = sanitizeArabicText(input.value);
    if (input.value !== sanitized) input.value = sanitized;
  }

  function discoverArabicTextInputs(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var found = [];
    scope.querySelectorAll("input, textarea").forEach(function (input) {
      if (isArabicTextInput(input)) found.push(input);
    });
    return found;
  }

  function initArabicTextInputs(root) {
    discoverArabicTextInputs(root).forEach(decorateArabicInput);
    if (root && root.querySelectorAll) {
      root.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateArabicInput);
    } else {
      document.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateArabicInput);
    }
  }

  function boot() {
    initArabicTextInputs(document);

    document.addEventListener(
      "beforeinput",
      function (event) {
        var input = event.target;
        if (!isArabicTextInput(input)) return;
        decorateArabicInput(input);
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
        if (!isArabicTextInput(input)) return;
        decorateArabicInput(input);
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
        if (!isArabicTextInput(input)) return;
        var sanitized = sanitizeArabicText(input.value);
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
        if (!isArabicTextInput(input)) return;
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
        var sanitized = sanitizeArabicText(merged);
        input.value = sanitized;
        var caret =
          (start == null ? current.length : start) +
          sanitizeArabicText(pasted).length;
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
        if (!isArabicTextInput(input)) return;
        var sanitized = sanitizeArabicText(input.value);
        if (input.value !== sanitized) input.value = sanitized;
      },
      true
    );

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        discoverArabicTextInputs(form).forEach(function (input) {
          input.value = sanitizeArabicText(input.value);
        });
      },
      true
    );

    if (window.MutationObserver) {
      var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          mutation.addedNodes.forEach(function (node) {
            if (!node || node.nodeType !== 1) return;
            initArabicTextInputs(node);
          });
        });
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  window.iroadArabicTextInputs = {
    init: initArabicTextInputs,
    sanitize: sanitizeArabicText,
    isArabicTextInput: isArabicTextInput,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
