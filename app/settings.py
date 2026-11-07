"""Studio-managed settings that are not content, kept in the database (table "settings").

The Gemini API key: which one the assistant uses, in order,
  1. the key saved in the studio (database, never in the code),
  2. GEMINI_API_KEY from the environment or portal/.env,
  3. no key: the assistant quotes the city's records instead of writing answers.
A key is only used if Google accepts it; a rejected key falls through to the next one.
`gemini_keys()` gives the same order to any code that wants to fail over per request.
"""
from __future__ import annotations

import datetime as dt
import os
import threading

from sqlalchemy import delete, insert, select, update

from . import content

_ENV_AT_START = os.environ.get("GEMINI_API_KEY", "")
_lock = threading.Lock()
state = {"active": None, "checked": None, "results": {}}


# ---------- key-value settings ----------
def _engine():
    from . import db
    db.con()
    from . import database as D
    return D.engine()


def get(key: str, default: str = "") -> str:
    from . import database as D
    with _engine().connect() as c:
        r = c.execute(select(D.settings.c.value).where(D.settings.c.key == key)).first()
    return r.value if r else default


def put(key: str, value: str | None, who: str = "") -> None:
    """Save a setting; None removes it."""
    from . import database as D
    t = dt.datetime.now().isoformat(timespec="seconds")
    with _engine().begin() as c:
        if value is None:
            c.execute(delete(D.settings).where(D.settings.c.key == key))
            return
        n = c.execute(update(D.settings).where(D.settings.c.key == key)
                      .values(value=value, updated_at=t, updated_by=who)).rowcount
        if not n:
            c.execute(insert(D.settings).values(key=key, value=value, updated_at=t, updated_by=who))


def meta_of(key: str) -> dict:
    from . import database as D
    with _engine().connect() as c:
        r = c.execute(select(D.settings).where(D.settings.c.key == key)).first()
    return {"updated_by": r.updated_by, "updated_at": r.updated_at} if r else {}


# ---------- Gemini key ----------
def env_key() -> str:
    """GEMINI_API_KEY from portal/.env, or from the environment at start-up (container hosts)."""
    p = content.ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf8").splitlines():
            if line.strip().startswith("GEMINI_API_KEY=") and not line.strip().startswith("#"):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    return _ENV_AT_START.strip()


def studio_key() -> str:
    return get("gemini_api_key").strip()


def gemini_keys() -> list[tuple[str, str]]:
    """[(source, key)] in the order to try them; empty when there is no key at all."""
    out = []
    for source, key in (("studio", studio_key()), ("env", env_key())):
        if key and key not in [k for _, k in out]:
            out.append((source, key))
    return out


def mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 10 else "set"


def set_studio_key(key: str, who: str):
    put("gemini_api_key", key.strip() if key else None, who)
    put("gemini_api_key_changed", dt.datetime.now().isoformat(timespec="seconds"), who)


def meta() -> dict:
    return meta_of("gemini_api_key_changed")


def check(key: str) -> dict:
    """Ask Google whether the key works and which models it can use."""
    from .rag.llm import Gemini
    try:
        g = Gemini(key)
        g.pick_models()
        return {"ok": True, "model": g.gen_model, "embed": g.embed_model}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "400" in msg or "403" in msg or "API key" in msg:
            msg = "Google rejected this key."
        elif "429" in msg:
            msg = "The key works but is over its quota right now."
        return {"ok": False, "error": msg[:200]}


def apply_ai() -> str:
    """Point the assistant at the first key Google accepts; otherwise switch AI answers off."""
    if os.environ.get("BATU_BUILD") == "1":
        return "build"
    from .rag.index import INDEX
    from .rag.llm import Gemini
    with _lock:
        results = {}
        chosen = None
        for source, key in gemini_keys():
            r = check(key)
            results[source] = r | {"key": mask(key)}
            if r["ok"]:
                chosen = (source, key)
                break
        g = Gemini(chosen[1] if chosen else "")
        if not chosen:
            g.key = ""  # no working key: quoted answers
        INDEX.gemini = g
        state.update(active=chosen[0] if chosen else "none", results=results,
                     checked=dt.datetime.now().isoformat(timespec="seconds"))
        return state["active"]


def apply_in_background():
    threading.Thread(target=apply_ai, daemon=True).start()
