"""Scheduling rules, auto-planner, next-letter suggestions and dashboard statistics."""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from .config import (add_business_days, business_days_between, holidays, is_business_day, load_config)
from . import store

SLOT = 30  # minutes
OPEN_STATUSES = {"Unplanned", "Proposed", "Offered", "Confirmed", "Reschedule"}
DECLINE_REASONS = ["Asset in use - not available", "Asset decommissioned / removed", "Asset damaged / awaiting repair",
                   "Access not available at scheduled time"]


# ---------------------------------------------------------------- calendar helpers
def work_window() -> tuple[time, time, float]:
    w = load_config()["work_day"]
    return time.fromisoformat(w["start"]), time.fromisoformat(w["end"]), float(w["capacity_hrs"])


def engineers() -> list[dict]:
    return load_config()["engineers"]


def leave_for(eng: str, d: date) -> str | None:
    for l in load_config()["leave"]:
        if l["engineer"] == eng and date.fromisoformat(l["from"]) <= d <= date.fromisoformat(l["to"]):
            return l["label"]
    return None


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _planned(orders: list[dict], exclude: str | None = None):
    for o in orders:
        if o["wo_number"] != exclude and o["start"] and o["engineer"] and o["plan_status"] in OPEN_STATUSES:
            yield o


# ---------------------------------------------------------------- validation (used by drag & drop)
def check_slot(orders: list[dict], wo: dict, start: datetime, end: datetime, eng: str) -> list[dict]:
    """Return a list of {level, msg}. level 'error' = rule break the UI should flag in red."""
    out: list[dict] = []
    ws, we, cap = work_window()
    d = start.date()
    if d.weekday() >= 5:
        out.append({"level": "error", "msg": "Weekend"})
    elif d in holidays():
        out.append({"level": "error", "msg": "Public holiday"})
    lv = leave_for(eng, d)
    if lv:
        out.append({"level": "error", "msg": f"{eng_name(eng)} is on leave ({lv})"})
    if start.time() < ws or end.time() > we or end.date() != d:
        out.append({"level": "warn", "msg": f"Outside working hours {ws:%H:%M}-{we:%H:%M}"})
    e = next((x for x in engineers() if x["id"] == eng), None)
    if e and wo["category"] not in e["skills"]:
        out.append({"level": "error", "msg": f"{e['name']} is not skilled for {wo['category']}"})
    day_hours = (end - start).total_seconds() / 3600
    for o in _planned(orders, exclude=wo["wo_number"]):
        if o["engineer"] != eng:
            continue
        s2, e2 = _dt(o["start"]), _dt(o["end"])
        if s2.date() == d:
            day_hours += (e2 - s2).total_seconds() / 3600
            if s2 < end and start < e2:
                out.append({"level": "error", "msg": f"Overlaps {o['wo_number']} ({o['account']})"})
    if day_hours > cap + 0.01:
        out.append({"level": "warn", "msg": f"Day booked {day_hours:.1f}h (capacity {cap:.0f}h)"})
    due = date.fromisoformat(wo["pm_due"])
    if d > due:
        out.append({"level": "warn", "msg": f"After PM due date ({due:%d %b %Y}) by {(d - due).days} days"})
    return out


def eng_name(eid: str) -> str:
    return next((e["name"] for e in engineers() if e["id"] == eid), eid)


# ---------------------------------------------------------------- auto-planner
def _free_start(busy: list[tuple[datetime, datetime]], day: date, dur: float) -> datetime | None:
    ws, we, cap = work_window()
    t = datetime.combine(day, ws)
    limit = datetime.combine(day, we)
    need = timedelta(hours=dur)
    booked = sum((e - s).total_seconds() for s, e in busy) / 3600
    if booked + dur > cap + 0.01:
        return None
    for s, e in sorted(busy):
        if t + need <= s:
            break
        t = max(t, e)
    return t if t + need <= limit else None


