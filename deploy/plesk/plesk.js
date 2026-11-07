/* Batu portal on the Plesk host: tracking and payment pages read their data from the PHP services.
   The pages themselves are static; this fills in the request, bill, checkout or receipt.
   Strings come translated in window.BATU_T (written by tools/build.py for each language). */
(function () {
  "use strict";
  var T = window.BATU_T || {}, B = window.BATU || {};
  var t = function (s) { return (T[s] || s); };
  var base = (window.BATU_BASE || "/") + (B.lang && B.lang !== "en" ? B.lang + "/" : "");
  var api = function (p) { return (window.BATU_BASE || "/") + "api/" + p; };
  var q = new URLSearchParams(location.search);
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var money = function (v) { return Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 }) + " " + t("birr"); };
  var check = '<svg class="check" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="29"/><path d="M19 33l9 9 17-19"/></svg>';
  var page = location.pathname.replace(window.BATU_BASE || "/", "/").replace(/^\/(om|am)\//, "/");
  var slot = document.querySelector("main .section .min0");
  var note = function (cls, html) { return '<p class="note ' + cls + '">' + html + "</p>"; };
  var get = function (url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; });
    });
  };
  var post = function (url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; }); });
  };
  var trnote = function (n) {  // "Payment received, receipt RCT-1234" -> translated prefix + code
    var m = /^(Payment received, receipt) (\S+)$/.exec(n || "");
    return m ? t("Payment received") + " · " + m[2] : t(n);
  };
  var tagClass = function (s) { return ["resolved", "closed", "ready", "scheduled", "paid"].indexOf(s) >= 0 ? "ok" : (s === "awaiting_payment" ? "warn" : "lake"); };
  var loading = function () { if (slot) slot.insertAdjacentHTML("beforeend", '<p class="muted plesk-loading">' + esc(t("Looking it up…")) + "</p>"); };
  var done = function () { var l = document.querySelector(".plesk-loading"); if (l) l.remove(); };

  /* ---------- tracking ---------- */
  if (page.indexOf("/track/") === 0 && q.get("ref") && slot) {
    var ref = q.get("ref"), input = document.getElementById("ref");
    if (input) input.value = ref;
    loading();
    get(api("request/" + encodeURIComponent(ref))).then(function (r) {
      done();
      if (r._status !== 200) { slot.insertAdjacentHTML("afterbegin", note("red", esc(t("No request has that reference. Check the number and try again.")))); return; }
      var h = "";
      if (q.get("new")) h += '<div class="success" style="margin-bottom:28px">' + check + '<h2 style="font-size:1.6rem">' + esc(t("Sent. We have your request.")) + '</h2><p class="muted">' + esc(t("Keep this reference number to follow your request")) + ':</p><span class="refbox pop">' + esc(r.ref) + "</span></div>";
      h += '<p class="eyebrow">' + esc(t(r.kind.charAt(0).toUpperCase() + r.kind.slice(1))) + ' · <span class="mono">' + esc(r.ref) + "</span></p>";
      h += '<h2 style="margin:6px 0 10px">' + esc(t(r.title)) + "</h2>";
      h += '<p style="margin-bottom:20px"><span class="tag ' + tagClass(r.status) + '" style="font-size:.8rem">' + esc(t(r.status_label)) + "</span></p>";
      if (r.status === "awaiting_payment" && !r.paid) h += '<p style="margin-bottom:20px"><a class="btn btn-accent" href="' + base + "pay/?ref=" + encodeURIComponent(r.ref) + '">' + esc(t("Pay")) + " " + esc(money(r.amount)) + "</a></p>";
      h += '<ol class="timeline">' + r.history.slice().reverse().map(function (x, i) {
        return '<li style="--i:' + i + '"><b>' + esc(trnote(x.note)) + "</b><small>" + esc(x.at.replace("T", " ")) + "</small></li>";
      }).join("") + "</ol>";
      slot.insertAdjacentHTML("afterbegin", h);
    }).catch(function () { done(); slot.insertAdjacentHTML("afterbegin", note("red", esc(t("Sorry, something went wrong. Please try again.")))); });
  }

  /* ---------- payment: bill, checkout, receipt ---------- */
  if (page.indexOf("/pay/") === 0 && slot) {
    var pid = q.get("pid"), rc = q.get("receipt"), pref = q.get("ref");
    if (q.get("failed")) slot.insertAdjacentHTML("afterbegin", note("red", esc(t("The payment did not go through. Nothing was charged. You can try again."))));
    var form = slot.querySelector("form");
    if (pref && !pid && !rc) {
      if (document.getElementById("ref")) document.getElementById("ref").value = pref;
      loading();
      get(api("request/" + encodeURIComponent(pref))).then(function (r) {
        done();
        if (r._status !== 200) { slot.insertAdjacentHTML("beforeend", note("red", esc(t("No bill or request has that reference. Check the number and try again.")))); return; }
        var h = '<div class="card" style="max-width:560px"><p class="eyebrow">' + esc(t("Bill")) + ' · <span class="mono">' + esc(r.ref) + "</span></p><h3>" + esc(t(r.title)) + "</h3>";
        if (r.amount) h += '<b style="font-family:var(--f-display);font-size:2rem" class="num">' + esc(money(r.amount)) + "</b>";
        h += '<p class="muted">' + esc(t("Status")) + ": " + esc(t(r.status_label)) + "</p>";
        if (r.paid) h += note("lake", esc(t("This has already been paid.")) + ' <a href="' + base + "track/?ref=" + encodeURIComponent(r.ref) + '">' + esc(t("See the status")) + "</a>");
        else if (!r.amount) h += note("", esc(t("This request has no fee to pay online.")));
        else if (r.payments !== "demo") h += note("lake", esc(t("Online payment is not switched on yet. Please pay at the Revenue Office and keep your reference number.")));
        else h += '<button class="btn btn-accent" type="button" data-start-pay>' + esc(t("Pay with")) + " " + esc(t("Telebirr (demo)")) + "</button>";
        slot.insertAdjacentHTML("beforeend", h + "</div>");
        var b = slot.querySelector("[data-start-pay]");
        if (b) b.addEventListener("click", function () {
          b.classList.add("is-loading");
          post(api("pay"), { ref: r.ref }).then(function (d) {
            if (d.pid) location.href = base + "pay/?pid=" + encodeURIComponent(d.pid);
            else { b.classList.remove("is-loading"); b.insertAdjacentHTML("afterend", note("red", esc(t(d.error || "Sorry, something went wrong. Please try again.")))); }
          });
        });
      });
    }
    if (pid || rc) {
      if (form) form.hidden = true;
      var head = document.querySelector(".page-head");
      loading();
      get(api("pay?pid=" + encodeURIComponent(pid || rc))).then(function (p) {
        done();
        if (p._status !== 200 || !p.request) { slot.insertAdjacentHTML("afterbegin", note("red", esc(t(p.error || "No bill or request has that reference. Check the number and try again.")))); return; }
        if (pid && p.status !== "paid") {
          slot.insertAdjacentHTML("afterbegin", '<div class="checkout" data-checkout><header><b>telebirr</b><span class="mono" style="font-size:.75rem">' + esc(t("DEMO · no money moves")) + '</span></header><div class="body">'
            + '<span class="muted">' + esc(t("Pay to")) + ": " + esc(t("Batu City Administration")) + "</span><span>" + esc(t(p.request.title)) + '</span><span class="amt num">' + esc(money(p.amount)) + "</span>"
            + '<span class="mono muted" style="font-size:.78rem">' + esc(t("Payment")) + " " + esc(p.id) + " · " + esc(t("Reference")) + " " + esc(p.request.ref) + "</span>"
            + '<button class="btn" style="background:#0B6E4F;color:#fff" data-confirm>' + esc(t("Confirm payment")) + '</button><button class="btn btn-ghost" data-cancel>' + esc(t("Cancel")) + "</button></div></div>");
          var co = slot.querySelector("[data-checkout]");
          co.querySelector("[data-confirm]").addEventListener("click", function (e) {
            e.target.classList.add("is-loading");
            post(api("pay?confirm=1"), { pid: p.id, result: "success" }).then(function (d) {
              location.href = base + "pay/?receipt=" + encodeURIComponent(p.id);
            });
          });
          co.querySelector("[data-cancel]").addEventListener("click", function () {
            post(api("pay?confirm=1"), { pid: p.id, result: "cancel" }).then(function () { location.href = base + "pay/?ref=" + encodeURIComponent(p.request.ref) + "&failed=1"; });
          });
          return;
        }
        // receipt
        if (head) head.querySelector("h1").textContent = t("Thank you. Your payment is confirmed.");
        var h = '<div class="success">' + check + '<p class="eyebrow" style="color:var(--ok)">' + esc(t("Payment received")) + "</p></div>"
          + '<div><span class="eyebrow">' + esc(t("Receipt number")) + '</span><br><span class="refbox pop">' + esc(p.receipt) + "</span></div>"
          + '<table class="t" style="max-width:560px"><tbody><tr><th>' + esc(t("For")) + "</th><td>" + esc(t(p.request.title)) + "</td></tr><tr><th>" + esc(t("Amount")) + '</th><td class="num">' + esc(money(p.amount)) + "</td></tr><tr><th>" + esc(t("Reference")) + '</th><td class="mono">' + esc(p.request.ref) + "</td></tr></tbody></table>";
        if (p.request.kind === "booking") h += '<div class="card" style="max-width:560px"><p class="eyebrow">' + esc(t("Your ticket")) + "</p><p>" + esc(t("Show this code at the jetty")) + ':</p><div id="qr" style="background:#fff;padding:10px;width:max-content"></div><span class="refbox">' + esc(p.request.ref) + "</span></div>";
        h += '<div style="display:flex;gap:10px;flex-wrap:wrap"><a class="btn btn-lake" href="' + base + "track/?ref=" + encodeURIComponent(p.request.ref) + '">' + esc(t("Track this request")) + "</a></div>";
        slot.insertAdjacentHTML("afterbegin", '<div style="display:grid;gap:16px">' + h + "</div>");
        if (p.request.kind === "booking") {
          var s = document.createElement("script");
          s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js";
          s.onload = function () { if (window.QRCode) new window.QRCode(document.getElementById("qr"), { text: p.request.ref, width: 140, height: 140 }); };
          document.head.appendChild(s);
        }
      });
    }
  }
})();
