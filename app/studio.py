"""Batu Studio: the staff side of the portal, at /admin.

Staff sign in with a username and password (scrypt hashes in the database). On a fresh install
the first administrator is created from the studio computer itself, or anywhere with the
STUDIO_SETUP_TOKEN from the server's environment. Every form is built from app/admin_schema.py;
saves go through app/store.py, which keeps each earlier version.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import hmac
import importlib.util
import io
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import admin_schema as S
from . import content, db, store
from . import database as D

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(content.ROOT / "templates"))
VAR = content.ROOT / "var"
SESSION_HOURS = 12
COOKIE = "batu_studio"


# ---------- users and sessions (tables studio_users and settings) ----------
_secret_cache: bytes | None = None


def _secret() -> bytes:
    """SECRET_KEY from the environment, or a random one kept in the database."""
    global _secret_cache
    if _secret_cache is None:
        env = os.getenv("SECRET_KEY", "").strip()
        if env:
            _secret_cache = env.encode()
        else:
            from . import settings as st
            v = st.get("studio_secret")
            if not v:
                v = secrets.token_hex(32)
                st.put("studio_secret", v, "system")
            _secret_cache = v.encode()
    return _secret_cache


def _users() -> dict:
    from sqlalchemy import select
    db.con()
    with D.engine().connect() as c:
        return {r.name: {"salt": r.salt, "hash": r.hash, "role": r.role, "created": r.created}
                for r in c.execute(select(D.studio_users).order_by(D.studio_users.c.name))}


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


def set_password(name: str, password: str, role: str | None = None):
    from sqlalchemy import insert, select, update
    salt = secrets.token_bytes(16)
    h = _hash(password, salt)
    db.con()
    with D.engine().begin() as c:
        if c.execute(select(D.studio_users.c.name).where(D.studio_users.c.name == name)).first():
            vals = {"salt": salt.hex(), "hash": h} | ({"role": role} if role else {})
            c.execute(update(D.studio_users).where(D.studio_users.c.name == name).values(**vals))
        else:
            c.execute(insert(D.studio_users).values(name=name, salt=salt.hex(), hash=h, role=role or "editor",
                                                    created=dt.datetime.now().isoformat(timespec="seconds")))


def delete_user(name: str):
    from sqlalchemy import delete
    with D.engine().begin() as c:
        c.execute(delete(D.studio_users).where(D.studio_users.c.name == name))


def check_password(name: str, password: str) -> bool:
    rec = _users().get(name)
    if not rec:
        _hash(password, b"0" * 16)  # same work either way
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(rec["salt"])), rec["hash"])


def _sign(value: str) -> str:
    return hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()


def _make_cookie(name: str) -> str:
    exp = int(time.time()) + SESSION_HOURS * 3600
    body = base64.urlsafe_b64encode(f"{name}|{exp}|{secrets.token_hex(8)}".encode()).decode()
    return f"{body}.{_sign(body)}"


def current_user(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE, "")
    if "." not in raw:
        return None
    body, sig = raw.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        name, exp, _ = base64.urlsafe_b64decode(body).decode().split("|")
    except Exception:  # noqa: BLE001
        return None
    if int(exp) < time.time():
        return None
    rec = _users().get(name)
    if not rec:
        return None
    return {"name": name, "role": rec.get("role", "editor"), "csrf": _sign("csrf:" + raw)[:32]}


class NeedLogin(Exception):
    pass


def need(request: Request, role: str | None = None) -> dict:
    u = current_user(request)
    if not u:
        raise NeedLogin()
    if role == "admin" and u["role"] != "admin":
        raise HTTPException(403, "Only administrators can do this.")
    return u


async def need_post(request: Request, role: str | None = None):
    """Signed-in user plus a valid form token (protects against cross-site form posts)."""
    u = need(request, role)
    form = await request.form()
    if not hmac.compare_digest(str(form.get("_csrf", "")), u["csrf"]):
        raise HTTPException(400, "This form expired. Go back, reload the page and try again.")
    return u, form


_fails: dict[str, list] = {}


def _setup_token_ok(token: str) -> bool:
    expected = os.getenv("STUDIO_SETUP_TOKEN", "").strip()
    return len(expected) >= 16 and hmac.compare_digest(token.strip(), expected)


def _is_local(request: Request) -> bool:
    """Setup without a token only on a laptop: SQLite (no DATABASE_URL) and a request from this computer.
    On a server the address can come from a proxy header, so there the setup token is always required."""
    if os.getenv("DATABASE_URL", "").strip():
        return False
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


# ---------- rendering ----------
def page(request: Request, name: str, user: dict | None, **kw):
    from markupsafe import Markup

    def csrf():
        return Markup(f'<input type="hidden" name="_csrf" value="{user["csrf"]}">') if user else ""

    base = dict(request=request, user=user, S=S, groups=S.GROUPS, nav=_nav() if user else {}, now=dt.datetime.now(),
                csrf=csrf, content_mod=content,
                flash=request.query_params.get("ok", ""), err=request.query_params.get("err", ""),
                image_url=image_url, store_conflicts=len(store.conflicts), site_name=content.site()["city"].get("name_om", "Batu"))
    base.update(kw)
    return templates.TemplateResponse(request, f"studio/{name}", base)


def _nav():
    out = {g: [] for g in S.GROUPS}
    for s in S.SINGLES.values():
        out[s.group].append(("s", s.name, s.title, None))
    for c in S.COLLECTIONS.values():
        try:
            n = len(_get_list(c))
        except Exception:  # noqa: BLE001
            n = 0
        out[c.group].append(("c", c.name, c.title, n))
    return out


def back(url: str, ok: str = "", err: str = "") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    q = (f"ok={_q(ok)}" if ok else "") + (f"err={_q(err)}" if err else "")
    return RedirectResponse(url + (sep + q if q else ""), status_code=303)


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


# ---------- reading and writing records ----------
def _get_list(c: S.Collection) -> list:
    return store.read(c.file).get(c.path, [])


def _find(c: S.Collection, key: str):
    items = _get_list(c)
    if c.id_key:
        for i, it in enumerate(items):
            if str(it.get(c.id_key)) == key:
                return i, it
        return None, None
    if key.isdigit() and int(key) < len(items):
        return int(key), items[int(key)]
    return None, None


def _key_of(c: S.Collection, i: int, item: dict) -> str:
    return str(item.get(c.id_key)) if c.id_key else str(i)


def parse_fields(fields: list, form, prefix: str = "", base: dict | None = None) -> tuple[dict, list]:
    """Turn posted form values back into a record. Keys the schema doesn't know are kept."""
    out = dict(base or {})
    errors = []
    for f in fields:
        name = prefix + f.key
        if f.type == "object":
            sub, e = parse_fields(f.sub, form, name + ".", (base or {}).get(f.key) or {})
            out[f.key], errors = sub, errors + e
            continue
        if f.type == "rows":
            n = int(form.get(name + ".__n", "0") or 0)
            old = (base or {}).get(f.key) or []
            rows = []
            for i in range(n):
                if form.get(f"{name}.{i}.__del"):
                    continue
                if not any(str(form.get(f"{name}.{i}.{s.key}", "")).strip() for s in f.sub if s.type != "bool"):
                    continue
                r, e = parse_fields(f.sub, form, f"{name}.{i}.", old[i] if i < len(old) and isinstance(old[i], dict) else {})
                rows.append(r)
                errors += e
            out[f.key] = rows
            continue
        raw = form.get(name)
        if f.type == "bool":
            out[f.key] = raw is not None
            continue
        raw = (str(raw) if raw is not None else "").replace("\r\n", "\n").strip()
        if raw == "" and f.key not in (base or {}) and not f.required and f.type not in ("number",):
            continue  # an optional field left empty: don't add a blank key to the file
        if raw == "" and (base or {}).get(f.key, "x") is None and not f.required:
            out[f.key] = None  # keep an empty value empty (null), as it was
            continue
        if f.type == "lines":
            out[f.key] = [x.strip() for x in raw.split("\n") if x.strip()]
        elif f.type in ("number", "int"):
            if raw == "":
                out[f.key] = 0 if f.type == "number" else None
            else:
                try:
                    v = float(raw.replace(",", ""))
                    out[f.key] = int(v) if (f.type == "int" or v.is_integer()) else v
                except ValueError:
                    errors.append(f"{f.label}: '{raw}' is not a number.")
        elif f.type == "coords":
            if not raw:
                out[f.key] = None
            else:
                try:
                    lat, lng = [float(x) for x in re.split(r"[,\s]+", raw) if x][:2]
                    out[f.key] = [lat, lng]
                except ValueError:
                    errors.append(f"{f.label}: write it as latitude, longitude (e.g. 7.93, 38.71).")
        elif f.type == "date" and raw and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            errors.append(f"{f.label}: use the date picker (YYYY-MM-DD).")
        elif f.type == "url" and raw and not re.match(r"(https?://|/|#)", raw):
            errors.append(f"{f.label}: a link must start with https:// or /.")
        else:
            out[f.key] = raw
        if f.type in ("date", "url"):
            out[f.key] = raw
        if f.required and not raw:
            errors.append(f"{f.label} is required.")
    return out, errors


