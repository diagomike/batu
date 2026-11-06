"""Batu City Administration portal (demo build)."""
from __future__ import annotations

import datetime as dt
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import content, db, payments
from .rag.agent import answer
from .rag.index import INDEX


def _load_env():
    p = content.ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "batu-demo-admin")
UPLOADS = content.ROOT / "var" / "uploads"

@asynccontextmanager
async def lifespan(app):
    db.con()
    INDEX.gemini = INDEX.gemini.__class__()  # re-read env after .env is loaded
    n = INDEX.build()
    print(f"[rag] indexed {n} documents; gemini={'on' if INDEX.gemini.enabled else 'off'}")
    from . import settings  # studio key first, then .env key, then quoted answers (app/settings.py)
    settings.apply_in_background()
    yield


app = FastAPI(title="Batu City Administration", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=content.ROOT / "static"), name="static")

# The static copy of the site (GitHub Pages, Plesk) calls /api/ask on this server from another origin.
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "https://diagomike.github.io").split(",") if o.strip()]
if _origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], max_age=86400)
templates = Jinja2Templates(directory=str(content.ROOT / "templates"))


# ---------- helpers ----------
def lang_of(request: Request) -> str:
    q = request.query_params.get("lang")
    if q in content.LANGS:
        return q
    c = request.cookies.get("lang")
    return c if c in content.LANGS else os.getenv("DEFAULT_LANG", content.DEFAULT_LANG)


def ctx(request: Request, **kw):
    lang = lang_of(request)
    today = dt.date.today()
    media = content.media()

    def t(text):
        return content.tr(text, lang)

    def img(slug, size=800):
        if slug and slug in media:
            return f"/static/img/{slug}-{size}.jpg"
        return None

    def credit(slug):
        m = media.get(slug)
        if not m:
            return ""
        lic = m["licence"]
        return f"{m['credit']} · {lic}" if lic else m["credit"]

    def nl2p(text):
        return Markup("".join(f"<p>{escape(t(p))}</p>" for p in (text or "").split("\n\n") if p.strip()))

    def money(v):
        return f"{v:,.0f} birr" if v is not None else ""

    def et(d):
        return content.et_date(content.parse_date(d) if isinstance(d, str) else d, lang)

    def gc(d):
        return content.gc_date(content.parse_date(d) if isinstance(d, str) else d)

    palette_items = (
        [{"t": t(label), "u": href, "k": t("Page")} for href, label in [
            ("/services", "Services"), ("/discover", "Discover Batu"), ("/kebele", "Find my kebele"),
            ("/government", "City government"), ("/invest", "Invest"), ("/news", "News"), ("/emergency", "Emergency numbers"),
            ("/about", "About Batu")]]
        + [{"t": t(label), "u": href, "k": t("Action")} for href, label in [
            ("/report", "Report a problem"), ("/pay", "Pay a fee"), ("/book", "Book a boat trip"), ("/track", "Track a request"),
            ("/report?category=complaint", "Make a complaint"), ("/settings/lowdata?back=/", "Low-data mode")]]
        + [{"t": t(s["title"]), "u": f"/services/{s['id']}", "k": t("Service")} for s in content.services_data()["services"]]
        + [{"t": t(p["title"]), "u": f"/discover/{p['id']}", "k": t("Place")} for p in content.discover()["places"]]
    )
    base = dict(
        palette_items=palette_items,
        request=request, lang=lang, langs=content.LANGS, t=t, img=img, credit=credit, nl2p=nl2p, money=money,
        et=et, gc=gc, today=today, today_et=content.et_date(today, lang), today_gc=content.gc_date(today),
        site=content.site(), low_data=request.cookies.get("lowdata") == "1",
        machine=lang in content.MACHINE_TRANSLATED, reviewer=content.REVIEWERS.get(lang),
        path=request.url.path, categories=content.services_data()["categories"],
        offices=content.offices(), gemini_on=INDEX.gemini.enabled,
    )
    base.update(kw)
    return base


def render(request, name, status=200, **kw):
    resp = templates.TemplateResponse(request, name, ctx(request, **kw), status_code=status)
    q = request.query_params.get("lang")
    if q in content.LANGS:
        resp.set_cookie("lang", q, max_age=31536000, samesite="lax")
    return resp


def services_in(cat):
    return [s for s in content.services_data()["services"] if s["category"] == cat]


