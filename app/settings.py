"""Studio-managed settings that are not content: for now, the Gemini API key.

Which key the assistant uses, in order:
  1. the key saved in the studio (var/studio_settings.json, never committed),
  2. GEMINI_API_KEY from portal/.env,
  3. no key: the assistant quotes the city's records instead of writing answers.
A key is only used if Google accepts it; a rejected key falls through to the next one.
`gemini_keys()` gives the same order to any code that wants to fail over per request.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading

from . import content

FILE = content.ROOT / "var" / "studio_settings.json"
_ENV_AT_START = os.environ.get("GEMINI_API_KEY", "")
_lock = threading.Lock()
state = {"active": None, "checked": None, "results": {}}


def _read() -> dict:
    return json.loads(FILE.read_text(encoding="utf8")) if FILE.exists() else {}


def _write(d: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf8")
    os.replace(tmp, FILE)


def env_key() -> str:
    """GEMINI_API_KEY as written in portal/.env (falls back to the environment at start-up)."""
    p = content.ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf8").splitlines():
            if line.strip().startswith("GEMINI_API_KEY=") and not line.strip().startswith("#"):
                return line.split("=", 1)[1].strip()
    return _ENV_AT_START.strip()


def studio_key() -> str:
    return _read().get("gemini_api_key", "").strip()


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
    d = _read()
    if key:
        d.update(gemini_api_key=key.strip(), updated_by=who, updated_at=dt.datetime.now().isoformat(timespec="seconds"))
    else:
        d.pop("gemini_api_key", None)
        d.update(updated_by=who, updated_at=dt.datetime.now().isoformat(timespec="seconds"))
    _write(d)


def meta() -> dict:
    d = _read()
    return {"updated_by": d.get("updated_by"), "updated_at": d.get("updated_at")}


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