def autoplan(orders: list[dict], wo_numbers: list[str], from_date: date, lead_days: int = 0,
             cluster: bool = True, horizon_days: int = 120) -> dict:
    """Place the given work orders on engineers' calendars.

    Heuristic: most urgent customer first; try to keep one customer's assets on the same day with the same
    engineer (less travel, one site visit); prefer engineers from the same service territory; earliest
    feasible day inside the horizon, honouring skills, leave, holidays and daily capacity.
    """
    targets = [o for o in orders if o["wo_number"] in set(wo_numbers)]
    busy: dict[tuple[str, date], list[tuple[datetime, datetime]]] = defaultdict(list)
    for o in _planned(orders):
        if o["wo_number"] in set(wo_numbers):
            continue
        s, e = _dt(o["start"]), _dt(o["end"])
        busy[(o["engineer"], s.date())].append((s, e))
    load: dict[str, float] = defaultdict(float)
    for (eng, _d), iv in busy.items():
        load[eng] += sum((e - s).total_seconds() for s, e in iv) / 3600

    groups: dict[str, list[dict]] = defaultdict(list)
    for o in targets:
        groups[o["account"]].append(o)
    ordered = sorted(groups.values(), key=lambda g: min(x["pm_due"] for x in g))
    first_day = add_business_days(from_date, lead_days) if lead_days else from_date
    placed, failed = [], []
    for grp in ordered:
        grp.sort(key=lambda x: -x["duration_hrs"])
        group_days: dict[date, str] = {}  # day -> engineer already visiting this customer
        for o in grp:
            best = None
            due = date.fromisoformat(o["pm_due"])
            for e in engineers():
                if o["category"] not in e["skills"]:
                    continue
                region_pen = 0 if e["home"] == o["region"] else (6 if "Regional" in (e["home"], o["region"]) else 2)
                target = max(first_day, due - timedelta(days=10))  # aim to land ~10 days before the PM falls due
                for off in range(horizon_days):
                    d = first_day + timedelta(days=off)
                    if not is_business_day(d) or leave_for(e["id"], d):
                        continue
                    st = _free_start(busy[(e["id"], d)], d, o["duration_hrs"])
                    if not st:
                        continue
                    same_visit = cluster and group_days.get(d) == e["id"]
                    late = max(0, (d - due).days)
                    cost = (region_pen + abs((d - target).days) * 0.25 + late * 0.6 + load[e["id"]] * 0.02
                            - (4 if same_visit else 0))
                    if not best or cost < best[0]:
                        best = (cost, e["id"], st)
                    if d > target + timedelta(days=21) and best:
                        break
            if not best:
                failed.append(o["wo_number"])
                continue
            _c, eid, st = best
            en = st + timedelta(hours=o["duration_hrs"])
            busy[(eid, st.date())].append((st, en))
            load[eid] += o["duration_hrs"]
            group_days[st.date()] = eid
            placed.append({"wo_number": o["wo_number"], "engineer": eid,
                           "start": st.isoformat(), "end": en.isoformat()})
    return {"placed": placed, "failed": failed}


# ---------------------------------------------------------------- next-best letter
def attempts_age(o: dict, today: date) -> int:
    ref = o["last_contact"] or o["offer_sent"]
    return business_days_between(date.fromisoformat(ref[:10]), today) if ref else 0


def suggest(o: dict, today: date) -> dict | None:
    """What should the coordinator do next with this work order?"""
    st = o["plan_status"]
    hold = load_config()["offer_hold_business_days"]
    due = date.fromisoformat(o["pm_due"])
    days_to_due = (due - today).days
    if st == "Unplanned":
        if days_to_due <= 30:
            return {"action": "plan_urgent", "label": "Plan now (due within 30 days)" if days_to_due >= 0 else
                    "Overdue - plan now", "letter": None, "urgency": 0 if days_to_due < 0 else 1}
        return None
    if st == "Proposed":
        return {"action": "send_offer", "label": "Ready to send booking request", "letter": "booking_request",
                "urgency": 2}
    if st == "Offered":
        age = attempts_age(o, today)
        if age >= hold:
            n = o["attempts"] or 1
            if n == 1:
                return {"action": "follow_up", "label": f"No reply after {age} business days", "letter": "follow_up",
                        "urgency": 1}
            if n == 2:
                return {"action": "third_attempt", "label": f"Second chase unanswered ({age} bd)",
                        "letter": "third_attempt", "urgency": 1}
            return {"action": "close", "label": "Final attempt unanswered - close request",
                    "letter": "declination", "urgency": 2}
        return None
    if st == "Reschedule":
        return {"action": "reschedule", "label": "Customer / technician needs a new date", "letter": "reschedule",
                "urgency": 1}
    if st == "Declined":
        return {"action": "declination_form", "label": "Send declination form for signature",
                "letter": "declination", "urgency": 3}
    if st == "Confirmed" and 0 <= (_dt(o["start"]).date() - today).days <= 7 if o["start"] else False:
        return {"action": "upcoming", "label": "Service within 7 days", "letter": None, "urgency": 4}
    if st == "Completed" and o["last_letter"] != "site_closure":
        return {"action": "closure", "label": "Send site closure summary", "letter": "site_closure", "urgency": 4}
    return None