def _untranslated(strings: list[str]) -> dict:
    res = {}
    for lang in content.MACHINE_TRANSLATED:
        tab = content.table(lang)
        res[lang] = [s for s in dict.fromkeys(strings) if s not in tab]
    return res


# ---------- auth pages ----------
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not _users():
        return page(request, "setup.html", None, local=_is_local(request),
                    token_set=len(os.getenv("STUDIO_SETUP_TOKEN", "").strip()) >= 16)
    u = current_user(request)
    if not u:
        return page(request, "login.html", None)
    reqs = db.list_requests(500)
    open_reqs = [r for r in reqs if r["status"] not in ("resolved", "closed", "rejected")]
    recent = []
    for f in FILES:
        for h in store.history(f)[:5]:
            recent.append(h | {"file": f})
    recent.sort(key=lambda h: h["when"], reverse=True)
    missing = translation_counts()
    return page(request, "dashboard.html", u, reqs=reqs[:8], open_count=len(open_reqs), recent=recent[:10],
                missing=missing, conflicts=store.conflicts)


@router.post("/setup")
async def setup(request: Request, name: str = Form(...), password: str = Form(...), password2: str = Form(...),
                token: str = Form("")):
    if _users():
        raise HTTPException(403, "Setup is already done.")
    if not (_is_local(request) or _setup_token_ok(token)):
        return back("/admin", err="Wrong setup token. Find STUDIO_SETUP_TOKEN in the server's environment settings.")
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{2,32}", name):
        return back("/admin", err="Username: 2-32 letters, numbers, dots or dashes.")
    if len(password) < 10 or password != password2:
        return back("/admin", err="Passwords must match and be at least 10 characters.")
    set_password(name, password, role="admin")
    resp = back("/admin", ok=f"Welcome, {name}. Your administrator account is ready.")
    resp.set_cookie(COOKIE, _make_cookie(name), httponly=True, samesite="strict", path="/admin",
                    secure=request.url.scheme == "https", max_age=SESSION_HOURS * 3600)
    return resp


