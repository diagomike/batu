"""Requests, payments, sign-ups, the assistant log and residents' photos.

Stored through app/database.py: PostgreSQL in production (DATABASE_URL), SQLite at DB_PATH
otherwise. The function names and the shapes they return are the same as before the move to
SQLAlchemy, so pages, the studio and the assistant did not have to change.
"""
from __future__ import annotations

import datetime as dt
import secrets
import threading

from sqlalchemy import delete, func, insert, select, update

from . import content
from . import database as D

DB_PATH = content.ROOT / "var" / "batu.db"  # SQLite file when DATABASE_URL is not set

STATUS_LABELS = {
    "received": "Received",
    "in_review": "In review",
    "awaiting_payment": "Awaiting payment",
    "paid": "Paid",
    "scheduled": "Scheduled",
    "in_progress": "Work in progress",
    "ready": "Ready to collect",
    "resolved": "Resolved",
    "closed": "Closed",
    "rejected": "Not approved",
}


def now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


_ready = False
_ready_lock = threading.Lock()


def con():
    """Make sure the database is migrated and seeded; returns the engine."""
    global _ready
    with _ready_lock:
        if not _ready:
            D.migrate()
            _seed()
            _ready = True
    return D.engine()


def _seed():
    from . import store
    store.sync_from_files()
    # A sample bill so the payment flow can be tried end to end.
    with D.engine().begin() as c:
        if not c.execute(select(D.requests.c.ref).where(D.requests.c.ref == "LL-BTU-0001")).first():
            _insert_request(c, "LL-BTU-0001", "bill", "land-lease-payment", "Land lease instalment 2019 E.C. (sample bill)",
                            {"holder": "Sample land holder", "plot": "Plot B-114 (sample)"}, "awaiting_payment", 4200)


def new_ref(prefix: str) -> str:
    stamp = dt.date.today().strftime("%y%m")
    return f"BTU-{prefix}-{stamp}-{secrets.token_hex(2).upper()}"


def _insert_request(c, ref, kind, service_id, title, data, status, amount=None):
    t = now()
    history = [{"at": t, "status": status, "note": "Request received" if status != "awaiting_payment" else "Bill issued"}]
    c.execute(insert(D.requests).values(ref=ref, kind=kind, service_id=service_id, title=title, data=data, status=status,
                                        amount=amount, paid=False, created=t, updated=t, history=history))


def create_request(kind: str, prefix: str, service_id: str | None, title: str, data: dict, amount: float | None = None) -> str:
    con()
    status = "awaiting_payment" if amount else "received"
    for _ in range(6):
        ref = new_ref(prefix)
        with D.engine().begin() as c:
            if c.execute(select(D.requests.c.ref).where(D.requests.c.ref == ref)).first():
                continue  # reference taken this month; draw another
            _insert_request(c, ref, kind, service_id, title, data, status, amount)
            return ref
    raise RuntimeError("could not find a free reference number")


def _row(r) -> dict:
    d = dict(r._mapping)
    d["paid"] = 1 if d.get("paid") else 0
    d["status_label"] = STATUS_LABELS.get(d["status"], d["status"])
    return d


def get_request(ref: str):
    con()
    with D.engine().connect() as c:
        r = c.execute(select(D.requests).where(func.upper(D.requests.c.ref) == (ref or "").strip().upper())).first()
    if not r:
        return None
    d = _row(r)
    d["data"] = d["data"] or {}
    d["history"] = d["history"] or []
    return d


def set_status(ref: str, status: str, note: str = ""):
    r = get_request(ref)
    if not r:
        return False
    hist = r["history"] + [{"at": now(), "status": status, "note": note or STATUS_LABELS.get(status, status)}]
    with D.engine().begin() as c:
        c.execute(update(D.requests).where(D.requests.c.ref == r["ref"]).values(status=status, updated=now(), history=hist))
    return True


def list_requests(limit=100):
    con()
    t = D.requests.c
    with D.engine().connect() as c:
        rows = c.execute(select(t.ref, t.kind, t.title, t.status, t.amount, t.paid, t.created)
                         .order_by(t.created.desc()).limit(limit)).all()
    return [_row(r) for r in rows]


