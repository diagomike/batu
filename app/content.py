"""Loads the city's content files, translations and calendar helpers.

Content lives in data/*.json, written in English. Translations live in
data/i18n/<lang>.json as {english text: translated text}. Anything not yet
translated falls back to English.
"""
from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

LANGS = {
    "om": {"name": "Afaan Oromoo", "short": "OM", "html": "om"},
    "am": {"name": "አማርኛ", "short": "AM", "html": "am"},
    "en": {"name": "English", "short": "EN", "html": "en"},
}
DEFAULT_LANG = "en"  # switch to "om" (or set DEFAULT_LANG in .env) once Afaan Oromoo translation is complete
MACHINE_TRANSLATED = {"om", "am"}
REVIEWERS = {"om": "Caalaa Placeholder (dummy reviewer)", "am": "Abebe Placeholder (dummy reviewer)"}


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf8"))


@lru_cache(maxsize=None)
def site():
    return _load("site.json")


@lru_cache(maxsize=None)
def services_data():
    return _load("services.json")


@lru_cache(maxsize=None)
def offices():
    return {o["id"]: o for o in _load("offices.json")["offices"]}


@lru_cache(maxsize=None)
def kebeles():
    return _load("kebeles.json")


@lru_cache(maxsize=None)
def discover():
    return _load("discover.json")


@lru_cache(maxsize=None)
def news_seed():
    return _load("news.json")


@lru_cache(maxsize=None)
def projects():
    return _load("projects.json")


@lru_cache(maxsize=None)
def media():
    p = DATA / "media.json"
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else {}


def service(sid: str):
    return next((s for s in services_data()["services"] if s["id"] == sid), None)


def place(pid: str):
    return next((p for p in discover()["places"] if p["id"] == pid), None)


# ---------- translation ----------
_tables: dict[str, dict] = {}


def table(lang: str) -> dict:
    if lang not in _tables:
        p = DATA / "i18n" / f"{lang}.json"
        _tables[lang] = json.loads(p.read_text(encoding="utf8")) if p.exists() else {}
    return _tables[lang]


def reload_tables():
    _tables.clear()


def tr(text, lang: str):
    """Translate an English string; fall back to English."""
    if not text or lang == "en" or not isinstance(text, str):
        return text
    return table(lang).get(text, text)


# ---------- Ethiopian calendar ----------
ET_MONTHS = {
    "en": ["Meskerem", "Tikimt", "Hidar", "Tahsas", "Tir", "Yekatit", "Megabit", "Miyazya", "Ginbot", "Sene", "Hamle", "Nehase", "Pagume"],
    "om": ["Fulbaana", "Onkoloolessa", "Sadaasa", "Muddee", "Amajjii", "Guraandhala", "Bitootessa", "Eebila", "Caamsaa", "Waxabajjii", "Adoolessa", "Hagayya", "Qaam'ee"],
    "am": ["መስከረም", "ጥቅምት", "ኅዳር", "ታኅሣሥ", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜን"],
}
GC_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ETHIOPIC_EPOCH = 1723856  # Julian day number of 1 Meskerem, year 1 (Amete Mihret)


def to_ethiopian(d: dt.date):
    jdn = d.toordinal() + 1721425  # proleptic Gregorian ordinal -> Julian day number
    r = (jdn - ETHIOPIC_EPOCH) % 1461
    n = r % 365 + 365 * (r // 1460)
    year = 4 * ((jdn - ETHIOPIC_EPOCH) // 1461) + r // 365 - r // 1460
    month = n // 30 + 1
    day = n % 30 + 1
    return year, month, day


def et_date(d: dt.date, lang: str = "en") -> str:
    y, m, day = to_ethiopian(d)
    names = ET_MONTHS.get(lang, ET_MONTHS["en"])
    suffix = {"en": "E.C.", "om": "A.L.I.", "am": "ዓ.ም."}.get(lang, "E.C.")
    return f"{day} {names[m - 1]} {y} {suffix}"


def gc_date(d: dt.date) -> str:
    return f"{d.day} {GC_MONTHS[d.month - 1]} {d.year}"


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])
