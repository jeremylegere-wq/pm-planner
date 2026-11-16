"""SQLite store. Source fields come from the report and are overwritten on refresh;
planning fields (status, schedule, engineer, contact history) are owned by this app and survive refreshes."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .config import ROOT
from . import connector

DB_PATH = ROOT / "data" / "planner.db"

SOURCE_FIELDS = ["wo_number", "case_number", "account", "address", "suburb", "state", "postcode", "region",
                 "system_id", "serial", "product", "category", "msa_number", "contract_start", "contract_end",
                 "pm_due", "pm_sequence", "duration_hrs", "priority", "sf_status", "contact_name",
                 "contact_email", "contact_phone", "lat", "lon"]
PLAN_FIELDS = ["plan_status", "start", "end", "engineer", "offer_sent", "last_contact", "attempts",
               "decline_reason", "notes", "in_source", "first_seen", "last_letter"]

STATUSES = ["Unplanned", "Proposed", "Offered", "Confirmed", "Reschedule", "Declined", "Completed", "Closed"]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS work_orders (
  wo_number TEXT PRIMARY KEY,
  {', '.join(f + (' REAL' if f in ('duration_hrs', 'lat', 'lon') else ' TEXT') for f in SOURCE_FIELDS if f != 'wo_number')},
  plan_status TEXT DEFAULT 'Unplanned', start TEXT, end TEXT, engineer TEXT,
  offer_sent TEXT, last_contact TEXT, attempts INTEGER DEFAULT 0, decline_reason TEXT, notes TEXT,
  in_source INTEGER DEFAULT 1, first_seen TEXT, last_letter TEXT
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, wo_number TEXT, kind TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    have = {r["name"] for r in c.execute("PRAGMA table_info(work_orders)")}
    for f in ("lat", "lon"):  # migrate databases created before map support
        if f not in have:
            c.execute(f"ALTER TABLE work_orders ADD COLUMN {f} REAL")
    return c


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def log(c, wo: str, kind: str, detail: str = "") -> None:
    c.execute("INSERT INTO activity(ts,wo_number,kind,detail) VALUES (?,?,?,?)", (now(), wo, kind, detail))


def refresh_from_source() -> dict:
    """Pull the report and upsert. Returns counts."""
    rows = connector.fetch()
    c = conn()
    existing = {r["wo_number"] for r in c.execute("SELECT wo_number FROM work_orders")}
    seen, added, updated = set(), 0, 0
    for r in rows:
        wo = r["wo_number"]
        seen.add(wo)
        if wo in existing:
            sets = ", ".join(f"{f}=?" for f in SOURCE_FIELDS if f != "wo_number")
            c.execute(f"UPDATE work_orders SET {sets}, in_source=1 WHERE wo_number=?",
                      [r[f] for f in SOURCE_FIELDS if f != "wo_number"] + [wo])
            updated += 1
        else:
            cols = SOURCE_FIELDS + ["first_seen", "plan_status"]
            c.execute(f"INSERT INTO work_orders({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [r[f] for f in SOURCE_FIELDS] + [now(), "Unplanned"])
            log(c, wo, "imported", "New in report")
            added += 1
    gone = existing - seen
    for wo in gone:
        c.execute("UPDATE work_orders SET in_source=0 WHERE wo_number=?", (wo,))
        row = c.execute("SELECT plan_status FROM work_orders WHERE wo_number=?", (wo,)).fetchone()
        if row["plan_status"] in ("Confirmed", "Offered", "Proposed"):
            c.execute("UPDATE work_orders SET plan_status='Completed' WHERE wo_number=?", (wo,))
            log(c, wo, "completed", "Dropped out of the open-PM report - treated as completed")
    c.execute("INSERT OR REPLACE INTO meta VALUES ('last_refresh', ?)", (now(),))
    c.commit()
    c.close()
    return {"rows": len(rows), "added": added, "updated": updated, "removed": len(gone)}


def all_orders(include_gone: bool = False) -> list[dict]:
    c = conn()
    q = "SELECT * FROM work_orders" + ("" if include_gone else " WHERE in_source=1 OR plan_status='Completed'")
    rows = [dict(r) for r in c.execute(q + " ORDER BY pm_due, account")]
    c.close()
    return rows


def get(wo: str) -> dict | None:
    c = conn()
    r = c.execute("SELECT * FROM work_orders WHERE wo_number=?", (wo,)).fetchone()
    c.close()
    return dict(r) if r else None


def update(wo: str, fields: dict, kind: str | None = None, detail: str = "") -> dict:
    allowed = set(PLAN_FIELDS)
    fields = {k: v for k, v in fields.items() if k in allowed}
    c = conn()
    if fields:
        c.execute(f"UPDATE work_orders SET {', '.join(f'{k}=?' for k in fields)} WHERE wo_number=?",
                  list(fields.values()) + [wo])
    if kind:
        log(c, wo, kind, detail)
    c.commit()
    r = dict(c.execute("SELECT * FROM work_orders WHERE wo_number=?", (wo,)).fetchone())
    c.close()
    return r


def activity(wo: str | None = None, limit: int = 60) -> list[dict]:
    c = conn()
    if wo:
        rows = c.execute("SELECT * FROM activity WHERE wo_number=? ORDER BY id DESC LIMIT ?", (wo, limit))
    else:
        rows = c.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))
    out = [dict(r) for r in rows]
    c.close()
    return out


def meta(k: str) -> str | None:
    c = conn()
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    c.close()
    return r["v"] if r else None


def reset() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