# ---------------------------------------------------------------- dashboard
def dashboard(today: date | None = None, region: str | None = None, account: str | None = None) -> dict:
    today = today or date.today()
    everything = store.all_orders()
    orders = [o for o in everything if (not region or o["region"] == region) and (not account or o["account"] == account)]
    open_ = [o for o in orders if o["plan_status"] in OPEN_STATUSES]
    by_status = defaultdict(int)
    for o in orders:
        by_status[o["plan_status"]] += 1

    overdue = [o for o in open_ if date.fromisoformat(o["pm_due"]) < today and o["plan_status"] != "Confirmed"]
    offered = [o for o in orders if o["offer_sent"]]
    responded = [o for o in offered if o["plan_status"] in ("Confirmed", "Completed", "Reschedule", "Declined")]
    confirmed_rate = (sum(1 for o in responded if o["plan_status"] in ("Confirmed", "Completed")) / len(offered)
                      if offered else 0)

    # month buckets of PM due date
    months: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for o in orders:
        if o["plan_status"] == "Closed":
            continue
        key = o["pm_due"][:7]
        grp = {"Unplanned": "Unplanned", "Proposed": "Proposed", "Offered": "Offered", "Reschedule": "Offered",
               "Confirmed": "Confirmed", "Completed": "Completed", "Declined": "Declined"}[o["plan_status"]]
        months[key][grp] += 1
    month_rows = [{"month": m, **v} for m, v in sorted(months.items())]

    # offer ageing
    ageing = {"0-2 days": 0, "3-5 days": 0, "6-10 days": 0, "11+ days": 0}
    for o in orders:
        if o["plan_status"] == "Offered":
            a = attempts_age(o, today)
            ageing["0-2 days" if a <= 2 else "3-5 days" if a <= 5 else "6-10 days" if a <= 10 else "11+ days"] += 1

    # engineer utilisation for the next 4 weeks
    _ws, _we, cap = work_window()
    util = []
    horizon_end = today + timedelta(days=28)
    for e in engineers():
        days = [today + timedelta(days=i) for i in range(28)]
        avail = sum(cap for d in days if is_business_day(d) and not leave_for(e["id"], d))
        booked = 0.0
        for o in _planned(everything):
            if o["engineer"] == e["id"]:
                s = _dt(o["start"])
                if today <= s.date() < horizon_end:
                    booked += (_dt(o["end"]) - s).total_seconds() / 3600
        util.append({"id": e["id"], "name": e["name"], "home": e["home"], "booked": round(booked, 1),
                     "available": avail, "pct": round(100 * booked / avail) if avail else 0})

    mod_counts = defaultdict(int)
    for o in open_:
        mod_counts[o["category"]] += 1
    region_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for o in open_:
        region_status[o["region"]][o["plan_status"]] += 1

    # action queue grouped by customer + action
    queue: dict[tuple, dict] = {}
    for o in orders:
        s = suggest(o, today)
        if not s:
            continue
        k = (o["account"], s["action"])
        q = queue.setdefault(k, {**s, "account": o["account"], "wos": [], "earliest_due": o["pm_due"],
                                 "contact": o["contact_email"]})
        q["wos"].append(o["wo_number"])
        q["earliest_due"] = min(q["earliest_due"], o["pm_due"])
    actions = sorted(queue.values(), key=lambda q: (q["urgency"], q["earliest_due"]))
    action_counts = defaultdict(int)
    for q in actions:
        action_counts[q["action"]] += len(q["wos"])

    # upcoming confirmed visits (next 14 days)
    upcoming = []
    for o in orders:
        if o["plan_status"] in ("Confirmed", "Offered", "Proposed") and o["start"]:
            s = _dt(o["start"])
            if today <= s.date() <= today + timedelta(days=14):
                upcoming.append({"wo": o["wo_number"], "account": o["account"], "category": o["category"],
                                 "start": o["start"], "engineer": eng_name(o["engineer"]), "status": o["plan_status"]})
    upcoming.sort(key=lambda x: x["start"])

    return {
        "today": today.isoformat(), "filter": {"region": region, "account": account},
        "last_refresh": store.meta("last_refresh"),
        "kpis": {
            "open": len(open_), "unplanned": by_status["Unplanned"], "proposed": by_status["Proposed"],
            "offered": by_status["Offered"], "confirmed": by_status["Confirmed"],
            "reschedule": by_status["Reschedule"], "declined": by_status["Declined"],
            "completed": by_status["Completed"], "overdue": len(overdue),
            "confirm_rate": round(100 * confirmed_rate), "follow_ups": action_counts["follow_up"]
            + action_counts["third_attempt"] + action_counts["close"],
        },
        "months": month_rows, "ageing": ageing, "utilisation": util,
        "category": dict(mod_counts), "region": {k: dict(v) for k, v in region_status.items()},
        "actions": actions[:40], "action_total": len(actions), "upcoming": upcoming[:25],
    }


