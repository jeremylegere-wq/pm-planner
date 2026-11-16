from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import letters, outlook, planner, store
from .config import ROOT, load_config, holidays

app = Flask(__name__, static_folder=str(ROOT / "web"), static_url_path="")
app.json.sort_keys = False


def _today() -> date:
    return date.today()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/favicon.ico")
def favicon():
    return ("", 204)


@app.get("/api/bootstrap")
def bootstrap():
    cfg = load_config()
    return jsonify({
        "company": cfg["company"], "engineers": cfg["engineers"], "leave": cfg["leave"],
        "holidays": sorted(cfg["holidays"]), "work_day": cfg["work_day"], "statuses": store.STATUSES,
        "letters": [{"key": k, "label": v["label"]} for k, v in letters.LETTERS.items()],
        "decline_reasons": planner.DECLINE_REASONS, "today": _today().isoformat(),
        "outlook": {"com": outlook.have_com(), "mode": cfg["outlook"]["mode"], "allow_send": cfg["outlook"]["allow_send"]},
        "source": cfg["source"],
    })


@app.get("/api/dashboard")
def dashboard():
    return jsonify(planner.dashboard(_today(), request.args.get("region") or None, request.args.get("account") or None))


@app.get("/api/orders")
def orders():
    today = _today()
    rows = store.all_orders()
    for o in rows:
        s = planner.suggest(o, today)
        o["suggest"] = s["label"] if s else None
        o["suggest_letter"] = s["letter"] if s else None
    return jsonify(rows)


@app.post("/api/orders/<wo>/move")
def move(wo):
    body = request.get_json()
    o = store.get(wo)
    if not o:
        return jsonify({"error": "not found"}), 404
    start = datetime.fromisoformat(body["start"])
    end = start + timedelta(hours=o["duration_hrs"])
    eng = body["engineer"]
    warns = planner.check_slot(store.all_orders(), o, start, end, eng)
    hard = [w for w in warns if w["level"] == "error"]
    if hard and not body.get("force"):
        return jsonify({"saved": False, "warnings": warns})
    fields = {"engineer": eng, "start": start.isoformat(), "end": end.isoformat()}
    detail = f"{planner.eng_name(eng)} {start:%a %d %b %H:%M}"
    if o["plan_status"] in ("Unplanned", "Closed"):
        fields["plan_status"] = "Proposed"
    elif o["plan_status"] in ("Offered", "Confirmed") and (o["start"] != fields["start"] or o["engineer"] != eng):
        fields["plan_status"] = "Reschedule"
        detail += " (customer needs a new notice)"
    r = store.update(wo, fields, "scheduled", detail)
    return jsonify({"saved": True, "order": r, "warnings": warns})


@app.post("/api/orders/<wo>/unschedule")
def unschedule(wo):
    r = store.update(wo, {"engineer": None, "start": None, "end": None, "plan_status": "Unplanned"},
                     "unscheduled", "Removed from calendar")
    return jsonify(r)


@app.post("/api/orders/<wo>/status")
def set_status(wo):
    b = request.get_json()
    f = {"plan_status": b["status"]}
    if b.get("reason"):
        f["decline_reason"] = b["reason"]
    if b.get("notes") is not None:
        f["notes"] = b["notes"]
    f["last_contact"] = _today().isoformat()
    if b["status"] == "Unplanned":
        f.update(engineer=None, start=None, end=None)
    return jsonify(store.update(wo, f, "status", f"-> {b['status']}" + (f" ({b['reason']})" if b.get("reason") else "")))


@app.post("/api/autoplan")
def autoplan():
    b = request.get_json()
    orders_ = store.all_orders()
    wos = b.get("wos") or [o["wo_number"] for o in orders_ if o["plan_status"] == "Unplanned"]
    res = planner.autoplan(orders_, wos, date.fromisoformat(b.get("from") or _today().isoformat()),
                           lead_days=int(b.get("lead_days", 0)), cluster=b.get("cluster", True))
    if b.get("commit"):
        for p in res["placed"]:
            store.update(p["wo_number"], {"engineer": p["engineer"], "start": p["start"], "end": p["end"],
                                          "plan_status": "Proposed"}, "autoplanned",
                         f"{planner.eng_name(p['engineer'])} {p['start'][:16]}")
    return jsonify(res)


