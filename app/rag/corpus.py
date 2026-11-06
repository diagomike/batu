"""Turns the city's content into small, citable documents for retrieval.

Every document carries a title, a link to the page it came from, and a note
when its facts are still samples. The assistant may only answer from these.
"""
from __future__ import annotations

from .. import content, db


def _fee(s):
    f = s.get("fee", {})
    if f.get("amount") is None:
        return f.get("note", "")
    if f["amount"] == 0:
        return f"Free. {f.get('note', '')}".strip()
    return f"{f['amount']} {f.get('unit', 'birr')} ({f.get('note', '')})"


SKIP_KEYS = {"id", "category", "office", "image", "url", "coords", "kind", "keywords", "source_url", "date", "created_via"}


def _strings(obj, key=None):
    """All human-readable strings in a record, in order (used for translated search and quotes)."""
    if isinstance(obj, str):
        return [] if key in SKIP_KEYS else [p for p in obj.split("\n\n") if p.strip()]
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if k not in SKIP_KEYS:
                out += _strings(v, k)
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            out += _strings(v, key)
        return out
    return []


def documents() -> list[dict]:
    docs: list[dict] = []
    offices = content.offices()
    site = content.site()

    def add(id, type, title, url, parts, sample=False, office=None, record=None):
        text = "\n".join(p for p in parts if p)
        pieces = [title] + (_strings(record) if record is not None else [p for p in parts if p])
        docs.append({"id": id, "type": type, "title": title, "url": url, "text": text,
                     "sample": sample, "office": office, "pieces": pieces})

    for s in content.services_data()["services"]:
        off = offices.get(s["office"], {})
        add(f"service:{s['id']}", "service", s["title"], f"/services/{s['id']}", [
            s["title"] + ".", s["summary"],
            f"Who can use it: {s['who']}",
            "Documents to bring: " + "; ".join(s["documents"]) if s["documents"] else "",
            "Steps: " + " ".join(f"{i+1}. {x}" for i, x in enumerate(s["steps"])),
            f"Fee: {_fee(s)}", f"Time: {s['time']}",
            f"Office: {off.get('name', s['office'])}",
            "Keywords: " + ", ".join(s.get("keywords", [])),
        ], sample=True, office=off.get("name"), record={k: s[k] for k in ("summary", "who", "documents", "steps", "time")})

    for o in offices.values():
        add(f"office:{o['id']}", "office", o["name"], f"/government#{o['id']}", [
            o["name"] + ".", o["does"], f"Head: {o['head']}" + (f" ({o['head_status']})" if o.get("head_status") else ""),
        ], sample=o["head"].startswith("To be"), record={"does": o["does"]})

    kb = content.kebeles()
    add("kebeles", "kebele", "Kebeles of Batu", "/kebele", [kb["note"]] + [
        f"{k['name']}: {k['area']}. Landmarks: {', '.join(k['landmarks'])}. Waste collection day: {k['waste_day']} (sample)."
        for k in kb["kebeles"]], sample=True)

    for p in content.discover()["places"]:
        add(f"place:{p['id']}", "place", p["title"], f"/discover/{p['id']}", [
            p["title"] + ". " + p["summary"], p["body"], "Facts: " + "; ".join(p["facts"]),
            "Sources: " + "; ".join(p["sources"]),
        ], record={k: p[k] for k in ("summary", "body", "facts")})
    d = content.discover()
    add("day-trips", "place", "Day trips from Batu", "/discover#day-trips",
        [f"{t['title']} ({t['distance']}): {t['text']}" for t in d["day_trips"]])
    add("stays", "place", "Where to stay in Batu", "/discover#stay",
        [f"{s['name']}, {s['where']}: {s['text']}" for s in d["stays"]], sample=True)
    add("events", "event", "Festivals and events calendar", "/discover#events",
        [f"{e['date']}: {e['title']} at {e['where']}" for e in d["events"]])
    add("getting-here", "place", "Getting to Batu", "/discover#getting-here", [d["getting_here"]])

    for i, f in enumerate(site["facts"]):
        add(f"fact:{i}", "fact", f["q"], "/about", [f["q"], f["a"]], record={"a": f["a"]})

    add("emergency", "emergency", "Emergency numbers", "/emergency", [
        "In an emergency call: " + ", ".join(f"{e['label']} {e['number']}" for e in site["emergency"]) + ".",
        "These national short codes work from any phone. Local station numbers are being confirmed."])

    m = site["mayor"]
    add("mayor", "government", "The Mayor of Batu", "/government", [f"{m['name']}, {m['title']}. {m['status']}"])

    for pr in content.projects()["projects"]:
        add(f"project:{pr['id']}", "project", pr["title"], "/government#projects", [
            f"{pr['title']} ({pr['kind']}, {pr['length']}). Status: {pr['status']}. Progress: {pr['progress']}%" +
            (" (sample)" if pr["progress_sample"] else "") + f". Source: {pr['source']}."], sample=pr["progress_sample"])

    for n in db.list_news("news", 200):
        add(f"news:{n['id']}", "news", n["title"], f"/news/{n['id']}", [
            f"{n['date']}: {n['title']}.", n["summary"], n["body"], f"Source: {n['source']}"],
            record={"summary": n["summary"], "body": n["body"]})
    for n in db.list_news("notice", 50):
        add(f"notice:{n['id']}", "notice", n["title"], "/news#notices", [f"{n['date']}: {n['title']}. {n['summary']}"],
            sample=bool(n["sample"]))
    seed = content.news_seed()
    for t in seed["tenders"]:
        add(f"tender:{t['id']}", "tender", t["title"], "/news#tenders", [
            f"Tender: {t['title']}. Office: {t['office']}. Published {t['published']}, deadline {t['deadline']}. Status: {t['status']}. Document fee {t['fee']} birr."],
            sample=t.get("sample", False))
    for v in seed["vacancies"]:
        add(f"vacancy:{v['id']}", "vacancy", v["title"], "/news#vacancies", [
            f"Vacancy: {v['title']} at the {v['office']}, {v['positions']} position(s), apply by {v['deadline']}."], sample=True)

    add("payments-howto", "help", "How to pay city fees online", "/pay", [
        "You can pay city fees online with Telebirr using the reference number on your bill or request.",
        "Go to Pay a fee, enter the reference, check the amount and pay. You get a receipt number straight away.",
        "Fees that can be paid online include land lease, permits, certificates, tender documents, sign permits, market stall rent and boat trips.",
        "Water and electricity bills are paid to the utilities, not to the city."])
    add("track-howto", "help", "How to track a request", "/track", [
        "Every request, report, booking and complaint gets a reference number such as BTU-R-2611-AB12.",
        "Enter it on the Track a request page to see its status and history."])
    add("assistant-about", "help", "About the Ask Batu assistant", "/assistant", [
        "Ask Batu answers only from the city's published pages and shows its sources.",
        "It does not give legal advice and does not take payments or personal data.",
        "If it cannot find an answer it says so and points to the right office."])
    return docs