@router.post("/login")
async def login(request: Request, name: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "?"
    recent = [t for t in _fails.get(ip, []) if time.time() - t < 900]
    if len(recent) >= 8:
        return back("/admin", err="Too many failed attempts. Wait 15 minutes and try again.")
    name = name.strip().lower()
    if not check_password(name, password):
        _fails[ip] = recent + [time.time()]
        return back("/admin", err="Wrong username or password.")
    _fails.pop(ip, None)
    resp = back("/admin")
    resp.set_cookie(COOKIE, _make_cookie(name), httponly=True, samesite="strict", path="/admin",
                    secure=request.url.scheme == "https", max_age=SESSION_HOURS * 3600)
    return resp


@router.post("/logout")
async def logout(request: Request):
    await need_post(request)
    resp = back("/admin", ok="Signed out.")
    resp.delete_cookie(COOKIE, path="/admin")
    return resp


# ---------- collections ----------
def _coll(name: str) -> S.Collection:
    c = S.COLLECTIONS.get(name)
    if not c:
        raise HTTPException(404)
    return c


@router.get("/c/{name}", response_class=HTMLResponse)
def coll_list(request: Request, name: str, q: str = ""):
    u = need(request)
    c = _coll(name)
    items = [(_key_of(c, i, it), i, it) for i, it in enumerate(_get_list(c))]
    if q:
        ql = q.lower()
        items = [x for x in items if ql in json.dumps(x[2], ensure_ascii=False).lower()]
    if c.sort_key:
        items.sort(key=lambda x: str(x[2].get(c.sort_key, "")), reverse=True)
    return page(request, "list.html", u, c=c, items=items, q=q)


@router.get("/c/{name}/new", response_class=HTMLResponse)
def coll_new(request: Request, name: str):
    u = need(request)
    c = _coll(name)
    rec = {}
    for f in c.fields:
        if f.type == "date":
            rec[f.key] = dt.date.today().isoformat()
    return page(request, "edit.html", u, c=c, rec=rec, key="", errors=[], untranslated={})


@router.get("/c/{name}/{key}", response_class=HTMLResponse)
def coll_edit(request: Request, name: str, key: str):
    u = need(request)
    c = _coll(name)
    i, rec = _find(c, key)
    if rec is None:
        raise HTTPException(404)
    return page(request, "edit.html", u, c=c, rec=rec, key=key, errors=[],
                untranslated=_untranslated(S.translatable_strings(c.fields, rec)))


@router.post("/c/{name}/save", response_class=HTMLResponse)
async def coll_save(request: Request, name: str):
    u, form = await need_post(request)
    c = _coll(name)
    orig = str(form.get("_key", ""))
    data = store.read(c.file)
    items = data.setdefault(c.path, [])
    idx, old = _find(c, orig) if orig else (None, None)
    rec, errors = parse_fields(c.fields, form, "", old or {})
    if c.id_key:
        rid = str(rec.get(c.id_key, "")).strip()
        if not rid:
            seed = f"{rec.get('date', '')} {rec.get(c.label, '')}" if c.new_at_top else str(rec.get(c.label, ""))
            rid = store.slug(seed, {str(x.get(c.id_key)) for x in items})
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*", rid):
            errors.append("Web address name: use lowercase letters, numbers and dashes only.")
        if any(str(x.get(c.id_key)) == rid for j, x in enumerate(items) if j != idx):
            errors.append(f"Another record already uses the name '{rid}'.")
        rec[c.id_key] = rid
    if errors:
        return page(request, "edit.html", u, c=c, rec=rec, key=orig, errors=errors, untranslated={})
    if idx is None:
        if c.file == "news.json" and c.path == "news":
            rec["created_via"] = "studio"
        if c.new_at_top:
            items.insert(0, rec)
            idx = 0
        else:
            items.append(rec)
            idx = len(items) - 1
    else:
        items[idx] = rec
    store.write(c.file, data, who=u["name"], note=f"{c.title}: {rec.get(c.label, '')}"[:120])
    key = _key_of(c, idx, rec)
    miss = _untranslated(S.translatable_strings(c.fields, rec))
    note = ""
    if any(miss.values()):
        note = f" {max(len(v) for v in miss.values())} new text(s) need translating."
    return back(f"/admin/c/{name}/{key}", ok=f"Saved.{note}")


@router.post("/c/{name}/{key}/delete")
async def coll_delete(request: Request, name: str, key: str):
    u, _ = await need_post(request)
    c = _coll(name)
    data = store.read(c.file)
    items = data.get(c.path, [])
    idx, rec = _find(c, key)
    if rec is None:
        raise HTTPException(404)
    items.pop(idx)
    store.write(c.file, data, who=u["name"], note=f"deleted {c.title}: {rec.get(c.label, '')}"[:120])
    return back(f"/admin/c/{name}", ok=f"Deleted “{rec.get(c.label, key)}”. It can be restored from History.")


@router.post("/c/{name}/{key}/move")
async def coll_move(request: Request, name: str, key: str):
    u, form = await need_post(request)
    c = _coll(name)
    data = store.read(c.file)
    items = data.get(c.path, [])
    idx, rec = _find(c, key)
    if rec is None:
        raise HTTPException(404)
    j = idx + (-1 if form.get("dir") == "up" else 1)
    if 0 <= j < len(items):
        items[idx], items[j] = items[j], items[idx]
        store.write(c.file, data, who=u["name"], note=f"reordered {c.title}")
    return back(f"/admin/c/{name}")


# ---------- single records ----------
def _single(name: str) -> S.Single:
    s = S.SINGLES.get(name)
    if not s:
        raise HTTPException(404)
    return s


@router.get("/s/{name}", response_class=HTMLResponse)
def single_edit(request: Request, name: str):
    u = need(request)
    s = _single(name)
    data = store.read(s.file)
    rec = data.get(s.path, {}) if s.path else data
    return page(request, "single.html", u, s=s, rec=rec, errors=[],
                untranslated=_untranslated(S.translatable_strings(s.fields, rec)))


@router.post("/s/{name}", response_class=HTMLResponse)
async def single_save(request: Request, name: str):
    u, form = await need_post(request)
    s = _single(name)
    data = store.read(s.file)
    old = data.get(s.path, {}) if s.path else data
    rec, errors = parse_fields(s.fields, form, "", old)
    if errors:
        return page(request, "single.html", u, s=s, rec=rec, errors=errors, untranslated={})
    if s.path:
        data[s.path] = rec
    else:
        data = rec
    store.write(s.file, data, who=u["name"], note=s.title)
    return back(f"/admin/s/{name}", ok="Saved.")


# ---------- media library (photos in the database, table media_files) ----------
IMG = content.ROOT / "static" / "img"


def image_url(slug: str, size: int = 800) -> str:
    """Photos from the code repository are static files; studio uploads are served from the database."""
    return f"/static/img/{slug}-{size}.jpg" if (IMG / f"{slug}-{size}.jpg").exists() else f"/media/{slug}-{size}.jpg"


@router.get("/media", response_class=HTMLResponse)
def media_list(request: Request, q: str = ""):
    u = need(request)
    items = sorted(content.media().items())
    if q:
        items = [x for x in items if q.lower() in json.dumps(x, ensure_ascii=False).lower()]
    return page(request, "media.html", u, items=items, q=q, used=_image_usage(), image_url=image_url)


def _image_usage() -> dict:
    used: dict[str, list] = {}
    for c in S.COLLECTIONS.values():
        for f in c.fields:
            if f.type == "image":
                for it in _get_list(c):
                    if it.get(f.key):
                        used.setdefault(it[f.key], []).append(f"{c.title}: {it.get(c.label, '')}")
    return used


@router.post("/media/upload")
async def media_upload(request: Request, photo: UploadFile = File(...)):
    u, form = await need_post(request)
    from PIL import Image, ImageOps
    from sqlalchemy import delete, insert
    blob = await photo.read()
    if len(blob) > 25_000_000:
        return back("/admin/media", err="That file is over 25 MB.")
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(blob))).convert("RGB")
    except Exception:  # noqa: BLE001
        return back("/admin/media", err="That file is not a photo the studio can read (use JPG, PNG or WebP).")
    slug = store.slug(str(form.get("slug") or Path(photo.filename or "photo").stem), set(content.media()))
    t = dt.datetime.now().isoformat(timespec="seconds")
    with D.engine().begin() as c:
        c.execute(delete(D.media_files).where(D.media_files.c.slug == slug))
        for size in (1600, 800):
            copy = im.copy()
            copy.thumbnail((size, size * 2))
            buf = io.BytesIO()
            copy.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
            c.execute(insert(D.media_files).values(slug=slug, size=size, content_type="image/jpeg",
                                                   data=buf.getvalue(), updated_at=t))
    m = store.read("media.json")
    m[slug] = {"caption": str(form.get("caption", "")).strip(), "credit": str(form.get("credit", "")).strip() or "City of Batu",
               "licence": str(form.get("licence", "")).strip(), "licence_url": str(form.get("licence_url", "")).strip(),
               "source": str(form.get("source", "")).strip(), "kind": str(form.get("kind", "")).strip() or "photo"}
    store.write("media.json", m, who=u["name"], note=f"photo {slug}")
    return back(f"/admin/media?q={slug}", ok=f"Photo '{slug}' added in two sizes (1600 and 800 px).")


