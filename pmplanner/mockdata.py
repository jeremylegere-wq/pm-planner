"""Generate a synthetic field-service-system style PM work order export.

Everything here is invented: customer names, contacts, serial numbers, contract
numbers. Contact e-mails use the reserved ``.example`` domain so nothing can be
delivered to a real mailbox even if "send" were enabled.

Usage:
    python -m pmplanner.mockdata                 # writes data/PM_Work_Order_Export.xlsx
    python -m pmplanner.mockdata --drift         # simulate a nightly refresh (some WOs move on)
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from .config import load_config, ROOT

SEED = 20261116

# category -> (products, duration range hrs, asset-id prefix, weight)
CATEGORIES = {
    "HVAC": (["Rooftop Package Unit RPU-20", "Chiller CH-300", "Air Handling Unit AHU-8", "Split System VRF-12"], (1.5, 3.5), "HV", 34),
    "ELEC": (["Main Switchboard MSB-400", "UPS System UPS-60", "Distribution Panel DP-12"], (2.0, 4.0), "EL", 18),
    "FIRE": (["Fire Indicator Panel FP-8", "Sprinkler Pump Set SP-2", "Emergency Lighting Suite"], (1.0, 3.0), "FS", 20),
    "LIFT": (["Passenger Lift PL-4", "Goods Lift GL-2", "Escalator ES-1"], (2.0, 4.0), "LF", 12),
    "GEN":  (["Standby Generator GEN-250", "Standby Generator GEN-500"], (3.0, 5.0), "GN", 8),
    "REFR": (["Cold Room CR-30", "Refrigeration Pack RP-6"], (2.5, 4.5), "RF", 8),
}

# fictional customers: (name, suburb, state, postcode, region, street)
CUSTOMERS = [
    ("Ashbourne Shopping Centre", "Ashbourne", "VIC", "3040", "Metro North", "12 Wattle Street"),
    ("Brightwater Business Park", "Brightwater", "VIC", "3152", "Metro East", "88 Creek Road"),
    ("Cedar Park Towers", "Cedar Park", "VIC", "3125", "Metro East", "4/200 High Street"),
    ("Delmont Grand Hotel", "Delmont", "VIC", "3181", "Metro South", "1 Harbour Parade"),
    ("Eastgate Plaza", "Eastgate", "VIC", "3130", "Metro East", "35 Station Street"),
    ("Fairview Distribution Centre", "Fairview", "VIC", "3011", "Metro West", "7 Foundry Lane"),
    ("Glenhaven Regional Council", "Glenhaven", "VIC", "3350", "Regional", "300 Ridge Road"),
    ("Harbourside Marina Complex", "Harbourside", "VIC", "3207", "Metro South", "22 Dock Street"),
    ("Ironbark Cold Storage", "Ironbark", "VIC", "3550", "Regional", "9 Box Street"),
    ("Jacaranda Office Park", "Jacaranda", "VIC", "3056", "Metro North", "61 Park Avenue"),
    ("Kestrel Valley Water Authority", "Kestrel Valley", "VIC", "3690", "Regional", "1 Treatment Plant Road"),
    ("Lakeview Retirement Village", "Lakeview", "VIC", "3199", "Metro South", "14 Lakeside Drive"),
    ("Marlowe Corporate Centre", "Marlowe", "VIC", "3000", "Metro North", "Level 3, 120 Collins Lane"),
    ("Northcote Print & Packaging", "Northcote Heights", "VIC", "3070", "Metro North", "5 Bridge Road"),
    ("Oakridge Logistics Hub", "Oakridge", "VIC", "3166", "Metro South", "48 University Way"),
    ("Pinecrest Sports Complex", "Pinecrest", "VIC", "3109", "Metro East", "17 Forest Road"),
    ("Quarry Hill Mining Supplies", "Quarry Hill", "VIC", "3550", "Regional", "2 Quarry Road"),
    ("Riverside Community Centre", "Riverside", "VIC", "3021", "Metro West", "90 River Street"),
    ("Summit Data Centre", "Summit", "VIC", "3084", "Metro North", "3 Summit Place"),
    ("Tallowood Dairy Co-op", "Tallowood", "VIC", "3875", "Regional", "55 Main Street"),
    ("Unity Food Processing", "Unity", "VIC", "3029", "Metro West", "8 Industry Court"),
    ("Valley Convention Centre", "Valley", "VIC", "3150", "Metro East", "6 Elm Grove"),
    ("Westmoor Transport Depot", "Westfield", "VIC", "3012", "Metro West", "400 Sunshine Road"),
    ("Yarra Bend Apartments", "Yarra Bend", "VIC", "3068", "Metro North", "27 Rathdowne Row"),
    ("Zenith Tower", "Zenith", "VIC", "3168", "Metro South", "1 Clayton Close"),
    ("Albion Rail Maintenance", "Albion", "VIC", "3020", "Metro West", "15 Depot Street"),
    ("Banksia University Campus", "Banksia", "VIC", "3195", "Metro South", "70 Banksia Drive"),
    ("Coastal Bays Holiday Park", "Coastal Bays", "VIC", "3930", "Regional", "31 Esplanade"),
    ("Dunmore Wind & Solar", "Dunmore", "VIC", "3300", "Regional", "10 Wind Farm Road"),
    ("Elm Street Primary School", "Elmwood", "VIC", "3125", "Metro East", "20 Elm Street"),
]


# fictional sites -> (lat, lon); placed in real Victorian localities purely so the map looks right
COORDS = {
    "Ashbourne Shopping Centre": (-37.69, 144.93), "Brightwater Business Park": (-37.83, 145.18),
    "Cedar Park Towers": (-37.85, 145.10), "Delmont Grand Hotel": (-37.92, 145.00),
    "Eastgate Plaza": (-37.78, 145.22), "Fairview Distribution Centre": (-37.78, 144.88),
    "Glenhaven Regional Council": (-37.56, 143.85), "Harbourside Marina Complex": (-37.87, 144.98),
    "Ironbark Cold Storage": (-36.76, 144.28), "Jacaranda Office Park": (-37.72, 145.04),
    "Kestrel Valley Water Authority": (-36.12, 146.89), "Lakeview Retirement Village": (-38.05, 145.17),
    "Marlowe Corporate Centre": (-37.81, 144.96), "Northcote Print & Packaging": (-37.77, 145.00),
    "Oakridge Logistics Hub": (-37.91, 145.12), "Pinecrest Sports Complex": (-37.80, 145.30),
    "Quarry Hill Mining Supplies": (-36.45, 143.95), "Riverside Community Centre": (-37.75, 144.77),
    "Summit Data Centre": (-37.65, 145.03), "Tallowood Dairy Co-op": (-38.10, 147.07),
    "Unity Food Processing": (-37.86, 144.73), "Valley Convention Centre": (-37.88, 145.24),
    "Westmoor Transport Depot": (-37.79, 144.82), "Yarra Bend Apartments": (-37.80, 145.02),
    "Zenith Tower": (-37.93, 145.18), "Albion Rail Maintenance": (-37.82, 144.85),
    "Banksia University Campus": (-37.96, 145.06), "Coastal Bays Holiday Park": (-38.60, 145.60),
    "Dunmore Wind & Solar": (-38.38, 142.48), "Elm Street Primary School": (-37.84, 145.20),
}

FIRST = ["Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn", "Harper", "Rowan",
         "Sasha", "Devon", "Kai", "Remy", "Ellis", "Blair", "Cameron", "Skyler"]
LAST = ["Abbott", "Barnes", "Chen", "Dixon", "Ellery", "Foster", "Grant", "Hughes", "Iyer", "Jensen",
        "Kerr", "Lowe", "Marsh", "Nolan", "Osei", "Pratt", "Quill", "Reyes", "Stone", "Tran"]

HEADERS = [
    "Work Order Number", "Case Number", "Account Name", "Site Street Address", "Site City", "Site State",
    "Site Postcode", "Service Territory", "Asset ID", "Serial Number", "Asset Description", "Asset Category",
    "Service Contract #", "Contract Start Date", "Contract End Date", "PM Due Date", "PM Sequence",
    "Estimated Duration (hrs)", "Priority", "Work Order Status", "Site Contact Name",
    "Site Contact Email", "Site Contact Phone", "Site Latitude", "Site Longitude",
]


def _slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())[:14]


def generate_rows(today: date | None = None, seed: int = SEED) -> list[list]:
    rnd = random.Random(seed)
    today = today or date.today()
    mods = list(CATEGORIES)
    weights = [CATEGORIES[m][3] for m in mods]

    contacts = {}
    contracts = {}
    for i, c in enumerate(CUSTOMERS):
        fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
        contacts[c[0]] = (f"{fn} {ln}", f"{fn.lower()}.{ln.lower()}@{_slug(c[0])}.example",
                          f"03 5550 {rnd.randint(1000, 9999)}")
        start = date(today.year - rnd.randint(0, 3), rnd.randint(1, 12), 1)
        contracts[c[0]] = (f"MSA-{100200 + i * 7}", start, start.replace(year=start.year + 5))

    rows = []
    wo = 410000
    case = 3300000
    sid = 5000
    # each customer owns a handful of assets, each with a PM due in the window
    for cust in CUSTOMERS:
        n_assets = rnd.choice([4, 6, 8, 10, 12, 16, 20, 26])
        msa, cs, ce = contracts[cust[0]]
        cname, cemail, cphone = contacts[cust[0]]
        for _ in range(n_assets):
            mod = rnd.choices(mods, weights)[0]
            prods, (dlo, dhi), pref, _w = CATEGORIES[mod]
            dur = round(rnd.uniform(dlo, dhi) * 2) / 2
            # due-dates: spread from 3 weeks ago to ~22 weeks out, clustered by month
            offset = int(rnd.triangular(-21, 130, 35))
            due = today + timedelta(days=offset)
            if due.weekday() >= 5:
                due += timedelta(days=7 - due.weekday())
            sid += rnd.randint(1, 9)
            wo += rnd.randint(1, 4)
            case += rnd.randint(1, 30)
            seq = rnd.choice(["A", "B", "C", "D"]) if mod in ("LIFT", "GEN") else rnd.choice(["A", "B", ""])
            prio = "High" if (due - today).days < 14 else rnd.choice(["Normal", "Normal", "Normal", "Low"])
            rows.append([
                f"WO-{wo:08d}", f"{case:08d}", cust[0], cust[5], cust[1], cust[2], cust[3], cust[4],
                f"{sid:07d}", f"{pref}{rnd.randint(100000, 999999)}", rnd.choice(prods), mod,
                msa, cs, ce, due, seq, dur, prio, "Open", cname, cemail, cphone,
                COORDS[cust[0]][0], COORDS[cust[0]][1],
            ])
    rows.sort(key=lambda r: (r[15], r[2]))
    return rows


def write_export(path: Path, rows: list[list], sheet: str = "PM Work Orders") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    head_fill = PatternFill("solid", fgColor="1F3A5F")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    widths = [16, 12, 32, 26, 16, 8, 10, 14, 11, 14, 32, 10, 14, 14, 14, 13, 8, 12, 9, 12, 20, 36, 14, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for idx in (13, 14, 15):
            row[idx].number_format = "dd/mm/yyyy"
    # a tiny README sheet so a viewer knows this is not real data
    info = wb.create_sheet("README")
    info["A1"] = "SYNTHETIC DATA - generated by pmplanner.mockdata"
    info["A2"] = ("Mimics a field-service system report (ServiceMax / Salesforce / similar) of open planned-maintenance work orders. "
                  "Point config.json -> source.path at a real report export (same column headers, or edit "
                  "column_map) to run against live data.")
    info.column_dimensions["A"].width = 120
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def drift_export(path: Path, sheet: str, today: date | None = None, seed: int | None = None) -> int:
    """Simulate a nightly report refresh: add a few new WOs, drop a few closed ones."""
    today = today or date.today()
    rnd = random.Random(seed or int(today.strftime("%Y%m%d")))
    wb = load_workbook(path)
    ws = wb[sheet]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    # drop ~2% (completed in the source system), add ~15 new
    keep = [list(r) for r in rows if rnd.random() > 0.02]
    fresh = generate_rows(today, seed=rnd.randint(1, 10**6))
    max_wo = max(int(r[0].split("-")[1]) for r in keep)
    added = rnd.sample(fresh, 15)
    for k, r in enumerate(added, 1):
        r[0] = f"WO-{max_wo + k * 3:08d}"
        keep.append(r)
    keep.sort(key=lambda r: (r[15], r[2]))
    write_export(path, keep, sheet)
    return len(added)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drift", action="store_true", help="simulate a refresh of an existing export")
    args = ap.parse_args()
    cfg = load_config()
    out = ROOT / cfg["source"]["path"]
    if args.drift and out.exists():
        n = drift_export(out, cfg["source"]["sheet"])
        print(f"Refreshed {out} (+{n} new work orders)")
    else:
        rows = generate_rows()
        write_export(out, rows, cfg["source"]["sheet"])
        print(f"Wrote {len(rows)} synthetic work orders to {out}")


if __name__ == "__main__":
    main()
