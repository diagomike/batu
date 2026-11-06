"""SQLite storage for requests, payments, pushed news and the assistant log."""
from __future__ import annotations

import datetime as dt
import json
import secrets
import sqlite3
import threading
from pathlib import Path

from . import content

DB_PATH = content.ROOT / "var" / "batu.db"
_lock = threading.Lock()

SCHEMA = """
create table if not exists requests (
  ref text primary key,
  kind text not null,            -- report, complaint, booking, application, visit, bill
  service_id text,
  title text,
  data text not null,            -- json
  status text not null,
  amount real,
  paid integer not null default 0,
  created text not null,
  updated text not null,
  history text not null          -- json list of {at, status, note}
);
create table if not exists payments (
  id text primary key,
  request_ref text not null,
  amount real not null,
  provider text not null,
  status text not null,          -- pending, paid, failed
  created text not null,
  receipt text
);
create table if not exists news (
  id text primary key,
  date text not null,
  category text,
  title text not null,
  summary text,
  body text,
  source text,
  url text,
  image text,
  kind text not null default 'news',   -- news or notice
  sample integer not null default 0,
  created_via text not null default 'seed'
);
create table if not exists ask_log (
  id integer primary key autoincrement,
  at text not null,
  lang text,
  question text,
  mode text,
  found integer,
  sources text,
  ms integer
);
create table if not exists subscriptions (
  id integer primary key autoincrement,
  at text not null,
  channel text not null,
  contact text not null,
  topics text
);
"""

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


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


_con = None


def con():
    global _con
    if _con is None:
        _con = connect()
        _con.executescript(SCHEMA)
        _seed()
    return _con


def _seed():
    c = _con
    if c.execute("select count(*) from news").fetchone()[0] == 0:
        seed = content.news_seed()
        for n in seed["news"]:
            c.execute(
                "insert into news(id,date,category,title,summary,body,source,url,image,kind,sample,created_via) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                (n["id"], n["date"], n["category"], n["title"], n["summary"], n["body"], n["source"], n["url"], n.get("image"), "news", 0, "seed"),
            )
        for n in seed["notices"]:
            c.execute(
                "insert into news(id,date,category,title,summary,body,source,url,image,kind,sample,created_via) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                (n["id"], n["date"], n["kind"], n["title"], n["text"], n["text"], "City of Batu", "", None, "notice", 1 if n.get("sample") else 0, "seed"),
            )
        # A sample bill so the payment flow can be tried end to end.
        _insert_request("LL-BTU-0001", "bill", "land-lease-payment", "Land lease instalment 2019 E.C. (sample bill)",
                        {"holder": "Sample land holder", "plot": "Plot B-114 (sample)"}, "awaiting_payment", 4200)
        c.commit()


def new_ref(prefix: str) -> str:
    stamp = dt.date.today().strftime("%y%m")
    return f"BTU-{prefix}-{stamp}-{secrets.token_hex(2).upper()}"


def _insert_request(ref, kind, service_id, title, data, status, amount=None):
    t = now()
    history = [{"at": t, "status": status, "note": "Request received" if status != "awaiting_payment" else "Bill issued"}]
    _con.execute(
        "insert or ignore into requests(ref,kind,service_id,title,data,status,amount,paid,created,updated,history) values(?,?,?,?,?,?,?,?,?,?,?)",
        (ref, kind, service_id, title, json.dumps(data, ensure_ascii=False), status, amount, 0, t, t, json.dumps(history)),
    )


def create_request(kind: str, prefix: str, service_id: str | None, title: str, data: dict, amount: float | None = None) -> str:
    ref = new_ref(prefix)
    status = "awaiting_payment" if amount else "received"
    with _lock:
        _insert_request(ref, kind, service_id, title, data, status, amount)
        con().commit()
    return ref


