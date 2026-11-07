"""Content documents (site.json, services.json, i18n/om.json ...) kept in the database.

The JSON files in data/ are the starting point and the export format; the database is what
the site reads and the studio edits, so edits survive redeploys on container hosts.

How a file in data/ and the database stay in step (sync_from_files, at every start):
  - not in the database yet                 -> loaded from the file
  - never edited in the studio, file changed -> updated from the file (e.g. translation fixes in git)
  - edited in the studio, file changed       -> the studio version stays; the studio lists it under
                                               Backup, where staff can load the file instead
Every save keeps the version it replaced (content_versions, last 50 per document).
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import threading

from sqlalchemy import delete, insert, select, update

from . import content
from . import database as D

DATA = content.DATA
FILES = ["site.json", "services.json", "offices.json", "kebeles.json", "discover.json", "news.json",
         "projects.json", "media.json", "i18n/om.json", "i18n/am.json", "i18n/reviewed.json"]
KEEP_VERSIONS = 50
_lock = threading.RLock()
_cache: dict[str, object] = {}
_after_save = []      # callbacks after each save (the studio re-indexes the assistant here)
conflicts: dict[str, str] = {}  # document -> why the file in data/ was not loaded
_MISSING = object()


def on_save(fn):
    _after_save.append(fn)
    return fn


def _check(name: str):
    if not re.fullmatch(r"[a-z0-9_\-/]+\.json", name) or ".." in name:
        raise ValueError(f"bad content name: {name}")


def _stamp() -> str:
    return dt.datetime.now().isoformat(timespec="microseconds")


def _file_hash(name: str) -> str | None:
    p = DATA / name
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else None


def _engine():
    from . import db
    db.con()
    return D.engine()


# ---------- read and write ----------
def read(name: str, default=_MISSING):
    _check(name)
    with _lock:
        if name in _cache:
            return copy.deepcopy(_cache[name])
    with _engine().connect() as c:
        row = c.execute(select(D.content_docs.c.data).where(D.content_docs.c.name == name)).first()
    if row is None:
        if default is not _MISSING:
            return default
        raise FileNotFoundError(name)
    with _lock:
        _cache[name] = row.data
    return copy.deepcopy(row.data)


def write(name: str, data, who: str = "studio", note: str = "") -> None:
    """Save a document and keep the one it replaces under History."""
    _check(name)
    data = json.loads(json.dumps(data, ensure_ascii=False))  # plain JSON only
    with _lock, _engine().begin() as c:
        old = c.execute(select(D.content_docs).where(D.content_docs.c.name == name)).first()
        if old is not None and old.data == data:
            return
        t = _stamp()
        if old is not None:
            c.execute(insert(D.content_versions).values(name=name, data=old.data, saved_at=t, who=who, note=note[:300]))
            c.execute(update(D.content_docs).where(D.content_docs.c.name == name)
                      .values(data=data, updated_at=t, updated_by=who))
            ids = [r.id for r in c.execute(select(D.content_versions.c.id).where(D.content_versions.c.name == name)
                                           .order_by(D.content_versions.c.id.desc()))]
            if len(ids) > KEEP_VERSIONS:
                c.execute(delete(D.content_versions).where(D.content_versions.c.id.in_(ids[KEEP_VERSIONS:])))
        else:
            c.execute(insert(D.content_docs).values(name=name, data=data, updated_at=t, updated_by=who, seed_hash=None))
        conflicts.pop(name, None)
    refresh()


def history(name: str) -> list[dict]:
    with _engine().connect() as c:
        rows = c.execute(select(D.content_versions).where(D.content_versions.c.name == name)
                         .order_by(D.content_versions.c.id.desc())).all()
    return [{"id": str(r.id), "when": r.saved_at[:19].replace("T", " "), "who": r.who or "", "note": r.note or "",
             "size": len(json.dumps(r.data, ensure_ascii=False).encode())} for r in rows]


def restore(name: str, version: str, who: str) -> None:
    with _engine().connect() as c:
        row = c.execute(select(D.content_versions.c.data).where(D.content_versions.c.name == name,
                                                                D.content_versions.c.id == int(version))).first()
    if row is None:
        raise FileNotFoundError(version)
    write(name, row.data, who=who, note=f"restored version {version}")


def refresh() -> None:
    """Drop cached content so the next request reads the database again."""
    with _lock:
        _cache.clear()
    for fn in (content.site, content.services_data, content.offices, content.kebeles, content.discover,
               content.news_seed, content.projects, content.media):
        fn.cache_clear()
    content.reload_tables()
    for fn in _after_save:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a failed re-index must not lose the save
            print("[store] after-save hook failed:", e)


# ---------- data/ files <-> database ----------
def sync_from_files(eng=None) -> dict:
    """Load data/*.json into the database following the rules at the top of this file."""
    eng = eng or D.engine()
    report = {"loaded": [], "updated": [], "kept": []}
    with _lock, eng.begin() as c:
        for name in FILES:
            h = _file_hash(name)
            if h is None:
                continue
            doc = c.execute(select(D.content_docs).where(D.content_docs.c.name == name)).first()
            if doc is not None and doc.seed_hash == h:
                continue
            data = json.loads((DATA / name).read_text(encoding="utf8"))
            t = _stamp()
            if doc is None:
                c.execute(insert(D.content_docs).values(name=name, data=data, updated_at=t, updated_by="seed", seed_hash=h))
                report["loaded"].append(name)
            elif doc.updated_by == "seed":
                if doc.data != data:
                    c.execute(insert(D.content_versions).values(name=name, data=doc.data, saved_at=t, who="seed",
                                                                note="updated from data/" + name))
                c.execute(update(D.content_docs).where(D.content_docs.c.name == name).values(data=data, updated_at=t, seed_hash=h))
                report["updated"].append(name)
            else:
                conflicts[name] = f"data/{name} changed in the code after it was edited in the studio (by {doc.updated_by})."
                report["kept"].append(name)
    with _lock:
        _cache.clear()
    return report


def load_file(name: str, who: str) -> None:
    """Replace a document with the file from data/ (the studio's "load from code")."""
    data = json.loads((DATA / name).read_text(encoding="utf8"))
    write(name, data, who=who, note=f"loaded data/{name}")
    with _engine().begin() as c:  # follow the file again from now on
        c.execute(update(D.content_docs).where(D.content_docs.c.name == name)
                  .values(updated_by="seed", seed_hash=_file_hash(name)))
    conflicts.pop(name, None)
    refresh()


def export_all() -> dict:
    with _engine().connect() as c:
        return {r.name: r.data for r in c.execute(select(D.content_docs.c.name, D.content_docs.c.data))}


def status() -> list[dict]:
    with _engine().connect() as c:
        rows = c.execute(select(D.content_docs.c.name, D.content_docs.c.updated_at, D.content_docs.c.updated_by)
                         .order_by(D.content_docs.c.name)).all()
    return [{"name": r.name, "updated_at": r.updated_at[:19].replace("T", " "), "updated_by": r.updated_by,
             "conflict": conflicts.get(r.name, ""), "in_code": (DATA / r.name).exists()} for r in rows]


# ---------- news and notices (the news.json document) ----------
def _norm(item: dict, kind: str) -> dict:
    """One shape for pages and the assistant, whatever the stored fields are called."""
    text = item.get("text", "")
    return {
        "id": item.get("id", ""),
        "date": item.get("date", ""),
        "category": item.get("category") or item.get("kind") or ("City" if kind == "news" else "Notice"),
        "title": item.get("title", ""),
        "summary": item.get("summary") or text,
        "body": item.get("body") or item.get("summary") or text,
        "source": item.get("source", "City of Batu"),
        "url": item.get("url", ""),
        "image": item.get("image") or None,
        "kind": kind,
        "sample": 1 if item.get("sample") else 0,
        "created_via": item.get("created_via", "seed"),
    }


def _key(kind: str) -> str:
    return "notices" if kind == "notice" else "news"


def list_news(kind: str = "news", limit: int = 50) -> list[dict]:
    items = [_norm(n, kind) for n in content.news_seed().get(_key(kind), [])]
    items.sort(key=lambda n: n["date"], reverse=True)
    return items[:limit]


def get_news(nid: str):
    for kind in ("news", "notice"):
        for n in list_news(kind, 10_000):
            if n["id"] == nid:
                return n
    return None


def slug(text: str, taken=()) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48] or "item"
    base, i = s, 2
    while s in taken:
        s = f"{base}-{i}"
        i += 1
    return s


def add_news(item: dict, kind: str = "news", via: str = "api") -> str:
    """Add or replace a news item or notice; returns its id."""
    with _lock:
        data = read("news.json")
        lst = data.setdefault(_key(kind), [])
        nid = item.get("id") or f"{dt.date.today().isoformat()}-{slug(item.get('title', ''))}"
        date = item.get("date") or dt.date.today().isoformat()
        if kind == "notice":
            rec = {"id": nid, "date": date, "kind": item.get("category") or item.get("kind") or "Notice",
                   "title": item["title"], "text": item.get("text") or item.get("summary") or item.get("body", ""),
                   "sample": bool(item.get("sample"))}
        else:
            rec = {"id": nid, "date": date, "category": item.get("category", "City"), "title": item["title"],
                   "summary": item.get("summary", ""), "body": item.get("body") or item.get("summary", ""),
                   "source": item.get("source", "City of Batu"), "url": item.get("url", ""),
                   "image": item.get("image") or ""}
        rec["created_via"] = via
        lst[:] = [x for x in lst if x.get("id") != nid]
        lst.insert(0, rec)
        write("news.json", data, who=via, note=f"{kind} {nid}")
    return nid


def delete_news(nid: str, who: str = "studio") -> bool:
    with _lock:
        data = read("news.json")
        changed = False
        for key in ("news", "notices"):
            before = len(data.get(key, []))
            data[key] = [x for x in data.get(key, []) if x.get("id") != nid]
            changed |= len(data[key]) != before
        if changed:
            write("news.json", data, who=who, note=f"deleted {nid}")
    return changed
