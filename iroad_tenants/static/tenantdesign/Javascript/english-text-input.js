/* English-only text inputs — document-level blocking for all English name/label fields. */
(function (window, document) {
  "use strict";

  var EXPLICIT_SELECTOR =
    "input.eal-english, textarea.eal-english, input[data-english-only], textarea[data-english-only], input.english-input, textarea.english-input";

  var INPUT_TYPES = { text: 1, search: 1, tel: 1, url: 1, "": 1 };

  /* Keep in sync with config/text_validators.py _ENGLISH_TEXT_FIELD_EXCLUSIONS */
  var SKIP_FIELD_NAMES = {
    body_en: 1,
    body_ar: 1,
    subject_en: 1,
    subject_ar: 1,
    content_en: 1,
    content_ar: 1,
    meta_description_en: 1,
    meta_description_ar: 1,
    message_body: 1,
    description: 1,
    description_en: 1,
    description_ar: 1,
  };

  /* Keep in sync with config/text_validators.py _ENGLISH_TEXT_FIELD_INCLUSIONS */
  var INCLUDE_FIELD_NAMES = { price_list_name: 1 };

  /* Basic Latin letters and common separators — mirrors ENGLISH_TEXT_RE in Python. */
  var DISALLOWED_RE = /[^A-Za-z\s\-'.]/g;

  var ENGLISH_LABEL_RE = /(english|إنجليز)/i;

  function sanitizeEnglishText(value) {
    return String(value || "").replace(DISALLOWED_RE, "");
  }

  function isAllowedText(value) {
    return sanitizeEnglishText(value) === String(value || "");
  }

  function fieldNameMatches(name, id) {
    var normalized = String(name || id || "").toLowerCase();
    if (!normalized || SKIP_FIELD_NAMES[normalized]) return false;
    if (INCLUDE_FIELD_NAMES[normalized]) return true;
    if (normalized.indexOf("english") >= 0) return true;
    return /_en$/.test(normalized);
  }

  function labelMatches(input) {
    var labels = input.labels || [];
    for (var i = 0; i < labels.length; i++) {
      if (ENGLISH_LABEL_RE.test(labels[i].textContent || "")) return true;
    }
    var labelledBy = input.getAttribute("aria-labelledby");
    if (labelledBy) {
      var labelNode = document.getElementById(labelledBy);
      if (labelNode && ENGLISH_LABEL_RE.test(labelNode.textContent || "")) {
        return true;
      }
    }
    return false;
  }

  function isEnglishTextInput(input) {
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

  function decorateEnglishInput(input) {
    if (!input || input.readOnly || input.disabled) return;
    input.classList.add("eal-english");
    input.setAttribute("data-english-only", "1");
    if (!input.getAttribute("lang")) input.setAttribute("lang", "en");
    input.setAttribute("inputmode", "text");
    input.setAttribute("autocomplete", input.getAttribute("autocomplete") || "off");
    var sanitized = sanitizeEnglishText(input.value);
    if (input.value !== sanitized) input.value = sanitized;
  }

  function discoverEnglishTextInputs(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var found = [];
    scope.querySelectorAll("input, textarea").forEach(function (input) {
      if (isEnglishTextInput(input)) found.push(input);
    });
    return found;
  }

  function initEnglishTextInputs(root) {
    discoverEnglishTextInputs(root).forEach(decorateEnglishInput);
    if (root && root.querySelectorAll) {
      root.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateEnglishInput);
    } else {
      document.querySelectorAll(EXPLICIT_SELECTOR).forEach(decorateEnglishInput);
    }
  }

  function boot() {
    initEnglishTextInputs(document);

    document.addEventListener(
      "beforeinput",
      function (event) {
        var input = event.target;
        if (!isEnglishTextInput(input)) return;
        decorateEnglishInput(input);
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
        if (!isEnglishTextInput(input)) return;
        decorateEnglishInput(input);
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
        if (!isEnglishTextInput(input)) return;
        var sanitized = sanitizeEnglishText(input.value);
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
        if (!isEnglishTextInput(input)) return;
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
        var sanitized = sanitizeEnglishText(merged);
        input.value = sanitized;
        var caret =
          (start == null ? current.length : start) +
          sanitizeEnglishText(pasted).length;
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
        if (!isEnglishTextInput(input)) return;
        var sanitized = sanitizeEnglishText(input.value);
        if (input.value !== sanitized) input.value = sanitized;
      },
      true
    );

    document.addEventListener(
      "submit",
      function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        discoverEnglishTextInputs(form).forEach(function (input) {
          input.value = sanitizeEnglishText(input.value);
        });
      },
      true
    );

    if (window.MutationObserver) {
      var observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          mutation.addedNodes.forEach(function (node) {
            if (!node || node.nodeType !== 1) return;
            initEnglishTextInputs(node);
          });
        });
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  window.iroadEnglishTextInputs = {
    init: initEnglishTextInputs,
    sanitize: sanitizeEnglishText,
    isEnglishTextInput: isEnglishTextInput,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
