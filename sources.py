"""Tallowa Components - five adjacent-system MCP sources.

Five small, hand-curated MCP tool surfaces (CMMS/maintenance, WMS/warehouse,
EHS/safety, Workforce/rostering, CRM/sales pipeline) - each a distinct
"system" a real plant would run alongside its ERP, each mounted as its own
Streamable-HTTP JSON-RPC endpoint (/mcp/cmms, /mcp/wms, /mcp/ehs,
/mcp/workforce, /mcp/crm) so ARAG's Smart agent can register each as a
separate retrieval source alongside the existing tallowa-mcp one.

Deliberately NOT built the way mcp.py builds the ERP catalogue (auto-generated
from a full REST/OpenAPI surface, forwarding the caller's JWT to an
in-process REST dispatch): these systems have no REST API and no UI at all -
"purely to provide requests," per the brief - so each tool is a plain Python
query function wired directly into a minimal JSON-RPC handler. Two reasons
to keep this lean, both learned the hard way wiring up the first source (see
ARAG-REARCH-STATE.md): (1) the flagship multi-hop demo question already
times out around 300s against a 120-tool catalog from ONE source - five more
full REST-style catalogues would make the planner's search space worse, so
each source here gets exactly 5 tools; (2) forwarding auth headers through
ARAG's Smart-agent node was the hardest part of the first integration
(empty `valid_headers` -> silent 401s) - these sources carry no sensitive
data, so they skip auth entirely rather than risk repeating that.

Seed data cross-references real identifiers already in data/erp.db (machine
asset_no, operator emp_no, customer code, line code, lot numbers) so a
cross-system question actually resolves to a coherent story - e.g. raw lot
WF-2261 (seeded quarantined in the ERP) was consumed on line A-1's assembly
cell; this module seeds a CMMS breakdown, an EHS incident and a WMS bin
location that all point at that same line/lot, on purpose.
"""
import asyncio
import json
import random
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from database import connect as erp_connect
from database import q as dbq
from database import q1 as dbq1

DB_PATH = Path(__file__).resolve().parent / "data" / "sources.db"
TODAY = date.today()

SCHEMA = """
CREATE TABLE cmms_work_orders (
  id INTEGER PRIMARY KEY, wo_no TEXT UNIQUE, asset_no TEXT, line_code TEXT,
  title TEXT, priority TEXT, status TEXT, opened_on TEXT, due_on TEXT,
  closed_on TEXT, assigned_to TEXT, description TEXT);

CREATE TABLE cmms_breakdowns (
  id INTEGER PRIMARY KEY, asset_no TEXT, line_code TEXT, started_at TEXT,
  ended_at TEXT, downtime_minutes REAL, cause TEXT, wo_no TEXT);

CREATE TABLE cmms_pm_schedule (
  id INTEGER PRIMARY KEY, asset_no TEXT, task TEXT, interval_days INTEGER,
  last_done TEXT, next_due TEXT);

CREATE TABLE cmms_spare_parts (
  id INTEGER PRIMARY KEY, part_no TEXT, description TEXT, qty_on_hand INTEGER,
  reorder_point INTEGER, bin TEXT);

CREATE TABLE wms_bins (
  id INTEGER PRIMARY KEY, bin_code TEXT, part_no TEXT, lot_no TEXT, qty REAL,
  zone TEXT, updated_at TEXT);

CREATE TABLE wms_cycle_counts (
  id INTEGER PRIMARY KEY, part_no TEXT, bin_code TEXT, counted_qty REAL,
  system_qty REAL, variance REAL, counted_on TEXT, counted_by TEXT);

CREATE TABLE wms_putaways (
  id INTEGER PRIMARY KEY, part_no TEXT, lot_no TEXT, qty REAL, from_dock TEXT,
  target_bin TEXT, status TEXT, created_at TEXT);

CREATE TABLE wms_dock_schedule (
  id INTEGER PRIMARY KEY, dock TEXT, direction TEXT, carrier TEXT,
  scheduled_at TEXT, ref TEXT, status TEXT);

CREATE TABLE ehs_incidents (
  id INTEGER PRIMARY KEY, incident_no TEXT UNIQUE, line_code TEXT,
  severity TEXT, category TEXT, description TEXT, occurred_at TEXT,
  reported_by TEXT, status TEXT, injury INTEGER DEFAULT 0);

CREATE TABLE ehs_near_misses (
  id INTEGER PRIMARY KEY, line_code TEXT, description TEXT, occurred_at TEXT,
  reported_by TEXT, category TEXT);

CREATE TABLE ehs_corrective_actions (
  id INTEGER PRIMARY KEY, incident_no TEXT, action TEXT, owner TEXT,
  due_on TEXT, status TEXT, closed_on TEXT);

CREATE TABLE ehs_safety_audits (
  id INTEGER PRIMARY KEY, line_code TEXT, audit_date TEXT, auditor TEXT,
  score REAL, findings TEXT);

CREATE TABLE workforce_employees (
  id INTEGER PRIMARY KEY, emp_no TEXT UNIQUE, name TEXT, role TEXT,
  line_code TEXT, shift TEXT, hire_date TEXT, employment_type TEXT);

CREATE TABLE workforce_roster (
  id INTEGER PRIMARY KEY, roster_date TEXT, shift TEXT, line_code TEXT,
  emp_no TEXT, role TEXT);

CREATE TABLE workforce_absences (
  id INTEGER PRIMARY KEY, emp_no TEXT, absence_date TEXT, reason TEXT,
  approved INTEGER DEFAULT 1);

CREATE TABLE workforce_certifications (
  id INTEGER PRIMARY KEY, emp_no TEXT, cert_name TEXT, issued_on TEXT,
  expires_on TEXT);

CREATE TABLE workforce_overtime (
  id INTEGER PRIMARY KEY, emp_no TEXT, work_date TEXT, hours REAL,
  reason TEXT);

CREATE TABLE crm_opportunities (
  id INTEGER PRIMARY KEY, opp_no TEXT UNIQUE, customer_code TEXT, name TEXT,
  stage TEXT, value REAL, expected_close TEXT, owner TEXT);

CREATE TABLE crm_quotes (
  id INTEGER PRIMARY KEY, quote_no TEXT UNIQUE, customer_code TEXT,
  part_no TEXT, qty REAL, unit_price REAL, status TEXT, issued_on TEXT,
  expires_on TEXT);

CREATE TABLE crm_interactions (
  id INTEGER PRIMARY KEY, customer_code TEXT, kind TEXT, summary TEXT,
  occurred_at TEXT, owner TEXT);

CREATE TABLE crm_account_health (
  id INTEGER PRIMARY KEY, customer_code TEXT UNIQUE, health_score INTEGER,
  nps INTEGER, churn_risk TEXT, renewal_date TEXT, notes TEXT);
"""


