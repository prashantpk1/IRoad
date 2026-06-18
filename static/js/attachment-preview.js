/* Global attachment file preview modal */
function initAttachmentPreview() {
  var modalEl = document.getElementById("iroadAttachmentPreviewModal");
  if (!modalEl || typeof bootstrap === "undefined") return;

  var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  var titleEl = document.getElementById("iroadAttachmentPreviewTitle");
  var bodyEl = document.getElementById("iroadAttachmentPreviewBody");
  var downloadBtn = document.getElementById("iroadAttachmentPreviewDownload");
  var openBtn = document.getElementById("iroadAttachmentPreviewOpen");
  var activeBlobUrl = "";

  function fileKindFromSource(source) {
    var normalized = (source || "").split("?")[0].split("#")[0];
    var ext = normalized.split(".").pop().toLowerCase();
    if (["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"].indexOf(ext) >= 0) {
      return "image";
    }
    if (ext === "pdf") return "pdf";
    if (["mp4", "webm", "ogg", "mov"].indexOf(ext) >= 0) return "video";
    return "other";
  }

  function fileKind(name, url) {
    var kind = fileKindFromSource(name);
    if (kind !== "other") return kind;
    return fileKindFromSource(url);
  }

  function revokeBlobUrl() {
    if (activeBlobUrl) {
      URL.revokeObjectURL(activeBlobUrl);
      activeBlobUrl = "";
    }
  }

  function clearBody() {
    bodyEl.innerHTML = "";
    revokeBlobUrl();
  }

  function showLoader() {
    bodyEl.innerHTML =
      '<div class="iroad-attachment-preview-loader">' +
      '<div class="spinner-border text-primary" role="status">' +
      '<span class="visually-hidden">Loading preview...</span>' +
      "</div>" +
      "</div>";
  }

  function showFallback(name) {
    bodyEl.innerHTML =
      '<div class="iroad-attachment-preview-fallback">' +
      '<i class="bi bi-file-earmark"></i>' +
      '<p class="mb-1 fw-semibold">' +
      (name || "Attachment") +
      "</p>" +
      '<p class="mb-0">Preview is not available for this file type. Use Open or Download.</p>' +
      "</div>";
  }

  function fetchBlob(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (res) {
      if (!res.ok) {
        throw new Error("Failed to load attachment");
      }
      return res.blob();
    });
  }

  function setBlobPreview(blob, className, tagName, extraAttrs) {
    revokeBlobUrl();
    activeBlobUrl = URL.createObjectURL(blob);
    var node = document.createElement(tagName || "iframe");
    node.src = activeBlobUrl;
    node.className = className;
    if (extraAttrs) {
      Object.keys(extraAttrs).forEach(function (key) {
        node.setAttribute(key, extraAttrs[key]);
      });
    }
    bodyEl.innerHTML = "";
    bodyEl.appendChild(node);
    downloadBtn.href = activeBlobUrl;
  }

  function showImagePreview(url, name) {
    showLoader();
    fetchBlob(url)
      .then(function (blob) {
        revokeBlobUrl();
        activeBlobUrl = URL.createObjectURL(blob);
        var img = document.createElement("img");
        img.src = activeBlobUrl;
        img.alt = name || "Attachment preview";
        img.className = "iroad-attachment-preview-img";
        img.loading = "lazy";
        bodyEl.innerHTML = "";
        bodyEl.appendChild(img);
        downloadBtn.href = activeBlobUrl;
      })
      .catch(function () {
        var img = document.createElement("img");
        img.src = url;
        img.alt = name || "Attachment preview";
        img.className = "iroad-attachment-preview-img";
        img.loading = "lazy";
        img.onerror = function () {
          showFallback(name);
        };
        bodyEl.innerHTML = "";
        bodyEl.appendChild(img);
        downloadBtn.href = url;
      });
  }

  function showPdfPreview(url, name) {
    showLoader();
    fetchBlob(url)
      .then(function (blob) {
        var pdfBlob =
          blob.type === "application/pdf"
            ? blob
            : new Blob([blob], { type: "application/pdf" });
        setBlobPreview(pdfBlob, "iroad-attachment-preview-iframe", "embed", {
          type: "application/pdf",
        });
      })
      .catch(function () {
        showFallback(name);
        downloadBtn.href = url;
      });
  }

  function showVideoPreview(url, name) {
    showLoader();
    fetchBlob(url)
      .then(function (blob) {
        setBlobPreview(blob, "iroad-attachment-preview-video", "video", {
          controls: "controls",
        });
      })
      .catch(function () {
        var video = document.createElement("video");
        video.src = url;
        video.controls = true;
        video.className = "iroad-attachment-preview-video";
        bodyEl.innerHTML = "";
        bodyEl.appendChild(video);
        downloadBtn.href = url;
      });
  }

  function showPreview(url, name) {
    if (!url) return;

    var kind = fileKind(name, url);
    titleEl.textContent = name || "Attachment preview";
    openBtn.href = url;
    downloadBtn.href = url;
    clearBody();

    if (kind === "image") {
      showImagePreview(url, name);
    } else if (kind === "pdf") {
      showPdfPreview(url, name);
    } else if (kind === "video") {
      showVideoPreview(url, name);
    } else {
      showFallback(name);
    }

    modal.show();
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-attachment-preview]");
    if (!link) return;

    event.preventDefault();
    var url = link.getAttribute("data-file-url") || link.getAttribute("href") || "";
    var name = link.getAttribute("data-file-name") || "";
    showPreview(url, name);
  });

  modalEl.addEventListener("hidden.bs.modal", function () {
    clearBody();
    downloadBtn.href = "#";
    openBtn.href = "#";
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAttachmentPreview);
} else {
  initAttachmentPreview();
}
