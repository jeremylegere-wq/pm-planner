"""Letter engine. Each letter is defined once as a list of blocks and rendered to
(a) Outlook-safe HTML for the e-mail body and (b) a .docx for printing / attaching.

Generic planned-maintenance correspondence for a field service business: booking request, follow-up,
reschedule, confirmation, final attempt, declination (+ signable form), site closure and
service-not-required. Branded for the fictional "Northstar Field Services".
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

from .config import ROOT, load_config

HOLD = "5 business days"
NAVY = "1F3A5F"

# --------------------------------------------------------------------------- block definitions
SIGNOFF = [("p", "Kind Regards,"), ("sign", None)]

LETTERS: dict[str, dict] = {
    "booking_request": {
        "label": "Booking request (offer)",
        "subject": "{company} – Service Booking Request – {state} – {mods} – {year} – {ref}",
        "heading": "Planned Maintenance Service Schedule",
        "after": {"status": "Offered", "attempt": +1},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Please find below the proposed maintenance service date to ensure your equipment remains "
                  "safe and meets compliance standards."),
            ("p", "Please check that the customer, address and equipment details are correct, and confirm if "
                  "the proposed date is suitable at your earliest convenience."),
            ("p", "Please be aware that if you do not confirm the offered date within " + HOLD + ", it may no longer be available."),
            ("kv", "customer"),
            ("note", "**Please advise if any machine is at a different location, or resides at a residential address.**"),
            ("assets", "proposed"),
            ("p", "PLEASE SELECT FROM THE OPTIONS BELOW:"),
            ("buttons", None),
            ("small", "If the buttons do not work on your system, please reply-all to this email."),
            ("note", "** Please ensure the equipment is accessible and that any required keys, access cards or permits are available at the scheduled time."),
            ("note", "** If you are not the contact person for this machine, please advise and, if possible, forward this "
                     "letter to the correct person to ensure timely service."),
            ("p", "Thank you."),
        ] + SIGNOFF,
    },
    "follow_up": {
        "label": "Follow-up (no reply)",
        "subject": "{company} – Service Confirmation Required – {state} – {mods} – {year} – {ref}",
        "heading": "Planned Maintenance Service – Confirmation Required",
        "after": {"status": "Offered", "attempt": +1},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Your {company} equipment has been scheduled for Planned Maintenance Service as per the "
                  "booking request below. To date we have not been contacted to confirm this booking or to "
                  "reschedule to a preferred date."),
            ("assets", "proposed"),
            ("p", "Please reply with acceptance, or a reschedule request with preferred dates or days of the week, "
                  "to complete this process. Please also advise if you are not the contact person to organise this service."),
            ("buttons", None),
            ("p", "If you have any queries regarding this upcoming maintenance service please contact us on "
                  "{phone_au} or email {email}."),
        ] + SIGNOFF,
    },
    "follow_up_new_date": {
        "label": "Follow-up proposing new date",
        "subject": "{company} – Service Confirmation Required – {state} – {mods} – {year} – {ref}",
        "heading": "Planned Maintenance Service – New Date Proposed",
        "after": {"status": "Offered", "attempt": +1},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Unfortunately the originally proposed appointment is no longer available, but we could schedule "
                  "your service as shown below."),
            ("assets", "proposed"),
            ("p", "Could you please kindly confirm at your earliest convenience if this would be suitable, so that we "
                  "can finalise your booking as soon as possible?"),
            ("buttons", None),
        ] + SIGNOFF,
    },
    "reschedule": {
        "label": "Reschedule request",
        "subject": "URGENT – {company} – Service Reschedule Request – {state} – {mods} – {year} – {ref}",
        "heading": "Planned Maintenance Service Reschedule Request",
        "after": {"status": "Offered", "attempt": +1},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Due to unforeseen circumstances, we will need to reschedule your Planned Maintenance Service. "
                  "Our next available appointment is shown below."),
            ("assets", "proposed"),
            ("p", "If this date works for your schedule please reply and we will confirm the date change. "
                  "Alternatively, please advise a suitable day for servicing and we will do our best to accommodate your request."),
            ("buttons", None),
            ("p", "Please accept our sincere apologies for any inconvenience this reschedule request may have caused."),
        ] + SIGNOFF,
    },
    "confirmation": {
        "label": "Booking confirmation",
        "subject": "{company} – Service Confirmed – {state} – {mods} – {year} – {ref}",
        "heading": "Confirmed Planned Maintenance Service",
        "after": {"status": "Confirmed", "attempt": 0},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Thank you for taking the time to confirm your service appointment{plural}."),
            ("p", "A technician will be allocated to {thisthese} Service Request{plural}. Please ensure the "
                  "equipment is made available for the service at the agreed time{plural}."),
            ("assets", "confirmed"),
            ("note", "***PLEASE NOTE***"),
            ("modnotes", None),
            ("p", "For safety reasons, you must provide a second person onsite for any work we do outside regular "
                  "service hours. If you cannot provide such a person, {company} will do so at your cost and charge you accordingly."),
            ("p", "Need to make any changes? Please contact us on {phone_au} or {email} as soon as you can."),
        ] + SIGNOFF,
    },
    "third_attempt": {
        "label": "Third (final) attempt",
        "subject": "RE: URGENT – {company} – Third Attempt Letter – {state} – {mods} – {year} – {ref}",
        "heading": "Planned Maintenance Service – Third (Final) Attempt",
        "after": {"status": "Offered", "attempt": +1},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "We are reaching out again regarding the scheduling of your Planned Maintenance visit for the "
                  "{mods} equipment at {account}."),
            ("assets", "proposed"),
            ("p", "This will be our third and final attempt to confirm a booking time. We want to ensure your "
                  "equipment continues to operate reliably and remains within service entitlements."),
            ("p", "If we do not receive a response, we will need to close this service request for now. However, if you "
                  "do locate this asset within the next 30 days, please advise and we can re-open the service request."),
            ("buttons", None),
            ("p", "If you have any queries please contact us on {phone_au} or email {email}."),
        ] + SIGNOFF,
    },
    "declination": {
        "label": "Declination letter (+ form)",
        "subject": "URGENT – {company} – Service Declination Letter – {state} – {mods} – {year} – {ref}",
        "heading": "Planned Maintenance Service Declination Letter",
        "after": {"status": "Declined", "attempt": 0},
        "attach_form": True,
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Please see the attached Planned Maintenance Service Declination Letter in regards to the "
                  "'Declination of the Planned Maintenance Service' for your {company} equipment."),
            ("note", "**Declination reason – {decline_reason}**"),
            ("assets", "plain"),
            ("p", "Please complete and return the form at your earliest convenience. If you do locate this asset within "
                  "the next 30 days, please advise and we can re-open the service request."),
            ("p", "If you have any queries regarding this Declination Letter please contact us on {phone_au} or email {email}."),
        ] + SIGNOFF,
    },
    "site_closure": {
        "label": "Site closure summary",
        "subject": "{company} – PM Site Closure Summary – {state} – {account}",
        "heading": "Planned Maintenance Service – Site Closure Summary",
        "after": {"status": None, "attempt": 0},
        "blocks": [
            ("p", "Dear Customer,"),
            ("p", "Thank you for your cooperation during our recent Planned Maintenance (PM) visit. Please find "
                  "below a summary of the activities completed onsite and the next scheduled PM due for your equipment."),
            ("kv", "customer"),
            ("assets", "closure"),
            ("p", "Please feel free to share any comments regarding the visit, the communication, or your overall experience. "
                  "If you would like to add or update the site contact for future bookings, we are happy to update our "
                  "records – just let us know."),
            ("small", "Should this summary have reached you in error, or you are not the appropriate contact for this "
                      "equipment, kindly forward it to the correct person or advise us so we can update our details."),
        ] + SIGNOFF,
    },
    "pm_not_required": {
        "label": "Service not required",
        "subject": "{company} – Annual Planned Maintenance Arrangements – {account}",
        "heading": "Private and Confidential",
        "after": {"status": "Closed", "attempt": 0},
        "blocks": [
            ("p", "Dear Customer,"),
            ("note", "**RE: ANNUAL PLANNED MAINTENANCE ARRANGEMENTS**"),
            ("p", "We write to confirm that, as per the product manuals, an annual Planned Maintenance service is not "
                  "mandatory for the asset(s) listed below. The manufacturer has determined that they have no high-wear "
                  "components that fail with use, therefore no scheduled inspections are mandatory. "
                  "If your site requires a Planned Maintenance Service, one can be arranged via an On Demand Service quote."),
            ("assets", "plain"),
            ("p", "Thank you for your continued confidence in our products and solutions. We value the continued "
                  "opportunity to work together on your service needs."),
            ("p", "Yours Sincerely,"), ("sign", None),
        ],
    },
}

CATEGORY_NOTES = {
    "HVAC": "Please ensure roof, plant room and ceiling-space access is available, and that building management is aware of any planned shutdowns.",
    "ELEC": "Planned isolations may be required. Please confirm an agreed outage window and nominate a site contact who can authorise switching.",
    "FIRE": "Please notify your monitoring provider and building occupants before testing begins. Alarms and sprinklers may be tested during the visit.",
    "LIFT": "The lift or escalator will be out of service during the visit. Please arrange alternative access and signage.",
    "GEN": "The generator may be run under load. Please ensure fuel levels are adequate and that the surrounding area is clear.",
    "REFR": "Please ensure stock can be relocated or protected if temperatures need to be held, and that door and plant access is clear.",
}


# --------------------------------------------------------------------------- context
def _fmt_dt(v: str | None, with_time=True) -> str:
    if not v:
        return "To be advised"
    d = datetime.fromisoformat(v)
    return d.strftime("%a, %d-%b-%Y, %H:%M") if with_time else d.strftime("%a, %d-%b-%Y")


def build_context(orders: list[dict], letter_key: str, today: date | None = None) -> dict:
    cfg = load_config()["company"]
    o0 = orders[0]
    mods = sorted({o["category"] for o in orders})
    multi = len(orders) > 1
    ref = (f"SID: {o0['system_id']}" if not multi else f"{o0['account']} ({len(orders)} assets)")
    return {
        "company": cfg["name"], "team": cfg["team"], "email": cfg["email"], "phone_au": cfg["phone_au"],
        "phone_nz": cfg["phone_nz"], "state": o0["state"] or cfg["state_label"],
        "mods": ", ".join(mods), "year": (today or date.today()).year, "ref": ref,
        "account": o0["account"], "address": f"{o0['address']}, {o0['suburb']} {o0['state']} {o0['postcode']}",
        "contact_name": o0["contact_name"], "to": o0["contact_email"],
        "plural": "s" if multi else "", "thisthese": "these" if multi else "this",
        "decline_reason": o0.get("decline_reason") or "Asset not available",
        "today": (today or date.today()).strftime("%A, %d %B %Y"),
        "orders": orders, "mod_list": mods, "letter": letter_key,
    }


def _fmt(text: str, ctx: dict) -> str:
    class D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return text.format_map(D(ctx))


def subject_for(key: str, ctx: dict) -> str:
    return _fmt(LETTERS[key]["subject"], ctx)


def _bold(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))


# --------------------------------------------------------------------------- asset table columns
def asset_columns(kind: str) -> tuple[list[str], callable]:
    if kind in ("proposed", "confirmed"):
        hdr = ["Proposed schedule" if kind == "proposed" else "Confirmed schedule", "Case #", "Work order #",
               "Asset ID", "Serial number", "Asset"]
        row = lambda o: [_fmt_dt(o["start"]) + (f" – {datetime.fromisoformat(o['end']):%H:%M}" if o["end"] else ""),
                         o["case_number"], o["wo_number"], o["system_id"], o["serial"], o["product"]]
    elif kind == "closure":
        hdr = ["Asset", "Type", "PM completed on", "Case #", "Next PM due"]
        row = lambda o: [f"{o['system_id']} – {o['product']}", o["category"],
                         _fmt_dt(o["start"], False), o["case_number"], _next_pm(o)]
    else:
        hdr = ["Asset ID", "Serial number", "Asset", "Contract #", "Service date"]
        row = lambda o: [o["system_id"], o["serial"], o["product"], o["msa_number"], o["pm_due"]]
    return hdr, row


def _next_pm(o: dict) -> str:
    d = date.fromisoformat(o["pm_due"])
    try:
        return d.replace(year=d.year + 1).strftime("%b %Y")
    except ValueError:
        return d.strftime("%b %Y")


def mailto(kind: str, ctx: dict) -> str:
    wos = ", ".join(o["wo_number"] for o in ctx["orders"])
    subj = f"{kind} – {ctx['account']} – {wos}"
    body = f"{kind} for work order(s): {wos}\n\nPreferred dates / comments:\n"
    return f"mailto:{ctx['email']}?subject={quote(subj)}&body={quote(body)}"


# --------------------------------------------------------------------------- HTML rendering
def render_html(key: str, orders: list[dict], today: date | None = None) -> tuple[str, str]:
    L, ctx = LETTERS[key], build_context(orders, key, today)
    parts = []
    for kind, val in L["blocks"]:
        if kind == "p":
            parts.append(f"<p style='margin:0 0 12px'>{_bold(_fmt(val, ctx))}</p>")
        elif kind == "note":
            parts.append(f"<p style='margin:0 0 12px;color:#444'>{_bold(_fmt(val, ctx))}</p>")
        elif kind == "small":
            parts.append(f"<p style='margin:0 0 12px;font-size:12px;color:#666'>{_bold(_fmt(val, ctx))}</p>")
        elif kind == "kv":
            parts.append("<table style='margin:0 0 14px;font-size:14px'>"
                         f"<tr><td style='padding:2px 14px 2px 0;color:#666'>Customer:</td><td><b>{html.escape(ctx['account'])}</b></td></tr>"
                         f"<tr><td style='padding:2px 14px 2px 0;color:#666'>Address:</td><td>{html.escape(ctx['address'])}</td></tr></table>")
        elif kind == "assets":
            hdr, row = asset_columns(val)
            th = "".join(f"<th align='left' style='background:#{NAVY};color:#fff;padding:6px 8px;font-size:12px'>{h}</th>" for h in hdr)
            trs = "".join("<tr>" + "".join(f"<td style='padding:6px 8px;border-bottom:1px solid #dde3ea;font-size:13px'>{html.escape(str(c))}</td>"
                                           for c in row(o)) + "</tr>" for o in orders)
            parts.append(f"<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;margin:0 0 14px;width:100%'><tr>{th}</tr>{trs}</table>")
        elif kind == "modnotes":
            parts.append("<ul style='margin:0 0 12px;padding-left:20px'>" + "".join(
                f"<li style='margin:0 0 4px'><b>{m}:</b> {html.escape(CATEGORY_NOTES[m])}</li>" for m in ctx["mod_list"]) + "</ul>")
        elif kind == "buttons":
            btn = lambda t, c, k: (f"<a href='{html.escape(mailto(k, ctx))}' style='display:inline-block;padding:9px 22px;margin-right:10px;"
                                   f"background:{c};color:#fff;text-decoration:none;border-radius:4px;font-weight:bold;font-size:13px'>{t}</a>")
            parts.append("<p style='margin:0 0 14px'>" + btn("CONFIRM", "#1c7c54", "CONFIRM") + btn("RESCHEDULE", "#b4540f", "RESCHEDULE") + "</p>")
        elif kind == "sign":
            parts.append(f"<p style='margin:0'><b>{html.escape(ctx['team'])}</b><br>{html.escape(ctx['company'])}<br>"
                         f"T: {ctx['phone_au']} (AUS) &nbsp; T: {ctx['phone_nz']} (NZ)<br>E: {ctx['email']}</p>")
    body = (f"<div style='font-family:Calibri,Arial,sans-serif;font-size:14px;color:#222;max-width:760px'>"
            f"<div style='background:#{NAVY};color:#fff;padding:12px 16px'><span style='font-size:18px;font-weight:bold'>{html.escape(ctx['company'])}</span>"
            f"<span style='float:right;font-size:12px'>{ctx['today']}</span></div>"
            f"<h2 style='color:#{NAVY};font-size:17px;margin:16px 0 12px'>{html.escape(L['heading'])}</h2>" + "".join(parts) + "</div>")
    return subject_for(key, ctx), body


# --------------------------------------------------------------------------- DOCX rendering
def _shade(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_)
    tcPr.append(shd)


def _runs(p, text: str):
    for i, seg in enumerate(re.split(r"\*\*", text)):
        r = p.add_run(seg)
        r.bold = i % 2 == 1


def render_docx(key: str, orders: list[dict], path: Path, today: date | None = None) -> Path:
    L, ctx = LETTERS[key], build_context(orders, key, today)
    d = Document()
    sec = d.sections[0]
    sec.left_margin = sec.right_margin = Cm(2)
    sec.orientation = 1
    st = d.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
    t = d.add_paragraph(); r = t.add_run(ctx["company"]); r.bold = True; r.font.size = Pt(16); r.font.color.rgb = RGBColor.from_string(NAVY)
    dp = d.add_paragraph(ctx["today"]); dp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    h = d.add_paragraph(); r = h.add_run(L["heading"]); r.bold = True; r.font.size = Pt(13); r.font.color.rgb = RGBColor.from_string(NAVY)
    for kind, val in L["blocks"]:
        if kind in ("p", "note", "small"):
            p = d.add_paragraph(); _runs(p, _fmt(val, ctx))
            if kind == "small":
                for r in p.runs: r.font.size = Pt(8.5)
        elif kind == "kv":
            p = d.add_paragraph(); p.add_run("Customer: ").bold = True; p.add_run(ctx["account"])
            p = d.add_paragraph(); p.add_run("Address: ").bold = True; p.add_run(ctx["address"])
        elif kind == "assets":
            hdr, row = asset_columns(val)
            tb = d.add_table(rows=1, cols=len(hdr)); tb.style = "Table Grid"
            for i, hname in enumerate(hdr):
                c = tb.rows[0].cells[i]; c.text = ""; rr = c.paragraphs[0].add_run(hname); rr.bold = True
                rr.font.size = Pt(9); rr.font.color.rgb = RGBColor(255, 255, 255); _shade(c, NAVY)
            for o in orders:
                cells = tb.add_row().cells
                for i, v in enumerate(row(o)):
                    cells[i].text = ""; cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(9)
            d.add_paragraph()
        elif kind == "modnotes":
            for m in ctx["mod_list"]:
                p = d.add_paragraph(style="List Bullet"); p.add_run(m + ": ").bold = True; p.add_run(CATEGORY_NOTES[m])
        elif kind == "buttons":
            d.add_paragraph("To respond, reply to this letter to " + ctx["email"] + " quoting the work order number(s): CONFIRM or RESCHEDULE.")
        elif kind == "sign":
            p = d.add_paragraph(); p.add_run(ctx["team"]).bold = True
            d.add_paragraph(f"{ctx['company']}\nT: {ctx['phone_au']} (AUS)  T: {ctx['phone_nz']} (NZ)\nE: {ctx['email']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path


def render_declination_form(orders: list[dict], path: Path, today: date | None = None) -> Path:
    """Customer-signed declination form (the attachment sent with the declination letter)."""
    ctx = build_context(orders, "declination", today)
    o0 = orders[0]
    d = Document()
    d.sections[0].left_margin = d.sections[0].right_margin = Cm(2)
    d.styles["Normal"].font.name = "Calibri"; d.styles["Normal"].font.size = Pt(10.5)
    h = d.add_paragraph(); r = h.add_run("Planned Maintenance MSA Declination"); r.bold = True; r.font.size = Pt(16)
    r.font.color.rgb = RGBColor.from_string(NAVY)
    tb = d.add_table(rows=0, cols=2); tb.style = "Table Grid"
    for k, v in [("CUSTOMER NAME", ctx["account"]), ("MAINTENANCE SERVICE AGREEMENT #", o0["msa_number"]),
                 ("CONTRACT START DATE", o0["contract_start"]), ("CONTRACT END DATE", o0["contract_end"]),
                 ("SYSTEM ID / SERIAL NUMBER", "; ".join(f"{o['system_id']} / {o['serial']}" for o in orders)),
                 ("LOCATION", ctx["address"]), ("PLANNED MAINTENANCE DATE", "; ".join(sorted({o['pm_due'] for o in orders}))),
                 ("PM SEQUENCE IF APPLICABLE", ", ".join(o["pm_sequence"] for o in orders if o["pm_sequence"]) or "n/a")]:
        c = tb.add_row().cells; c[0].text = k; c[1].text = str(v); _shade(c[0], "E8EEF5")
        c[0].paragraphs[0].runs[0].bold = True
    d.add_paragraph()
    d.add_paragraph(f"We, {ctx['account']}, have elected not to accept the planned maintenance of the above equipment as per "
                    "our Maintenance Service Agreement referenced above, because one of the following conditions exists "
                    "(check that which applies):")
    for opt in ["Asset is currently in use and not available for servicing",
                "We are unable or unwilling to provide access at the scheduled service time due to ____________________",
                "Asset has been decommissioned or removed and a return to service date is unknown",
                "Asset has been damaged, such that the maintenance cannot be carried out. The schedule for repairs is not known",
                "Asset is not available until ____________. We understand that the planned maintenance schedule will not "
                "change and all future planned maintenance services remain as previously scheduled",
                "OTHER: ______________________________________________"]:
        d.add_paragraph("☐  " + opt)
    for t in ["We understand that in signing this document we potentially forego our contractual entitlement to this planned "
              "maintenance. We understand and accept any quality and regulatory risk and/or responsibility that may occur as a "
              "result of this decision, and that there will be no compensation for this declination.",
              "We agree that if service is declined for either of the first two reasons above and requires rescheduling, the "
              "rescheduled service may be charged at then-current additional call-out rates.",
              "We understand that the next Planned Maintenance for the above equipment will be ______________.",
              f"Dated and signed this ______ day of ____________, {ctx['year']}",
              "Please provide the signature of an individual with responsibility for risk and compliance."]:
        d.add_paragraph(t)
    for f in ["Signature", "Printed Name", "Title", "Site Name"]:
        d.add_paragraph(f"{f}: " + "_" * 60)
    p = d.add_paragraph(); r = p.add_run("INTERNAL: attach documentation to the service record and email to the Contract Administrator. "
                                         "If no signed letter is received, the PM decline is documented in the service record.")
    r.italic = True; r.font.size = Pt(8.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path