def d(offset_days: int) -> str:
    return (TODAY + timedelta(days=offset_days)).isoformat()


def ts(offset_days: int, hour=9, minute=0) -> str:
    base = datetime.combine(TODAY + timedelta(days=offset_days),
                            datetime.min.time(), tzinfo=timezone.utc)
    return (base + timedelta(hours=hour, minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ------------------------------------------------------------ seeding
def _erp_refs() -> dict:
    """Real identifiers pulled from the ERP's own database, so this module's
    synthetic data cross-references genuine machines/operators/customers/lots
    rather than inventing a parallel cast of names."""
    con = erp_connect()
    lines = dbq(con, "SELECT code, name FROM lines")
    machines = dbq(con, """SELECT m.asset_no, m.name, l.code AS line_code, m.status
                           FROM machines m JOIN lines l ON l.id = m.line_id""")
    operators = dbq(con, """SELECT o.emp_no, o.name, o.role, l.code AS line_code, o.shift
                            FROM operators o JOIN lines l ON l.id = o.line_id
                            WHERE o.status = 'active'""")
    customers = dbq(con, "SELECT code, name FROM customers")
    parts = dbq(con, "SELECT part_no, name FROM parts")
    finished_lots = dbq(con, """SELECT fl.lot_no, p.part_no, fl.status
                                FROM finished_lots fl JOIN parts p ON p.id = fl.part_id
                                WHERE fl.status != 'shipped' LIMIT 12""")
    raw_lots = dbq(con, """SELECT rl.lot_no, p.part_no, rl.status
                           FROM raw_lots rl JOIN parts p ON p.id = rl.part_id
                           LIMIT 12""")
    # ERP's own demo activity window - NOT relative to "today" the way this
    # module's own seed dates are (erp.db was seeded whenever it was last
    # built/reset, a different moment to this module's own seed() run).
    # Date-ranged tables that could be asked about a SPECIFIC ERP-narrative
    # date (e.g. "the shift roster the night RUN-1111 ran") need to cover
    # that actual window, not just a few days either side of "today" -
    # confirmed live: workforce_roster's old range missed RUN-1111's date
    # entirely, so a real question about it got a genuine (not fake) empty
    # result. Falls back to a window around today if the ERP tables are
    # ever empty (never happens in practice, but keeps this from crashing).
    bounds = dbq1(con, """SELECT min(d) AS lo, max(d) AS hi FROM (
                          SELECT started_at AS d FROM runs WHERE started_at IS NOT NULL
                          UNION ALL SELECT found_at FROM defects
                          UNION ALL SELECT placed_at FROM holds)""")
    con.close()
    return {"lines": lines, "machines": machines, "operators": operators,
            "customers": customers, "parts": parts,
            "finished_lots": finished_lots, "raw_lots": raw_lots,
            "erp_date_bounds": bounds}


def seed() -> None:
    random.seed(42)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    ref = _erp_refs()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    lines = ref["lines"]
    machines = ref["machines"]
    operators = ref["operators"]
    customers = ref["customers"]
    parts = ref["parts"]

    # Roster coverage window: span the ERP's own activity window (2 days'
    # margin either side) as well as today, so a question tied to either
    # a specific ERP-narrative date or "right now" both get real rows.
    bounds = ref["erp_date_bounds"] or {}
    if bounds.get("lo") and bounds.get("hi"):
        lo_offset = (date.fromisoformat(bounds["lo"][:10]) - TODAY).days - 2
        hi_offset = (date.fromisoformat(bounds["hi"][:10]) - TODAY).days + 2
    else:
        lo_offset, hi_offset = -3, 3
    roster_range = range(min(lo_offset, -3), max(hi_offset, 3) + 1)

    # --- narrative anchor: raw lot WF-2261 was consumed on line A-1 -------
    anchor_line = "A-1"
    anchor_machines = [m["asset_no"] for m in machines if m["line_code"] == anchor_line]

    # --- CMMS --------------------------------------------------------
    priorities = ["low", "normal", "high", "urgent"]
    wo_statuses = ["open", "in_progress", "closed"]
    causes = ["bearing wear", "sensor fault", "hydraulic leak", "tooling change",
             "electrical fault", "calibration drift", "belt slip"]
    con.execute("""INSERT INTO cmms_work_orders (wo_no, asset_no, line_code, title,
                  priority, status, opened_on, due_on, closed_on, assigned_to, description)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
               ("WO-4401", "ASM-01", anchor_line,
                "Investigate intermittent torque-tool fault on assembly cell",
                "high", "open", d(-2), d(2), None, "Reece Ahmadi",
                "Torque verification station flagged three out-of-spec cycles "
                "on the shift that ran fastener lot WF-2261; tool recalibration "
                "in progress, cell held pending sign-off."))
    for i, m in enumerate(machines):
        if m["asset_no"] == "ASM-01":
            continue
        status = random.choice(wo_statuses)
        opened = -random.randint(1, 30)
        con.execute("""INSERT INTO cmms_work_orders (wo_no, asset_no, line_code,
                      title, priority, status, opened_on, due_on, closed_on,
                      assigned_to, description) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   (f"WO-{4402 + i}", m["asset_no"], m["line_code"],
                    f"{random.choice(['PM check', 'Alignment', 'Replace consumable', 'Inspect', 'Repair'])} - {m['name']}",
                    random.choice(priorities), status, d(opened), d(opened + 7),
                    d(opened + random.randint(1, 6)) if status == "closed" else None,
                    random.choice(["Reece Ahmadi", "Priya Nagesh", "Dale Fenwick"]),
                    f"Routine trigger from PM schedule for {m['asset_no']}."))

    con.execute("""INSERT INTO cmms_breakdowns (asset_no, line_code, started_at,
                  ended_at, downtime_minutes, cause, wo_no) VALUES (?,?,?,?,?,?,?)""",
               ("ASM-01", anchor_line, ts(-2, 14, 10), ts(-2, 15, 5), 55,
                "sensor fault - torque tool", "WO-4401"))
    for i, m in enumerate(random.sample(machines, min(10, len(machines)))):
        started = -random.randint(1, 45)
        down = random.choice([15, 25, 40, 60, 90, 120])
        con.execute("""INSERT INTO cmms_breakdowns (asset_no, line_code, started_at,
                      ended_at, downtime_minutes, cause, wo_no) VALUES (?,?,?,?,?,?,?)""",
                   (m["asset_no"], m["line_code"], ts(started, 8 + i % 8, 0),
                    ts(started, 8 + i % 8, down), down, random.choice(causes), None))

    for m in machines:
        last = -random.randint(5, 80)
        interval = random.choice([30, 60, 90])
        con.execute("""INSERT INTO cmms_pm_schedule (asset_no, task, interval_days,
                      last_done, next_due) VALUES (?,?,?,?,?)""",
                   (m["asset_no"], f"Scheduled PM - {m['name']}", interval,
                    d(last), d(last + interval)))

    spares = [("TC-FAST-M8", "M8 hex fastener - production consumable", 4200, 1500, "SP-A-04"),
             ("TC-BRG-2210", "Ball bearing 2210", 38, 20, "SP-B-11"),
             ("TC-SENS-TQ1", "Torque sensor module", 6, 4, "SP-A-02"),
             ("TC-BELT-V45", "V-belt 45in", 12, 6, "SP-C-08"),
             ("TC-HYD-SEAL", "Hydraulic seal kit", 22, 10, "SP-B-03"),
             ("TC-CAL-KIT", "Calibration reference kit", 3, 2, "SP-A-01")]
    for p in spares:
        con.execute("""INSERT INTO cmms_spare_parts (part_no, description,
                      qty_on_hand, reorder_point, bin) VALUES (?,?,?,?,?)""", p)

    # --- WMS -----------------------------------------------------------
    zones = ["Raw Materials", "WIP Staging", "Finished Goods", "Quarantine"]
    con.execute("""INSERT INTO wms_bins (bin_code, part_no, lot_no, qty, zone,
                  updated_at) VALUES (?,?,?,?,?,?)""",
               ("Q-04", next((r["part_no"] for r in ref["raw_lots"] if r["lot_no"] == "WF-2261"), "TC-30412"),
                "WF-2261", 1840, "Quarantine", ts(-2, 15, 30)))
    for i, rl in enumerate([r for r in ref["raw_lots"] if r["lot_no"] != "WF-2261"][:8]):
        con.execute("""INSERT INTO wms_bins (bin_code, part_no, lot_no, qty, zone,
                      updated_at) VALUES (?,?,?,?,?,?)""",
                   (f"RM-{i+1:02d}", rl["part_no"], rl["lot_no"],
                    random.choice([500, 900, 1200, 2400, 3000]),
                    "Raw Materials", ts(-random.randint(1, 20))))
    for i, fl in enumerate(ref["finished_lots"][:8]):
        con.execute("""INSERT INTO wms_bins (bin_code, part_no, lot_no, qty, zone,
                      updated_at) VALUES (?,?,?,?,?,?)""",
                   (f"FG-{i+1:02d}", fl["part_no"], fl["lot_no"],
                    random.choice([20, 45, 80, 120]), "Finished Goods",
                    ts(-random.randint(1, 10))))

    for i, p in enumerate(random.sample(parts, min(10, len(parts)))):
        sysq = random.choice([50, 120, 300, 600])
        variance = random.choice([0, 0, 0, -2, 3, -5, 8])
        con.execute("""INSERT INTO wms_cycle_counts (part_no, bin_code, counted_qty,
                      system_qty, variance, counted_on, counted_by)
                      VALUES (?,?,?,?,?,?,?)""",
                   (p["part_no"], f"RM-{(i%8)+1:02d}", sysq + variance, sysq,
                    variance, d(-random.randint(1, 14)),
                    random.choice(["Nadia Cross", "Owen Peaty", "Farid Osei"])))

    for i in range(6):
        con.execute("""INSERT INTO wms_putaways (part_no, lot_no, qty, from_dock,
                      target_bin, status, created_at) VALUES (?,?,?,?,?,?,?)""",
                   (parts[i % len(parts)]["part_no"], f"IN-{9000+i}",
                    random.choice([200, 400, 600]), f"Dock {random.choice(['1', '2', '3'])}",
                    f"RM-{(i%8)+1:02d}", random.choice(["pending", "pending", "completed"]),
                    ts(-random.randint(0, 5))))

    carriers = ["Coastal Freight", "Interstate Logistics", "Southern Cross Transport"]
    for i in range(8):
        direction = "inbound" if i % 2 == 0 else "outbound"
        con.execute("""INSERT INTO wms_dock_schedule (dock, direction, carrier,
                      scheduled_at, ref, status) VALUES (?,?,?,?,?,?)""",
                   (f"Dock {(i % 3) + 1}", direction, random.choice(carriers),
                    ts(random.randint(-2, 5), 7 + i, 0),
                    f"{'PO' if direction == 'inbound' else 'SHP'}-{9100+i}",
                    random.choice(["scheduled", "scheduled", "completed"])))

    # --- EHS -------------------------------------------------------------
    con.execute("""INSERT INTO ehs_incidents (incident_no, line_code, severity,
                  category, description, occurred_at, reported_by, status, injury)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
               ("EHS-3301", anchor_line, "minor", "near-miss-escalation",
                "Operator flagged a sharp edge on a returned fastener bin from "
                "quarantined lot WF-2261 during handling; no injury, bin relabelled "
                "and isolated.", ts(-2, 15, 40), "Jo Marsh", "open", 0))
    categories = ["slip/trip", "manual handling", "PPE non-compliance", "chemical exposure",
                 "machine guarding", "ergonomic strain"]
    severities = ["minor", "moderate", "major"]
    for i in range(9):
        line = random.choice(lines)["code"]
        con.execute("""INSERT INTO ehs_incidents (incident_no, line_code, severity,
                      category, description, occurred_at, reported_by, status, injury)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (f"EHS-{3302 + i}", line, random.choice(severities),
                    random.choice(categories),
                    f"{random.choice(categories).replace('/', ' or ')} incident logged on {line}.",
                    ts(-random.randint(1, 60), 9 + i % 7, 0),
                    random.choice([o["name"] for o in operators]),
                    random.choice(["open", "closed", "closed"]),
                    1 if random.random() < 0.15 else 0))

    for i in range(7):
        line = random.choice(lines)["code"]
        con.execute("""INSERT INTO ehs_near_misses (line_code, description,
                      occurred_at, reported_by, category) VALUES (?,?,?,?,?)""",
                   (line, f"Near-miss reported on {line}: {random.choice(categories)}.",
                    ts(-random.randint(1, 45)),
                    random.choice([o["name"] for o in operators]),
                    random.choice(categories)))

    con.execute("""INSERT INTO ehs_corrective_actions (incident_no, action, owner,
                  due_on, status, closed_on) VALUES (?,?,?,?,?,?)""",
               ("EHS-3301", "Re-inspect and re-tape all quarantine bins from "
                "supplier Warrigal Fasteners; brief handlers at shift start.",
                "Jo Marsh", d(3), "open", None))
    for i in range(6):
        opened = -random.randint(2, 40)
        status = random.choice(["open", "closed", "closed"])
        con.execute("""INSERT INTO ehs_corrective_actions (incident_no, action,
                      owner, due_on, status, closed_on) VALUES (?,?,?,?,?,?)""",
                   (f"EHS-{3302 + i}", "Corrective action assigned per incident review.",
                    random.choice(["Reece Ahmadi", "Priya Nagesh", "Dale Fenwick"]),
                    d(opened + 14), status, d(opened + 10) if status == "closed" else None))

    for line in lines:
        con.execute("""INSERT INTO ehs_safety_audits (line_code, audit_date,
                      auditor, score, findings) VALUES (?,?,?,?,?)""",
                   (line["code"], d(-random.randint(5, 90)),
                    random.choice(["Dale Fenwick", "Priya Nagesh"]),
                    round(random.uniform(78, 99), 1),
                    random.choice(["Minor housekeeping items only",
                                   "PPE compliance reinforced",
                                   "No findings", "One guarding gap corrected on site"])))

    # --- Workforce ---------------------------------------------------
    for o in operators:
        con.execute("""INSERT OR IGNORE INTO workforce_employees (emp_no, name, role,
                      line_code, shift, hire_date, employment_type) VALUES (?,?,?,?,?,?,?)""",
                   (o["emp_no"], o["name"], o["role"], o["line_code"], o["shift"],
                    d(-random.randint(120, 1800)),
                    random.choice(["full_time", "full_time", "full_time", "casual"])))

    for offset in roster_range:
        rd = d(offset)
        for o in operators:
            if random.random() < 0.85:
                con.execute("""INSERT INTO workforce_roster (roster_date, shift,
                              line_code, emp_no, role) VALUES (?,?,?,?,?)""",
                           (rd, o["shift"], o["line_code"], o["emp_no"], o["role"]))

    for i in range(10):
        o = random.choice(operators)
        con.execute("""INSERT INTO workforce_absences (emp_no, absence_date, reason,
                      approved) VALUES (?,?,?,?)""",
                   (o["emp_no"], d(-random.randint(1, 30)),
                    random.choice(["personal leave", "sick leave", "carer's leave"]),
                    1))

    cert_names = ["Forklift licence", "Working at heights", "Confined space entry",
                 "First aid", "Torque tool calibration", "Chemical handling"]
    for o in operators:
        for _ in range(random.randint(1, 2)):
            issued = -random.randint(60, 700)
            con.execute("""INSERT INTO workforce_certifications (emp_no, cert_name,
                          issued_on, expires_on) VALUES (?,?,?,?)""",
                       (o["emp_no"], random.choice(cert_names), d(issued),
                        d(issued + 730)))

    for i in range(10):
        o = random.choice(operators)
        con.execute("""INSERT INTO workforce_overtime (emp_no, work_date, hours,
                      reason) VALUES (?,?,?,?)""",
                   (o["emp_no"], d(-random.randint(1, 20)),
                    random.choice([2, 3, 4]),
                    random.choice(["production catch-up", "breakdown coverage",
                                  "shift handover overlap"])))

    # --- CRM -----------------------------------------------------------
    stages = ["prospecting", "qualifying", "proposal", "negotiation", "won", "lost"]
    for i, c in enumerate(customers):
        for j in range(random.randint(1, 2)):
            con.execute("""INSERT INTO crm_opportunities (opp_no, customer_code,
                          name, stage, value, expected_close, owner)
                          VALUES (?,?,?,?,?,?,?)""",
                       (f"OPP-{5000 + i*10 + j}", c["code"],
                        f"{c['name']} - {random.choice(['program expansion', 'new part award', 'annual contract renewal'])}",
                        random.choice(stages), random.choice([45000, 80000, 120000, 220000]),
                        d(random.randint(10, 90)),
                        random.choice(["Sam Ilic", "Grace Whitton"])))

    for i, c in enumerate(customers):
        p = parts[i % len(parts)]
        con.execute("""INSERT INTO crm_quotes (quote_no, customer_code, part_no, qty,
                      unit_price, status, issued_on, expires_on) VALUES (?,?,?,?,?,?,?,?)""",
                   (f"QT-{6000+i}", c["code"], p["part_no"],
                    random.choice([500, 1000, 2500]), round(random.uniform(4, 60), 2),
                    random.choice(["sent", "accepted", "expired"]),
                    d(-random.randint(1, 30)), d(random.randint(5, 30))))

    interaction_kinds = ["call", "site visit", "email", "QBR"]
    for i in range(14):
        c = random.choice(customers)
        con.execute("""INSERT INTO crm_interactions (customer_code, kind, summary,
                      occurred_at, owner) VALUES (?,?,?,?,?)""",
                   (c["code"], random.choice(interaction_kinds),
                    f"{random.choice(interaction_kinds).title()} with {c['name']} "
                    f"re: {random.choice(['delivery performance', 'upcoming RFQ', 'quality escape follow-up', 'program roadmap'])}.",
                    ts(-random.randint(1, 60)),
                    random.choice(["Sam Ilic", "Grace Whitton"])))

    risk_by_code = {}
    for i, c in enumerate(customers):
        risk = "high" if i == 0 else random.choice(["low", "low", "medium", "high"])
        risk_by_code[c["code"]] = risk
        con.execute("""INSERT INTO crm_account_health (customer_code, health_score,
                      nps, churn_risk, renewal_date, notes) VALUES (?,?,?,?,?,?)""",
                   (c["code"], {"low": random.randint(75, 95), "medium": random.randint(55, 74),
                               "high": random.randint(30, 54)}[risk],
                    {"low": random.randint(30, 60), "medium": random.randint(0, 29),
                    "high": random.randint(-30, -1)}[risk],
                    risk, d(random.randint(30, 365)),
                    "Elevated churn risk - recent quality escape under review."
                    if risk == "high" else "Stable account."))

    con.commit()
    con.close()


# ------------------------------------------------------------ tool functions
def _rows(con, sql, args=()):
    return dbq(con, sql, args)


def cmms_list_work_orders(args):
    con = connect()
    sql = "SELECT * FROM cmms_work_orders WHERE 1=1"
    params = []
    if args.get("status"):
        sql += " AND status = ?"; params.append(args["status"])
    if args.get("asset_no"):
        sql += " AND asset_no = ?"; params.append(args["asset_no"])
    if args.get("priority"):
        sql += " AND priority = ?"; params.append(args["priority"])
    rows = _rows(con, sql + " ORDER BY opened_on DESC LIMIT 50", params)
    con.close()
    return rows


def cmms_get_work_order(args):
    con = connect()
    row = dbq1(con, "SELECT * FROM cmms_work_orders WHERE wo_no = ?", (args.get("wo_no"),))
    con.close()
    return [row] if row else []


def cmms_list_breakdowns(args):
    con = connect()
    sql = "SELECT * FROM cmms_breakdowns WHERE 1=1"
    params = []
    if args.get("asset_no"):
        sql += " AND asset_no = ?"; params.append(args["asset_no"])
    if args.get("since"):
        sql += " AND started_at >= ?"; params.append(args["since"])
    rows = _rows(con, sql + " ORDER BY started_at DESC LIMIT 50", params)
    con.close()
    return rows


def cmms_list_pm_schedule(args):
    con = connect()
    sql = "SELECT * FROM cmms_pm_schedule WHERE 1=1"
    params = []
    if args.get("asset_no"):
        sql += " AND asset_no = ?"; params.append(args["asset_no"])
    if args.get("due_before"):
        sql += " AND next_due <= ?"; params.append(args["due_before"])
    rows = _rows(con, sql + " ORDER BY next_due ASC LIMIT 50", params)
    con.close()
    return rows


def cmms_list_spare_parts(args):
    con = connect()
    sql = "SELECT * FROM cmms_spare_parts WHERE 1=1"
    if str(args.get("low_stock_only", "")).lower() in ("1", "true", "yes"):
        sql += " AND qty_on_hand <= reorder_point"
    rows = _rows(con, sql + " ORDER BY part_no")
    con.close()
    return rows


def wms_get_bin_inventory(args):
    con = connect()
    sql = "SELECT * FROM wms_bins WHERE 1=1"
    params = []
    if args.get("part_no"):
        sql += " AND part_no = ?"; params.append(args["part_no"])
    if args.get("bin_code"):
        sql += " AND bin_code = ?"; params.append(args["bin_code"])
    rows = _rows(con, sql + " ORDER BY bin_code LIMIT 50", params)
    con.close()
    return rows


def wms_locate_lot(args):
    con = connect()
    rows = _rows(con, "SELECT * FROM wms_bins WHERE lot_no = ?", (args.get("lot_no"),))
    con.close()
    return rows


def wms_list_cycle_counts(args):
    con = connect()
    sql = "SELECT * FROM wms_cycle_counts WHERE 1=1"
    params = []
    if args.get("part_no"):
        sql += " AND part_no = ?"; params.append(args["part_no"])
    if str(args.get("variance_only", "")).lower() in ("1", "true", "yes"):
        sql += " AND variance != 0"
    rows = _rows(con, sql + " ORDER BY counted_on DESC LIMIT 50", params)
    con.close()
    return rows


def wms_list_pending_putaways(args):
    con = connect()
    rows = _rows(con, "SELECT * FROM wms_putaways WHERE status = 'pending' "
                      "ORDER BY created_at DESC LIMIT 50")
    con.close()
    return rows


def wms_list_dock_schedule(args):
    con = connect()
    sql = "SELECT * FROM wms_dock_schedule WHERE 1=1"
    params = []
    if args.get("date"):
        sql += " AND scheduled_at LIKE ?"; params.append(args["date"] + "%")
    rows = _rows(con, sql + " ORDER BY scheduled_at LIMIT 50", params)
    con.close()
    return rows


def ehs_list_incidents(args):
    con = connect()
    sql = "SELECT * FROM ehs_incidents WHERE 1=1"
    params = []
    if args.get("severity"):
        sql += " AND severity = ?"; params.append(args["severity"])
    if args.get("line_code"):
        sql += " AND line_code = ?"; params.append(args["line_code"])
    if args.get("since"):
        sql += " AND occurred_at >= ?"; params.append(args["since"])
    rows = _rows(con, sql + " ORDER BY occurred_at DESC LIMIT 50", params)
    con.close()
    return rows


def ehs_get_incident(args):
    con = connect()
    row = dbq1(con, "SELECT * FROM ehs_incidents WHERE incident_no = ?",
              (args.get("incident_no"),))
    con.close()
    return [row] if row else []


def ehs_list_near_misses(args):
    con = connect()
    sql = "SELECT * FROM ehs_near_misses WHERE 1=1"
    params = []
    if args.get("line_code"):
        sql += " AND line_code = ?"; params.append(args["line_code"])
    if args.get("since"):
        sql += " AND occurred_at >= ?"; params.append(args["since"])
    rows = _rows(con, sql + " ORDER BY occurred_at DESC LIMIT 50", params)
    con.close()
    return rows


def ehs_list_corrective_actions(args):
    con = connect()
    sql = "SELECT * FROM ehs_corrective_actions WHERE 1=1"
    params = []
    if args.get("status"):
        sql += " AND status = ?"; params.append(args["status"])
    if args.get("incident_no"):
        sql += " AND incident_no = ?"; params.append(args["incident_no"])
    rows = _rows(con, sql + " ORDER BY due_on LIMIT 50", params)
    con.close()
    return rows


def ehs_list_safety_audits(args):
    con = connect()
    sql = "SELECT * FROM ehs_safety_audits WHERE 1=1"
    params = []
    if args.get("line_code"):
        sql += " AND line_code = ?"; params.append(args["line_code"])
    rows = _rows(con, sql + " ORDER BY audit_date DESC LIMIT 50", params)
    con.close()
    return rows


def workforce_get_roster(args):
    con = connect()
    sql = "SELECT * FROM workforce_roster WHERE 1=1"
    params = []
    if args.get("date"):
        sql += " AND roster_date = ?"; params.append(args["date"])
    if args.get("shift"):
        sql += " AND shift = ?"; params.append(args["shift"])
    if args.get("line_code"):
        sql += " AND line_code = ?"; params.append(args["line_code"])
    rows = _rows(con, sql + " ORDER BY roster_date DESC LIMIT 100", params)
    con.close()
    return rows


def workforce_list_absences(args):
    con = connect()
    sql = "SELECT * FROM workforce_absences WHERE 1=1"
    params = []
    if args.get("emp_no"):
        sql += " AND emp_no = ?"; params.append(args["emp_no"])
    if args.get("since"):
        sql += " AND absence_date >= ?"; params.append(args["since"])
    rows = _rows(con, sql + " ORDER BY absence_date DESC LIMIT 50", params)
    con.close()
    return rows


def workforce_list_certifications(args):
    con = connect()
    sql = "SELECT * FROM workforce_certifications WHERE 1=1"
    params = []
    if args.get("emp_no"):
        sql += " AND emp_no = ?"; params.append(args["emp_no"])
    if args.get("expiring_within_days"):
        cutoff = d(int(args["expiring_within_days"]))
        sql += " AND expires_on <= ?"; params.append(cutoff)
    rows = _rows(con, sql + " ORDER BY expires_on ASC LIMIT 50", params)
    con.close()
    return rows


def workforce_list_overtime(args):
    con = connect()
    sql = "SELECT * FROM workforce_overtime WHERE 1=1"
    params = []
    if args.get("emp_no"):
        sql += " AND emp_no = ?"; params.append(args["emp_no"])
    if args.get("since"):
        sql += " AND work_date >= ?"; params.append(args["since"])
    rows = _rows(con, sql + " ORDER BY work_date DESC LIMIT 50", params)
    con.close()
    return rows


def workforce_get_employee(args):
    con = connect()
    row = dbq1(con, "SELECT * FROM workforce_employees WHERE emp_no = ?",
              (args.get("emp_no"),))
    con.close()
    return [row] if row else []


def crm_list_opportunities(args):
    con = connect()
    sql = "SELECT * FROM crm_opportunities WHERE 1=1"
    params = []
    if args.get("customer_code"):
        sql += " AND customer_code = ?"; params.append(args["customer_code"])
    if args.get("stage"):
        sql += " AND stage = ?"; params.append(args["stage"])
    rows = _rows(con, sql + " ORDER BY expected_close LIMIT 50", params)
    con.close()
    return rows


def crm_get_account_health(args):
    con = connect()
    row = dbq1(con, "SELECT * FROM crm_account_health WHERE customer_code = ?",
              (args.get("customer_code"),))
    con.close()
    return [row] if row else []


def crm_list_quotes(args):
    con = connect()
    sql = "SELECT * FROM crm_quotes WHERE 1=1"
    params = []
    if args.get("customer_code"):
        sql += " AND customer_code = ?"; params.append(args["customer_code"])
    if args.get("status"):
        sql += " AND status = ?"; params.append(args["status"])
    rows = _rows(con, sql + " ORDER BY issued_on DESC LIMIT 50", params)
    con.close()
    return rows


def crm_list_interactions(args):
    con = connect()
    sql = "SELECT * FROM crm_interactions WHERE 1=1"
    params = []
    if args.get("customer_code"):
        sql += " AND customer_code = ?"; params.append(args["customer_code"])
    if args.get("since"):
        sql += " AND occurred_at >= ?"; params.append(args["since"])
    rows = _rows(con, sql + " ORDER BY occurred_at DESC LIMIT 50", params)
    con.close()
    return rows


def crm_list_at_risk_accounts(args):
    con = connect()
    rows = _rows(con, "SELECT * FROM crm_account_health WHERE churn_risk = 'high' "
                      "ORDER BY health_score ASC")
    con.close()
    return rows


# ------------------------------------------------------------ MCP sources
def _t(name, description, properties, fn):
    return {"name": name, "description": description,
           "input_schema": {"type": "object", "properties": properties},
           "fn": fn}


_STR = lambda desc: {"type": "string", "description": desc}

SOURCES = [
    {
        "path": "/mcp/cmms",
        "name": "tallowa-cmms",
        "title": "Tallowa CMMS (maintenance)",
        "description": "Computerised maintenance management system: work "
                       "orders, breakdown history, preventive-maintenance "
                       "schedule and spare-parts stock for plant machines.",
        "tools": [
            _t("cmms_list_work_orders",
              "List maintenance work orders, optionally filtered. "
              "args: {status, asset_no, priority}",
              {"status": _STR("open|in_progress|closed"),
               "asset_no": _STR("Machine asset number, e.g. ASM-01"),
               "priority": _STR("low|normal|high|urgent")},
              cmms_list_work_orders),
            _t("cmms_get_work_order", "Get one work order by number. args: {wo_no}",
              {"wo_no": _STR("Work order number, e.g. WO-4401")},
              cmms_get_work_order),
            _t("cmms_list_breakdowns",
              "List unplanned breakdown/downtime events. args: {asset_no, since}",
              {"asset_no": _STR("Machine asset number"),
               "since": _STR("ISO date/time lower bound")},
              cmms_list_breakdowns),
            _t("cmms_list_pm_schedule",
              "List preventive-maintenance schedule entries. args: {asset_no, due_before}",
              {"asset_no": _STR("Machine asset number"),
               "due_before": _STR("ISO date upper bound on next_due")},
              cmms_list_pm_schedule),
            _t("cmms_list_spare_parts",
              "List maintenance spare-parts stock. args: {low_stock_only}",
              {"low_stock_only": _STR("true to only show items at/under reorder point")},
              cmms_list_spare_parts),
        ],
    },
    {
        "path": "/mcp/wms",
        "name": "tallowa-wms",
        "title": "Tallowa WMS (warehouse)",
        "description": "Warehouse management system: physical bin-level "
                       "inventory, cycle counts, putaway tasks and dock "
                       "schedule - the physical-floor truth, distinct from "
                       "the ERP's order-level stock ledger.",
        "tools": [
            _t("wms_get_bin_inventory",
              "Get physical bin inventory. args: {part_no, bin_code}",
              {"part_no": _STR("Part number"), "bin_code": _STR("Bin code, e.g. RM-01")},
              wms_get_bin_inventory),
            _t("wms_locate_lot", "Find which bin(s) a lot currently sits in. args: {lot_no}",
              {"lot_no": _STR("Raw or finished lot number, e.g. WF-2261")},
              wms_locate_lot),
            _t("wms_list_cycle_counts",
              "List cycle-count records. args: {part_no, variance_only}",
              {"part_no": _STR("Part number"),
               "variance_only": _STR("true to only show counts with a variance")},
              wms_list_cycle_counts),
            _t("wms_list_pending_putaways", "List putaway tasks not yet completed.",
              {}, wms_list_pending_putaways),
            _t("wms_list_dock_schedule",
              "List inbound/outbound dock bookings. args: {date}",
              {"date": _STR("ISO date, e.g. 2026-08-05")}, wms_list_dock_schedule),
        ],
    },
    {
        "path": "/mcp/ehs",
        "name": "tallowa-ehs",
        "title": "Tallowa EHS (safety)",
        "description": "Environmental, health & safety system: incident "
                       "reports, near-misses, corrective actions and safety "
                       "audit scores by line.",
        "tools": [
            _t("ehs_list_incidents",
              "List safety incidents. args: {severity, line_code, since}",
              {"severity": _STR("minor|moderate|major"),
               "line_code": _STR("Line code, e.g. A-1"),
               "since": _STR("ISO date/time lower bound")},
              ehs_list_incidents),
            _t("ehs_get_incident", "Get one incident by number. args: {incident_no}",
              {"incident_no": _STR("Incident number, e.g. EHS-3301")}, ehs_get_incident),
            _t("ehs_list_near_misses", "List near-miss reports. args: {line_code, since}",
              {"line_code": _STR("Line code"), "since": _STR("ISO date/time lower bound")},
              ehs_list_near_misses),
            _t("ehs_list_corrective_actions",
              "List corrective actions raised from incidents. args: {status, incident_no}",
              {"status": _STR("open|closed"), "incident_no": _STR("Incident number")},
              ehs_list_corrective_actions),
            _t("ehs_list_safety_audits", "List line safety-audit results. args: {line_code}",
              {"line_code": _STR("Line code")}, ehs_list_safety_audits),
        ],
    },
    {
        "path": "/mcp/workforce",
        "name": "tallowa-workforce",
        "title": "Tallowa Workforce (rostering)",
        "description": "Workforce management system: shift rosters, "
                       "absences, certification expiry and overtime - "
                       "distinct from the ERP's operator/skills master.",
        "tools": [
            _t("workforce_get_roster",
              "Get the shift roster. args: {date, shift, line_code}",
              {"date": _STR("ISO date"), "shift": _STR("day|afternoon|night"),
               "line_code": _STR("Line code")}, workforce_get_roster),
            _t("workforce_list_absences", "List absences. args: {emp_no, since}",
              {"emp_no": _STR("Employee number, e.g. TC1001"),
               "since": _STR("ISO date lower bound")}, workforce_list_absences),
            _t("workforce_list_certifications",
              "List employee certifications, optionally expiring soon. "
              "args: {emp_no, expiring_within_days}",
              {"emp_no": _STR("Employee number"),
               "expiring_within_days": _STR("Only certs expiring within N days")},
              workforce_list_certifications),
            _t("workforce_list_overtime", "List overtime hours. args: {emp_no, since}",
              {"emp_no": _STR("Employee number"), "since": _STR("ISO date lower bound")},
              workforce_list_overtime),
            _t("workforce_get_employee", "Get one employee record. args: {emp_no}",
              {"emp_no": _STR("Employee number")}, workforce_get_employee),
        ],
    },
    {
        "path": "/mcp/crm",
        "name": "tallowa-crm",
        "title": "Tallowa CRM (sales pipeline)",
        "description": "Customer relationship management system: sales "
                       "pipeline opportunities, quotes, contact history and "
                       "account health/churn-risk - distinct from the ERP's "
                       "order-execution customer master.",
        "tools": [
            _t("crm_list_opportunities",
              "List sales pipeline opportunities. args: {customer_code, stage}",
              {"customer_code": _STR("Customer code, e.g. MAR"),
               "stage": _STR("prospecting|qualifying|proposal|negotiation|won|lost")},
              crm_list_opportunities),
            _t("crm_get_account_health",
              "Get account health score, NPS and churn risk. args: {customer_code}",
              {"customer_code": _STR("Customer code")}, crm_get_account_health),
            _t("crm_list_quotes", "List quotes. args: {customer_code, status}",
              {"customer_code": _STR("Customer code"),
               "status": _STR("sent|accepted|expired")}, crm_list_quotes),
            _t("crm_list_interactions",
              "List logged customer interactions (calls, visits, QBRs). "
              "args: {customer_code, since}",
              {"customer_code": _STR("Customer code"),
               "since": _STR("ISO date/time lower bound")}, crm_list_interactions),
            _t("crm_list_at_risk_accounts",
              "List accounts flagged high churn risk, worst-health first.",
              {}, crm_list_at_risk_accounts),
        ],
    },
]


_UUID_SUFFIX = re.compile(
    r"__[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _strip_agent_suffix(name: str) -> str:
    # ARAG's Smart-agent node namespaces each registered agent's tool names
    # with a trailing "__<uuid>" - see mcp.py's identical fix, learned the
    # hard way on the first source (ARAG-REARCH-STATE.md, 9th pass).
    return _UUID_SUFFIX.sub("", name or "")


def _call_tool(source: dict, name: str, arguments: dict) -> dict:
    lookup = _strip_agent_suffix(name)
    t = next((x for x in source["tools"] if x["name"] == lookup), None)
    if not t:
        return {"isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
    try:
        rows = t["fn"](arguments or {})
    except Exception as e:
        return {"isError": True,
                "content": [{"type": "text", "text": f"Tool error: {e}"}]}
    return {"content": [{"type": "text", "text": json.dumps(rows)}]}


async def _handle_rpc(source: dict, msg: dict):
    method = msg.get("method") or ""
    params = msg.get("params") or {}
    rid = msg.get("id")
    if rid is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": text}}

    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or "2025-03-26",
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": source["name"], "version": "1.0.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": t["name"], "description": t["description"],
                              "inputSchema": t["input_schema"]}
                             for t in source["tools"]]})
    if method == "tools/call":
        res = await asyncio.to_thread(
            _call_tool, source, params.get("name") or "", params.get("arguments") or {})
        return ok(res)
    return err(-32601, f"Method not found: {method}")