def get_request(ref: str):
    row = con().execute("select * from requests where upper(ref)=upper(?)", (ref.strip(),)).fetchone()
    if not row:
        return None
    r = dict(row)
    r["data"] = json.loads(r["data"])
    r["history"] = json.loads(r["history"])
    r["status_label"] = STATUS_LABELS.get(r["status"], r["status"])
    return r


def set_status(ref: str, status: str, note: str = ""):
    r = get_request(ref)
    if not r:
        return False
    hist = r["history"] + [{"at": now(), "status": status, "note": note or STATUS_LABELS.get(status, status)}]
    with _lock:
        con().execute("update requests set status=?, updated=?, history=? where ref=?", (status, now(), json.dumps(hist), r["ref"]))
        con().commit()
    return True


def list_requests(limit=100):
    rows = con().execute("select ref,kind,title,status,amount,paid,created from requests order by created desc limit ?", (limit,)).fetchall()
    return [dict(r) | {"status_label": STATUS_LABELS.get(r["status"], r["status"])} for r in rows]


def create_payment(request_ref: str, amount: float, provider: str) -> str:
    pid = "PAY-" + secrets.token_hex(4).upper()
    with _lock:
        con().execute("insert into payments(id,request_ref,amount,provider,status,created) values(?,?,?,?,?,?)",
                      (pid, request_ref, amount, provider, "pending", now()))
        con().commit()
    return pid


def get_payment(pid: str):
    row = con().execute("select * from payments where id=?", (pid,)).fetchone()
    return dict(row) if row else None


def complete_payment(pid: str) -> str | None:
    p = get_payment(pid)
    if not p or p["status"] == "paid":
        return p and p["receipt"]
    receipt = "RCT-" + secrets.token_hex(4).upper()
    with _lock:
        con().execute("update payments set status='paid', receipt=? where id=?", (receipt, pid))
        con().execute("update requests set paid=1 where ref=?", (p["request_ref"],))
        con().commit()
    r = get_request(p["request_ref"])
    if r:
        next_status = "scheduled" if r["kind"] == "booking" else ("closed" if r["kind"] == "bill" else "in_review")
        set_status(r["ref"], "paid", f"Payment received, receipt {receipt}")
        set_status(r["ref"], next_status, "")
    return receipt


def list_news(kind="news", limit=50):
    rows = con().execute("select * from news where kind=? order by date desc limit ?", (kind, limit)).fetchall()
    return [dict(r) for r in rows]


def get_news(nid: str):
    row = con().execute("select * from news where id=?", (nid,)).fetchone()
    return dict(row) if row else None


def add_news(item: dict, kind="news", via="api") -> str:
    nid = item.get("id") or f"{kind}-{dt.date.today().isoformat()}-{secrets.token_hex(2)}"
    with _lock:
        con().execute(
            "insert or replace into news(id,date,category,title,summary,body,source,url,image,kind,sample,created_via) values(?,?,?,?,?,?,?,?,?,?,?,?)",
            (nid, item.get("date") or dt.date.today().isoformat(), item.get("category", "City"), item["title"],
             item.get("summary", ""), item.get("body", item.get("summary", "")), item.get("source", "City of Batu"),
             item.get("url", ""), item.get("image"), kind, 1 if item.get("sample") else 0, via),
        )
        con().commit()
    return nid


def delete_news(nid: str):
    with _lock:
        con().execute("delete from news where id=?", (nid,))
        con().commit()


def log_ask(lang, question, mode, found, sources, ms):
    with _lock:
        con().execute("insert into ask_log(at,lang,question,mode,found,sources,ms) values(?,?,?,?,?,?,?)",
                      (now(), lang, question, mode, 1 if found else 0, json.dumps(sources), ms))
        con().commit()


def recent_asks(limit=30):
    return [dict(r) for r in con().execute("select * from ask_log order by id desc limit ?", (limit,)).fetchall()]


def add_subscription(channel, contact, topics):
    with _lock:
        con().execute("insert into subscriptions(at,channel,contact,topics) values(?,?,?,?)", (now(), channel, contact, topics))
        con().commit()
