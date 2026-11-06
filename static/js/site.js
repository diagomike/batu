/* Batu portal: assistant, stepped forms, state animations, kebele finder, map.
   Plain JS. Every feature degrades to a normal page or form without JavaScript. */
(function () {
  "use strict";
  var B = window.BATU || { lang: "en", mode: {} };
  var shot = /[?&]shot=1/.test(location.search);
  var reduce = shot || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  if (shot) document.documentElement.classList.add("shot");

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------- assistant ---------- */
  /* On the static copy (GitHub Pages, Plesk) pages live under BATU_BASE plus a language folder,
     and questions go to the API server in BATU_API. On the live server both are empty. */
  function pageUrl(u) {
    if (!window.BATU_STATIC || !u || u.charAt(0) !== "/") return u;
    var m = u.match(/^([^?#]*)(.*)$/), p = m[1].replace(/^\/|\/$/g, "");
    return (window.BATU_BASE || "/") + (B.lang === "en" ? "" : B.lang + "/") + (p ? p + "/" : "") + m[2];
  }
  function renderAnswer(log, res) {
    var m = el("div", "msg a" + (res.emergency ? " emergency" : ""));
    m.setAttribute("data-label", B.name || "Ask Batu");
    m.appendChild(document.createTextNode(res.answer || res.error || B.error));
    if (res.mode && B.mode[res.mode]) {
      m.appendChild(el("div", "meta", B.mode[res.mode] + (res.model ? " · " + res.model.replace("models/", "") : "")));
    }
    if (res.sources && res.sources.length) {
      var s = el("div", "src");
      s.appendChild(el("b", null, B.sources));
      res.sources.forEach(function (src) {
        var a = el("a", null, "→ " + src.title + (src.sample ? " (" + B.sample + ")" : ""));
        a.href = pageUrl(src.url);
        s.appendChild(a);
      });
      m.appendChild(s);
    }
    log.appendChild(m);
    m.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }

  function ask(q, log) {
    if (!q || !q.trim()) return;
    log.appendChild(el("div", "msg u", q));
    var wait = el("div", "msg a typing");
    wait.setAttribute("aria-label", B.thinking);
    var dots = el("span", "typing-dots");
    dots.innerHTML = "<i></i><i></i><i></i>";
    wait.appendChild(dots);
    log.appendChild(wait);
    wait.scrollIntoView({ block: "nearest" });
    // The last two exchanges go along so follow-ups like "how much is it?" make sense.
    var hist = log._hist || (log._hist = []);
    fetch((window.BATU_API || "").replace(/\/$/, "") + "/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: q, lang: B.lang, history: hist.slice(-2) }) })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        wait.remove(); renderAnswer(log, res);
        if (res.answer && !res.emergency) hist.push({ q: q, a: res.answer.slice(0, 400) });
      })
      .catch(function () { wait.remove(); renderAnswer(log, { answer: B.error }); });
  }

  var fab = document.getElementById("fab"), panel = document.getElementById("askpanel"), scrim = document.getElementById("askscrim");
  if (panel) {
    var close = document.getElementById("askclose"), form = document.getElementById("askform"), input = document.getElementById("askq"), log = document.getElementById("asklog");
    var openPanel = function () {
      panel.hidden = false;
      if (scrim && window.innerWidth <= 980) scrim.hidden = false;
      panel.classList.remove("closing");
      panel.classList.add("opening");
      if (fab) fab.setAttribute("aria-expanded", "true");
      setTimeout(function () { input.focus(); }, 120);
    };
    var closePanel = function () {
      if (panel.hidden) return;
      panel.classList.remove("opening");
      panel.classList.add("closing");
      if (scrim) scrim.hidden = true;
      if (fab) fab.setAttribute("aria-expanded", "false");
      setTimeout(function () { panel.hidden = true; panel.classList.remove("closing"); }, reduce ? 0 : 220);
    };
    if (fab) fab.addEventListener("click", function () { panel.hidden ? openPanel() : closePanel(); });
    document.querySelectorAll("[data-open-ask]").forEach(function (a) {
      a.addEventListener("click", function (e) { e.preventDefault(); openPanel(); });
    });
    close.addEventListener("click", closePanel);
    if (scrim) scrim.addEventListener("click", closePanel);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePanel(); });
    form.addEventListener("submit", function (e) { e.preventDefault(); var q = input.value; input.value = ""; ask(q, log); });
  }

  var chatform = document.getElementById("chatform");
  if (chatform) {
    var chatlog = document.getElementById("chatlog"), chatq = document.getElementById("chatq");
    chatform.addEventListener("submit", function (e) { e.preventDefault(); var q = chatq.value; chatq.value = ""; ask(q, chatlog); });
    document.querySelectorAll("#suggest button").forEach(function (b) {
      b.addEventListener("click", function () { ask(b.dataset.q, chatlog); });
    });
    // The static copy cannot read ?q= on the server, so pick it up here.
    var qs = (location.search.match(/[?&]q=([^&]*)/) || [])[1];
    if (window.BATU_STATIC && qs && !chatq.value) { chatq.value = decodeURIComponent(qs.replace(/\+/g, " ")); window.ASK_AUTO = true; }
    if (window.ASK_AUTO && chatq.value) { var q0 = chatq.value; chatq.value = ""; ask(q0, chatlog); }
  }

  /* ---------- stepped forms ---------- */
  function labelFor(field) {
    var l = field.id && document.querySelector('label[for="' + field.id + '"]');
    return l ? l.textContent.trim() : "";
  }

  function buildReview(form, dl) {
    dl.innerHTML = "";
    var seen = {};
    form.querySelectorAll("input, select, textarea").forEach(function (f) {
      if (f.type === "hidden" || !f.name || seen[f.name]) return;
      var name = "", value = "";
      if (f.type === "radio") {
        var c = form.querySelector('input[name="' + f.name + '"]:checked');
        if (!c) return;
        seen[f.name] = true;
        var lg = f.closest("fieldset") && f.closest("fieldset").querySelector("legend");
        name = lg ? lg.textContent.trim() : f.name;
        var lab = c.closest("label");
        var strong = lab && lab.querySelector("b");
        value = (strong ? strong.textContent : (lab ? lab.textContent : c.value)).trim();
      } else if (f.type === "file") {
        name = labelFor(f); value = f.files && f.files[0] ? f.files[0].name : "";
      } else if (f.tagName === "SELECT") {
        name = labelFor(f); value = f.value ? f.options[f.selectedIndex].text : "";
      } else {
        name = labelFor(f); value = f.value.trim();
      }
      if (!value) return;
      var row = el("div"), dt = el("dt", null, name), dd = el("dd", null, value);
      row.appendChild(dt); row.appendChild(dd); dl.appendChild(row);
    });
  }

  document.querySelectorAll("form[data-stepper]").forEach(function (form) {
    var steps = Array.prototype.slice.call(form.querySelectorAll(".step"));
    if (steps.length < 2) return;
    var i = 0;
    var head = el("div", "stepper-head");
    var meta = el("div", "meta");
    var count = el("span"), title = el("b");
    meta.appendChild(count); meta.appendChild(title);
    var bar = el("div", "track-bar"), fill = el("i");
    bar.appendChild(fill);
    head.appendChild(meta); head.appendChild(bar);
    form.insertBefore(head, form.firstElementChild);

    var nav = el("div", "step-nav");
    var back = el("button", "btn btn-ghost", B.back || "Back"); back.type = "button";
    var next = el("button", "btn btn-lake push", B.next || "Next"); next.type = "button";
    var submit = el("button", "btn btn-accent push", form.dataset.submitLabel || "Send"); submit.type = "submit";
    nav.appendChild(back); nav.appendChild(next); nav.appendChild(submit);
    var after = form.querySelector(".nojs-submit");
    form.insertBefore(nav, after || null);

    function valid(step) {
      var ok = true, first = null;
      step.querySelectorAll("input, select, textarea").forEach(function (f) {
        var field = f.closest(".field");
        if (!f.checkValidity()) {
          ok = false; first = first || f;
          if (field) { field.classList.remove("invalid"); void field.offsetWidth; field.classList.add("invalid"); }
        } else if (field) field.classList.remove("invalid");
      });
      if (first) { first.focus(); first.reportValidity && first.reportValidity(); }
      return ok;
    }

    function show(n, dir) {
      steps.forEach(function (s, k) { s.classList.toggle("current", k === n); s.classList.remove("enter-next", "enter-prev"); });
      var s = steps[n];
      if (dir) { void s.offsetWidth; s.classList.add(dir > 0 ? "enter-next" : "enter-prev"); }
      if (s.hasAttribute("data-review")) buildReview(form, s.querySelector(".review"));
      var lg = s.querySelector("legend");
      count.textContent = (B.step || "Step") + " " + (n + 1) + " " + (B.of || "of") + " " + steps.length;
      title.textContent = lg ? lg.textContent : "";
      fill.style.width = ((n + 1) / steps.length * 100) + "%";
      back.style.visibility = n === 0 ? "hidden" : "visible";
      next.hidden = n === steps.length - 1;
      submit.hidden = n !== steps.length - 1;
      if (dir) {
        var f = s.querySelector("input:not([type=hidden]), select, textarea");
        if (f && f.type !== "radio") setTimeout(function () { f.focus({ preventScroll: true }); }, 60);
        head.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
      }
      i = n;
    }

    next.addEventListener("click", function () { if (valid(steps[i])) show(i + 1, 1); });
    back.addEventListener("click", function () { show(i - 1, -1); });
    form.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && i < steps.length - 1) { e.preventDefault(); next.click(); }
    });
    form.addEventListener("submit", function (e) {
      for (var k = 0; k < steps.length; k++) {
        if (!steps[k].hasAttribute("data-review") && !valid(steps[k])) { e.preventDefault(); show(k, -1); return; }
      }
    });
    show(0, 0);
  });

  /* ---------- loading state on any submit ---------- */
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var f = e.target;
    if (f.id === "askform" || f.id === "chatform" || f.hasAttribute("data-checkout")) return;
    var b = e.submitter || f.querySelector("button[type=submit], button:not([type])");
    if (b) setTimeout(function () { b.classList.add("is-loading"); }, 0);
  });

  /* ---------- checkout: processing -> confirmed -> receipt ---------- */
  var co = document.querySelector("form[data-checkout]");
  if (co) co.addEventListener("submit", function (e) {
    if (co.dataset.done) return;
    e.preventDefault();
    var body = co.closest(".body");
    var p = el("div", "processing");
    p.innerHTML = '<div class="ring"></div>';
    p.appendChild(el("b", null, B.processing));
    body.appendChild(p);
    setTimeout(function () {
      p.innerHTML = '<svg class="check" viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="29"/><path d="M19 33l9 9 17-19"/></svg>';
      p.appendChild(el("b", null, B.confirmed));
      setTimeout(function () { co.dataset.done = "1"; co.submit(); }, reduce ? 200 : 950);
    }, reduce ? 300 : 1400);
  });

  /* ---------- command palette (Ctrl/Cmd + K) ---------- */
  var pal = document.getElementById("palette");
  if (pal) {
    var palItems = [];
    try { palItems = JSON.parse(document.getElementById("palette-data").textContent); } catch (e) {}
    var pin = document.getElementById("palq"), plist = document.getElementById("pallist"), sel = 0, shown = [];
    var render = function () {
      var q = pin.value.trim().toLowerCase();
      shown = (q ? palItems.filter(function (it) { return it.t.toLowerCase().indexOf(q) >= 0; }) : palItems.slice(0, 14)).slice(0, 9);
      if (q) shown.push({ t: (B.lang === "om" ? "Gaafadhaa: " : B.lang === "am" ? "ጠይቅ፡ " : "Ask Batu: ") + pin.value.trim(), u: pageUrl("/ask?q=" + encodeURIComponent(pin.value.trim())), k: "AI" });
      sel = Math.min(sel, shown.length - 1);
      plist.innerHTML = "";
      shown.forEach(function (it, i) {
        var li = el("li"), a = el("a");
        a.href = it.u; a.setAttribute("role", "option"); a.setAttribute("aria-selected", i === sel ? "true" : "false");
        a.appendChild(el("span", null, it.t)); a.appendChild(el("small", null, it.k));
        li.appendChild(a); plist.appendChild(li);
      });
    };
    var openPal = function () { pal.hidden = false; pin.value = ""; sel = 0; render(); setTimeout(function () { pin.focus(); }, 20); };
    var closePal = function () { pal.hidden = true; };
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); pal.hidden ? openPal() : closePal(); }
      else if (!pal.hidden) {
        if (e.key === "Escape") closePal();
        else if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); render(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); render(); }
        else if (e.key === "Enter" && shown[sel]) { e.preventDefault(); location.href = shown[sel].u; }
      }
    });
    pin.addEventListener("input", function () { sel = 0; render(); });
    pal.addEventListener("click", function (e) { if (e.target === pal) closePal(); });
    document.querySelectorAll("[data-palette]").forEach(function (a) { a.addEventListener("click", function (e) { e.preventDefault(); openPal(); }); });
  }

  /* ---------- header over hero: solid after scrolling; parallax photos ---------- */
  var mh = document.getElementById("masthead");
  var para = reduce ? [] : Array.prototype.slice.call(document.querySelectorAll("[data-parallax]"));
  var ticking = false;
  function onScroll() {
    if (mh && mh.classList.contains("over")) mh.classList.toggle("scrolled", window.scrollY > 40);
    para.forEach(function (img) {
      var r = img.parentElement.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) return;
      var p = (r.top + r.height / 2 - window.innerHeight / 2) / window.innerHeight;
      img.style.translate = "0 " + (p * -60).toFixed(1) + "px";
    });
    ticking = false;
  }
  window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();
  var mnav = document.querySelector(".mnav");
  if (mnav) mnav.addEventListener("toggle", function () { document.body.style.overflow = mnav.open ? "hidden" : ""; });

  /* ---------- explorer: highlight the section in view ---------- */
  var exLinks = Array.prototype.slice.call(document.querySelectorAll(".explorer a[href^='#']"));
  if (exLinks.length && "IntersectionObserver" in window) {
    var exIo = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        exLinks.forEach(function (a) {
          var on = a.getAttribute("href") === "#" + en.target.id;
          a.classList.toggle("on", on);
          if (on && a.scrollIntoView && window.innerWidth < 981) a.parentElement.parentElement.scrollTo({ left: a.offsetLeft - 12, behavior: reduce ? "auto" : "smooth" });
        });
      });
    }, { rootMargin: "-30% 0px -60% 0px" });
    exLinks.forEach(function (a) { var t = document.querySelector(a.getAttribute("href")); if (t) exIo.observe(t); });
  }

  /* ---------- kebele finder and map ---------- */
  var kq = document.getElementById("kq");
  if (kq) {
    var items = Array.prototype.slice.call(document.querySelectorAll("#klist .kebele"));
    var none = document.getElementById("knone");
    var filter = function () {
      var v = kq.value.trim().toLowerCase(), shown = 0;
      items.forEach(function (it) {
        var ok = !v || it.dataset.search.indexOf(v) >= 0;
        it.hidden = !ok;
        if (ok) shown++;
      });
      none.hidden = shown > 0;
    };
    kq.addEventListener("input", filter);
    filter();

    var btn = document.getElementById("loadmap");
    if (btn) btn.addEventListener("click", function () {
      btn.classList.add("is-loading");
      var s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
      s.onload = function () {
        var box = document.getElementById("mapbox");
        box.innerHTML = '<div id="map"></div>';
        box.classList.add("loaded");
        var map = L.map("map").setView(window.KEBELE_CENTER, 13);
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
        items.forEach(function (it) {
          L.circleMarker([+it.dataset.lat, +it.dataset.lng], { radius: 8, color: "#1D5A54", fillColor: "#B3141D", fillOpacity: .9 })
            .addTo(map).bindPopup(it.dataset.name);
        });
      };
      document.head.appendChild(s);
    });
  }
})();