def create_payment(request_ref: str, amount: float, provider: str) -> str:
    con()
    pid = "PAY-" + secrets.token_hex(4).upper()
    with D.engine().begin() as c:
        c.execute(insert(D.payments).values(id=pid, request_ref=request_ref, amount=amount, provider=provider,
                                            status="pending", created=now()))
    return pid


def get_payment(pid: str):
    con()
    with D.engine().connect() as c:
        r = c.execute(select(D.payments).where(D.payments.c.id == pid)).first()
    return dict(r._mapping) if r else None


def complete_payment(pid: str) -> str | None:
    p = get_payment(pid)
    if not p or p["status"] == "paid":
        return p and p["receipt"]
    receipt = "RCT-" + secrets.token_hex(4).upper()
    with D.engine().begin() as c:
        c.execute(update(D.payments).where(D.payments.c.id == pid).values(status="paid", receipt=receipt))
        c.execute(update(D.requests).where(D.requests.c.ref == p["request_ref"]).values(paid=True))
    r = get_request(p["request_ref"])
    if r:
        next_status = "scheduled" if r["kind"] == "booking" else ("closed" if r["kind"] == "bill" else "in_review")
        set_status(r["ref"], "paid", f"Payment received, receipt {receipt}")
        set_status(r["ref"], next_status, "")
    return receipt


def list_payments(limit=200):
    con()
    with D.engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(select(D.payments).order_by(D.payments.c.created.desc()).limit(limit))]


# ---------- news and notices: kept under their old names; the data is a content document ----------
def list_news(kind="news", limit=50):
    from . import store
    return store.list_news(kind, limit)


def get_news(nid: str):
    from . import store
    return store.get_news(nid)


def add_news(item: dict, kind="news", via="api") -> str:
    from . import store
    return store.add_news(item, kind=kind, via=via)


def delete_news(nid: str):
    from . import store
    store.delete_news(nid)


# ---------- assistant log ----------
def log_ask(lang, question, mode, found, sources, ms):
    con()
    with D.engine().begin() as c:
        c.execute(insert(D.ask_log).values(at=now(), lang=lang, question=question, mode=mode, found=bool(found),
                                           sources=list(sources or []), ms=ms))


def recent_asks(limit=30):
    con()
    with D.engine().connect() as c:
        rows = c.execute(select(D.ask_log).order_by(D.ask_log.c.id.desc()).limit(limit)).all()
    return [dict(r._mapping) | {"found": 1 if r.found else 0} for r in rows]


def asks_since(since_iso: str, mode: str | None = None) -> int:
    """How many questions since a time (optionally of one mode), e.g. for a daily AI limit."""
    con()
    q = select(func.count()).select_from(D.ask_log).where(D.ask_log.c.at >= since_iso)
    if mode:
        q = q.where(D.ask_log.c.mode == mode)
    with D.engine().connect() as c:
        return c.execute(q).scalar_one()


# ---------- notice sign-ups ----------
def add_subscription(channel, contact, topics):
    con()
    with D.engine().begin() as c:
        c.execute(insert(D.subscriptions).values(at=now(), channel=channel, contact=contact, topics=topics))


def list_subscriptions(limit=500):
    con()
    with D.engine().connect() as c:
        rows = c.execute(select(D.subscriptions).order_by(D.subscriptions.c.id.desc()).limit(limit)).all()
    return [dict(r._mapping) for r in rows]


def delete_subscription(sid: int):
    with D.engine().begin() as c:
        c.execute(delete(D.subscriptions).where(D.subscriptions.c.id == sid))


# ---------- photos residents attach to reports ----------
def save_upload(name: str, data: bytes, content_type: str):
    con()
    with D.engine().begin() as c:
        c.execute(insert(D.uploads).values(name=name, data=data, content_type=content_type, created=now()))


def get_upload(name: str):
    con()
    with D.engine().connect() as c:
        r = c.execute(select(D.uploads).where(D.uploads.c.name == name)).first()
    return dict(r._mapping) if r else None