# ---------------------------------------------------------------- demo workflow seeding
def seed_demo_states(seed: int = 7, today: date | None = None) -> None:
    """Give the freshly imported mock data a believable mid-flight workflow so the dashboard has something to show."""
    today = today or date.today()
    rnd = random.Random(seed)
    orders = store.all_orders()
    soon = [o for o in orders if date.fromisoformat(o["pm_due"]) <= today + timedelta(days=75)]
    past = [o for o in soon if date.fromisoformat(o["pm_due"]) < today]
    future = [o for o in soon if o not in past]

    # past-due: mostly completed on time, a few stragglers
    for o in past:
        r = rnd.random()
        if r < 0.62:
            _set(o, "Completed", date.fromisoformat(o["pm_due"]) - timedelta(days=rnd.randint(0, 6)), orders, rnd, today)
        elif r < 0.75:
            store.update(o["wo_number"], {"plan_status": "Offered", "offer_sent": (today - timedelta(days=rnd.randint(14, 24))).isoformat(),
                                          "last_contact": (today - timedelta(days=rnd.randint(8, 16))).isoformat(),
                                          "attempts": 3})

    # future: plan most, with a funnel shape - the closer to due the further along
    pool = [o["wo_number"] for o in future if rnd.random() < 0.78]
    plan = autoplan(orders, pool, today + timedelta(days=1))
    placed = {p["wo_number"]: p for p in plan["placed"]}
    for o in future:
        p = placed.get(o["wo_number"])
        if not p:
            continue
        days_out = (date.fromisoformat(p["start"][:10]) - today).days
        r = rnd.random()
        fields = {"engineer": p["engineer"], "start": p["start"], "end": p["end"]}
        if days_out <= 14:
            status = "Confirmed" if r < 0.7 else "Offered" if r < 0.88 else "Reschedule" if r < 0.94 else "Declined"
        elif days_out <= 35:
            status = "Confirmed" if r < 0.35 else "Offered" if r < 0.8 else "Proposed" if r < 0.93 else "Reschedule"
        else:
            status = "Proposed" if r < 0.7 else "Offered" if r < 0.9 else "Confirmed"
        fields["plan_status"] = status
        if status in ("Offered", "Confirmed", "Reschedule", "Declined"):
            n = rnd.choices([1, 2, 3], [60, 28, 12])[0] if status == "Offered" else 1
            sent = today - timedelta(days=rnd.randint(1, 8) + (n - 1) * 8)
            fields.update(offer_sent=sent.isoformat(), attempts=n,
                          last_contact=(sent + timedelta(days=(n - 1) * 8 + (0 if status == "Offered" else 3))).isoformat(),
                          last_letter="booking_request" if n == 1 else "follow_up")
        if status == "Declined":
            fields["decline_reason"] = rnd.choice(DECLINE_REASONS)
        store.update(o["wo_number"], fields, "seeded", f"Demo state {status}")


def _set(o, status, when: date, orders, rnd, today):
    eng = rnd.choice([e for e in engineers() if o["category"] in e["skills"]] or engineers())
    ws, _we, _c = work_window()
    st = datetime.combine(when if is_business_day(when) else add_business_days(when, -1), ws) + timedelta(hours=rnd.choice([0, 0, 2, 4]))
    en = st + timedelta(hours=o["duration_hrs"])
    sent = st.date() - timedelta(days=rnd.randint(12, 20))
    store.update(o["wo_number"], {"plan_status": status, "engineer": eng["id"], "start": st.isoformat(),
                                  "end": en.isoformat(), "offer_sent": sent.isoformat(),
                                  "last_contact": sent.isoformat(), "attempts": 1,
                                  "last_letter": "site_closure" if rnd.random() < 0.5 else "booking_request"},
                 "seeded", "Demo completed PM")