# ---------- pages ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    svc = content.services_data()
    top = [content.service(i) for i in ["resident-id", "land-lease-payment", "building-permit", "trade-licence", "boat-tour", "report-problem"]]
    return render(request, "home.html", top=top, notices=db.list_news("notice", 4), news=db.list_news("news", 3),
                  places=[content.place(p) for p in ["tulu-gudo", "timket", "birds"]],
                  projects=content.projects()["projects"][:3], tenders=content.news_seed()["tenders"],
                  vacancies=content.news_seed()["vacancies"], counts={c["id"]: len(services_in(c["id"])) for c in svc["categories"]},
                  kebeles=content.kebeles()["kebeles"], events=content.discover()["events"][:4],
                  all_places=[p for p in content.discover()["places"] if p["id"] not in ("tulu-gudo", "timket", "birds")])


@app.get("/services", response_class=HTMLResponse)
def services(request: Request, q: str = ""):
    items = content.services_data()["services"]
    if q:
        ql = q.lower()
        items = [s for s in items if ql in (s["title"] + s["summary"] + " ".join(s.get("keywords", []))).lower()
                 or ql in content.tr(s["title"], lang_of(request)).lower()]
    return render(request, "services.html", items=items, q=q, by_cat={c["id"]: services_in(c["id"]) for c in content.services_data()["categories"]})


@app.get("/services/{sid}", response_class=HTMLResponse)
def service_page(request: Request, sid: str):
    s = content.service(sid)
    if not s:
        raise HTTPException(404)
    related = [x for x in services_in(s["category"]) if x["id"] != sid][:4]
    return render(request, "service.html", s=s, office=content.offices().get(s["office"]), related=related)


@app.get("/services/{sid}/apply", response_class=HTMLResponse)
def apply_form(request: Request, sid: str):
    s = content.service(sid)
    if not s:
        raise HTTPException(404)
    return render(request, "apply.html", s=s, kebeles=content.kebeles()["kebeles"])


@app.post("/services/{sid}/apply")
def apply_submit(request: Request, sid: str, name: str = Form(...), phone: str = Form(""), kebele: str = Form(""),
                 details: str = Form(""), visit_date: str = Form("")):
    s = content.service(sid)
    if not s:
        raise HTTPException(404)
    amount = s["fee"].get("amount") or None
    ref = db.create_request("application", "A", sid, s["title"],
                            {"name": name, "phone": phone, "kebele": kebele, "details": details, "visit_date": visit_date}, amount)
    return RedirectResponse(f"/track?ref={ref}&new=1", status_code=303)


@app.get("/kebele", response_class=HTMLResponse)
def kebele(request: Request):
    return render(request, "kebele.html", kb=content.kebeles())


@app.get("/government", response_class=HTMLResponse)
def government(request: Request):
    return render(request, "government.html", projects=content.projects())


@app.get("/discover", response_class=HTMLResponse)
def discover(request: Request):
    return render(request, "discover.html", d=content.discover())


@app.get("/discover/{pid}", response_class=HTMLResponse)
def place(request: Request, pid: str):
    p = content.place(pid)
    if not p:
        raise HTTPException(404)
    others = [x for x in content.discover()["places"] if x["id"] != pid][:3]
    return render(request, "place.html", p=p, others=others)


@app.get("/invest", response_class=HTMLResponse)
def invest(request: Request):
    return render(request, "invest.html", projects=content.projects()["projects"], tenders=content.news_seed()["tenders"])


@app.get("/news", response_class=HTMLResponse)
def news(request: Request):
    seed = content.news_seed()
    return render(request, "news.html", news=db.list_news("news"), notices=db.list_news("notice"),
                  tenders=seed["tenders"], vacancies=seed["vacancies"])


@app.get("/news/{nid}", response_class=HTMLResponse)
def news_item(request: Request, nid: str):
    n = db.get_news(nid)
    if not n:
        raise HTTPException(404)
    return render(request, "news_item.html", n=n, more=[x for x in db.list_news("news", 4) if x["id"] != nid][:3])


@app.get("/emergency", response_class=HTMLResponse)
def emergency(request: Request):
    return render(request, "emergency.html")


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return render(request, "about.html", media_items=sorted(content.media().items(), key=lambda kv: kv[1]["kind"]))


@app.get("/assistant", response_class=HTMLResponse)
def assistant_info(request: Request):
    return render(request, "assistant.html", asks=db.recent_asks(8), docs=len(INDEX.docs), model=INDEX.gemini.gen_model)