@app.post("/api/refresh")
def refresh():
    try:
        return jsonify(store.refresh_from_source())
    except Exception as e:  # surfaced to the UI toast
        return jsonify({"error": str(e)}), 400


@app.post("/api/demo/drift")
def drift():
    from . import mockdata
    src = load_config()["source"]
    n = mockdata.drift_export(ROOT / src["path"], src["sheet"], _today())
    r = store.refresh_from_source()
    r["simulated_new"] = n
    return jsonify(r)


@app.get("/api/activity")
def activity():
    return jsonify(store.activity(request.args.get("wo"), 80))


# ----------------------------------------------------------------------------- letters
def _group(wos: list[str]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for w in wos:
        o = store.get(w)
        if o:
            groups[o["account"]].append(o)
    return groups


@app.post("/api/letters/preview")
def preview():
    b = request.get_json()
    out = []
    for acct, os_ in _group(b["wos"]).items():
        if b["letter"] == "booking_request" and not any(o["start"] for o in os_):
            pass
        subject, body = letters.render_html(b["letter"], os_, _today())
        out.append({"account": acct, "to": os_[0]["contact_email"], "subject": subject, "html": body,
                    "wos": [o["wo_number"] for o in os_],
                    "unscheduled": [o["wo_number"] for o in os_ if not o["start"] and b["letter"] != "pm_not_required"
                                    and letters.LETTERS[b["letter"]]["blocks"] and any(k == "assets" and v in ("proposed", "confirmed") for k, v in letters.LETTERS[b["letter"]]["blocks"])]})
    return jsonify(out)


@app.post("/api/letters/generate")
def generate():
    b = request.get_json()
    key, mode = b["letter"], b.get("mode", "display")
    L = letters.LETTERS[key]
    day_dir = ROOT / "out" / "letters" / _today().isoformat()
    items, written = [], []
    for acct, os_ in _group(b["wos"]).items():
        subject, body = letters.render_html(key, os_, _today())
        stem = f"{acct} - {key}".replace("/", "-")
        docx_path = letters.render_docx(key, os_, day_dir / f"{stem}.docx", _today())
        atts = []
        if L.get("attach_form"):
            atts.append(letters.render_declination_form(os_, day_dir / f"{acct} - Declination Form.docx", _today()))
        items.append({"to": os_[0]["contact_email"], "subject": subject, "html": body, "attachments": atts, "name": f"{acct} - {L['label']}"})
        written.append(str(docx_path.relative_to(ROOT)))
    try:
        res = outlook.create_drafts(items, mode, ROOT / "out" / "drafts" / _today().isoformat())
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    if b.get("update_status", True):
        after = L["after"]
        for w in b["wos"]:
            o = store.get(w)
            f = {"last_contact": _today().isoformat(), "last_letter": key}
            if after["status"]:
                f["plan_status"] = after["status"]
            if after["attempt"]:
                f["attempts"] = (o["attempts"] or 0) + after["attempt"]
            if key in ("booking_request", "follow_up", "reschedule") and not o["offer_sent"]:
                f["offer_sent"] = _today().isoformat()
            if key in ("reschedule", "follow_up_new_date"):
                f["offer_sent"] = _today().isoformat()
            store.update(w, f, "letter", f"{L['label']} ({res['engine']})")
    res["docx"] = written
    return jsonify(res)


@app.get("/api/export/schedule")
def export_schedule():
    """Round-trip file: scheduled start/end + engineer per work order, ready to load back into the source system."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Work Order Number", "Scheduled Start", "Scheduled End", "Assigned Technician", "Planning Status", "Customer Notified"])
    for o in store.all_orders():
        if o["start"]:
            w.writerow([o["wo_number"], o["start"].replace("T", " "), o["end"].replace("T", " "),
                        planner.eng_name(o["engineer"]), o["plan_status"], o["offer_sent"] or ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=PM_Schedule_Import.csv"})


def bootstrap_data(reset: bool = False) -> None:
    """First run: make mock report, import it, and put the workflow mid-flight."""
    from . import mockdata
    src = load_config()["source"]
    path = ROOT / src["path"]
    if reset:
        store.reset()
    if reset or not path.exists():
        mockdata.write_export(path, mockdata.generate_rows(), src["sheet"])
    first = not store.DB_PATH.exists()
    store.refresh_from_source()
    if first:
        planner.seed_demo_states(today=_today())
