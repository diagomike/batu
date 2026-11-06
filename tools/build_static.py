"""Save the portal as a static site (for GitHub Pages or any plain web host).

    python tools/build_static.py                 # site served at /
    python tools/build_static.py --base /batu/   # site served at /batu/ (GitHub project page)
    python tools/build_static.py --api https://batu-ask.onrender.com   # assistant answers via that server

Every public page is rendered by the real app and written as <path>/index.html,
once per language: English at the root, Afaan Oromoo under om/, Amharic under am/.
Things that need the server (forms, payments, the assistant, tracking) show a
short "preview" note instead of failing. The build uses a fresh, empty database,
so nothing visitors typed into a local copy ends up in the output.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# No AI key and a throwaway database for the build, whatever is in .env or var/.
os.environ["GEMINI_API_KEY"] = ""
os.environ["DEFAULT_LANG"] = "en"
_tmp = Path(tempfile.mkdtemp(prefix="batu-build-"))

from app import content, db  # noqa: E402

db.DB_PATH = _tmp / "batu.db"
from app.rag import index as rag_index  # noqa: E402

rag_index.VEC_PATH = _tmp / "vectors.npz"
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

LANG_PREFIX = {"en": "", "om": "om/", "am": "am/"}
SKIP_PREFIXES = ("/static", "/settings", "/api", "/admin", "/pay/", "/receipt")


def page_paths() -> list[str]:
    paths = ["/", "/services", "/kebele", "/government", "/discover", "/invest", "/news", "/emergency",
             "/about", "/assistant", "/ask", "/report", "/book", "/pay", "/track"]
    for s in content.services_data()["services"]:
        paths += [f"/services/{s['id']}", f"/services/{s['id']}/apply"]
    paths += [f"/discover/{p['id']}" for p in content.discover()["places"]]
    seed = content.news_seed()
    paths += [f"/news/{n['id']}" for n in seed.get("news", []) + seed.get("notices", []) if "id" in n]
    return paths


class Rewriter:
    """Turn the app's root-relative links into links that work under `base`."""

    def __init__(self, base: str, lang: str):
        self.base = base
        self.prefix = base + LANG_PREFIX[lang]

    def page(self, url: str) -> str:
        """'/services/x?y#z' -> '<prefix>services/x/?y#z' (directory-style, works on any static host)."""
        m = re.match(r"([^?#]*)([?#].*)?$", url)
        path, rest = m.group(1), m.group(2) or ""
        if path.startswith("/static/"):
            return self.base + path[1:] + rest
        if path.startswith("/settings/lang/"):
            code = path.rsplit("/", 1)[-1]
            back = re.search(r"back=([^&#]*)", rest)
            target = back.group(1) if back else "/"
            return self.base + LANG_PREFIX.get(code, "") + self._dir(target)
        if path.startswith("/settings/lowdata"):
            return "#lowdata"
        return self.prefix + self._dir(path) + rest

    @staticmethod
    def _dir(path: str) -> str:
        path = path.strip("/")
        return path + "/" if path else ""

    def html(self, text: str) -> str:
        # href/src/action="/..."  (but not protocol-relative //host)
        text = re.sub(r'((?:href|src|action|poster)=")(/(?!/)[^"]*)"',
                      lambda m: m.group(1) + self.page(m.group(2)) + '"', text)
        # srcset entries, CSS url(...) in inline styles
        text = re.sub(r"(?<=[\s,(\"'])/static/", self.base + "static/", text)
        # JSON blobs such as the command palette: "u": "/services"
        text = re.sub(r'("u":\s*")(/(?!/)[^"]*)"', lambda m: m.group(1) + self.page(m.group(2)) + '"', text)
        # The low-data switch needs a cookie a static site cannot read, so those links are dropped.
        text = re.sub(r'<a href="#lowdata">[^<]*</a>', "", text)
        return text


# Settings read by site.js; must come before it, so this goes into <head>.
HEAD_JS = "<script>window.BATU_STATIC=true;window.BATU_BASE=%(base)s;window.BATU_API=%(api)s;</script>"

STATIC_JS = """<script>
(function(){
  var B=window.BATU||{};
  if(!window.BATU_API)B.error=%(ask)s;
  document.addEventListener("submit",function(e){
    var f=e.target;if(!f||(f.getAttribute("method")||"").toLowerCase()!=="post")return;
    e.preventDefault();e.stopImmediatePropagation();
    var n=f.querySelector(".static-note");
    if(!n){n=document.createElement("p");n.className="note static-note";n.setAttribute("role","status");n.textContent=%(form)s;f.appendChild(n)}
    n.scrollIntoView({block:"nearest",behavior:"smooth"});
  },true);
})();
</script>
"""


def build(out: Path, base: str, api: str = ""):
    if not base.startswith("/"):
        base = "/" + base
    if not base.endswith("/"):
        base += "/"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    import json

    with TestClient(app) as client:
        paths = page_paths()
        written = 0
        for lang in LANG_PREFIX:
            rw = Rewriter(base, lang)
            t = lambda s: content.tr(s, lang)  # noqa: E731
            head = HEAD_JS % {"base": json.dumps(base), "api": json.dumps(api.rstrip("/"))}
            js = STATIC_JS % {
                "base": json.dumps(base),
                "ask": json.dumps(t("The assistant needs the live city server. This preview cannot answer questions yet.")),
                "form": json.dumps(t("This is a preview of the portal. Forms are switched off until it runs on the city server.")),
            }
            for p in paths:
                r = client.get(p, cookies={"lang": lang})
                if r.status_code != 200:
                    print(f"  skip {lang} {p}: {r.status_code}")
                    continue
                html = rw.html(r.text).replace("<head>", "<head>" + head, 1).replace("</body>", js + "</body>", 1)
                dest = out / LANG_PREFIX[lang] / p.strip("/") / "index.html"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(html, encoding="utf8")
                written += 1
        # A 404 page in English (GitHub Pages serves /404.html for missing paths).
        r = client.get("/this-page-does-not-exist", headers={"accept": "text/html"}, cookies={"lang": "en"})
        if "<html" in r.text:
            (out / "404.html").write_text(Rewriter(base, "en").html(r.text), encoding="utf8")

    # Static files, with root-relative URLs inside CSS pointed at the base (site.js handles its own links).
    shutil.copytree(ROOT / "static", out / "static")
    for f in (out / "static").rglob("*"):
        if f.suffix == ".css":
            f.write_text(f.read_text(encoding="utf8").replace('url("/static/', f'url("{base}static/')
                         .replace("url(/static/", f"url({base}static/"), encoding="utf8")
    (out / ".nojekyll").write_text("")
    print(f"wrote {written} pages for {len(LANG_PREFIX)} languages to {out} (base {base})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/", help="URL path the site is served under, e.g. /batu/")
    ap.add_argument("--out", default=str(ROOT / "build"), help="output folder")
    ap.add_argument("--api", default=os.getenv("ASK_API_URL", ""),
                    help="server that answers /api/ask, e.g. https://batu-ask.onrender.com (empty: assistant shows a note)")
    a = ap.parse_args()
    try:
        build(Path(a.out), a.base, a.api)
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
