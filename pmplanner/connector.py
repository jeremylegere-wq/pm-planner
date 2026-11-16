"""Source connectors: where the PM work order report comes from.

* ``file``        - an .xlsx / .csv export of a field service system report (ServiceMax, Salesforce, ServiceNow FSM, etc.) (default; works offline)
* ``salesforce``  - live SOQL pull (needs ``pip install simple-salesforce`` and credentials in env vars)

Both return a list of dicts keyed by the *internal* field names in config["column_map"].
"""
from __future__ import annotations

import csv
import os
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from .config import ROOT, load_config

DATE_FIELDS = {"contract_start", "contract_end", "pm_due"}


def _to_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _normalise(raw: dict, cmap: dict) -> dict | None:
    out = {}
    for field, col in cmap.items():
        v = raw.get(col)
        if field in DATE_FIELDS:
            v = _to_date(v)
        elif field in ("duration_hrs", "lat", "lon"):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = 2.0 if field == "duration_hrs" else None
        else:
            v = "" if v is None else str(v).strip()
        out[field] = v
    return out if out.get("wo_number") and out.get("pm_due") else None


def read_file(path: Path, sheet: str | None, cmap: dict) -> list[dict]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(it)]
        rows = [dict(zip(header, r)) for r in it]
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    optional = {cmap.get("lat"), cmap.get("lon")}
    missing = [c for c in cmap.values() if rows and c not in rows[0] and c not in optional]
    if missing:
        raise ValueError("Report is missing expected columns (edit column_map in config.json): "
                         + ", ".join(missing))
    return [r for r in (_normalise(x, cmap) for x in rows) if r]


SOQL = """
SELECT Name, Case.CaseNumber, Account.Name, SVMXC__Street__c, SVMXC__City__c, SVMXC__State__c,
       SVMXC__Zip__c, SVMXC__Service_Group__r.Name, SVMXC__Component__r.Name,
       SVMXC__Component__r.SVMXC__Serial_Lot_Number__c, SVMXC__Product__r.Name,
       SVMXC__Service_Contract__r.Name, SVMXC__Preferred_Start_Time__c
FROM SVMXC__Service_Order__c
WHERE SVMXC__Order_Type__c = 'Preventative Maintenance' AND SVMXC__Order_Status__c = 'Open'
""".strip()  # illustrative only - adjust object / field API names to your org


def read_salesforce(cmap: dict) -> list[dict]:  # pragma: no cover - needs credentials
    try:
        from simple_salesforce import Salesforce
    except ImportError as e:
        raise RuntimeError("pip install simple-salesforce to use the live connector") from e
    sf = Salesforce(username=os.environ["SF_USER"], password=os.environ["SF_PASS"],
                    security_token=os.environ["SF_TOKEN"], domain=os.environ.get("SF_DOMAIN", "login"))
    records = sf.query_all(SOQL)["records"]
    # TODO: flatten `records` into the same column names used by column_map, then:
    raise NotImplementedError("Map SOQL fields onto column_map for your org, then call _normalise().")


def fetch() -> list[dict]:
    cfg = load_config()
    src, cmap = cfg["source"], cfg["column_map"]
    if src["type"] == "salesforce":
        return read_salesforce(cmap)
    path = Path(src["path"])
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}. Run `python -m pmplanner.mockdata` for demo data.")
    return read_file(path, src.get("sheet"), cmap)
