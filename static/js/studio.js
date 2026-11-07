/* Batu Studio helpers: repeatable rows, photo preview, confirmations, unsaved-change guard,
   and live progress for translation and publishing. Everything works without it, more plainly. */
(function () {
  "use strict";

  // Repeatable rows: "+ Add" clones the <template>, renumbering __i__.
  document.querySelectorAll("[data-rows]").forEach(function (box) {
    var count = box.querySelector("[data-count]"), list = box.querySelector(".rowlist"), tpl = box.querySelector("template");
    var btn = box.querySelector("[data-add-row]");
    if (!btn || !tpl) return;
    btn.addEventListener("click", function () {
      var i = parseInt(count.value, 10) || 0;
      var html = tpl.innerHTML.split("__i__").join(String(i));
      var holder = document.createElement("div");
      holder.innerHTML = html;
      var row = holder.firstElementChild;
      list.appendChild(row);
      count.value = i + 1;
      var first = row.querySelector("input:not([type=checkbox]),textarea,select");
      if (first) first.focus();
      markDirty();
    });
    box.addEventListener("change", function (e) {
      if (e.target.matches("[data-del]")) e.target.closest("[data-row]").classList.toggle("removing", e.target.checked);
    });
  });

  // Photo picker preview.
  document.querySelectorAll("[data-imgpick]").forEach(function (sel) {
    var img = sel.parentElement.querySelector("[data-preview]");
    sel.addEventListener("change", function () {
      if (sel.value) { img.src = "/media/" + sel.value + "-800.jpg"; img.hidden = false; } else img.hidden = true;
    });
  });

  // Confirm before destructive actions.
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!window.confirm(f.dataset.confirm)) e.preventDefault(); });
  });

  // Warn before leaving a form with unsaved changes.
  var dirty = false;
  function markDirty() { dirty = true; }
  document.querySelectorAll("form[data-guard]").forEach(function (f) {
    f.addEventListener("input", markDirty);
    f.addEventListener("change", markDirty);
    f.addEventListener("submit", function () { dirty = false; });
  });
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  // Ctrl/Cmd+S saves the form on the page.
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      var f = document.querySelector("form[data-guard]");
      if (f) { e.preventDefault(); dirty = false; f.requestSubmit ? f.requestSubmit() : f.submit(); }
    }
  });

  // Live progress.
  function poll(url, box, done) {
    var log = box.querySelector(".log");
    var t = setInterval(function () {
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (s) {
        if (log) { log.hidden = false; log.textContent = (s.log || []).join("\n") || "Starting…"; }
        if (!s.running) { clearInterval(t); if (done) done(s); }
      }).catch(function () { clearInterval(t); });
    }, 1500);
  }
  var tr = document.querySelector("[data-trstatus]");
  if (tr && tr.querySelector("button[disabled]")) poll("/admin/translations/status", tr, function () { location.reload(); });
})();
