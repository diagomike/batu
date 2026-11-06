"""Read and write the content files in data/ safely.

Every save is atomic (write to a temp file, then replace), keeps the previous version in
var/history/<file>/<time>.json, and clears the in-memory caches so the site shows the change
at once. News and notices live in data/news.json; this module is their single source.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import threading
from pathlib import Path

from . import content

DATA = content.DATA
HISTORY = content.ROOT / "var" / "history"
KEEP_VERSIONS = 50
_lock = threading.RLock()
_after_save = []  # callbacks run after each save (the app registers a search re-index here)


def on_save(fn):
    _after_save.append(fn)
    return fn


def path_of(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_\-/]+\.json", name) or ".." in name:
        raise ValueError(f"bad content file name: {name}")
    return DATA / name


def read(name: str):
    return json.loads(path_of(name).read_text(encoding="utf8"))


def write(name: str, data, who: str = "studio", note: str = "") -> None:
    """Save a content file, keeping the old version in var/history."""
    p = path_of(name)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with _lock:
        if p.exists():
            old = p.read_text(encoding="utf8")
            if old == text:
                return
            hdir = HISTORY / name.replace("/", "__").removesuffix(".json")
            hdir.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            (hdir / f"{stamp}.json").write_text(old, encoding="utf8")
            (hdir / f"{stamp}.meta").write_text(json.dumps({"who": who, "note": note}), encoding="utf8")
            versions = sorted(hdir.glob("*.json"))
            for v in versions[:-KEEP_VERSIONS]:
                v.unlink(missing_ok=True)
                v.with_suffix(".meta").unlink(missing_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf8")
        os.replace(tmp, p)
    refresh()


def history(name: str) -> list[dict]:
    hdir = HISTORY / name.replace("/", "__").removesuffix(".json")
    out = []
    for v in sorted(hdir.glob("*.json"), reverse=True):
        meta = {}
        m = v.with_suffix(".meta")
        if m.exists():
            meta = json.loads(m.read_text(encoding="utf8"))
        stamp = v.stem
        when = dt.datetime.strptime(stamp[:15], "%Y%m%d-%H%M%S")
        out.append({"id": stamp, "when": when.strftime("%Y-%m-%d %H:%M:%S"), "who": meta.get("who", ""),
                    "note": meta.get("note", ""), "size": v.stat().st_size})
    return out


def restore(name: str, version: str, who: str) -> None:
    hdir = HISTORY / name.replace("/", "__").removesuffix(".json")
    v = hdir / f"{version}.json"
    if not re.fullmatch(r"[0-9\-]+", version) or not v.exists():
        raise FileNotFoundError(version)
    write(name, json.loads(v.read_text(encoding="utf8")), who=who, note=f"restored {version}")


def refresh() -> None:
    """Drop cached content so the next request reads the files again."""
    for fn in (content.site, content.services_data, content.offices, content.kebeles, content.discover,
               content.news_seed, content.projects, content.media):
        fn.cache_clear()
    content.reload_tables()
    for fn in _after_save:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a failed re-index must not lose the save
            print("[store] after-save hook failed:", e)


# ---------- news and notices (data/news.json) ----------
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


def migrate_db_news(con) -> int:
    """Move news pushed into the old SQLite table (admin or API) into news.json, once."""
    try:
        rows = con.execute("select * from news where created_via != 'seed'").fetchall()
    except Exception:  # noqa: BLE001 - table absent on new installs
        return 0
    existing = {n["id"] for k in ("news", "notice") for n in list_news(k, 10_000)}
    moved = 0
    for r in rows:
        r = dict(r)
        if r["id"] in existing:
            continue
        add_news(r, kind=r.get("kind") or "news", via=r.get("created_via") or "api")
        moved += 1
    if rows:
        con.execute("delete from news where created_via != 'seed'")
        con.commit()
    return moved


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(3)
