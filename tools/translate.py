"""Machine-translate all portal text into Afaan Oromoo (om) and Amharic (am).

Usage:  python tools/translate.py                    # translate missing strings (Google)
        python tools/translate.py --engine gemini    # use the Gemini API instead (GEMINI_API_KEY)
        python tools/translate.py --force            # re-translate everything
        python tools/translate.py --wait             # if Google rate-limits, retry every 15 min (up to 8 h)

Uses the Google Cloud Translation API when GOOGLE_TRANSLATE_API_KEY is set
(recommended for production). Without a key it uses Google Translate's public
web endpoint, which is fine for a demo. Results are written to data/i18n/<lang>.json
as {english: translation}; edit those files to correct a translation by hand.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "i18n"
LANGS = ["om", "am"]

TEXT_KEYS = {"title", "summary", "body", "who", "documents", "steps", "time", "note", "unit", "label", "text",
             "kicker", "facts", "area", "landmarks", "caption", "status", "kind", "q", "a", "does", "head",
             "message", "hours", "where", "distance", "getting_here", "category", "length", "name_status",
             "administrator", "waste_day", "office", "name", "head_status", "positions_label", "number"}
SKIP_NAMES = {"Ahmedin Ismail", "Kamaal Badhaasoo", "Jeylaan Burqaa"}
T_CALL = re.compile(r"""\bt\(\s*(["'])(.+?)\1\s*\)""")


def template_strings():
    out = set()
    for p in (ROOT / "templates").glob("*.html"):
        for m in T_CALL.finditer(p.read_text(encoding="utf8")):
            out.add(m.group(2))
    # strings passed through t() from Python
    for line in (ROOT / "app" / "main.py").read_text(encoding="utf8").splitlines():
        for m in re.finditer(r'"([A-Z][^"]{3,80})"', line):
            if "REPORT_TYPES" in line or '"title":' in line or line.strip().startswith('"'):
                out.add(m.group(1))
    from app.db import STATUS_LABELS
    out.update(STATUS_LABELS.values())
    out.update(["Received", "Request received", "Bill issued", "Report", "Complaint", "Booking", "Application", "Bill",
                "Payment received", "Police", "Ambulance", "Fire and rescue", "National short code", "Sample",
                "Emergency numbers", "Open", "Closed", "Under construction", "Ongoing", "Reopened", "Open to investors",
                "Under construction (federal project)", "Road", "Public space", "Heritage", "Investment", "Highway",
                "Culture", "Tourism", "Development", "Education", "Environment", "Event", "Water", "Service",
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "To be confirmed", "birr", "birr per month",
                "birr per boat", "birr per day", "Complaint about a service", "Problem report"])
    return out


def data_strings(docs=None):
    """Texts in the content. docs: content documents to read instead of data/*.json (the studio passes the database's)."""
    out = set()

    def walk(obj, key=None):
        if isinstance(obj, str):
            if key in TEXT_KEYS and obj.strip() and obj not in SKIP_NAMES and not obj.startswith(("http", "/")):
                out.add(obj)
                for para in obj.split("\n\n"):
                    if para.strip():
                        out.add(para.strip())
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, k)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, key)

    if docs is None:
        docs = [json.loads(p.read_text(encoding="utf8")) for p in (ROOT / "data").glob("*.json")]
    for d in docs:
        walk(d)
    # news and notices are in data/news.json, which the walk above already covers
    return out


def _load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
KEY = os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
LANG_NAMES = {"om": "Afaan Oromoo (Oromo, Latin Qubee script)", "am": "Amharic (Ge'ez script)"}


def gemini_batch(texts: list[str], lang: str) -> list[str]:
    """Translate a batch with the Gemini API (used with --engine gemini)."""
    from app.rag.llm import Gemini
    g = Gemini()
    system = (f"You translate a city government website from English into {LANG_NAMES[lang]}. "
              "Use plain, polite public-service language. Keep numbers, names of people and places, "
              "codes and URLs unchanged. Return JSON: {\"t\": [translations in the same order]}.")
    out = g.generate_json(system, json.dumps({"texts": texts}, ensure_ascii=False))
    res = out.get("t", [])
    return res if len(res) == len(texts) else [""] * len(texts)
client = httpx.Client(timeout=40, headers={"User-Agent": "Mozilla/5.0 BatuPortalDemo"})