@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request, q: str = ""):
    return render(request, "ask.html", q=q)


# ---------- assistant API ----------
_hits: dict[str, deque] = defaultdict(deque)


@app.post("/api/ask")
async def api_ask(request: Request):
    # Behind a proxy (Render, Plesk) the visitor's address is the first X-Forwarded-For entry.
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = fwd or (request.client.host if request.client else "?")
    now = time.time()
    dq = _hits[ip]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= 10:
        return JSONResponse({"error": "Too many questions in a minute. Please wait a moment."}, status_code=429)
    dq.append(now)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Send JSON: {\"q\": \"...\", \"lang\": \"om|am|en\"}"}, status_code=400)
    lang = body.get("lang") if body.get("lang") in content.LANGS else lang_of(request)
    history = body.get("history") if isinstance(body.get("history"), list) else None
    res = await run_in_threadpool(answer, str(body.get("q", "")), lang, history)
    for s in res.get("sources", []):
        s["title"] = content.tr(s["title"], lang)
    return res


@app.get("/api/health")
def api_health():
    return {"ok": True, "docs": len(INDEX.docs), "gemini": INDEX.gemini.enabled, "model": INDEX.gemini.gen_model}


# ---------- report a problem ----------
REPORT_TYPES = ["Pothole or damaged road", "Street light out", "Blocked drain or flooding", "Water leak",
                "Missed waste collection", "Illegal dumping", "Damaged public space", "Other"]


@app.get("/report", response_class=HTMLResponse)
def report_form(request: Request, category: str = ""):
    return render(request, "report.html", types=REPORT_TYPES, kebeles=content.kebeles()["kebeles"], complaint=category == "complaint")


@app.post("/report")
async def report_submit(request: Request, kind: str = Form("report"), type: str = Form(""), where: str = Form(""),
                        kebele: str = Form(""), details: str = Form(...), phone: str = Form(""),
                        photo: UploadFile | None = File(None)):
    data = {"type": type, "where": where, "kebele": kebele, "details": details, "phone": phone}
    if photo is not None and photo.filename:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        ext = Path(photo.filename).suffix.lower()[:5] if Path(photo.filename).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        name = secrets.token_hex(6) + ext
        blob = await photo.read()
        if len(blob) <= 6_000_000:
            (UPLOADS / name).write_bytes(blob)
            data["photo"] = name
    is_complaint = kind == "complaint"
    ref = db.create_request("complaint" if is_complaint else "report", "C" if is_complaint else "R", None,
                            "Complaint about a service" if is_complaint else (type or "Problem report"), data)
    return RedirectResponse(f"/track?ref={ref}&new=1", status_code=303)


# ---------- bookings ----------
TRIPS = {
    "birds": {"title": "Bird and hippo boat trip (about 1 hour)", "price": 650},
    "gelila": {"title": "Gelila island and Bird Island (about 3 hours)", "price": 1500},
    "tulu-gudo": {"title": "Tulu Gudo island and monastery (about 5 hours)", "price": 3000},
    "venue": {"title": "City hall or sports field (per day)", "price": 800},
}


@app.get("/book", response_class=HTMLResponse)
def book_form(request: Request, trip: str = "birds"):
    return render(request, "book.html", trips=TRIPS, trip=trip if trip in TRIPS else "birds")


@app.post("/book")
def book_submit(trip: str = Form(...), date: str = Form(...), people: int = Form(1), name: str = Form(...), phone: str = Form("")):
    tr = TRIPS.get(trip)
    if not tr:
        raise HTTPException(400)
    ref = db.create_request("booking", "B", "boat-tour" if trip != "venue" else "venue-booking", tr["title"],
                            {"trip": trip, "date": date, "people": people, "name": name, "phone": phone}, tr["price"])
    return RedirectResponse(f"/pay?ref={ref}", status_code=303)


# ---------- payments ----------
@app.get("/pay", response_class=HTMLResponse)
def pay_page(request: Request, ref: str = ""):
    r = db.get_request(ref) if ref else None
    return render(request, "pay.html", ref=ref, r=r, provider=payments.provider())


@app.post("/pay")
def pay_start(ref: str = Form(...)):
    r = db.get_request(ref)
    if not r or not r["amount"] or r["paid"]:
        return RedirectResponse(f"/pay?ref={ref}", status_code=303)
    p = payments.provider()
    pid = db.create_payment(r["ref"], r["amount"], p.name)
    return RedirectResponse(p.start(pid, r["amount"], r["title"], f"/pay/return/{pid}"), status_code=303)