def mount(app: FastAPI) -> None:
    """Register one /mcp/<system> Streamable-HTTP JSON-RPC endpoint per
    source in SOURCES. Call AFTER mcp.mount(app) - independent of it, but
    keeps hosted-MCP-surface registration together in app.py."""
    if not DB_PATH.exists():
        seed()

    for source in SOURCES:
        def make_handlers(source=source):
            @app.post(source["path"], include_in_schema=False)
            async def mcp_post(request: Request):
                try:
                    payload = await request.json()
                except Exception:
                    return JSONResponse({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "Parse error"}},
                                        status_code=400)
                if isinstance(payload, list):
                    out = [r for m in payload
                          if (r := await _handle_rpc(source, m)) is not None]
                    if not out:
                        return Response(status_code=202)
                    return JSONResponse(out)
                res = await _handle_rpc(source, payload)
                if res is None:
                    return Response(status_code=202)
                return JSONResponse(res)

            @app.get(source["path"], include_in_schema=False)
            async def mcp_get():
                return JSONResponse({
                    "service": source["name"], "transport": "streamable-http",
                    "tools": len(source["tools"]),
                    "message": f"POST JSON-RPC 2.0 frames to this URL. "
                              f"{source['description']}",
                })
            return mcp_post, mcp_get
        make_handlers()
