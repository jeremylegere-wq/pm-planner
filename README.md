# Planned Maintenance Planner – field service coordination (demo)

A planned-maintenance dashboard, drag-and-drop Gantt planner and customer correspondence engine for any
field service team (HVAC, electrical, fire, lifts, generators, refrigeration in the demo data). **All data is synthetic** (fictional customers, contacts, serials,
technicians; contact e-mails use the reserved `.example` domain).

## Run
    pip install -r requirements.txt
    python run.py              # opens http://127.0.0.1:5055   (python run.py --reset rebuilds the demo)

First run generates `data/PM_Work_Order_Export.xlsx` (a mock field-service-system report) and puts the
workflow mid-flight so the dashboard has something to show.

## Screens
* **Dashboard** – interactive Victoria map (+ Melbourne inset) with a pie bubble per site; click a site or
  territory to cross-filter KPIs, charts, action queue and upcoming visits. KPI tiles, workload by month,
  offer ageing, modality mix, technician utilisation, status by territory.
* **Planner** – Gantt by technician. Drag a backlog job onto a row, drag bars to re-time / re-assign. Rules checked:
  weekends, public holidays, leave, technician skills, overlaps, daily capacity, after-PM-due-date. "Auto-plan"
  clusters each customer's assets into one visit, matches skills/territory, aims ~10 days before due.
* **Work orders** – filter, multi-select, bulk letters / auto-plan, side drawer with status buttons + activity log.
* **Letters** – booking request, follow-up, follow-up with new date, reschedule, confirmation (modality-specific
  notes), third/final attempt, declination (+ signable form .docx), site closure, PM-not-mandatory. One letter per
  customer; preview, then Open in Outlook / Save to Drafts / .eml files. Sending is off unless `outlook.allow_send`.
* **Data & export** – refresh from the report, simulate an overnight refresh, export schedule CSV for a data load.

## Connecting to your field service system (ServiceMax, Salesforce, ServiceNow FSM, ...)
Edit `config.json`: `source.path` (scheduled report export, .xlsx/.csv) and `column_map` (your column headers).
Refresh keeps planning decisions (dates, technician, letter history) and adds new work orders as Unplanned.
`pmplanner/connector.py` has a stubbed `simple-salesforce` SOQL pull for a live feed.

## Outlook
Windows + desktop Outlook + `pywin32` → real mail items (shared mailbox via `outlook.shared_mailbox`).
Otherwise `.eml` files with `X-Unsent: 1` are written to `out/drafts/` – double-click to open as a draft.
Word copies of each letter go to `out/letters/`.