@router.post("/media/{slug}/save")
async def media_save(request: Request, slug: str):
    u, form = await need_post(request)
    m = store.read("media.json")
    if slug not in m:
        raise HTTPException(404)
    for k in ("caption", "credit", "licence", "licence_url", "source", "kind"):
        m[slug][k] = str(form.get(k, "")).strip()
    store.write("media.json", m, who=u["name"], note=f"photo {slug} credits")
    return back(f"/admin/media?q={slug}", ok="Credits saved.")


@router.post("/media/{slug}/delete")
async def media_delete(request: Request, slug: str):
    u, _ = await need_post(request)
    from sqlalchemy import delete
    if slug in _image_usage():
        return back("/admin/media", err=f"'{slug}' is still used on the site. Pick another photo there first.")
    m = store.read("media.json")
    if m.pop(slug, None) is None:
        raise HTTPException(404)
    store.write("media.json", m, who=u["name"], note=f"removed photo {slug}")
    with D.engine().begin() as c:
        c.execute(delete(D.media_files).where(D.media_files.c.slug == slug))
    return back("/admin/media", ok=f"Removed '{slug}'." + (" Its files in static/img stay in the code repository."
                                                          if (IMG / f"{slug}-800.jpg").exists() else ""))


# ---------- translations ----------
_tr_mod = None
_tr_state = {"running": False, "log": [], "started": None, "finished": None}


