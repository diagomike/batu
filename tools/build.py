"""Build the site for the Plesk host (batu.gov.et) and, if asked, upload it.

    python tools/build.py                       # dist/httpdocs, ready to upload
    python tools/build.py --zip                 # also dist/batu-site-<date>.zip (upload in Plesk File Manager)
    python tools/build.py --upload              # send changed files over FTPS (FTP_* in .env)
    python tools/build.py --api https://...     # assistant answers from that server (default: ASK_API_URL)

The pages come from tools/build_static.py (every public page in English, Afaan Oromoo and
Amharic). On top of that this adds what the host needs: the PHP services in api/ for forms,
tracking and payments (deploy/plesk/api), the .htaccess that routes form posts to them, the
script that fills in the tracking and payment pages, a sitemap and robots.txt.
The studio's Publish button runs this script. It prints "RESULT {...}" as its last line.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

os.environ["BATU_BUILD"] = "1"  # never switch AI on or touch the studio's settings during a build
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_static as bs  # noqa: E402  (renders the pages; also sets up a throwaway database)

from app import content  # noqa: E402
from app import main as appmain  # noqa: E402

PLESK = ROOT / "deploy" / "plesk"
FORM_NOTE = re.compile(r"<script>\s*\(function\(\)\{\s*var B=window\.BATU\|\|\{\};.*?</script>\s*", re.S)

# Texts the tracking and payment pages show (deploy/plesk/plesk.js), translated per language.
UI = ["Looking it up…", "No request has that reference. Check the number and try again.", "Sent. We have your request.",
      "Keep this reference number to follow your request", "Pay", "Bill", "Status", "This has already been paid.",
      "See the status", "This request has no fee to pay online.", "Pay with", "Telebirr (demo)",
      "Online payment is not switched on yet. Please pay at the Revenue Office and keep your reference number.",
      "The payment did not go through. Nothing was charged. You can try again.",
      "No bill or request has that reference. Check the number and try again.", "DEMO · no money moves", "Pay to",
      "Batu City Administration", "Payment", "Reference", "Confirm payment", "Cancel", "Payment received",
      "Thank you. Your payment is confirmed.", "Receipt number", "For", "Amount", "Your ticket",
      "Show this code at the jetty", "Track this request", "Sorry, something went wrong. Please try again.", "birr",
      "Request received", "Bill issued", "Report", "Complaint", "Booking", "Application", "Bill",
      "Complaint about a service", "Problem report",
      "Too many tries in a short time. Please wait a few minutes and try again."]


def catalogue() -> dict:
    """What the PHP services need to know: fees, trips and status names."""
    from app import db
    return {
        "statuses": db.STATUS_LABELS,
        "services": {s["id"]: {"title": s["title"], "fee": (s.get("fee") or {}).get("amount") or 0}
                     for s in content.services_data()["services"]},
        "trips": appmain.TRIPS,
        "report_types": appmain.REPORT_TYPES,
    }


def strings_for(lang: str, cat: dict) -> dict:
    keys = set(UI) | set(cat["statuses"].values()) | {s["title"] for s in cat["services"].values()} \
        | {t["title"] for t in cat["trips"].values()} | set(cat["report_types"])
    out = {}
    for k in sorted(keys):
        v = content.tr(k, lang)
        if v != k:
            out[k] = v
    return out


def adapt_pages(site: Path, api: str) -> int:
    """Swap the preview's "forms are off" script for the hosted one, page by page."""
    cat = catalogue()
    tables = {lang: strings_for(lang, cat) for lang in ("en", "om", "am")}
    pages = 0
    for f in site.rglob("*.html"):
        html = f.read_text(encoding="utf8")
        html, n = FORM_NOTE.subn("", html, count=1)
        if not n and f.name != "404.html":
            raise SystemExit(f"build_static's preview script changed; update FORM_NOTE in tools/build.py ({f})")
        rel = f.relative_to(site).as_posix()
        lang = rel.split("/")[0] if rel.split("/")[0] in ("om", "am") else "en"
        page = rel.removeprefix(lang + "/") if lang != "en" else rel
        extra = ""
        if not api:
            extra += ("<script>if(window.BATU)BATU.error=%s;</script>" %
                      json.dumps(content.tr("The assistant needs the live city server. This preview cannot answer questions yet.", lang)))
        if page in ("track/index.html", "pay/index.html"):
            extra += "<script>window.BATU_T=%s;</script><script src=\"/static/js/plesk.js\" defer></script>" % json.dumps(
                tables[lang], ensure_ascii=False)
        if extra:
            html = html.replace("</body>", extra + "</body>", 1)
        f.write_text(html, encoding="utf8")
        pages += 1
    return pages


