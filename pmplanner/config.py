from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

_cache: dict | None = None


def load_config(reload: bool = False) -> dict:
    global _cache
    if _cache is None or reload:
        _cache = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _cache


def holidays() -> set[date]:
    return {date.fromisoformat(d) for d in load_config()["holidays"]}


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays()


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if is_business_day(d):
            left -= 1
    return d


def business_days_between(a: date, b: date) -> int:
    """Whole business days from a (exclusive) to b (inclusive); negative if b < a."""
    if a == b:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if sign == 1 else (b, a)
    n, d = 0, lo
    while d < hi:
        d += timedelta(days=1)
        if is_business_day(d):
            n += 1
    return n * sign


def parse_dt(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))
