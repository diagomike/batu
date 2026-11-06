/* Batu portal: cinematic entrances. Works with css/cinema.css; see the notes at the top of that file.
   Order of events: split headings into word masks (still hidden) -> wait for fonts and the hero photo
   (capped, so a slow network never holds the page) -> add html.go -> scenes play as they scroll in. */
(function () {
  "use strict";
  var root = document.documentElement, cl = root.classList;
  if (!cl.contains("cine")) return;
  var T = cl.contains("seen") ? 0.6 : 1;
  var lowdata = cl.contains("lowdata");
  var each = function (sel, fn) { Array.prototype.forEach.call(document.querySelectorAll(sel), fn); };

  /* ---------- split a heading into word masks without changing its layout ---------- */
  function split(el) {
    var i = 0;
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (n) {
        if (n.nodeType === 3) {
          if (!n.textContent.trim()) return;
          var frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach(function (part) {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
            var mask = document.createElement("span"), word = document.createElement("span");
            mask.className = "w";
            word.textContent = part;
            word.style.setProperty("--wi", Math.min(i++, 14));
            mask.appendChild(word);
            frag.appendChild(mask);
          });
          node.replaceChild(frag, n);
        } else if (n.nodeType === 1 && !n.classList.contains("sample") && n.tagName !== "BR" && n.tagName !== "SVG") {
          walk(n);
        }
      });
    })(el);
    el.classList.add("ws");
  }
  function play(el, delay) {
    if (!el) return;
    el.style.setProperty("--d", Math.round(delay) + "ms");
    el.classList.add("wp");
  }

  /* ---------- digits settle from noise, left to right (coordinates) ---------- */
  function scramble(el, dur) {
    if (!el) return;
    var final = el.textContent, start = 0;
    requestAnimationFrame(function frame(t) {
      if (!start) start = t;
      var p = Math.min(1, (t - start) / dur), out = "";
      for (var k = 0; k < final.length; k++) {
        var c = final.charAt(k);
        out += /\d/.test(c) && k / final.length >= p ? String((Math.random() * 10) | 0) : c;
      }
      el.textContent = out;
      if (p < 1) requestAnimationFrame(frame);
      else el.textContent = final;
    });
  }

  /* ---------- numbers count up when the stat comes into view ---------- */
  function countUp(el, delay) {
    if (!el) return;
    var txt = el.textContent, m = txt.match(/^([\d.,]+)(.*)$/);
    if (!m) return;
    var raw = m[1], rest = m[2], dec = (raw.split(".")[1] || "").length;
    var target = parseFloat(raw.replace(/,/g, "")), comma = raw.indexOf(",") >= 0;
    var fmt = function (v) {
      var s = v.toFixed(dec);
      if (comma) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      return s + rest;
    };
    el.textContent = fmt(0);
    setTimeout(function () {
      var start = 0, dur = 1700;
      requestAnimationFrame(function f(t) {
        if (!start) start = t;
        var p = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - p, 4);
        el.textContent = p < 1 ? fmt(target * e) : txt;
        if (p < 1) requestAnimationFrame(f);
      });
    }, delay + 150);
  }

  /* ---------- the hero search types its own example ---------- */
  var heroInput = document.getElementById("heroq"), heroPh = heroInput ? heroInput.getAttribute("placeholder") || "" : "";
  if (heroInput && heroPh) heroInput.setAttribute("placeholder", "");
  function typePlaceholder(delay) {
    if (!heroInput || !heroPh) return;
    var restore = function () { heroInput.setAttribute("placeholder", heroPh); };
    heroInput.addEventListener("focus", restore, { once: true });
    setTimeout(function () {
      var k = 0;
      (function step() {
        if (document.activeElement === heroInput || heroInput.value) return restore();
        k++;
        heroInput.setAttribute("placeholder", heroPh.slice(0, k) + (k < heroPh.length ? "▍" : ""));
        if (k < heroPh.length) setTimeout(step, 24 + Math.random() * 34);
      })();
    }, delay);
  }

  /* ---------- hero slideshow: next photo only once it is decoded; pauses off screen ---------- */
  function slideshow(delay) {
    var imgs = Array.prototype.slice.call(document.querySelectorAll(".imm .slides img"));
    var hero = document.querySelector(".imm");
    if (imgs.length < 2 || lowdata || !hero) return;
    var i = 0, visible = true;
    function next() {
      var n = imgs[(i + 1) % imgs.length];
      var show = function () { imgs[i].classList.remove("on"); i = (i + 1) % imgs.length; imgs[i].classList.add("on"); };
      (n.decode ? n.decode() : Promise.resolve()).then(show, show);
    }
    if ("IntersectionObserver" in window) new IntersectionObserver(function (e) { visible = e[0].isIntersecting; }).observe(hero);
    setTimeout(function tick() {
      if (visible && !document.hidden) next();
      setTimeout(tick, 7000);
    }, delay);
  }

  /* ---------- hero photo drifts slower than the page ---------- */
  var slides = document.querySelector(".imm .slides");
  if (slides) {
    var busy = false;
    window.addEventListener("scroll", function () {
      if (busy) return;
      busy = true;
      requestAnimationFrame(function () {
        var y = window.scrollY;
        if (y < window.innerHeight * 1.3) slides.style.translate = "0 " + (y * 0.32).toFixed(1) + "px";
        busy = false;
      });
    }, { passive: true });
  }

  /* ---------- scenes and reveals ---------- */
  var REVEAL = ".section .story,.section .card,.events-grid a,.section .row,.stat,.news-item,.kebele,.ncard,.evt,.section .chips a,.section .quote,.pcard,.bar,.explorer";
  var SCENES = ".story-panel,.visit-band,.stat-band,.sec-head";
  function enter(el, rd) {
    el.style.setProperty("--rd", Math.round(rd) + "ms");
    if (el.matches(".sec-head")) play(el.querySelector("h2"), rd + 260);
    else if (el.matches(".story-panel")) {
      play(el.querySelector("h2"), rd + 700);
      var c = el.querySelector(".n span:last-child");
      setTimeout(function () { scramble(c, 900); }, rd + 650);
    } else if (el.matches(".visit-band")) play(el.querySelector("h2"), rd + 550);
    else if (el.matches(".stat")) countUp(el.querySelector(".num"), rd);
    el.classList.add("in");
  }
  function observe() {
    var els = document.querySelectorAll(SCENES + "," + REVEAL);
    if (!("IntersectionObserver" in window)) { Array.prototype.forEach.call(els, function (el) { enter(el, 0); }); return; }
    var t0 = performance.now();
    // Things already on screen when the page opens wait for the header to start first.
    var head = document.querySelector(".page-head,.hero,.imm");
    var base = head ? (head.matches(".imm") ? 1500 : 420) * T : 0;
    var io = new IntersectionObserver(function (entries) {
      var first = performance.now() - t0 < 250, k = 0;
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        io.unobserve(en.target);
        enter(en.target, (first ? base : 0) + Math.min(k++, 8) * 75);
      });
    }, { rootMargin: "0px 0px -10% 0px" });
    Array.prototype.forEach.call(els, function (el) { io.observe(el); });
  }

  /* ---------- go ---------- */
  each(".imm h1,.hero h1,.page-head h1,.story-panel h2,.visit-band h2,.sec-head h2", split);

  function go() {
    cl.add("go");
    try { sessionStorage.setItem("batu-seen", "1"); } catch (e) { /* private mode */ }
    play(document.querySelector(".imm h1"), 420 * T);
    play(document.querySelector(".page-head h1"), 200 * T);
    play(document.querySelector(".hero h1"), 520 * T);
    var coord = document.querySelector(".imm .coord");
    setTimeout(function () { scramble(coord, 1000 * T); }, 450 * T);
    typePlaceholder(1900 * T);
    slideshow(6500 * T);
    observe();
  }

  var waits = [];
  if (document.fonts && document.fonts.ready) waits.push(document.fonts.ready);
  var heroImg = lowdata ? null : document.querySelector(".imm .slides img.on,.hero img.bg");
  if (heroImg && heroImg.decode) waits.push(heroImg.decode().catch(function () {}));
  var cap = new Promise(function (r) { setTimeout(r, heroImg ? 1300 : 600); });
  Promise.race([Promise.all(waits), cap]).then(function () {
    // A tab opened in the background waits until it is looked at, so the entrance is not missed.
    if (document.hidden) document.addEventListener("visibilitychange", function () { requestAnimationFrame(go); }, { once: true });
    else requestAnimationFrame(go);
  });
})();