def translate(text: str, lang: str) -> str:
    for attempt in range(5):
        try:
            if KEY:
                r = client.post("https://translation.googleapis.com/language/translate/v2",
                                params={"key": KEY}, data={"q": text, "source": "en", "target": lang, "format": "text"})
                r.raise_for_status()
                return r.json()["data"]["translations"][0]["translatedText"]
            r = client.post("https://translate.googleapis.com/translate_a/single",
                            params={"client": "gtx", "sl": "en", "tl": lang, "dt": "t", "ie": "UTF-8", "oe": "UTF-8"},
                            data={"q": text})
            r.raise_for_status()
            out = "".join(seg[0] for seg in json.loads(r.content.decode("utf-8"))[0] if seg and seg[0])
            if "�" in out:
                raise ValueError("bad characters in response")
            time.sleep(0.15)
            return out
        except Exception as e:  # noqa: BLE001
            time.sleep(3 * (attempt + 1))
            last = e
    print("  failed:", text[:60], last)
    return ""


class Blocked(Exception):
    """Google answered with something other than a translation (rate limit or a CAPTCHA page)."""


def translate_lines(lines: list[str], lang: str) -> list[str] | None:
    """Translate several one-line strings in one request (joined by newlines).
    Returns None when the line count does not survive the round trip, so the caller can go one by one."""
    r = client.post("https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": "en", "tl": lang, "dt": "t", "ie": "UTF-8", "oe": "UTF-8"},
                    data={"q": "\n".join(lines)}, follow_redirects=False)
    if r.status_code != 200 or not r.content.startswith(b"["):
        raise Blocked(f"HTTP {r.status_code} {r.headers.get('location', '')[:80]}")
    text = "".join(seg[0] for seg in json.loads(r.content.decode("utf-8"))[0] if seg and seg[0])
    out = [x.strip() for x in text.split("\n")]
    if len(out) != len(lines) or any(not x or "�" in x for x in out):
        return None
    return out


def batched(todo: list[str], lang: str, table: dict, path: Path):
    """Polite path for the public endpoint: about 40 lines per request, one request at a time."""
    singles = [s for s in todo if "\n" not in s]
    multi = [s for s in todo if "\n" in s]
    batches, cur, size = [], [], 0
    for s in singles:
        if cur and (size + len(s) > 1800 or len(cur) >= 40):
            batches.append(cur); cur, size = [], 0
        cur.append(s); size += len(s) + 1
    if cur:
        batches.append(cur)
    done = 0
    for b in batches + [[m] for m in multi]:
        if len(b) == 1:
            res = [translate(b[0], lang)]
        else:
            res = translate_lines(b, lang)
            if res is None:  # line count changed; fall back to one request per string
                res = [translate(s, lang) for s in b]
        for s, tr in zip(b, res):
            if tr:
                table[s] = tr
        done += len(b)
        path.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf8")
        print(f"  {lang} {done}/{len(todo)}", flush=True)
        time.sleep(1.5)


def main():
    force = "--force" in sys.argv
    strings = sorted((template_strings() | data_strings()) - {""})
    print(f"{len(strings)} strings")
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        path = OUT / f"{lang}.json"
        table = {} if force or not path.exists() else json.loads(path.read_text(encoding="utf8"))
        table = {k: v for k, v in table.items() if "�" not in v}
        todo = [s for s in strings if s not in table]
        print(f"{lang}: {len(todo)} to translate")
        done = 0
        if "--engine" in sys.argv and sys.argv[sys.argv.index("--engine") + 1] == "gemini":
            for k in range(0, len(todo), 30):
                batch = todo[k:k + 30]
                try:
                    for s, tr in zip(batch, gemini_batch(batch, lang)):
                        if tr:
                            table[s] = tr
                except Exception as e:  # noqa: BLE001
                    print("  batch failed:", e)
                    time.sleep(10)
                path.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf8")
                print(f"  {lang} {min(k + 30, len(todo))}/{len(todo)}", flush=True)
                time.sleep(4)
            continue
        if not KEY:
            # --wait: when Google rate-limits us, check again every 15 minutes (one small request)
            # for up to 8 hours instead of giving up. It never tries to get around the limit.
            deadline = time.time() + 8 * 3600
            while True:
                try:
                    batched([s for s in todo if s not in table], lang, table, path)
                    break
                except Blocked as e:
                    path.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf8")
                    if "--wait" not in sys.argv or time.time() > deadline:
                        print(f"Google stopped answering ({e}). Progress saved; run again later, "
                              "or set GOOGLE_TRANSLATE_API_KEY to use the official API.")
                        return
                    print(f"  rate-limited ({e}); trying again in 15 minutes", flush=True)
                    time.sleep(900)
            print(f"{lang}: {len(table)} entries saved")
            continue
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(translate, s, lang): s for s in todo}
            from concurrent.futures import as_completed
            for fut in as_completed(futures):
                s, tr = futures[fut], fut.result()
                if tr:
                    table[s] = tr
                done += 1
                if done % 50 == 0:
                    path.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf8")
                    print(f"  {lang} {done}/{len(todo)}", flush=True)
        path.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf8")
        print(f"{lang}: {len(table)} entries saved")


if __name__ == "__main__":
    main()