def add_server_files(site: Path):
    shutil.copytree(PLESK / "api", site / "api")
    (site / "api" / "data").mkdir(exist_ok=True)
    (site / "api" / "data" / "catalogue.json").write_text(json.dumps(catalogue(), ensure_ascii=False, indent=1), encoding="utf8")
    shutil.copy(PLESK / "plesk.js", site / "static" / "js" / "plesk.js")
    shutil.copy(PLESK / "root.htaccess", site / ".htaccess")
    (site / ".nojekyll").unlink(missing_ok=True)
    domain = content.site()["city"].get("domain", "batu.gov.et")
    urls = []
    for f in sorted(site.rglob("index.html")):
        rel = f.parent.relative_to(site).as_posix()
        urls.append(f"https://{domain}/" + ("" if rel == "." else rel + "/"))
    today = dt.date.today().isoformat()
    (site / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
                                      + "</urlset>\n", encoding="utf8")
    (site / "robots.txt").write_text(f"User-agent: *\nDisallow: /api/\nSitemap: https://{domain}/sitemap.xml\n", encoding="utf8")
    return len(urls)


def make_zip(site: Path, out: Path) -> Path:
    z = out / f"batu-site-{dt.datetime.now():%Y%m%d-%H%M}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(site.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(site).as_posix())
    return z


def upload(site: Path) -> int:
    """Send new and changed files to the host over FTPS. Never deletes anything there."""
    import ftplib

    host, user, pw = os.getenv("FTP_HOST", ""), os.getenv("FTP_USER", ""), os.getenv("FTP_PASSWORD", "")
    root = os.getenv("FTP_DIR", "httpdocs").strip("/")
    if not (host and user and pw):
        raise SystemExit("Uploading needs FTP_HOST, FTP_USER and FTP_PASSWORD in portal/.env (see DEPLOY.md).")
    manifest_path = ROOT / "var" / f"upload-manifest-{host}.json"
    sent = json.loads(manifest_path.read_text(encoding="utf8")) if manifest_path.exists() else {}
    files = [f for f in sorted(site.rglob("*")) if f.is_file()]
    todo = []
    for f in files:
        rel = f.relative_to(site).as_posix()
        h = hashlib.sha1(f.read_bytes()).hexdigest()
        if sent.get(rel) != h:
            todo.append((rel, f, h))
    print(f"upload: {len(todo)} of {len(files)} files changed since the last upload to {host}", flush=True)
    if not todo:
        return 0
    ftp = ftplib.FTP_TLS(host, timeout=60)
    ftp.login(user, pw)
    ftp.prot_p()
    made = set()

    def cd_make(path: str):
        ftp.cwd("/" + root if root else "/")
        for part in [p for p in path.split("/") if p]:
            key = "/".join([root] + [p for p in path.split("/") if p][: path.split("/").index(part) + 1])
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                if key not in made:
                    ftp.mkd(part)
                    made.add(key)
                ftp.cwd(part)

    done = 0
    for rel, f, h in todo:
        folder, name = rel.rsplit("/", 1) if "/" in rel else ("", rel)
        cd_make(folder)
        with open(f, "rb") as fh:
            ftp.storbinary(f"STOR {name}", fh)
        sent[rel] = h
        done += 1
        if done % 25 == 0 or done == len(todo):
            print(f"upload: {done}/{len(todo)}", flush=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(sent), encoding="utf8")
    ftp.quit()
    return done


def publish(out: Path, api: str, do_zip: bool, do_upload: bool) -> dict:
    site = out / "httpdocs"
    print("Rendering every page in English, Afaan Oromoo and Amharic…", flush=True)
    bs.build(site, "/", api)
    pages = adapt_pages(site, api)
    urls = add_server_files(site)
    print(f"Added the PHP services, .htaccess and a sitemap of {urls} addresses.", flush=True)
    size = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    result = {"pages": pages, "out": str(site), "size_mb": round(size / 1e6, 1)}
    if do_zip:
        z = make_zip(site, out)
        result["zip"] = z.name
        print(f"Zip: {z} ({z.stat().st_size / 1e6:.1f} MB)", flush=True)
    if do_upload:
        result["uploaded"] = upload(site)
        print(f"Uploaded {result['uploaded']} files.", flush=True)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--api", default=os.getenv("ASK_API_URL", ""),
                    help="server that answers /api/ask until the PHP assistant ships (e.g. the Render server)")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    try:
        res = publish(Path(a.out), a.api.rstrip("/"), a.zip, a.upload)
        print("RESULT " + json.dumps(res), flush=True)
    finally:
        shutil.rmtree(bs._tmp, ignore_errors=True)