def tr_tool():
    """tools/translate.py, loaded as a module (it also runs from the command line)."""
    global _tr_mod
    if _tr_mod is None:
        spec = importlib.util.spec_from_file_location("batu_translate", content.ROOT / "tools" / "translate.py")
        _tr_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_tr_mod)
    return _tr_mod


CONTENT_DOCS = ["site.json", "services.json", "offices.json", "kebeles.json", "discover.json", "news.json",
                "projects.json", "media.json"]


def all_strings() -> list[str]:
    t = tr_tool()
    docs = [store.read(n, {}) for n in CONTENT_DOCS]
    return sorted((t.template_strings() | t.data_strings(docs)) - {""})


def _reviewed() -> dict:
    return store.read("i18n/reviewed.json", {})


def translation_counts() -> dict:
    try:
        strings = all_strings()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    rev = _reviewed()
    out = {"total": len(strings)}
    for lang in sorted(content.MACHINE_TRANSLATED):
        tab = content.table(lang)
        out[lang] = {"missing": sum(1 for s in strings if s not in tab),
                     "reviewed": sum(1 for s in rev.get(lang, []) if s in tab)}
    return out


@router.get("/translations", response_class=HTMLResponse)
def translations(request: Request, q: str = "", show: str = "missing", page_no: int = 1):
    u = need(request)
    strings = all_strings()
    rev = _reviewed()
    tabs = {lang: content.table(lang) for lang in ("om", "am")}
    rows = []
    for s in strings:
        miss = [l for l in tabs if s not in tabs[l]]
        unrev = [l for l in tabs if s in tabs[l] and s not in rev.get(l, [])]
        if show == "missing" and not miss:
            continue
        if show == "unreviewed" and not unrev:
            continue
        if q and q.lower() not in (s + tabs["om"].get(s, "") + tabs["am"].get(s, "")).lower():
            continue
        rows.append({"en": s, "om": tabs["om"].get(s, ""), "am": tabs["am"].get(s, ""),
                     "rev_om": s in rev.get("om", []), "rev_am": s in rev.get("am", [])})
    per = 40
    pages = max(1, (len(rows) + per - 1) // per)
    page_no = min(max(1, page_no), pages)
    return page(request, "translations.html", u, rows=rows[(page_no - 1) * per: page_no * per], total=len(rows),
                pages=pages, page_no=page_no, q=q, show=show, counts=translation_counts(), state=_tr_state,
                reviewers=content.REVIEWERS, has_key=bool(os.getenv("GOOGLE_TRANSLATE_API_KEY")))


@router.post("/translations/save")
async def translations_save(request: Request):
    u, form = await need_post(request)
    n = int(form.get("__n", "0") or 0)
    tabs = {lang: dict(store.read(f"i18n/{lang}.json")) for lang in ("om", "am")}
    rev = _reviewed()
    changed = 0
    for i in range(n):
        en = str(form.get(f"{i}.en", ""))
        if not en:
            continue
        for lang in ("om", "am"):
            v = str(form.get(f"{i}.{lang}", "")).replace("\r\n", "\n").strip()
            if v and tabs[lang].get(en) != v:
                tabs[lang][en] = v
                changed += 1
            elif not v and en in tabs[lang]:
                del tabs[lang][en]
                changed += 1
            r = set(rev.get(lang, []))
            if form.get(f"{i}.rev_{lang}") and v:
                r.add(en)
            else:
                r.discard(en)
            rev[lang] = sorted(r)
    for lang in ("om", "am"):
        store.write(f"i18n/{lang}.json", dict(sorted(tabs[lang].items())), who=u["name"], note="translations edited")
    store.write("i18n/reviewed.json", rev, who=u["name"], note="review marks")
    return back(str(form.get("_back") or "/admin/translations"), ok=f"Saved {changed} change(s).")


@router.post("/translations/run")
async def translations_run(request: Request):
    u, _ = await need_post(request)
    if _tr_state["running"]:
        return back("/admin/translations", err="A translation run is already going.")
    threading.Thread(target=_run_translation, args=(u["name"],), daemon=True).start()
    return back("/admin/translations", ok="Translating the missing texts in the background. This page shows progress.")


@router.get("/translations/status")
def translations_status(request: Request):
    need(request)
    return JSONResponse(_tr_state | {"counts": translation_counts()})


def _run_translation(who: str):
    st = _tr_state
    st.update(running=True, log=[], started=dt.datetime.now().isoformat(timespec="seconds"), finished=None)
    t = tr_tool()
    try:
        strings = all_strings()
        for lang in ("om", "am"):
            tab = dict(content.table(lang))
            todo = [s for s in strings if s not in tab]
            st["log"].append(f"{lang}: {len(todo)} to translate")
            if not todo:
                continue
            path = VAR / f"translation-progress-{lang}.json"  # progress file; the result goes to the database
            path.parent.mkdir(parents=True, exist_ok=True)
            if t.KEY:
                for s in todo:
                    v = t.translate(s, lang)
                    if v:
                        tab[s] = v
            else:
                try:
                    t.batched(todo, lang, tab, path)
                except t.Blocked as e:
                    st["log"].append(f"Google is limiting requests ({e}). Saved what was done; try again later, "
                                     "or add GOOGLE_TRANSLATE_API_KEY to .env.")
            store.write(f"i18n/{lang}.json", dict(sorted(tab.items())), who=who, note="machine translation")
            st["log"].append(f"{lang}: {sum(1 for s in todo if s in tab)} translated")
    except Exception as e:  # noqa: BLE001
        st["log"].append(f"Stopped: {e}")
    finally:
        content.reload_tables()
        st.update(running=False, finished=dt.datetime.now().isoformat(timespec="seconds"))


# ---------- requests and other records from residents ----------
@router.get("/requests", response_class=HTMLResponse)
def requests_page(request: Request, status: str = "", q: str = ""):
    u = need(request)
    reqs = db.list_requests(1000)
    if status:
        reqs = [r for r in reqs if r["status"] == status]
    if q:
        reqs = [r for r in reqs if q.lower() in json.dumps(r, ensure_ascii=False).lower()]
    return page(request, "requests.html", u, reqs=reqs, statuses=db.STATUS_LABELS, status=status, q=q)


@router.get("/requests/{ref}", response_class=HTMLResponse)
def request_detail(request: Request, ref: str):
    u = need(request)
    r = db.get_request(ref)
    if not r:
        raise HTTPException(404)
    return page(request, "request.html", u, r=r, statuses=db.STATUS_LABELS)


@router.post("/requests/{ref}/status")
async def request_status(request: Request, ref: str):
    u, form = await need_post(request)
    status, note = str(form.get("status", "")), str(form.get("note", "")).strip()
    if status not in db.STATUS_LABELS:
        raise HTTPException(400)
    db.set_status(ref, status, note)
    return back(f"/admin/requests/{ref}", ok=f"Status set to “{db.STATUS_LABELS[status]}”. The resident sees it on the tracking page.")


@router.get("/uploads/{name}")
def upload_file(request: Request, name: str):
    """A photo a resident attached to a report (staff only)."""
    need(request)
    f = db.get_upload(name)
    if not f:
        raise HTTPException(404)
    return Response(f["data"], media_type=f["content_type"], headers={"Cache-Control": "private, max-age=3600"})


@router.get("/payments", response_class=HTMLResponse)
def payments_page(request: Request):
    u = need(request)
    rows = db.list_payments()
    return page(request, "table.html", u, title="Payments", cols=["id", "request_ref", "amount", "provider", "status", "receipt", "created"],
                rows=rows, link=("request_ref", "/admin/requests/{}"))


@router.get("/asks", response_class=HTMLResponse)
def asks_page(request: Request):
    u = need(request)
    return page(request, "table.html", u, title="Assistant questions", cols=["at", "lang", "question", "mode", "found", "ms"],
                rows=db.recent_asks(300), note="Numbers people typed are removed before questions are stored.")


@router.get("/subscribers", response_class=HTMLResponse)
def subscribers_page(request: Request):
    u = need(request)
    return page(request, "table.html", u, title="Subscribers", cols=["id", "at", "channel", "contact", "topics"],
                rows=db.list_subscriptions(), csv="/admin/subscribers.csv", delete="/admin/subscribers/{}/delete")


@router.get("/subscribers.csv")
def subscribers_csv(request: Request):
    need(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["at", "channel", "contact", "topics"])
    for r in db.list_subscriptions(100_000):
        w.writerow([r["at"], r["channel"], r["contact"], r["topics"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=batu-subscribers.csv"})


@router.post("/subscribers/{sid}/delete")
async def subscriber_delete(request: Request, sid: int):
    await need_post(request)
    db.delete_subscription(sid)
    return back("/admin/subscribers", ok="Removed.")


# ---------- history ----------
FILES = {"site.json": "City details", "services.json": "Services", "offices.json": "Offices", "kebeles.json": "Kebeles",
         "discover.json": "Discover", "news.json": "News and notices", "projects.json": "Projects", "media.json": "Photos",
         "i18n/om.json": "Afaan Oromoo translations", "i18n/am.json": "Amharic translations"}


@router.get("/history", response_class=HTMLResponse)
def history_page(request: Request, file: str = "news.json"):
    u = need(request)
    if file not in FILES:
        raise HTTPException(404)
    return page(request, "history.html", u, files=FILES, file=file, versions=store.history(file))


@router.post("/history/restore")
async def history_restore(request: Request):
    u, form = await need_post(request)
    file, version = str(form.get("file")), str(form.get("version"))
    if file not in FILES:
        raise HTTPException(404)
    store.restore(file, version, who=u["name"])
    return back(f"/admin/history?file={file}", ok="Restored. The version it replaced is in the list too, so this can be undone.")


# ---------- users ----------
@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    u = need(request, "admin")
    return page(request, "users.html", u, users=_users())


@router.post("/users/add")
async def users_add(request: Request):
    u, form = await need_post(request, "admin")
    name, pw, role = str(form.get("name", "")).strip().lower(), str(form.get("password", "")), str(form.get("role", "editor"))
    if not re.fullmatch(r"[a-z0-9._-]{2,32}", name):
        return back("/admin/users", err="Username: 2-32 letters, numbers, dots or dashes.")
    if len(pw) < 10:
        return back("/admin/users", err="Passwords must be at least 10 characters.")
    set_password(name, pw, role="admin" if role == "admin" else "editor")
    return back("/admin/users", ok=f"Account '{name}' saved. Give them the password in person.")


@router.post("/users/{name}/delete")
async def users_delete(request: Request, name: str):
    u, _ = await need_post(request, "admin")
    if name == u["name"]:
        return back("/admin/users", err="You cannot remove your own account.")
    delete_user(name)
    return back("/admin/users", ok=f"Removed '{name}'.")


@router.post("/account/password")
async def account_password(request: Request):
    u, form = await need_post(request)
    if not check_password(u["name"], str(form.get("old", ""))):
        return back("/admin/users" if u["role"] == "admin" else "/admin", err="Your current password is wrong.")
    pw = str(form.get("new", ""))
    if len(pw) < 10 or pw != str(form.get("new2", "")):
        return back("/admin", err="New passwords must match and be at least 10 characters.")
    set_password(u["name"], pw)
    return back("/admin", ok="Password changed.")


# ---------- AI settings (Gemini key) ----------
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    u = need(request, "admin")
    from . import settings as st
    from .rag.index import INDEX
    sk, ek = st.studio_key(), st.env_key()
    return page(request, "settings.html", u, studio_key=st.mask(sk) if sk else "", env_key=st.mask(ek) if ek else "",
                state=st.state, meta=st.meta(), on=INDEX.gemini.enabled)


@router.post("/settings/gemini")
async def settings_gemini(request: Request):
    u, form = await need_post(request, "admin")
    from . import settings as st
    action = str(form.get("action", "save"))
    if action == "remove":
        st.set_studio_key("", u["name"])
        active = st.apply_ai()
        return back("/admin/settings", ok=f"Studio key removed. The assistant now uses: {_ai_label(active)}.")
    if action == "test":
        active = st.apply_ai()
        return back("/admin/settings", ok=f"Checked again. The assistant uses: {_ai_label(active)}.")
    key = str(form.get("key", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,80}", key):
        return back("/admin/settings", err="That does not look like a Gemini API key (it usually starts with AIza).")
    res = st.check(key)
    if not res["ok"]:
        return back("/admin/settings", err=f"Not saved: {res['error']} The current key stays in use.")
    st.set_studio_key(key, u["name"])
    active = st.apply_ai()
    return back("/admin/settings", ok=f"Key saved and working ({res.get('model', '').replace('models/', '')}). "
                                      f"The assistant uses: {_ai_label(active)}.")


def _ai_label(active: str) -> str:
    return {"studio": "the key saved in the studio", "env": "the key in .env",
            "none": "no AI key (quoted answers from city records)"}.get(active, active)


# ---------- backup: export and import content ----------
@router.get("/backup", response_class=HTMLResponse)
def backup_page(request: Request):
    u = need(request, "admin")
    return page(request, "backup.html", u, docs=store.status())


@router.get("/backup/content.zip")
def backup_zip(request: Request):
    """Every content document as the JSON files of data/ (the format in the code repository)."""
    need(request, "admin")
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(store.export_all().items()):
            z.writestr(f"data/{name}", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=batu-content-{stamp}.zip"})


@router.post("/backup/import")
async def backup_import(request: Request, archive: UploadFile = File(...)):
    u, _ = await need_post(request, "admin")
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(await archive.read()))
    except zipfile.BadZipFile:
        return back("/admin/backup", err="That is not a zip file from Download all content.")
    done = []
    for info in z.infolist():
        name = info.filename.removeprefix("data/")
        if name in store.FILES and info.file_size < 20_000_000:
            try:
                data = json.loads(z.read(info).decode("utf8"))
            except ValueError:
                return back("/admin/backup", err=f"{name} in the zip is not valid JSON. Nothing after it was loaded.")
            store.write(name, data, who=u["name"], note="imported from a backup")
            done.append(name)
    if not done:
        return back("/admin/backup", err="No content files found in that zip.")
    return back("/admin/backup", ok=f"Loaded {len(done)} document(s): {', '.join(done)}. Earlier versions are in History.")


@router.post("/backup/load/{name:path}")
async def backup_load_file(request: Request, name: str):
    u, _ = await need_post(request, "admin")
    if name not in store.FILES or not (content.DATA / name).exists():
        raise HTTPException(404)
    store.load_file(name, u["name"])
    return back("/admin/backup", ok=f"Loaded data/{name} from the code. The studio version is in History.")


# ---------- search re-index after saves (debounced) ----------
_timer = None


def _schedule_reindex():
    global _timer
    if _timer:
        _timer.cancel()

    def run():
        try:
            from .rag.index import INDEX
            INDEX.build()
        except Exception as e:  # noqa: BLE001
            print("[studio] re-index failed:", e)

    _timer = threading.Timer(2.0, run)
    _timer.daemon = True
    _timer.start()


store.on_save(_schedule_reindex)