@app.get("/pay/demo-checkout/{pid}", response_class=HTMLResponse)
def demo_checkout(request: Request, pid: str):
    p = db.get_payment(pid)
    if not p:
        raise HTTPException(404)
    return render(request, "checkout.html", p=p, r=db.get_request(p["request_ref"]))


@app.post("/pay/demo-checkout/{pid}")
def demo_checkout_done(pid: str, result: str = Form("success")):
    if payments.provider().verify(pid, {"result": result}):
        db.complete_payment(pid)
        return RedirectResponse(f"/receipt/{pid}", status_code=303)
    p = db.get_payment(pid)
    return RedirectResponse(f"/pay?ref={p['request_ref'] if p else ''}&failed=1", status_code=303)


@app.get("/receipt/{pid}", response_class=HTMLResponse)
def receipt(request: Request, pid: str):
    p = db.get_payment(pid)
    if not p:
        raise HTTPException(404)
    return render(request, "receipt.html", p=p, r=db.get_request(p["request_ref"]))


# ---------- tracking ----------
@app.get("/track", response_class=HTMLResponse)
def track(request: Request, ref: str = "", new: int = 0):
    r = db.get_request(ref) if ref else None
    return render(request, "track.html", ref=ref, r=r, new=new)


@app.post("/subscribe")
def subscribe(channel: str = Form("sms"), contact: str = Form(...), topics: str = Form("notices")):
    db.add_subscription(channel, contact, topics)
    return RedirectResponse("/news?subscribed=1#notices", status_code=303)


@app.get("/settings/lowdata")
def toggle_lowdata(request: Request, back: str = "/"):
    resp = RedirectResponse(back if back.startswith("/") else "/", status_code=303)
    resp.set_cookie("lowdata", "0" if request.cookies.get("lowdata") == "1" else "1", max_age=31536000, samesite="lax")
    return resp


@app.get("/settings/lang/{code}")
def set_lang(code: str, back: str = "/"):
    resp = RedirectResponse(back if back.startswith("/") else "/", status_code=303)
    if code in content.LANGS:
        resp.set_cookie("lang", code, max_age=31536000, samesite="lax")
    return resp


# ---------- admin: Batu Studio (app/studio.py) ----------
from . import studio  # noqa: E402

app.include_router(studio.router)


@app.exception_handler(studio.NeedLogin)
async def _studio_login(request: Request, exc):
    return RedirectResponse("/admin?err=Please+sign+in.", status_code=303)


# /om/..., /am/..., /en/...: language in the address, same as the static build (app/langurls.py)
from .langurls import LangPrefix  # noqa: E402

app.add_middleware(LangPrefix)


def _check(token: str):
    # bearer token for machine pushes (POST /api/admin/news)
    if not secrets.compare_digest(token or "", ADMIN_TOKEN):
        raise HTTPException(403, "Wrong admin token")


# ---------- JSON API ----------
@app.get("/api/news")
def api_news(kind: str = "news", limit: int = 20):
    return db.list_news(kind, min(limit, 100))


@app.post("/api/admin/news")
async def api_push_news(request: Request, background: BackgroundTasks):
    """Push a news item or notice: Authorization: Bearer <ADMIN_TOKEN>.
    Body: {"kind": "news"|"notice", "title", "summary", "body", "category", "source", "url", "date", "image"}"""
    auth = request.headers.get("authorization", "")
    _check(auth.removeprefix("Bearer ").strip())
    item = await request.json()
    if not item.get("title"):
        raise HTTPException(400, "title is required")
    nid = db.add_news(item, kind=item.get("kind", "news"), via="api")
    background.add_task(INDEX.build)
    return {"id": nid, "reindex": "scheduled"}


@app.post("/api/admin/reindex")
def api_reindex(request: Request):
    _check(request.headers.get("authorization", "").removeprefix("Bearer ").strip())
    return {"documents": INDEX.build()}


@app.get("/api/request/{ref}")
def api_request(ref: str):
    r = db.get_request(ref)
    if not r:
        raise HTTPException(404)
    return {k: r[k] for k in ("ref", "kind", "title", "status", "status_label", "amount", "paid", "created", "updated", "history")}


@app.get("/health")
def health():
    return {"ok": True, "documents": len(INDEX.docs), "gemini": INDEX.gemini.enabled}


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "not found"}, status_code=404)
    return render(request, "404.html", status=404)
