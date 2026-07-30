"""Tallowa Components - the /api/ai/* surface (45 grounded features).

Three grounding modes, all through the platform proxy (key server-side only):
  kb      - retrieval + cited answer over the plant document set
  erp     - generation grounded in a live data digest queried from the ERP at
            call time (the digest is returned to the UI as the visible grounding)
  hybrid  - retrieval over the document set PLUS the live ERP digest injected
            into the generation template (cited answer + data panel)

Every retrieval is hard-scoped via resource_filters to this app's own seeded
resources. The generative model is pinned (the KB default refuses).
"""
import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from database import connect, q, q1, now, audit_log
from erp import (AP_ERROR_CODES, ENV, ap_similar_group, current_user,
                 trace_backward, trace_forward)

ROOT = Path(__file__).resolve().parent
HOST = ENV.get("ARAG_HOST", "")
KB = ENV.get("KB_ID", "")
HDRS = {"X-NUCLIA-SERVICEACCOUNT": f"Bearer {ENV.get('KB_TOKEN','')}"}
MODEL = "chatgpt-azure-4o-mini"

MANIFEST_PATH = ROOT / "data" / "kb-manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
RID_TO_FILE = {rid: f for f, rid in MANIFEST.items()}

SCOPES = {
    "quality": lambda f: f.startswith(("qm-", "qp-")),
    "safety": lambda f: f.startswith(("safety-", "sds-", "sec-04", "sop-line")),
    "work": lambda f: f.startswith(("swi-", "sop-", "qp-spc")),
    "supplier": lambda f: f.startswith(("sqa-", "sop-receiving", "qp-ppap")),
    "calibration": lambda f: f.startswith(("cal-", "qp-spc")),
    "training": lambda f: f.startswith(("trn-", "sop-line")),
    "customer": lambda f: f.startswith(("csr-", "wty-", "qp-8d")),
    "containment": lambda f: f.startswith(("qp-8d", "qm-07", "qm-04", "sqa-")),
    "finance": lambda f: f.startswith(("fin-",)),
    "all": lambda f: True,
}


def scope_rids(scope: str) -> list[str]:
    keep = SCOPES.get(scope, SCOPES["all"])
    return [rid for f, rid in MANIFEST.items() if keep(f)]


STYLE = ("Use Australian English spelling. Use a spaced hyphen, never an em dash. "
         "Never invent a figure, date, lot number or name - only use what the "
         "context and live plant data provide. Plain, direct language. ")

GROUNDED = STYLE + ("Answer only from the provided context and live plant data; "
                    "if something is not covered, say so plainly. ")

router = APIRouter(prefix="/api/ai")


# ------------------------------------------------------------ model calls
async def kb_ask(query: str, system: str, scope: str = "all", digest: str = "",
                 schema=None, top_k: int = 15, compose: bool = False) -> dict:
    prompt = {"system": system}
    if digest or compose:
        block = digest.replace("{", "(").replace("}", ")")
        prompt["user"] = (
            "Document context:\n{context}\n\n"
            + (f"Live plant data (queried now from the ERP):\n{block}\n\n" if block else "")
            + "Request: {question}\n\n"
            + ("Write the requested piece now, using only facts from the document "
               "context and the live plant data above." if compose else
               "Answer now, using only the document context and the live plant "
               "data above."))
    payload = {
        "query": query[:1900],
        "features": ["keyword", "semantic"],
        "citations": True,
        "top_k": top_k,
        "resource_filters": scope_rids(scope),
        "prompt": prompt,
        "generative_model": MODEL,
    }
    if schema:
        payload["answer_json_schema"] = schema
        payload["citations"] = False  # API rejects citations + schema together
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=90) as cx:
        r = await cx.post(f"{HOST}/api/v1/kb/{KB}/ask",
                          headers={**HDRS, "X-Synchronous": "true",
                                   "Content-Type": "application/json"},
                          json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"ask failed ({r.status_code}): {r.text[:200]}")
    d = r.json()
    d["_latency_ms"] = int((time.monotonic() - t0) * 1000)
    return d


async def predict_gen(instruction: str, payload_text: str) -> str:
    """Ungrounded-in-KB generation grounded in the injected live digest."""
    body = {
        "question": payload_text[:6000],
        "user_id": "erp",
        "query_context": [],
        "user_prompt": {"prompt": instruction.replace("{", "(").replace("}", ")")
                        + "\n\n{question}"},
        "generative_model": MODEL,
    }
    async with httpx.AsyncClient(timeout=90) as cx:
        r = await cx.post(f"{HOST}/api/v1/kb/{KB}/predict/chat",
                          headers={**HDRS, "X-Synchronous": "true",
                                   "Content-Type": "application/json"},
                          json=body)
    r.raise_for_status()
    text = re.sub(r"-?\d$", "", r.text.rstrip())
    if not text.strip():
        raise RuntimeError("empty generation")
    return text.strip()


def parse_citations(retrieval: dict) -> list[dict]:
    out = []
    for rid, res in (retrieval or {}).get("resources", {}).items():
        title = res.get("title") or rid
        for fid, field in (res.get("fields") or {}).items():
            for pid, para in (field.get("paragraphs") or {}).items():
                out.append({"rid": rid, "file": RID_TO_FILE.get(rid, title),
                            "title": title, "score": para.get("score"),
                            "snippet": (para.get("text") or "")[:280]})
    out.sort(key=lambda c: -(c["score"] or 0))
    seen, dedup = set(), []
    for c in out:
        key = (c["rid"], c["snippet"][:80])
        if key not in seen:
            seen.add(key)
            dedup.append(c)
    return dedup[:8]


def clean(text: str) -> str:
    return re.sub(r"\s*—\s*", " - ", text or "")


def cached_golden(key: str):
    p = ROOT / "static" / "cached" / f"{key}.json"
    if key and re.fullmatch(r"[a-z0-9\-]+", key) and p.exists():
        d = json.loads(p.read_text())
        d["cached"] = True
        return d
    return None


# Words too generic to prove a question MATCHES a cached golden's own
# scenario - excluded so two unrelated questions that happen to both be
# "which X are Y and what/how Z" don't look related on shared function words.
_GOLDEN_MATCH_STOPWORDS = {
    "a", "an", "the", "is", "are", "and", "or", "what", "which", "who", "for",
    "to", "of", "on", "in", "right", "now", "how", "much", "that", "this",
    "still", "currently", "at", "with", "from", "any",
}


def _question_tokens(q_text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9-]+", (q_text or "").lower())
            if w not in _GOLDEN_MATCH_STOPWORDS and len(w) > 2}


def _golden_matches_question(golden_events: list, asked_question: str) -> bool:
    """A cached golden is a safety net for the SAME question it was captured
    for, never a stand-in for a different scenario dressed up as a confident
    answer - that is exactly the bluff the honest gate exists to prevent.
    Every ops-assistant question shares one `golden` key (the UI always
    sends "ops-assistant"), so a bare key match is not enough; this compares
    the asked question against the golden's OWN captured question (its
    `start` event) by shared distinctive keywords, since the demo chip's
    wording can drift slightly from the golden's captured text."""
    stored_q = next((ev.get("question") for ev in golden_events
                     if ev.get("type") == "start" and ev.get("question")), None)
    if not stored_q:
        return False
    stored_tokens = _question_tokens(stored_q)
    if not stored_tokens:
        return False
    asked_tokens = _question_tokens(asked_question)
    overlap = stored_tokens & asked_tokens
    # Most of the golden's OWN vocabulary must reappear in what was asked -
    # a short generic question must not "cover" a long specific one.
    return len(overlap) / len(stored_tokens) >= 0.6


# =====================================================================
# Live-data digest builders. Each returns (digest_text, data_used_dict).
# =====================================================================
def money(v):
    return f"${(v or 0):,.2f}"


def dig_briefing(con, body):
    today = date.today().isoformat()
    week = (date.today() + timedelta(days=7)).isoformat()
    lines = []
    holds = q(con, "SELECT hold_no, scope, reason FROM holds WHERE status='open'")
    lines.append(f"Open quality holds ({len(holds)}):")
    lines += [f"  {h['hold_no']} [{h['scope']}] {h['reason'][:110]}" for h in holds]
    stopped = q(con, "SELECT code, stoppage_reason FROM lines WHERE status!='running'")
    lines.append(f"Stopped lines ({len(stopped)}):")
    lines += [f"  {s['code']}: {s['stoppage_reason']}" for s in stopped]
    crit = q(con, """SELECT defect_no, code, description FROM defects
                     WHERE status='open' AND severity='critical'""")
    lines.append(f"Open critical defects ({len(crit)}):")
    lines += [f"  {d['defect_no']} {d['code']}: {d['description'][:100]}" for d in crit]
    late = q(con, """SELECT po.po_no, s.name, po.expected_date FROM purchase_orders po
                     JOIN suppliers s ON s.id=po.supplier_id
                     WHERE po.status IN ('sent','confirmed') AND po.expected_date<?""",
             (today,))
    lines.append(f"Late supplier deliveries ({len(late)}):")
    lines += [f"  {p['po_no']} {p['name']} expected {p['expected_date']}" for p in late]
    due = q(con, """SELECT so.so_no, c.name, so.promised_date FROM sales_orders so
                    JOIN customers c ON c.id=so.customer_id
                    WHERE so.status IN ('approved','in_production')
                    AND so.promised_date<=? ORDER BY so.promised_date""", (week,))
    lines.append(f"Customer orders due within 7 days ({len(due)}):")
    lines += [f"  {d['so_no']} {d['name']} promised {d['promised_date']}" for d in due]
    over = q(con, "SELECT inv_no, total FROM invoices WHERE status='overdue'")
    lines.append(f"Overdue invoices ({len(over)}): "
                 + ", ".join(f"{o['inv_no']} {money(o['total'])}" for o in over))
    low = q1(con, """SELECT COUNT(*) n FROM (SELECT p.id FROM parts p
                     LEFT JOIN stock s ON s.part_id=p.id
                     LEFT JOIN locations l ON l.id=s.location_id AND l.type!='quarantine'
                     WHERE p.reorder_point>0 GROUP BY p.id
                     HAVING COALESCE(SUM(CASE WHEN l.id IS NULL THEN 0 ELSE s.qty END),0)
                            <p.reorder_point)""")["n"]
    lines.append(f"Parts below reorder point: {low}")
    exp = q(con, """SELECT o.name, s.code, os.expires_on FROM operator_skills os
                    JOIN operators o ON o.id=os.operator_id
                    JOIN skills s ON s.id=os.skill_id
                    WHERE os.expires_on <= ? ORDER BY os.expires_on""",
            ((date.today() + timedelta(days=60)).isoformat(),))
    lines.append("Certifications expired or expiring within 60 days: "
                 + ", ".join(f"{e['name']} ({e['code']} {e['expires_on']})" for e in exp))
    return "\n".join(lines), {"holds": len(holds), "stopped_lines": len(stopped),
                              "critical_defects": len(crit), "late_pos": len(late),
                              "orders_due_7d": len(due), "overdue_invoices": len(over),
                              "low_stock": low, "cert_issues": len(exp)}


def dig_dispatch(con, body):
    runs = q(con, """SELECT r.run_no, r.status, r.priority, r.qty_planned, r.qty_good,
                     r.scheduled_start, r.scheduled_end, p.part_no, l.code line,
                     l.status line_status, so.so_no, so.promised_date, c.name customer
                     FROM runs r JOIN parts p ON p.id=r.part_id
                     LEFT JOIN lines l ON l.id=r.line_id
                     LEFT JOIN sales_orders so ON so.id=r.sales_order_id
                     LEFT JOIN customers c ON c.id=so.customer_id
                     WHERE r.status IN ('planned','released','in_progress','quality_hold')
                     ORDER BY r.scheduled_start""")
    lines = ["Open production runs (dispatch list):"]
    for r in runs:
        lines.append(f"  {r['run_no']} {r['part_no']} x{r['qty_planned']:.0f} on "
                     f"{r['line']} ({r['line_status']}) status={r['status']} "
                     f"priority={r['priority']} start {r['scheduled_start']} "
                     f"customer={r['customer'] or 'stock'} "
                     f"promised={r['promised_date'] or '-'}")
    low = q(con, """SELECT p.part_no, p.reorder_point,
                    COALESCE(SUM(CASE WHEN l.type!='quarantine' THEN s.qty END),0) oh
                    FROM parts p LEFT JOIN stock s ON s.part_id=p.id
                    LEFT JOIN locations l ON l.id=s.location_id
                    WHERE p.reorder_point>0 GROUP BY p.id
                    HAVING oh < p.reorder_point""")
    lines.append("Material constraints (below reorder): "
                 + ", ".join(f"{r['part_no']} ({r['oh']:.0f} on hand)" for r in low))
    return "\n".join(lines), {"open_runs": len(runs), "constraints": len(low)}


def dig_run(con, body):
    run_no = body.get("run_no") or ""
    r = q1(con, """SELECT r.*, p.part_no, p.name part_name, p.safety_critical,
                   l.code line, so.so_no, c.name customer
                   FROM runs r JOIN parts p ON p.id=r.part_id
                   LEFT JOIN lines l ON l.id=r.line_id
                   LEFT JOIN sales_orders so ON so.id=r.sales_order_id
                   LEFT JOIN customers c ON c.id=so.customer_id WHERE r.run_no=?""",
           (run_no,))
    if not r:
        raise HTTPException(404, f"Run {run_no} not found")
    lines = [f"Production run {r['run_no']}: {r['part_no']} {r['part_name']} "
             f"x{r['qty_planned']:.0f} on line {r['line']}, status {r['status']}, "
             f"good {r['qty_good']:.0f}, scrap {r['qty_scrap']:.0f}, "
             f"customer {r['customer'] or 'stock'}, order {r['so_no'] or '-'}, "
             f"safety critical: {'yes' if r['safety_critical'] else 'no'}, "
             f"std cost {money(r['std_cost'])}, actual {money(r['actual_cost'])}."]
    if r["notes"]:
        lines.append(f"Notes: {r['notes']}")
    mats = q(con, """SELECT rm.qty, p.part_no, rl.lot_no, s.name supplier
                     FROM run_materials rm JOIN parts p ON p.id=rm.part_id
                     LEFT JOIN raw_lots rl ON rl.id=rm.raw_lot_id
                     LEFT JOIN suppliers s ON s.id=rl.supplier_id
                     WHERE rm.run_id=?""", (r["id"],))
    lines.append("Materials consumed: " + "; ".join(
        f"{m['part_no']} x{m['qty']:.0f}"
        + (f" lot {m['lot_no']} ({m['supplier']})" if m["lot_no"] else "")
        for m in mats))
    defs = q(con, """SELECT defect_no, code, severity, qty, status, description
                     FROM defects WHERE run_id=?""", (r["id"],))
    for dd in defs:
        lines.append(f"Defect {dd['defect_no']} [{dd['severity']}/{dd['status']}] "
                     f"{dd['code']} qty {dd['qty']:.0f}: {dd['description'][:100]}")
    tt = q(con, """SELECT o.name, rt.station, rt.minutes FROM run_time rt
                   JOIN operators o ON o.id=rt.operator_id WHERE rt.run_id=?""",
           (r["id"],))
    lines.append("Time entries: " + "; ".join(
        f"{t['name']} {t['minutes']:.0f} min at {t['station']}" for t in tt))
    fl = q(con, "SELECT lot_no, qty_produced, qty_shipped, status FROM finished_lots "
                "WHERE run_id=?", (r["id"],))
    for f in fl:
        lines.append(f"Finished lot {f['lot_no']}: {f['qty_produced']:.0f} produced, "
                     f"{f['qty_shipped']:.0f} shipped, status {f['status']}")
    hh = q(con, "SELECT hold_no, reason, status FROM holds WHERE scope='run' "
                "AND scope_id=?", (r["id"],))
    for h in hh:
        lines.append(f"Hold {h['hold_no']} ({h['status']}): {h['reason'][:110]}")
    return "\n".join(lines), {"run": run_no, "materials": len(mats),
                              "defects": len(defs), "time_entries": len(tt)}


def dig_similar_runs(con, body):
    run_no = body.get("run_no") or ""
    r = q1(con, "SELECT * FROM runs WHERE run_no=?", (run_no,))
    if not r:
        raise HTTPException(404, f"Run {run_no} not found")
    sib = q(con, """SELECT r.run_no, r.status, r.qty_planned, r.qty_good, r.qty_scrap,
                    r.std_cost, r.actual_cost, r.completed_at, l.code line
                    FROM runs r LEFT JOIN lines l ON l.id=r.line_id
                    WHERE r.part_id=? AND r.run_no!=? ORDER BY r.completed_at DESC
                    LIMIT 8""", (r["part_id"], run_no))
    p = q1(con, "SELECT part_no, name FROM parts WHERE id=?", (r["part_id"],))
    lines = [f"Past runs of {p['part_no']} {p['name']}:"]
    for s in sib:
        ftt = (100 * s["qty_good"] / (s["qty_good"] + s["qty_scrap"])
               if (s["qty_good"] or 0) + (s["qty_scrap"] or 0) else None)
        lines.append(f"  {s['run_no']} [{s['status']}] planned {s['qty_planned']:.0f} "
                     f"good {s['qty_good']:.0f} scrap {s['qty_scrap']:.0f} "
                     f"(FTT {ftt:.1f}%)" if ftt is not None else
                     f"  {s['run_no']} [{s['status']}] planned {s['qty_planned']:.0f}")
        defs = q(con, "SELECT code, qty FROM defects WHERE run_id="
                      "(SELECT id FROM runs WHERE run_no=?)", (s["run_no"],))
        if defs:
            lines.append("    defects: " + ", ".join(
                f"{d['code']} x{d['qty']:.0f}" for d in defs))
    return "\n".join(lines), {"similar_runs": len(sib), "part": p["part_no"]}


def dig_parts_kit(con, body):
    run_no = body.get("run_no") or ""
    r = q1(con, """SELECT r.*, p.part_no, p.name FROM runs r
                   JOIN parts p ON p.id=r.part_id WHERE r.run_no=?""", (run_no,))
    if not r:
        raise HTTPException(404, f"Run {run_no} not found")
    bom = q(con, """SELECT b.qty_per, b.station, c.part_no, c.name, c.traceable
                    FROM boms b JOIN parts c ON c.id=b.component_part_id
                    WHERE b.parent_part_id=?""", (r["part_id"],))
    lines = [f"Kit for {r['run_no']} - {r['part_no']} x{r['qty_planned']:.0f}:"]
    for b in bom:
        need = b["qty_per"] * r["qty_planned"]
        oh = q1(con, """SELECT COALESCE(SUM(s.qty),0) v FROM stock s
                        JOIN locations l ON l.id=s.location_id
                        JOIN parts p ON p.id=s.part_id
                        WHERE p.part_no=? AND l.type!='quarantine'""",
                (b["part_no"],))["v"]
        line = (f"  {b['part_no']} {b['name']}: need {need:.0f} at {b['station']}, "
                f"{oh:.0f} available")
        if b["traceable"]:
            lots = q(con, """SELECT rl.lot_no, rl.qty_remaining, rl.status
                             FROM raw_lots rl JOIN parts p ON p.id=rl.part_id
                             WHERE p.part_no=? AND rl.qty_remaining>0
                             ORDER BY rl.received_on""", (b["part_no"],))
            line += " | lots FIFO: " + ", ".join(
                f"{l['lot_no']} ({l['qty_remaining']:.0f}, {l['status']})"
                for l in lots) if lots else " | no lots on record"
        if oh < need:
            line += "  ** SHORT **"
        lines.append(line)
    return "\n".join(lines), {"run": run_no, "bom_lines": len(bom)}


def dig_day_plan(con, body):
    line_code = body.get("line") or "A-1"
    l = q1(con, "SELECT * FROM lines WHERE code=?", (line_code,))
    if not l:
        raise HTTPException(404, f"Line {line_code} not found")
    runs = q(con, """SELECT r.run_no, r.status, r.priority, r.qty_planned, r.qty_good,
                     p.part_no, so.promised_date, c.name customer
                     FROM runs r JOIN parts p ON p.id=r.part_id
                     LEFT JOIN sales_orders so ON so.id=r.sales_order_id
                     LEFT JOIN customers c ON c.id=so.customer_id
                     WHERE r.line_id=? AND r.status IN
                     ('released','in_progress','quality_hold','planned')
                     ORDER BY r.scheduled_start""", (l["id"],))
    crew = q(con, """SELECT o.name, o.role, o.shift FROM operators o
                     WHERE o.line_id=? AND o.status='active'""", (l["id"],))
    mach = q(con, """SELECT asset_no, name, status, next_service_due,
                     next_calibration_due FROM machines WHERE line_id=?""", (l["id"],))
    lines = [f"Line {l['code']} {l['name']} - status {l['status']}"
             + (f" ({l['stoppage_reason']})" if l["stoppage_reason"] else "")]
    lines.append("Runs on this line: " + "; ".join(
        f"{r['run_no']} {r['part_no']} x{r['qty_planned']:.0f} [{r['status']}"
        f"/{r['priority']}] for {r['customer'] or 'stock'}" for r in runs))
    lines.append("Crew: " + ", ".join(f"{c['name']} ({c['role']}, {c['shift']})"
                                      for c in crew))
    today = date.today().isoformat()
    lines.append("Equipment attention: " + "; ".join(
        f"{m['asset_no']} {m['name']} status={m['status']}"
        + (" SERVICE OVERDUE" if m["next_service_due"] < today else "")
        + (" CALIBRATION OVERDUE" if m["next_calibration_due"] < today else "")
        for m in mach))
    return "\n".join(lines), {"line": line_code, "runs": len(runs), "crew": len(crew)}


def dig_time_anomaly(con, body):
    rows = q(con, """SELECT r.run_no, p.part_no, o.name operator, rt.station,
                     rt.minutes, r.qty_planned, l.takt_seconds
                     FROM run_time rt JOIN runs r ON r.id=rt.run_id
                     JOIN parts p ON p.id=r.part_id
                     JOIN operators o ON o.id=rt.operator_id
                     LEFT JOIN lines l ON l.id=r.line_id""")
    lines = ["Labour time entries vs line takt:"]
    for r in rows:
        expected = (r["takt_seconds"] or 300) * r["qty_planned"] / 60 / 3
        flag = " ** ANOMALY: far above expected **" if r["minutes"] > expected * 2 else ""
        lines.append(f"  {r['run_no']} {r['part_no']} {r['operator']} at "
                     f"{r['station']}: {r['minutes']:.0f} min "
                     f"(rough per-station expectation {expected:.0f} min){flag}")
    return "\n".join(lines), {"entries": len(rows)}


def dig_customer(con, body):
    code = body.get("customer") or "ELL"
    c = q1(con, "SELECT * FROM customers WHERE code=?", (code,))
    if not c:
        raise HTTPException(404, f"Customer {code} not found")
    since = (date.today() - timedelta(days=90)).isoformat()
    sos = q(con, """SELECT so_no, customer_po, status, promised_date, total
                    FROM sales_orders WHERE customer_id=? ORDER BY ordered_on DESC
                    LIMIT 10""", (c["id"],))
    ships = q(con, """SELECT sh.shp_no, sh.shipped_on, sh.status, st.name plant
                      FROM shipments sh LEFT JOIN ship_tos st ON st.id=sh.ship_to_id
                      WHERE sh.customer_id=? ORDER BY sh.shipped_on DESC LIMIT 6""",
              (c["id"],))
    invs = q(con, """SELECT inv_no, status, due_on, total FROM invoices
                     WHERE customer_id=?""", (c["id"],))
    comps = q(con, """SELECT defect_no, code, severity, qty, found_at, status,
                      description FROM defects WHERE source='customer'
                      AND customer_id=?""", (c["id"],))
    shipped = q1(con, """SELECT COALESCE(SUM(sl.qty),0) n FROM shipment_lines sl
                         JOIN shipments sh ON sh.id=sl.shipment_id
                         WHERE sh.customer_id=? AND sh.shipped_on>=?""",
                 (c["id"], since))["n"]
    dq = sum(x["qty"] for x in comps)
    ppm = round(dq / shipped * 1_000_000) if shipped else 0
    lines = [f"Customer {c['name']} ({c['code']}, {c['type']}), terms "
             f"{c['payment_terms']} days, PPM target {c['ppm_target']}, "
             f"actual 90-day PPM {ppm} ({dq:.0f} defect units / {shipped:.0f} shipped)."]
    lines.append("Orders: " + "; ".join(
        f"{s['so_no']} ({s['customer_po']}) [{s['status']}] promised "
        f"{s['promised_date']} {money(s['total'])}" for s in sos))
    lines.append("Recent shipments: " + "; ".join(
        f"{s['shp_no']} {s['shipped_on']} to {s['plant']} [{s['status']}]"
        for s in ships))
    lines.append("Invoices: " + "; ".join(
        f"{i['inv_no']} [{i['status']}] due {i['due_on']} {money(i['total'])}"
        for i in invs))
    for x in comps:
        lines.append(f"Complaint {x['defect_no']} [{x['severity']}/{x['status']}] "
                     f"{x['code']} qty {x['qty']:.0f} on {x['found_at'][:10]}: "
                     f"{x['description'][:100]}")
    holds = q(con, "SELECT hold_no, scope, reason FROM holds WHERE status='open'")
    rel = [h for h in holds if code.lower() in (h["reason"] or "").lower()
           or c["name"].split()[0].lower() in (h["reason"] or "").lower()]
    for h in rel:
        lines.append(f"Related open hold {h['hold_no']}: {h['reason'][:120]}")
    return "\n".join(lines), {"customer": c["name"], "ppm_90d": ppm,
                              "orders": len(sos), "complaints": len(comps)}


def dig_maintenance(con, body):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=21)).isoformat()
    mach = q(con, """SELECT m.asset_no, m.name, m.type, m.status, m.next_service_due,
                     m.next_calibration_due, l.code line FROM machines m
                     LEFT JOIN lines l ON l.id=m.line_id""")
    lines = ["Machines (service and calibration position):"]
    for m in mach:
        flags = []
        if m["status"] != "running":
            flags.append(f"STATUS {m['status'].upper()}")
        if m["next_service_due"] < today:
            flags.append("service OVERDUE " + m["next_service_due"])
        elif m["next_service_due"] <= soon:
            flags.append("service due " + m["next_service_due"])
        if m["next_calibration_due"] < today:
            flags.append("calibration OVERDUE " + m["next_calibration_due"])
        elif m["next_calibration_due"] <= soon:
            flags.append("calibration due " + m["next_calibration_due"])
        if flags:
            lines.append(f"  {m['asset_no']} {m['name']} ({m['line'] or 'plant'}): "
                         + "; ".join(flags))
    mdef = q(con, """SELECT m.asset_no, d.code, COUNT(*) n FROM defects d
                     JOIN machines m ON m.id=d.machine_id
                     GROUP BY m.asset_no, d.code ORDER BY n DESC LIMIT 8""")
    lines.append("Defect history by machine: " + "; ".join(
        f"{r['asset_no']}: {r['code']} x{r['n']}" for r in mdef))
    tool = q(con, """SELECT tool_no, name, shots_since_service, service_interval_shots
                     FROM tooling WHERE service_interval_shots>0""")
    lines.append("Tooling life: " + "; ".join(
        f"{t['tool_no']} {t['name']} {t['shots_since_service']}/"
        f"{t['service_interval_shots']} shots "
        f"({100*t['shots_since_service']/t['service_interval_shots']:.0f}%)"
        for t in tool))
    return "\n".join(lines), {"machines": len(mach), "tooling_tracked": len(tool)}


def dig_dunning(con, body):
    over = q(con, """SELECT i.inv_no, i.due_on, i.total, c.name, c.code,
                     c.contact_name, c.payment_terms
                     FROM invoices i JOIN customers c ON c.id=i.customer_id
                     WHERE i.status='overdue' ORDER BY i.due_on""")
    lines = ["Overdue invoices:"]
    for o in over:
        days = (date.today() - date.fromisoformat(o["due_on"])).days
        lines.append(f"  {o['inv_no']} {o['name']} (contact {o['contact_name']}): "
                     f"{money(o['total'])}, due {o['due_on']}, {days} days overdue, "
                     f"terms {o['payment_terms']} days")
    return "\n".join(lines), {"overdue": len(over),
                              "value": round(sum(o["total"] for o in over), 2)}


def dig_lost_quotes(con, body):
    lost = q(con, """SELECT so.so_no, so.customer_po, so.lost_reason, so.total,
                     so.ordered_on, c.name FROM sales_orders so
                     JOIN customers c ON c.id=so.customer_id
                     WHERE so.status IN ('lost','rejected')""")
    lines = ["Lost and rejected quotes:"]
    for l in lost:
        lines.append(f"  {l['so_no']} {l['name']} ({l['customer_po']}) "
                     f"{money(l['total'])} on {l['ordered_on']}: "
                     f"{l['lost_reason'] or 'rejected - below minimum order quantity'}")
    won = q1(con, """SELECT COUNT(*) n, COALESCE(SUM(total),0) v FROM sales_orders
                     WHERE status IN ('fulfilled','in_production','approved')""")
    lines.append(f"For comparison, won orders: {won['n']} worth {money(won['v'])}.")
    return "\n".join(lines), {"lost": len(lost)}


def dig_calibration(con, body):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=30)).isoformat()
    dev = q(con, """SELECT asset_no, name, type, next_calibration_due,
                    last_calibration FROM machines
                    WHERE type IN ('test_rig','cmm') OR next_calibration_due<=?
                    ORDER BY next_calibration_due""", (soon,))
    lines = ["Measurement and test equipment calibration position:"]
    for m in dev:
        state = ("OVERDUE" if m["next_calibration_due"] < today else
                 "due soon" if m["next_calibration_due"] <= soon else "current")
        lines.append(f"  {m['asset_no']} {m['name']}: last {m['last_calibration']}, "
                     f"next due {m['next_calibration_due']} ({state})")
    return "\n".join(lines), {"devices": len(dev)}


def dig_recurring_preview(con, body):
    horizon = (date.today() + timedelta(days=21)).isoformat()
    rc = q(con, """SELECT rc.name, rc.qty, rc.cadence, rc.next_run_date,
                   p.part_no, c.name customer, l.code line
                   FROM recurring rc JOIN parts p ON p.id=rc.part_id
                   LEFT JOIN customers c ON c.id=rc.customer_id
                   LEFT JOIN lines l ON l.id=rc.line_id
                   WHERE rc.active=1 AND rc.next_run_date<=? ORDER BY rc.next_run_date""",
           (horizon,))
    lines = ["Release schedules generating runs in the next 21 days:"]
    for r in rc:
        lines.append(f"  {r['name']}: {r['part_no']} x{r['qty']:.0f} on {r['line']} "
                     f"({r['cadence']}), next {r['next_run_date']}, "
                     f"customer {r['customer'] or 'internal'}")
    load = q(con, """SELECT l.code, COUNT(*) n FROM runs r JOIN lines l ON l.id=r.line_id
                     WHERE r.status IN ('planned','released','in_progress')
                     GROUP BY l.code""")
    lines.append("Current open-run load by line: "
                 + ", ".join(f"{r['code']}: {r['n']}" for r in load))
    return "\n".join(lines), {"schedules_due": len(rc)}


def dig_demand_reorder(con, body):
    low = q(con, """SELECT p.part_no, p.name, p.reorder_point, p.reorder_qty,
                    p.std_cost, s.name supplier,
                    COALESCE((SELECT SUM(st.qty) FROM stock st
                      JOIN locations l ON l.id=st.location_id
                      WHERE st.part_id=p.id AND l.type!='quarantine'),0) oh
                    FROM parts p LEFT JOIN suppliers s ON s.id=p.preferred_supplier_id
                    WHERE p.reorder_point>0""")
    lowlist = [r for r in low if r["oh"] < r["reorder_point"]]
    lines = ["Parts below reorder point:"]
    for r in lowlist:
        lines.append(f"  {r['part_no']} {r['name']}: {r['oh']:.0f} on hand vs "
                     f"reorder point {r['reorder_point']:.0f}; reorder qty "
                     f"{r['reorder_qty']:.0f} from {r['supplier'] or 'unassigned'}")
    demand = q(con, """SELECT c.part_no, SUM(b.qty_per*r.qty_planned) need
                       FROM runs r JOIN boms b ON b.parent_part_id=r.part_id
                       JOIN parts c ON c.id=b.component_part_id
                       WHERE r.status IN ('planned','released')
                       GROUP BY c.part_no ORDER BY need DESC LIMIT 12""")
    lines.append("Demand from planned and released runs: " + "; ".join(
        f"{r['part_no']}: {r['need']:.0f}" for r in demand))
    open_po = q(con, """SELECT po.po_no, po.expected_date, p.part_no, pol.qty
                        FROM purchase_order_lines pol
                        JOIN purchase_orders po ON po.id=pol.po_id
                        JOIN parts p ON p.id=pol.part_id
                        WHERE po.status IN ('sent','confirmed','partial')""")
    lines.append("Already on order: " + "; ".join(
        f"{r['part_no']} x{r['qty']:.0f} on {r['po_no']} due {r['expected_date']}"
        for r in open_po))
    return "\n".join(lines), {"below_reorder": len(lowlist), "open_po_lines": len(open_po)}


def dig_skill_gap(con, body):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=60)).isoformat()
    certs = q(con, """SELECT o.name, o.emp_no, o.status op_status, l.code line,
                      s.code skill, os.expires_on FROM operator_skills os
                      JOIN operators o ON o.id=os.operator_id
                      JOIN skills s ON s.id=os.skill_id
                      LEFT JOIN lines l ON l.id=o.line_id ORDER BY os.expires_on""")
    lines = ["Certification register (holder, line, expiry):"]
    for c in certs:
        state = ("EXPIRED" if c["expires_on"] < today else
                 "expiring soon" if c["expires_on"] <= soon else "current")
        lines.append(f"  {c['name']} ({c['line'] or '-'}) {c['skill']} expires "
                     f"{c['expires_on']} [{state}]"
                     + (" - operator on leave" if c["op_status"] == "leave" else ""))
    sched = q(con, """SELECT l.code, COUNT(*) n FROM runs r
                      JOIN lines l ON l.id=r.line_id
                      WHERE r.status IN ('planned','released','in_progress')
                      GROUP BY l.code""")
    lines.append("Scheduled work by line: "
                 + ", ".join(f"{r['code']}: {r['n']} runs" for r in sched))
    lines.append("Station requirements: A-1 torque stations need TQ-1; S-1 presses "
                 "need PR-1; H-1 furnace needs HT-1; P-1 dosing needs PL-1; "
                 "hold/lot release needs QI.")
    return "\n".join(lines), {"certs": len(certs)}


def dig_sla(con, body):
    rows = q(con, """SELECT so.so_no, so.promised_date, so.status, c.name customer,
                     so.total FROM sales_orders so
                     JOIN customers c ON c.id=so.customer_id
                     WHERE so.status IN ('approved','in_production')
                     ORDER BY so.promised_date""")
    lines = ["Open customer orders vs promised ship dates (today is "
             + date.today().isoformat() + "):"]
    for r in rows:
        runs = q(con, """SELECT run_no, status, qty_planned, qty_good FROM runs
                         WHERE sales_order_id=(SELECT id FROM sales_orders
                         WHERE so_no=?)""", (r["so_no"],))
        rtxt = "; ".join(f"{x['run_no']} [{x['status']}] {x['qty_good']:.0f}/"
                         f"{x['qty_planned']:.0f}" for x in runs) or "no runs yet"
        lines.append(f"  {r['so_no']} {r['customer']} promised {r['promised_date']} "
                     f"{money(r['total'])} - runs: {rtxt}")
    lines.append("Note: line M-2 is stopped (spindle bearing) and A-1 has a held run "
                 "(RUN-1101, fastener containment).")
    return "\n".join(lines), {"open_orders": len(rows)}


def dig_margin(con, body):
    rows = q(con, """SELECT p.family, p.part_no, p.name, SUM(sol.qty) units,
                     ROUND(SUM(sol.line_total),2) revenue,
                     ROUND(SUM(sol.qty*p.std_cost),2) cost
                     FROM sales_order_lines sol
                     JOIN sales_orders so ON so.id=sol.sales_order_id
                     JOIN parts p ON p.id=sol.part_id
                     WHERE so.status IN ('fulfilled','in_production','approved')
                     GROUP BY p.part_no ORDER BY revenue DESC""")
    thr = float(q1(con, "SELECT value FROM settings WHERE "
                        "key='margin_risk_threshold'")["value"])
    lines = [f"Margin by part (margin-risk threshold {thr*100:.0f}%):"]
    for r in rows:
        m = (r["revenue"] - r["cost"]) / r["revenue"] * 100 if r["revenue"] else 0
        lines.append(f"  {r['part_no']} {r['name']} [{r['family']}]: "
                     f"{r['units']:.0f} units, revenue {money(r['revenue'])}, "
                     f"std cost {money(r['cost'])}, margin {m:.1f}%"
                     + ("  ** BELOW THRESHOLD **" if m < thr * 100 else ""))
    over = q(con, """SELECT r.run_no, p.part_no, r.std_cost, r.actual_cost
                     FROM runs r JOIN parts p ON p.id=r.part_id
                     WHERE r.actual_cost > r.std_cost*1.02 AND r.status='completed'""")
    lines.append("Completed runs over standard cost: " + "; ".join(
        f"{r['run_no']} {r['part_no']} actual {money(r['actual_cost'])} vs std "
        f"{money(r['std_cost'])}" for r in over))
    return "\n".join(lines), {"parts": len(rows), "cost_over_runs": len(over)}


def dig_exec(con, body):
    b, kpis = dig_briefing(con, body)
    m, _ = dig_margin(con, body)
    ppm = q(con, "SELECT code, name, ppm_target FROM customers")
    return b + "\n\n" + m, kpis


def dig_finance_exceptions(con, body):
    over = q(con, """SELECT i.inv_no, i.due_on, i.total, c.name FROM invoices i
                     JOIN customers c ON c.id=i.customer_id WHERE i.status='overdue'""")
    drafts = q(con, """SELECT i.inv_no, i.issued_on, i.total, c.name FROM invoices i
                       JOIN customers c ON c.id=i.customer_id WHERE i.status='draft'""")
    lines = ["Overdue receivables:"]
    for o in over:
        days = (date.today() - date.fromisoformat(o["due_on"])).days
        lines.append(f"  {o['inv_no']} {o['name']} {money(o['total'])} - "
                     f"{days} days past due")
    lines.append("Draft invoices not yet sent: " + "; ".join(
        f"{d['inv_no']} {d['name']} {money(d['total'])}" for d in drafts))
    held = q(con, """SELECT fl.lot_no, fl.qty_produced-fl.qty_shipped held_qty,
                     p.price FROM finished_lots fl JOIN parts p ON p.id=fl.part_id
                     WHERE fl.status='hold'""")
    hv = sum((h["held_qty"] or 0) * (h["price"] or 0) for h in held)
    lines.append(f"Revenue blocked behind quality holds: {money(hv)} across "
                 f"{len(held)} finished lots.")
    unb = q(con, """SELECT sh.shp_no FROM shipments sh
                    LEFT JOIN invoices i ON i.shipment_id=sh.id
                    WHERE sh.status IN ('despatched','delivered') AND i.id IS NULL""")
    lines.append("Shipments despatched but not invoiced: "
                 + (", ".join(u["shp_no"] for u in unb) or "none"))
    return "\n".join(lines), {"overdue": len(over), "held_value": round(hv, 2)}


def dig_fault_root_cause(con, body):
    since = (date.today() - timedelta(days=90)).isoformat()
    pareto = q(con, """SELECT code, COUNT(*) events, SUM(qty) units,
                       SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END) critical
                       FROM defects WHERE found_at>=? GROUP BY code
                       ORDER BY units DESC""", (since,))
    lines = ["Defect Pareto, last 90 days (code, events, affected units, critical):"]
    for p in pareto:
        lines.append(f"  {p['code']}: {p['events']} events, {p['units']:.0f} units, "
                     f"{p['critical']} critical")
    top = pareto[0]["code"] if pareto else ""
    focus = body.get("code") or "torque_retention"
    det = q(con, """SELECT d.defect_no, d.description, d.severity, d.status,
                    d.found_at, r.run_no, rl.lot_no raw_lot, m.asset_no,
                    c.name customer FROM defects d
                    LEFT JOIN runs r ON r.id=d.run_id
                    LEFT JOIN raw_lots rl ON rl.id=d.raw_lot_id
                    LEFT JOIN machines m ON m.id=d.machine_id
                    LEFT JOIN customers c ON c.id=d.customer_id
                    WHERE d.code=? ORDER BY d.found_at""", (focus,))
    lines.append(f"Detail for code '{focus}':")
    for x in det:
        lines.append(f"  {x['defect_no']} [{x['severity']}/{x['status']}] "
                     f"{x['found_at'][:10]} run={x['run_no'] or '-'} "
                     f"raw lot={x['raw_lot'] or '-'} machine={x['asset_no'] or '-'} "
                     f"customer={x['customer'] or '-'}: {x['description'][:110]}")
    return "\n".join(lines), {"codes": len(pareto), "top_code": top, "focus": focus}


def dig_fpy_root_cause(con, body):
    """UC1: ranked, correlated multi-factor root-cause suspects for an
    overnight FPY breach - material lot, equipment/PM, shift. Every number is
    computed from the seeded defect/machine/operator rows, never invented."""
    line_code = body.get("line") or "A-2"
    run_no = body.get("run_no")
    if run_no:
        run = q1(con, """SELECT r.*, p.part_no, p.name part_name, l.code line_code,
                         l.id as line_id FROM runs r JOIN parts p ON p.id=r.part_id
                         JOIN lines l ON l.id=r.line_id WHERE r.run_no=?""", (run_no,))
    else:
        run = q1(con, """SELECT r.*, p.part_no, p.name part_name, l.code line_code,
                         l.id as line_id FROM runs r JOIN parts p ON p.id=r.part_id
                         JOIN lines l ON l.id=r.line_id
                         WHERE l.code=? AND r.status='completed'
                           AND r.qty_good+r.qty_scrap>0
                         ORDER BY (1.0*r.qty_good)/(r.qty_good+r.qty_scrap) ASC,
                                  r.completed_at DESC LIMIT 1""", (line_code,))
    if not run:
        raise HTTPException(404, f"No completed run found on line {line_code}")
    denom = (run["qty_good"] or 0) + (run["qty_scrap"] or 0)
    fpy = round(100.0 * (run["qty_good"] or 0) / denom, 1) if denom else 100.0
    ftt_target = float(q1(con, "SELECT value FROM settings WHERE "
                              "key='ftt_target'")["value"])
    defs = q(con, """SELECT d.*, rl.lot_no raw_lot, rl.coa_ref, rl.received_on,
                     m.asset_no, m.next_service_due, m.last_service
                     FROM defects d LEFT JOIN raw_lots rl ON rl.id=d.raw_lot_id
                     LEFT JOIN machines m ON m.id=d.machine_id
                     WHERE d.run_id=? ORDER BY d.found_at""", (run["id"],))
    total_units = sum(d["qty"] for d in defs) or 1
    lines = [f"Run {run['run_no']} - {run['part_no']} {run['part_name']} on "
             f"line {run['line_code']}: FPY {fpy} per cent against the "
             f"{ftt_target} per cent target ({run['qty_good']:.0f} good, "
             f"{run['qty_scrap']:.0f} scrap of {denom:.0f} built). "
             f"{len(defs)} defect events, {total_units:.0f} units affected."]

    # suspect: material lot
    by_lot = {}
    for d in defs:
        if d["raw_lot"]:
            by_lot.setdefault(d["raw_lot"], []).append(d)
    for lot_no, items in by_lot.items():
        lot = q1(con, "SELECT * FROM raw_lots WHERE lot_no=?", (lot_no,))
        prior = q1(con, """SELECT COUNT(DISTINCT run_id) n FROM run_materials
                           WHERE raw_lot_id=? AND run_id!=?""",
                  (lot["id"], run["id"]))["n"]
        u = sum(d["qty"] for d in items)
        lines.append(
            f"SUSPECT (material): raw lot {lot_no} (CoA {lot['coa_ref']}, "
            f"received {lot['received_on']}) - "
            + ("FIRST USE on this line, no prior run history to compare "
               "against. " if prior == 0 else f"{prior} prior run(s) on "
               "this line with no equivalent defect pattern. ")
            + f"{u:.0f} of {total_units:.0f} defect units "
              f"({u/total_units*100:.0f} per cent) trace to this lot: "
            + "; ".join(f"{d['defect_no']} {d['description'][:100]}"
                       for d in items))

    # suspect: equipment / overdue PM
    by_machine = {}
    for d in defs:
        if d["asset_no"]:
            by_machine.setdefault(d["asset_no"], []).append(d)
    for asset, items in by_machine.items():
        m = items[0]
        overdue = bool(m["next_service_due"]) and m["next_service_due"] < date.today().isoformat()
        overdue_days = (date.today() - date.fromisoformat(m["next_service_due"])).days if overdue else 0
        u = sum(d["qty"] for d in items)
        lines.append(
            f"SUSPECT (equipment): {asset} - preventive maintenance "
            + (f"OVERDUE by {overdue_days} day(s) (due {m['next_service_due']}, "
               f"last service {m['last_service']}). "
               if overdue else f"current, last service {m['last_service']}. ")
            + f"{u:.0f} of {total_units:.0f} defect units "
              f"({u/total_units*100:.0f} per cent) recorded against this "
              f"machine: " + "; ".join(f"{d['defect_no']} {d['description'][:100]}"
                                       for d in items))

    # suspect: shift - compare event density across the two halves of the window
    times = sorted(d["found_at"] for d in defs)
    if len(times) >= 2:
        t0 = datetime.strptime(times[0], "%Y-%m-%dT%H:%M:%SZ")
        t1 = datetime.strptime(times[-1], "%Y-%m-%dT%H:%M:%SZ")
        tmid = (t0 + (t1 - t0) / 2).strftime("%Y-%m-%dT%H:%M:%SZ")
        early = [d for d in defs if d["found_at"] <= tmid]
        late = [d for d in defs if d["found_at"] > tmid]
        eu, lu = sum(d["qty"] for d in early), sum(d["qty"] for d in late)
        ratio = (len(early) / len(late)) if late else None
        shift_op = q1(con, """SELECT * FROM operators WHERE line_id=?
                              AND shift='night' AND notes IS NOT NULL
                              LIMIT 1""", (run["line_id"],))
        lines.append(
            f"SUSPECT (shift): defect events ran "
            + (f"{ratio:.1f}x more frequent " if ratio else "concentrated ")
            + f"in the first half of the window ({len(early)} events, "
              f"{eu:.0f} units, {times[0][11:16]}-{tmid[11:16]}) than the "
              f"second half ({len(late)} events, {lu:.0f} units, "
              f"{tmid[11:16]}-{times[-1][11:16]})."
            + (f" Night-shift note on {shift_op['name']} ({shift_op['emp_no']}), "
               f"line lead for {run['line_code']}: {shift_op['notes']}"
               if shift_op else ""))
    lines.append("Overlaps to weigh: the shift change and the material "
                 "changeover happened close together in this window - the "
                 "material and equipment evidence should be checked before "
                 "the shift factor is treated as more than a contributing "
                 "correlation.")
    return "\n".join(lines), {"line": run["line_code"], "run_no": run["run_no"],
                              "fpy": fpy, "total_defect_units": total_units}


def dig_risk_watchlist(con, body):
    today = date.today().isoformat()
    lines = ["Supplier risk signals:"]
    sups = q(con, """SELECT s.code, s.name, s.ppm, s.on_time_pct, s.rating,
                     (SELECT COUNT(*) FROM raw_lots rl WHERE rl.supplier_id=s.id
                       AND rl.status='quarantine') qlots,
                     (SELECT COUNT(*) FROM purchase_orders po WHERE po.supplier_id=s.id
                       AND po.status IN ('sent','confirmed') AND po.expected_date<?) late
                     FROM suppliers s""", (today,))
    for s in sups:
        flags = []
        if s["ppm"] and s["ppm"] > 350:
            flags.append(f"PPM {s['ppm']} above 350 threshold")
        if s["qlots"]:
            flags.append(f"{s['qlots']} quarantined lot(s)")
        if s["late"]:
            flags.append(f"{s['late']} late delivery(ies)")
        if s["on_time_pct"] and s["on_time_pct"] < 97:
            flags.append(f"on-time {s['on_time_pct']}% below 98% expectation")
        if flags:
            lines.append(f"  {s['name']} ({s['code']}): " + "; ".join(flags))
    lines.append("Order and run risk signals:")
    held = q(con, """SELECT r.run_no, p.part_no, so.so_no, c.name FROM runs r
                     JOIN parts p ON p.id=r.part_id
                     LEFT JOIN sales_orders so ON so.id=r.sales_order_id
                     LEFT JOIN customers c ON c.id=so.customer_id
                     WHERE r.status='quality_hold'""")
    for h in held:
        lines.append(f"  {h['run_no']} {h['part_no']} held (order {h['so_no']} "
                     f"for {h['name']})")
    lines.append("Open holds: " + "; ".join(
        f"{h['hold_no']} [{h['scope']}] {h['reason'][:80]}"
        for h in q(con, "SELECT * FROM holds WHERE status='open'")))
    crit = q(con, """SELECT defect_no, description FROM defects
                     WHERE status='open' AND severity='critical'""")
    lines.append("Open critical defects: " + "; ".join(
        f"{c['defect_no']}: {c['description'][:90]}" for c in crit))
    return "\n".join(lines), {"suppliers_flagged":
                              sum(1 for s in sups if s["ppm"] and s["ppm"] > 350
                                  or s["qlots"] or s["late"]),
                              "held_runs": len(held)}


def dig_cost_exceptions(con, body):
    runs = q(con, """SELECT r.run_no, p.part_no, r.qty_good, r.qty_scrap, r.std_cost,
                     r.actual_cost, l.code line FROM runs r
                     JOIN parts p ON p.id=r.part_id LEFT JOIN lines l ON l.id=r.line_id
                     WHERE r.status='completed' ORDER BY
                     (r.actual_cost-r.std_cost) DESC""")
    lines = ["Completed runs - actual vs standard cost:"]
    for r in runs:
        var = r["actual_cost"] - r["std_cost"]
        pct = var / r["std_cost"] * 100 if r["std_cost"] else 0
        lines.append(f"  {r['run_no']} {r['part_no']} on {r['line']}: std "
                     f"{money(r['std_cost'])}, actual {money(r['actual_cost'])}, "
                     f"variance {money(var)} ({pct:+.1f}%), scrap {r['qty_scrap']:.0f}")
    scrap = q(con, """SELECT p.family, ROUND(SUM(r.qty_scrap*p.std_cost),2) cost
                      FROM runs r JOIN parts p ON p.id=r.part_id
                      GROUP BY p.family""")
    lines.append("Scrap cost by family: " + "; ".join(
        f"{s['family']}: {money(s['cost'])}" for s in scrap))
    return "\n".join(lines), {"runs": len(runs)}


def dig_compliance(con, body):
    today = date.today().isoformat()
    cal_over = q(con, """SELECT asset_no, name, next_calibration_due FROM machines
                         WHERE next_calibration_due<?""", (today,))
    svc_over = q(con, """SELECT asset_no, name, next_service_due FROM machines
                         WHERE next_service_due<?""", (today,))
    exp = q(con, """SELECT o.name, s.code, os.expires_on FROM operator_skills os
                    JOIN operators o ON o.id=os.operator_id
                    JOIN skills s ON s.id=os.skill_id WHERE os.expires_on<?""",
            (today,))
    holds = q(con, "SELECT hold_no, placed_at, reason FROM holds WHERE status='open'")
    lines = ["Audit-readiness position (live):"]
    lines.append("Overdue calibrations: " + ("; ".join(
        f"{c['asset_no']} {c['name']} due {c['next_calibration_due']}"
        for c in cal_over) or "none"))
    lines.append("Overdue services: " + ("; ".join(
        f"{s['asset_no']} {s['name']} due {s['next_service_due']}"
        for s in svc_over) or "none"))
    lines.append("Expired certifications: " + ("; ".join(
        f"{e['name']} {e['code']} lapsed {e['expires_on']}" for e in exp) or "none"))
    for h in holds:
        age = (date.today() - date.fromisoformat(h["placed_at"][:10])).days
        lines.append(f"Open hold {h['hold_no']} aged {age} days: {h['reason'][:90]}")
    open8d = q(con, """SELECT defect_no, found_at FROM defects
                       WHERE severity='critical' AND status='open'""")
    for o in open8d:
        lines.append(f"Open critical defect (8D running): {o['defect_no']} "
                     f"since {o['found_at'][:10]}")
    return "\n".join(lines), {"cal_overdue": len(cal_over),
                              "cert_expired": len(exp), "open_holds": len(holds)}


def dig_ap_error_explain(con, body):
    """UC2 step 1: plain-English explanation of one AP posting failure, with
    the exact fix and the policy that authorises it. The fix/authority text
    is the deterministic AP_ERROR_CODES catalogue, not model-invented."""
    ap_no = body.get("ap_no") or "AP-8801"
    row = q1(con, """SELECT ai.*, s.name supplier_name, s.code supplier_code,
                     s.cost_center, po.po_no FROM ap_invoices ai
                     JOIN suppliers s ON s.id=ai.supplier_id
                     LEFT JOIN purchase_orders po ON po.id=ai.po_id
                     WHERE ai.ap_no=?""", (ap_no,))
    if not row:
        raise HTTPException(404, f"AP invoice {ap_no} not found")
    cat = AP_ERROR_CODES.get(row["error_code"], {})
    lines = [f"AP invoice {row['ap_no']} ({row['vendor_invoice_no']}) from "
             f"{row['supplier_name']} ({row['supplier_code']}), "
             f"{money(row['amount'])}, status {row['status']}, error code "
             f"{row['error_code']} - {cat.get('label','unclassified')}."]
    if row["po_no"]:
        lines.append(f"References purchase order {row['po_no']}.")
    lines.append(f"Vendor master cost centre on file: {row['cost_center']}.")
    lines.append(f"What the code means: {cat.get('plain_english','')}")
    lines.append(f"Exact fix: {cat.get('fix','')}")
    lines.append(f"Who may authorise it: {cat.get('authority','')}")
    lines.append(f"Policy reference: {cat.get('policy_ref','')}")
    return "\n".join(lines), {"ap_no": ap_no, "error_code": row["error_code"],
                              "amount": row["amount"], "escalate": cat.get("escalate", False)}


def dig_ap_batch_fix(con, body):
    """UC2 step 2-3: 'are there others like this?' - the shared root cause
    group, the total, and whether it is all within the clerk's authority.
    Computed by ap_similar_group (plain SQL), narrated here."""
    ap_no = body.get("ap_no") or "AP-8801"
    row = q1(con, """SELECT ai.*, s.name supplier_name FROM ap_invoices ai
                     JOIN suppliers s ON s.id=ai.supplier_id
                     WHERE ai.ap_no=?""", (ap_no,))
    if not row:
        raise HTTPException(404, f"AP invoice {ap_no} not found")
    group = ap_similar_group(con, ap_no)
    cat = AP_ERROR_CODES.get(row["error_code"], {})
    if not group or not group.get("root_cause_group"):
        return (f"AP invoice {ap_no} ({cat.get('label','')}) is a one-off - "
                f"no other invoice in today's queue shares this root cause. "
                f"Fix: {cat.get('fix','')}"), {"ap_no": ap_no, "group_count": 0}
    lines = [f"Shared root cause '{group['root_cause_group']}' found across "
             f"{group['count']} invoices, total {money(group['total_amount'])}, "
             f"per-invoice approval limit {money(group['approval_limit'])}, "
             f"all within the clerk's authority: "
             f"{'yes' if group['all_within_clerk_authority'] else 'no'}."]
    for r in group["similar"]:
        lines.append(f"  {r['ap_no']} {r['supplier_name']} {money(r['amount'])} "
                     f"[{r['error_code']}] status {r['status']}")
    lines.append(f"Fix for the group: {cat.get('fix','')}")
    lines.append(f"Authority: {cat.get('authority','')}")
    return "\n".join(lines), {"ap_no": ap_no,
                              "group_count": group["count"],
                              "total_amount": group["total_amount"],
                              "all_within_clerk_authority":
                              group["all_within_clerk_authority"]}


def dig_commit_date(con, body):
    pno = body.get("part_no") or "TC-30412"
    qty = float(body.get("qty") or 480)
    p = q1(con, "SELECT * FROM parts WHERE part_no=?", (pno,))
    if not p:
        raise HTTPException(404, f"Part {pno} not found")
    kit, _ = dig_parts_kit_for_part(con, p, qty)
    load = q(con, """SELECT l.code, l.status, COUNT(r.id) open_runs,
                     SUM(CASE WHEN r.status='in_progress' THEN 1 ELSE 0 END) active
                     FROM lines l LEFT JOIN runs r ON r.line_id=l.id
                     AND r.status IN ('planned','released','in_progress','quality_hold')
                     GROUP BY l.code""")
    hist = q(con, """SELECT run_no, qty_planned, started_at, completed_at FROM runs
                     WHERE part_id=? AND completed_at IS NOT NULL
                     ORDER BY completed_at DESC LIMIT 4""", (p["id"],))
    lines = [f"Commit-date assessment for {pno} x{qty:.0f}:", kit,
             "Line load: " + "; ".join(
                 f"{l['code']} ({l['status']}): {l['open_runs']} open runs"
                 for l in load),
             "Recent cycle history: " + "; ".join(
                 f"{h['run_no']} x{h['qty_planned']:.0f} took "
                 f"{h['started_at'][:10]} to {h['completed_at'][:10]}" for h in hist),
             f"Today is {date.today().isoformat()}."]
    return "\n".join(lines), {"part": pno, "qty": qty}


def dig_parts_kit_for_part(con, p, qty):
    bom = q(con, """SELECT b.qty_per, c.part_no, c.name, c.traceable
                    FROM boms b JOIN parts c ON c.id=b.component_part_id
                    WHERE b.parent_part_id=?""", (p["id"],))
    lines = ["Material position:"]
    for b in bom:
        need = b["qty_per"] * qty
        oh = q1(con, """SELECT COALESCE(SUM(s.qty),0) v FROM stock s
                        JOIN locations l ON l.id=s.location_id
                        JOIN parts pp ON pp.id=s.part_id
                        WHERE pp.part_no=? AND l.type!='quarantine'""",
                (b["part_no"],))["v"]
        lines.append(f"  {b['part_no']}: need {need:.0f}, available {oh:.0f}"
                     + ("  ** SHORT **" if oh < need else ""))
    return "\n".join(lines), {}


def dig_asset_service(con, body):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=30)).isoformat()
    tools = q(con, """SELECT t.tool_no, t.name, t.type, t.shots_since_service,
                      t.service_interval_shots, t.next_service_due, p.part_no
                      FROM tooling t LEFT JOIN parts p ON p.id=t.part_id""")
    lines = ["Tooling register (dies, fixtures, jigs, gauges) tied to part numbers:"]
    for t in tools:
        flags = []
        if t["service_interval_shots"]:
            pct = 100 * t["shots_since_service"] / t["service_interval_shots"]
            flags.append(f"{pct:.0f}% of shot life used")
            if pct > 90:
                flags.append("APPROACHING SHOT LIMIT")
        if t["next_service_due"] < today:
            flags.append("service OVERDUE " + t["next_service_due"])
        elif t["next_service_due"] <= soon:
            flags.append("service due " + t["next_service_due"])
        lines.append(f"  {t['tool_no']} {t['name']} (makes {t['part_no']}): "
                     + ("; ".join(flags) or "in service, no flags"))
    burr = q(con, """SELECT defect_no, description FROM defects
                     WHERE code='burr_height' AND status='open'""")
    for b in burr:
        lines.append(f"Related open defect {b['defect_no']}: {b['description'][:100]}")
    return "\n".join(lines), {"tools": len(tools)}


def dig_quote_risk(con, body):
    rows = q(con, """SELECT so.so_no, so.customer_po, so.status, so.ordered_on,
                     so.promised_date, so.total, c.name, c.type FROM sales_orders so
                     JOIN customers c ON c.id=so.customer_id
                     WHERE so.status IN ('draft','submitted')""")
    lines = ["Quotes and submitted orders awaiting decision:"]
    for r in rows:
        age = (date.today() - date.fromisoformat(r["ordered_on"])).days
        lines.append(f"  {r['so_no']} {r['name']} ({r['type']}) {money(r['total'])} "
                     f"[{r['status']}] aged {age} days, requested date "
                     f"{r['promised_date']}")
    lost = q(con, """SELECT so_no, lost_reason FROM sales_orders
                     WHERE status='lost'""")
    lines.append("Recent losses and reasons: " + "; ".join(
        f"{l['so_no']}: {l['lost_reason']}" for l in lost))
    return "\n".join(lines), {"pending": len(rows)}


def dig_audit(con, body):
    query = (body.get("query") or "").lower()
    rows = q(con, "SELECT * FROM audit ORDER BY at DESC LIMIT 120")
    if query:
        words = [w for w in re.findall(r"[a-z0-9\-]+", query) if len(w) > 2]
        scored = []
        for r in rows:
            blob = " ".join(str(v).lower() for v in r.values())
            score = sum(1 for w in words if w in blob)
            if score:
                scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        rows = [r for _, r in scored[:25]] or rows[:25]
    else:
        rows = rows[:25]
    lines = ["Audit trail entries (most relevant first):"]
    for r in rows:
        lines.append(f"  {r['at']} {r['user_email']} {r['action']} "
                     f"{r['entity']}={r['entity_id']}: {r['detail'][:110]}")
    return "\n".join(lines), {"entries": len(rows)}


def dig_lots(con, body):
    raw = q(con, """SELECT rl.lot_no, rl.status, rl.qty_received, rl.qty_remaining,
                    rl.received_on, p.part_no, s.name supplier FROM raw_lots rl
                    JOIN parts p ON p.id=rl.part_id
                    LEFT JOIN suppliers s ON s.id=rl.supplier_id
                    ORDER BY rl.received_on DESC""")
    fin = q(con, """SELECT fl.lot_no, fl.status, fl.qty_produced, fl.qty_shipped,
                    fl.produced_on, p.part_no FROM finished_lots fl
                    JOIN parts p ON p.id=fl.part_id ORDER BY fl.produced_on DESC""")
    lines = ["Raw-material lots:"]
    for r in raw:
        lines.append(f"  {r['lot_no']} {r['part_no']} from {r['supplier']}: "
                     f"{r['qty_remaining']:.0f}/{r['qty_received']:.0f} remaining, "
                     f"status {r['status']}, received {r['received_on']}")
    lines.append("Finished lots:")
    for f in fin:
        lines.append(f"  {f['lot_no']} {f['part_no']}: {f['qty_produced']:.0f} "
                     f"produced, {f['qty_shipped']:.0f} shipped, status {f['status']}")
    return "\n".join(lines), {"raw_lots": len(raw), "finished_lots": len(fin)}


def dig_recurring_suggest(con, body):
    pat = q(con, """SELECT c.name customer, p.part_no, COUNT(*) orders,
                    SUM(sol.qty) units, MIN(so.ordered_on) first_order,
                    MAX(so.ordered_on) last_order
                    FROM sales_order_lines sol
                    JOIN sales_orders so ON so.id=sol.sales_order_id
                    JOIN customers c ON c.id=so.customer_id
                    JOIN parts p ON p.id=sol.part_id
                    WHERE so.status IN ('fulfilled','in_production','approved')
                    GROUP BY c.name, p.part_no HAVING orders>=2""")
    existing = q(con, """SELECT rc.name, p.part_no, c.name customer FROM recurring rc
                         JOIN parts p ON p.id=rc.part_id
                         LEFT JOIN customers c ON c.id=rc.customer_id""")
    lines = ["Repeat ordering patterns:"]
    for r in pat:
        lines.append(f"  {r['customer']} orders {r['part_no']} repeatedly: "
                     f"{r['orders']} orders, {r['units']:.0f} units between "
                     f"{r['first_order']} and {r['last_order']}")
    lines.append("Existing schedules: " + "; ".join(
        f"{e['name']} ({e['part_no']} for {e['customer'] or 'internal'})"
        for e in existing))
    return "\n".join(lines), {"patterns": len(pat), "existing": len(existing)}


def dig_variation(con, body):
    so_no = body.get("so_no") or ""
    change = body.get("change") or "customer requested change"
    so = q1(con, """SELECT so.*, c.name customer FROM sales_orders so
                    JOIN customers c ON c.id=so.customer_id WHERE so.so_no=?""",
            (so_no,))
    if not so:
        raise HTTPException(404, f"Sales order {so_no} not found")
    sol = q(con, """SELECT sol.qty, sol.unit_price, p.part_no, p.name, p.std_cost
                    FROM sales_order_lines sol JOIN parts p ON p.id=sol.part_id
                    WHERE sol.sales_order_id=?""", (so["id"],))
    lines = [f"Sales order {so_no} for {so['customer']} ({so['customer_po']}), "
             f"total {money(so['total'])}, promised {so['promised_date']}.",
             "Lines: " + "; ".join(
                 f"{l['part_no']} x{l['qty']:.0f} at {money(l['unit_price'])} "
                 f"(std cost {money(l['std_cost'])})" for l in sol),
             f"Requested change: {change}"]
    return "\n".join(lines), {"so": so_no}


def dig_quote_comms(con, body):
    so_no = body.get("so_no") or ""
    so = q1(con, """SELECT so.*, c.name customer, c.contact_name FROM sales_orders so
                    JOIN customers c ON c.id=so.customer_id WHERE so.so_no=?""",
            (so_no,))
    if not so:
        raise HTTPException(404, f"Sales order {so_no} not found")
    sol = q(con, """SELECT sol.qty, sol.unit_price, sol.customer_part_no, p.name
                    FROM sales_order_lines sol JOIN parts p ON p.id=sol.part_id
                    WHERE sol.sales_order_id=?""", (so["id"],))
    age = (date.today() - date.fromisoformat(so["ordered_on"])).days
    lines = [f"Order {so_no} [{so['status']}] for {so['customer']} "
             f"(contact {so['contact_name']}), reference {so['customer_po']}, "
             f"value {money(so['total'])}, submitted {age} days ago, requested "
             f"date {so['promised_date']}.",
             "Lines: " + "; ".join(
                 f"{l['customer_part_no'] or l['name']} x{l['qty']:.0f} at "
                 f"{money(l['unit_price'])}" for l in sol)]
    return "\n".join(lines), {"so": so_no}


def dig_draft_quote(con, body):
    cust = body.get("customer") or "ELL"
    request_txt = body.get("request") or ""
    c = q1(con, "SELECT * FROM customers WHERE code=?", (cust,))
    if not c:
        raise HTTPException(404, f"Customer {cust} not found")
    cparts = q(con, """SELECT cp.customer_part_no, cp.price, p.part_no, p.name,
                       p.std_cost FROM customer_parts cp
                       JOIN parts p ON p.id=cp.part_id WHERE cp.customer_id=?""",
               (c["id"],))
    hist = q(con, """SELECT so_no, status, total, ordered_on FROM sales_orders
                     WHERE customer_id=? ORDER BY ordered_on DESC LIMIT 6""",
             (c["id"],))
    gst = q1(con, "SELECT value FROM settings WHERE key='gst_rate'")["value"]
    lines = [f"Customer: {c['name']} ({c['type']}), payment terms "
             f"{c['payment_terms']} days. GST rate {float(gst)*100:.0f}%. "
             f"All amounts AUD.",
             "Contract part prices: " + "; ".join(
                 f"{p['part_no']} {p['name']} = {money(p['price'])} "
                 f"(their ref {p['customer_part_no']}, std cost "
                 f"{money(p['std_cost'])})" for p in cparts),
             "Order history: " + "; ".join(
                 f"{h['so_no']} [{h['status']}] {money(h['total'])}" for h in hist),
             f"Request: {request_txt}"]
    return "\n".join(lines), {"customer": c["name"], "priced_parts": len(cparts)}


def dig_line(con, body):
    return dig_day_plan(con, body)


def dig_lot_trace(con, body):
    lot = body.get("lot") or "WF-2261"
    fwd = trace_forward(con, lot)
    direction = "forward"
    if not fwd:
        fwd = trace_backward(con, lot)
        direction = "backward"
    if not fwd:
        raise HTTPException(404, f"Lot {lot} not found (raw or finished)")
    lines = []
    if direction == "forward":
        rl = fwd["raw_lot"]
        lines.append(f"FORWARD TRACE of raw lot {rl['lot_no']} - {rl['part_no']} "
                     f"{rl['part_name']} from {rl['supplier_name']}, received "
                     f"{rl['received_on']}, {rl['qty_remaining']:.0f} of "
                     f"{rl['qty_received']:.0f} remaining, status {rl['status']}.")
        if fwd["hold"]:
            lines.append(f"Hold {fwd['hold']['hold_no']} [{fwd['hold']['status']}]: "
                         f"{fwd['hold']['reason'][:140]}")
        for r in fwd["runs"]:
            lines.append(f"Consumed by {r['run_no']} ({r['part_no']} "
                         f"{r['part_name']}, status {r['status']}): "
                         f"{r['consumed_qty']:.0f} units used.")
        for f in fwd["finished_lots"]:
            hold = f" - OPEN HOLD {f['open_hold']['hold_no']}" if f["open_hold"] else ""
            lines.append(f"Finished lot {f['lot_no']} from {f['run_no']}: "
                         f"{f['qty_produced']:.0f} produced, {f['qty_shipped']:.0f} "
                         f"shipped, {f['qty_produced']-f['qty_shipped']:.0f} on hand, "
                         f"status {f['status']}{hold}")
        for s in fwd["shipments"]:
            lines.append(f"Shipment {s['shp_no']} ({s['shipped_on']}, {s['status']}): "
                         f"{s['qty']:.0f} units of lot {s['finished_lot']} to "
                         f"{s['customer_name']} - {s['ship_to_name']} "
                         f"({s['city']}), their PO {s['customer_po']}")
        e = fwd["exposure"]
        lines.append(f"EXPOSURE: {e['shipped_qty']:.0f} units shipped to "
                     f"{', '.join(e['ship_tos'])}; {e['unshipped_qty']:.0f} units "
                     f"unshipped and blocked on site.")
    else:
        fl = fwd["finished_lot"]
        lines.append(f"BACKWARD TRACE of finished lot {fl['lot_no']} - "
                     f"{fl['part_no']} {fl['part_name']}: {fl['qty_produced']:.0f} "
                     f"produced on {fl['produced_on']}, status {fl['status']}.")
        r = fwd["run"]
        lines.append(f"Made by {r['run_no']} on line {r['line_code']}, completed "
                     f"{(r['completed_at'] or '')[:10]}.")
        for m in fwd["materials"]:
            if m["lot_no"]:
                lines.append(f"Input {m['part_no']} {m['part_name']}: lot "
                             f"{m['lot_no']} from {m['supplier_name']} (received "
                             f"{m['received_on']}, CoA {m['coa_ref']}, status "
                             f"{m['lot_status']}), {m['qty']:.0f} used")
            else:
                lines.append(f"Input {m['part_no']} {m['part_name']}: "
                             f"{m['qty']:.0f} used (non-lot-tracked)")
        for s in fwd["shipments"]:
            lines.append(f"Shipped: {s['qty']:.0f} on {s['shp_no']} "
                         f"({s['shipped_on']}) to {s['customer_name']} - "
                         f"{s['ship_to_name']}")
    return "\n".join(lines), {"lot": lot, "direction": direction,
                              "trace": fwd}


# =====================================================================
# Feature registry - name -> (mode, scope, system prompt, digest builder)
# =====================================================================
F = {}


def feature(name, mode, digest=None, scope="all", system="", compose=False):
    F[name] = {"mode": mode, "digest": digest, "scope": scope,
               "system": system, "compose": compose}


ANALYST = (STYLE + "You are the operations intelligence assistant inside Tallowa "
           "Components' plant platform, writing for the plant leadership team. "
           "Ground every statement in the live plant data provided - quote the "
           "actual identifiers, quantities and dates. Be specific and ranked; "
           "lead with what matters most. ")

feature("briefing", "erp", dig_briefing, system=ANALYST +
        "Write the daily plant briefing as a short prioritised list (most urgent "
        "first). One line of context, then numbered items. For each item name the "
        "records involved (run, lot, order, invoice numbers) and the single next "
        "action. Finish with one line on what is going well.")
feature("dispatch-actions", "erp", dig_dispatch, system=ANALYST +
        "Recommend the dispatch sequence for production control: which runs to "
        "start, expedite, resequence or hold back, and why - considering line "
        "status, priorities, promised dates and material constraints. Numbered, "
        "most urgent first.")
feature("day-plan", "erp", dig_day_plan, system=ANALYST +
        "Write the line lead's shift plan for this line: run order with targets, "
        "crewing notes, equipment attention items, and one risk to watch. Keep it "
        "tight enough to read at the morning huddle.")
feature("completion-note", "erp", dig_run, system=ANALYST +
        "Draft the completion note for this production run: what was built, "
        "yield, materials and lots consumed, defects raised and their state, "
        "labour, and anything the next shift or quality must know. Past tense, "
        "factual.")
feature("run-timeline", "erp", dig_run, system=ANALYST +
        "Narrate this production run as a timeline: creation, release, start, "
        "material issues with lot numbers, defects as they occurred, holds, "
        "completion state. Chronological, one event per line with dates where "
        "the data gives them.")
feature("similar-runs", "erp", dig_similar_runs, system=ANALYST +
        "Compare past runs of this part: yield and scrap trends, recurring defect "
        "codes, cost variance. Say what this run should watch for based on that "
        "history.")
feature("parts-kit", "erp", dig_parts_kit, system=ANALYST +
        "Produce the line-side kitting instruction for this run: what to pick, "
        "how much, which lots in FIFO order (respecting quarantine - a "
        "quarantined lot must never be picked), and flag any shortage with a "
        "recommended action.")
feature("time-anomaly", "erp", dig_time_anomaly, system=ANALYST +
        "Review the labour entries and call out anomalies - entries far above "
        "the expectation, and what a supervisor should check before treating "
        "them as errors (machine trouble, training, data entry).")
feature("customer-status-update", "erp", dig_customer, compose=True, system=ANALYST +
        "Draft a status update email the account manager can send this customer "
        "today: order progress, shipments, any issue affecting them stated "
        "honestly with the containment action, and the next milestone. "
        "Professional, warm, no waffle. Sign off as 'The Tallowa Components "
        "customer team'.")
feature("account-health", "erp", dig_customer, system=ANALYST +
        "Assess this customer account's health: delivery performance, quality "
        "(PPM vs their target), commercial position (orders, overdue invoices), "
        "open risks, and the relationship trajectory. End with a one-word "
        "rating - healthy, watch, or at-risk - and the two actions that most "
        "improve it.")
feature("proactive-maintenance", "erp", dig_maintenance, system=ANALYST +
        "Recommend the maintenance priorities: which machines and tooling to "
        "service first and why, connecting service state to the defect history "
        "and line impact. Numbered, most urgent first.")
feature("dunning-draft", "erp", dig_dunning, compose=True, system=ANALYST +
        "Draft one polite but firm payment reminder email per overdue customer, "
        "referencing the exact invoices, amounts and days overdue. Keep each "
        "under 120 words. Sign off as 'Tallowa Components accounts receivable'.")
feature("lost-quotes", "erp", dig_lost_quotes, system=ANALYST +
        "Analyse the lost and rejected quotes: patterns in the reasons, what "
        "they cost us, and two concrete changes that would win comparable "
        "business next time.")
feature("recurring-preview", "erp", dig_recurring_preview, system=ANALYST +
        "Preview what the release schedules will generate in the next three "
        "weeks and whether the lines can absorb it given current load. Flag "
        "any clash and suggest the resequencing.")
feature("demand-reorder", "erp", dig_demand_reorder, system=ANALYST +
        "Recommend the purchasing actions: what to reorder now, how much, from "
        "whom - netting off what is already on order and what planned runs will "
        "consume. Rank by production risk if not ordered this week.")
feature("skill-gap", "erp", dig_skill_gap, system=ANALYST +
        "Assess certification coverage against the scheduled work: expired and "
        "expiring certifications, which stations that puts at risk (remember: "
        "an expired TQ-1, HT-1 or PL-1 removes the operator from those stations "
        "immediately), and the renewal plan in priority order.")
feature("sla-early-warning", "erp", dig_sla, system=ANALYST +
        "Flag the customer orders most at risk of missing their promised ship "
        "date, and why (run progress, held runs, stopped lines). For each: risk "
        "level, days of buffer, and the action that protects the date. Most at "
        "risk first.")
feature("margin-insight", "erp", dig_margin, system=ANALYST +
        "Explain where margin is being made and lost by part and family, name "
        "anything under the margin-risk threshold, connect cost variance to its "
        "cause where the data shows one, and give the two highest-value margin "
        "actions.")
feature("exec-summary", "erp", dig_exec, system=ANALYST +
        "Write the weekly executive summary of the plant for the managing "
        "director: performance headline, the fastener containment status in "
        "plain terms, commercial position, the two biggest risks, the two "
        "biggest opportunities. Under 250 words.")
feature("finance-exceptions", "erp", dig_finance_exceptions, system=ANALYST +
        "Review the finance exceptions: overdue receivables, unsent drafts, "
        "revenue blocked behind quality holds, uninvoiced shipments. Quantify "
        "each and give the collection or release action.")
feature("cost-exceptions", "erp", dig_cost_exceptions, system=ANALYST +
        "Identify the runs with the worst cost variance against standard, "
        "explain the likely drivers visible in the data (scrap, labour), and "
        "recommend where a cost review would pay back first.")
feature("risk-watchlist", "erp", dig_risk_watchlist, system=ANALYST +
        "Build the plant risk watchlist: supplier risks, order and run risks, "
        "holds and critical defects. For each item: why it is on the list, "
        "severity, and the mitigating action in flight or needed. Ranked.")
feature("commit-date", "erp", dig_commit_date, system=ANALYST +
        "Recommend a ship date the plant can commit for this part and quantity, "
        "reasoning from material position, line load and recent cycle history. "
        "Give the date, the confidence, and what would pull it in.")
feature("asset-service", "erp", dig_asset_service, system=ANALYST +
        "Prioritise the tooling service plan: which dies, fixtures and gauges "
        "need attention, connecting shot-life and due dates to the defects they "
        "cause when they slip. Numbered.")
feature("quote-risk", "erp", dig_quote_risk, system=ANALYST +
        "Score each pending quote's risk of being lost (drawing on the loss "
        "history), with the reason and the follow-up that most improves the "
        "odds. Most at risk first.")
feature("quote-comms", "erp", dig_quote_comms, compose=True, system=ANALYST +
        "Draft the follow-up email for this pending order: reference their PO, "
        "confirm what was quoted, address the likely sticking point, and "
        "propose the next step. Under 150 words, warm and direct. Sign off as "
        "'The Tallowa Components sales team'.")
feature("variation-claim", "erp", dig_variation, compose=True, system=ANALYST +
        "Draft a commercial variation claim for the requested change to this "
        "order: what changes, the cost and price impact reasoning from the data "
        "given, the revised terms to agree, and the approval needed. Formal "
        "register.")
feature("draft-quote", "erp", dig_draft_quote, compose=True, system=ANALYST +
        "Draft the quotation: line items with the contract prices given (never "
        "invent a price - if a requested part has no contract price, say it "
        "needs commercial review), quantities from the request, subtotal, GST "
        "and total in AUD, validity 30 days, and lead-time language consistent "
        "with the order history. Ready to paste into an email.")
feature("audit-assistant", "erp", dig_audit, system=ANALYST +
        "Answer the question strictly from the audit trail entries provided - "
        "who did what, when, in what order. Quote entry timestamps and "
        "identifiers. If the trail does not contain the answer, say so.")
feature("lots", "erp", dig_lots, system=ANALYST +
        "Summarise the lot position: quarantined and held lots first (with "
        "why), then ageing raw lots, then finished-lot stock. Note anything "
        "that threatens FIFO or traceability discipline.")
feature("recurring-suggest", "erp", dig_recurring_suggest, system=ANALYST +
        "Suggest which repeat ordering patterns should become standing release "
        "schedules (that are not already), with the cadence and quantity the "
        "history supports, and the working-capital trade-off in one line each.")

# hybrid features - KB citations + live digest
feature("fault-root-cause", "hybrid", dig_fault_root_cause, scope="containment",
        system=GROUNDED + "You are the quality engineering assistant. Analyse the "
        "defect Pareto and the focus code's event detail, form the most likely "
        "root-cause hypothesis chain, and lay out the investigation per the "
        "plant's 8D procedure - citing the procedure steps that apply. Never "
        "state a cause as proven that the data only suggests.")
feature("fpy-root-cause", "hybrid", dig_fpy_root_cause, scope="containment",
        system=GROUNDED + "You are the quality engineering assistant. From the "
        "run's FPY breach and the SUSPECT lines given (material, equipment, "
        "shift), rank them by statistical weight into a numbered list of "
        "confidence-labelled suspects (HIGH/MEDIUM/LOW) - lead with the "
        "one the data most strongly supports. For each: the specific "
        "identifiers (lot, machine, defect numbers), the per centage of "
        "affected units, and why it is ranked where it is. Close with the "
        "single next containment action per the plant's 8D procedure "
        "(cite it). Never state a cause as proven that the data only "
        "correlates.")
feature("compliance-readiness", "hybrid", dig_compliance, scope="quality",
        system=GROUNDED + "You are the quality systems assistant preparing the "
        "plant for an audit. Assess readiness against the quality manual's "
        "commitments using the live position given, finding by finding: the "
        "requirement (cite it), the live evidence or gap, and the closure "
        "action. Be direct about gaps.")
feature("calibration-compliance", "hybrid", dig_calibration, scope="calibration",
        system=GROUNDED + "You are the calibration compliance assistant. Assess "
        "the equipment position against the calibration procedure (cite the "
        "intervals and rules), state clearly what an overdue device means for "
        "product already accepted, and give the action list.")
feature("safety-preflight", "hybrid", dig_day_plan, scope="safety",
        system=GROUNDED + "You are the safety assistant preparing a pre-shift "
        "briefing for this line. From the safety procedures (cite them) and the "
        "line's live state: the hazards on this line today, the PPE required, "
        "the LOTO rules that apply to any intervention, and anything the "
        "stoppages or equipment states add. Speak to the crew directly.")
feature("ap-error-explain", "hybrid", dig_ap_error_explain, scope="finance",
        system=GROUNDED + "You are the AP assistant explaining a posting "
        "failure to an AP clerk with no accounting background. From the "
        "invoice detail and the deterministic fix/authority given: explain "
        "the error code in one plain-English sentence, state the exact fix, "
        "and name the policy that authorises it (cite the policy document). "
        "Use only the amounts, codes and identifiers given - never invent "
        "one.")
feature("ap-batch-fix", "hybrid", dig_ap_batch_fix, scope="finance",
        system=GROUNDED + "You are the AP assistant proposing a batch "
        "correction. From the shared-root-cause group given: state how many "
        "invoices share the cause and the combined total, confirm whether "
        "the batch is within the clerk's approval authority, propose the "
        "single correction that fixes all of them, and cite the policy that "
        "authorises it. If it says this is a one-off, say plainly that no "
        "batch is available and give the single fix instead.")
feature("plant-access-briefing", "hybrid", dig_day_plan, scope="safety",
        system=GROUNDED + "You are preparing a visitor or contractor access "
        "briefing for this area. From the plant access procedure and PPE matrix "
        "(cite them) plus the line's live state: what they must wear, where "
        "they may walk, what is off-limits, and today's specific hazards.")


# ------------------------------------------------------------ registry route
async def run_feature(name: str, body: dict) -> dict:
    cfg = F[name]
    con = connect()
    try:
        digest, data_used = cfg["digest"](con, body) if cfg["digest"] else ("", {})
    finally:
        con.close()
    question = (body.get("query") or body.get("question") or
                DEFAULT_QUESTIONS.get(name, f"Provide the {name} analysis."))
    t0 = time.monotonic()
    if cfg["mode"] == "erp":
        text = await predict_gen(cfg["system"], "Live plant data (queried now "
                                 "from the ERP):\n" + digest
                                 + f"\n\nRequest: {question}")
        return {"answer": clean(text), "citations": [], "data_used": data_used,
                "digest": digest, "latency_ms": int((time.monotonic()-t0)*1000),
                "cached": False}
    d = await kb_ask(question, cfg["system"], cfg["scope"], digest,
                     compose=cfg["compose"])
    answer = clean(d.get("answer") or "")
    if d.get("status") in ("no_context", "no_retrieval_data") or not answer.strip():
        raise RuntimeError("no_context")
    return {"answer": answer, "citations": parse_citations(d.get("retrieval_results")),
            "data_used": data_used, "digest": digest,
            "latency_ms": d.get("_latency_ms"), "cached": False}


DEFAULT_QUESTIONS = {
    "briefing": "What is the state of the plant today and what needs attention first?",
    "dispatch-actions": "What should production control action next and in what order?",
    "day-plan": "Build the shift plan for this line.",
    "completion-note": "Draft the completion note for this run.",
    "run-timeline": "Narrate this run's timeline.",
    "similar-runs": "How have past runs of this part behaved and what should this run watch?",
    "parts-kit": "Build the kitting instruction for this run.",
    "time-anomaly": "Which labour entries look anomalous and what should be checked?",
    "customer-status-update": "Draft today's status update for this customer.",
    "account-health": "Assess this account's health.",
    "proactive-maintenance": "What should maintenance prioritise and why?",
    "dunning-draft": "Draft the payment reminders for the overdue invoices.",
    "lost-quotes": "What patterns explain our lost quotes and what should change?",
    "recurring-preview": "What will the release schedules generate and can we absorb it?",
    "demand-reorder": "What should purchasing reorder now?",
    "skill-gap": "Where are the certification gaps against scheduled work?",
    "sla-early-warning": "Which orders are at risk of missing their promised dates?",
    "margin-insight": "Where is margin being made and lost?",
    "exec-summary": "Write the weekly executive summary.",
    "finance-exceptions": "What are the finance exceptions and actions?",
    "cost-exceptions": "Which runs are over cost and why?",
    "risk-watchlist": "Build the plant risk watchlist.",
    "commit-date": "What ship date can we commit for this part and quantity?",
    "asset-service": "Prioritise the tooling service plan.",
    "quote-risk": "Score the pending quotes' loss risk.",
    "quote-comms": "Draft the follow-up for this pending order.",
    "variation-claim": "Draft the variation claim for this change.",
    "draft-quote": "Draft the quotation for this request.",
    "audit-assistant": "Answer from the audit trail.",
    "lots": "Summarise the lot position.",
    "recurring-suggest": "Which repeat patterns should become standing schedules?",
    "fault-root-cause": "Run the defect Pareto and root-cause analysis.",
    "fpy-root-cause": "Line 3 FPY alert overnight - what happened? Give me "
                      "the ranked, correlated suspects.",
    "compliance-readiness": "How ready are we for a quality audit?",
    "calibration-compliance": "Assess calibration compliance and its product impact.",
    "safety-preflight": "Prepare the pre-shift safety briefing for this line.",
    "plant-access-briefing": "Prepare the access briefing for a contractor visiting this line.",
    "ap-error-explain": "Explain this AP posting failure in plain English - "
                        "why it failed, the fix, and who can authorise it.",
    "ap-batch-fix": "Are there other invoices with the same cause? Propose "
                    "the batch fix.",
}


def _digest_detail(data_used: dict) -> str:
    """Short human-readable summary of the live figures a digest pulled -
    the trace card shows this, never the full digest text (too long)."""
    parts = []
    for k, v in (data_used or {}).items():
        if isinstance(v, (int, float, str)) and str(v) != "":
            parts.append(f"{k.replace('_', ' ')}: {v}")
    return ", ".join(parts[:5])


def _synth_feature_trace(cfg: dict, data: dict) -> list[dict]:
    """A cached-golden replay still shows the real SHAPE of the work (live
    data queried, documents consulted, answer composed) instead of dumping
    the stored answer straight onto the screen - the guaranteed-demo path
    must look exactly like the live one, just backed by a captured answer."""
    out = [{"type": "tool_call", "label": "Querying live plant data"},
           {"type": "tool_result", "ok": True, "label": "Live plant data retrieved",
            "detail": _digest_detail(data.get("data_used"))}]
    if cfg["mode"] != "erp":
        out.append({"type": "doc_search", "label": "Consulting the plant documents",
                    "detail": f"{len(data.get('citations') or [])} passage(s) matched"})
        out.append({"type": "composing", "label": "Composing the grounded answer"})
    else:
        out.append({"type": "composing", "label": "Composing the answer"})
    return out


async def stream_feature(name: str, body: dict):
    """NDJSON progress trace for a single grounded feature call - the real
    steps (live data queried, documents consulted, answer composed), not a
    generic spinner. Ends with one `result` event carrying exactly the
    payload the buffered endpoint would have returned, so callers render
    it identically either way."""
    cfg = F[name]
    golden = body.get("golden") or name
    question = (body.get("query") or body.get("question") or
                DEFAULT_QUESTIONS.get(name, f"Provide the {name} analysis."))
    yield {"type": "start", "question": question}

    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            for ev in _synth_feature_trace(cfg, c):
                yield ev
            yield {"type": "result", "data": c}
            yield {"type": "done"}
            return

    try:
        con = connect()
        try:
            t0 = time.monotonic()
            digest, data_used = cfg["digest"](con, body) if cfg["digest"] else ("", {})
            ms0 = int((time.monotonic() - t0) * 1000)
        finally:
            con.close()
        yield {"type": "tool_call", "label": "Querying live plant data"}
        yield {"type": "tool_result", "ok": True, "label": "Live plant data retrieved",
               "detail": _digest_detail(data_used), "duration_ms": ms0}

        if cfg["mode"] == "erp":
            yield {"type": "composing", "label": "Composing the answer"}
            t1 = time.monotonic()
            text = await predict_gen(cfg["system"], "Live plant data (queried now "
                                     "from the ERP):\n" + digest + f"\n\nRequest: {question}")
            ms1 = int((time.monotonic() - t1) * 1000)
            data = {"answer": clean(text), "citations": [], "data_used": data_used,
                    "digest": digest, "latency_ms": ms1, "cached": False}
        else:
            yield {"type": "doc_search", "label": "Consulting the plant documents"}
            yield {"type": "composing", "label": "Composing the grounded answer"}
            d = await kb_ask(question, cfg["system"], cfg["scope"], digest,
                             compose=cfg["compose"])
            answer = clean(d.get("answer") or "")
            if d.get("status") in ("no_context", "no_retrieval_data") or not answer.strip():
                raise RuntimeError("no_context")
            data = {"answer": answer, "citations": parse_citations(d.get("retrieval_results")),
                    "data_used": data_used, "digest": digest,
                    "latency_ms": d.get("_latency_ms"), "cached": False}
        yield {"type": "result", "data": data}
    except Exception:
        c = cached_golden(golden)
        if c:
            yield {"type": "fallback", "message": "Showing a captured example "
                                                   "while the live answer recovers."}
            for ev in _synth_feature_trace(cfg, c):
                yield ev
            yield {"type": "result", "data": c}
        else:
            yield {"type": "error", "message": "Could not generate a grounded "
                                               "answer for this - try again."}
    yield {"type": "done"}


def make_handler(name: str):
    async def handler(req: Request, user: dict = Depends(current_user)):
        body = {}
        try:
            body = await req.json()
        except Exception:
            pass
        if body.get("stream"):
            routed = AGENT_ROUTED_FEATURES.get(name)
            if routed:
                want_tool, question_fn = routed
                bearer = (req.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None
                gen = agent_feature_stream(question_fn(body), bearer, want_tool)
            else:
                gen = stream_feature(name, body)
            return StreamingResponse(
                (json.dumps(ev) + "\n" async for ev in gen),
                media_type="application/x-ndjson")
        golden = body.get("golden") or name
        if body.get("mode") == "cached":
            c = cached_golden(golden)
            if c:
                return c
        try:
            return await run_feature(name, body)
        except HTTPException:
            raise
        except Exception:
            c = cached_golden(golden)
            if c:
                return c
            return JSONResponse({"answer": "", "empty": True, "citations": [],
                                 "data_used": {}, "cached": False}, status_code=200)
    handler.__name__ = "ai_" + name.replace("-", "_")
    return handler


for _name in list(F):
    router.add_api_route(f"/{_name}", make_handler(_name), methods=["POST"],
                         name=f"ai_{_name}",
                         summary=f"AI: {_name.replace('-', ' ')}")


# ------------------------------------------------------------------ status
@router.get("/status")
async def ai_status(user: dict = Depends(current_user)):
    try:
        async with httpx.AsyncClient(timeout=15) as cx:
            r = await cx.get(f"{HOST}/api/v1/kb/{KB}/counters", headers=HDRS)
        ok = r.status_code == 200
        counters = r.json() if ok else {}
    except Exception:
        ok, counters = False, {}
    return {"online": ok, "documents": len(MANIFEST),
            "indexed_paragraphs": counters.get("paragraphs"),
            "features": len(F) + 10}


# ------------------------------------------------------------------- ask
@router.post("/ask")
async def ai_ask(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Empty query")
    golden = body.get("golden") or ""
    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            return c
    system = (GROUNDED + "You are the knowledge assistant inside Tallowa "
              "Components' plant platform, answering operators, line leads and "
              "quality staff from the plant's own controlled documents - "
              "procedures, standard work instructions, safety data and customer "
              "requirements. Name the document and section you rely on. Be "
              "precise about limits, torques, intervals and thresholds.")
    try:
        d = await kb_ask(query, system, body.get("scope") or "all",
                         top_k=int(body.get("top_k") or 15))
        answer = clean(d.get("answer") or "")
        if d.get("status") in ("no_context", "no_retrieval_data") or not answer.strip():
            return {"answer": "", "empty": True, "citations": [], "cached": False}
        return {"answer": answer,
                "citations": parse_citations(d.get("retrieval_results")),
                "latency_ms": d.get("_latency_ms"), "cached": False}
    except Exception:
        c = cached_golden(golden)
        if c:
            return c
        return JSONResponse({"answer": "", "empty": True, "citations": [],
                             "cached": False})


@router.post("/find")
async def ai_find(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Empty query")
    payload = {"query": query, "features": ["keyword", "semantic"], "top_k": 20,
               "resource_filters": scope_rids(body.get("scope") or "all")}
    try:
        async with httpx.AsyncClient(timeout=60) as cx:
            r = await cx.post(f"{HOST}/api/v1/kb/{KB}/find", headers=HDRS,
                              json=payload)
        r.raise_for_status()
    except Exception:
        return {"hits": []}
    hits = []
    for rid, res in (r.json().get("resources") or {}).items():
        best = None
        for fid, field in (res.get("fields") or {}).items():
            for pid, para in (field.get("paragraphs") or {}).items():
                if best is None or (para.get("score") or 0) > (best.get("score") or 0):
                    best = para
        if best and (best.get("score") or 0) >= 0.15:
            hits.append({"rid": rid, "file": RID_TO_FILE.get(rid, ""),
                         "title": res.get("title"), "score": best.get("score"),
                         "snippet": (best.get("text") or "")[:280]})
    hits.sort(key=lambda h: -(h["score"] or 0))
    return {"hits": hits}


# ------------------------------------------------------------- lot trace
@router.post("/lot-trace")
async def ai_lot_trace(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    golden = body.get("golden") or "lot-trace"
    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            return c
    con = connect()
    try:
        digest, data_used = dig_lot_trace(con, body)
    finally:
        con.close()
    system = (GROUNDED + "You are the traceability and containment assistant. "
              "From the trace data and the plant's containment procedures "
              "(cite them), narrate the exposure - exactly which runs, finished "
              "lots, quantities, shipments and customer plants are affected and "
              "what is already blocked - then lay out the containment actions "
              "and obligations (customer notification windows, supplier "
              "obligations) the procedures require. Precise numbers only from "
              "the trace data.")
    question = (body.get("query") or
                "Narrate the exposure for this lot and the required containment.")
    try:
        d = await kb_ask(question, system, "containment", digest)
        answer = clean(d.get("answer") or "")
        if d.get("status") in ("no_context", "no_retrieval_data") or not answer.strip():
            raise RuntimeError("no_context")
        return {"answer": answer,
                "citations": parse_citations(d.get("retrieval_results")),
                "data_used": data_used, "digest": digest,
                "latency_ms": d.get("_latency_ms"), "cached": False}
    except Exception:
        c = cached_golden(golden)
        if c:
            return c
        return {"answer": "", "empty": True, "citations": [],
                "data_used": data_used, "digest": digest, "cached": False}


# --------------------------------------------------------- 8D draft (UC1)
def split_8d_sections(md_text: str) -> dict:
    """Best-effort split of the generated draft into Problem / Root cause /
    Containment / Corrective action sections by markdown heading, so the
    editable fields can be pre-filled without a schema+citations call."""
    out = {"problem": "", "root_cause": "", "containment": "",
           "corrective_action": ""}
    key_map = [("problem", ("problem", "d2")), ("root_cause", ("root cause", "d4")),
               ("containment", ("containment", "d3")),
               ("corrective_action", ("corrective action", "d5", "prevention", "d7"))]
    current = None
    for line in md_text.splitlines():
        stripped = line.strip().lower().lstrip("#").strip()
        matched = None
        for key, aliases in key_map:
            if any(stripped.startswith(a) for a in aliases):
                matched = key
                break
        if matched:
            current = matched
            continue
        if current and line.strip():
            out[current] = (out[current] + " " + line.strip()).strip()
    return out


EIGHT_D_SYSTEM = (
    GROUNDED + "You are the quality engineering assistant drafting "
    "an 8D containment report from the evidence given, per the "
    "plant's QP-8D procedure (cite it). Structure the draft with "
    "these exact markdown headings, one short paragraph each: "
    "## Problem (D2) - the FPY breach in numbers; ## Root cause "
    "(D4) - the leading suspect from the evidence and its "
    "confidence, naming the identifiers; ## Containment (D3) - "
    "state the CURRENT containment status exactly as given (do not "
    "assume a hold exists if the data says it does not) and what "
    "should happen next; ## Corrective action (D5-D7) - pending "
    "the quality inspector's approval, so phrase it as a "
    "recommendation, not a completed action. Do not fabricate a "
    "defect, lot, hold number or machine identifier not present in "
    "the evidence.")


async def _8d_draft_events(body: dict):
    """Single source of truth for /8d-draft, streamed or buffered - the
    buffered route below just drains this to its final `result` event."""
    golden = body.get("golden") or "8d-draft"
    question = (body.get("query") or
                "Draft the 8D containment report from this evidence.")
    yield {"type": "start", "question": question}

    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            yield {"type": "tool_call",
                   "label": "Querying the root-cause evidence and containment status"}
            yield {"type": "tool_result", "ok": True,
                   "label": "Evidence and containment status retrieved",
                   "detail": _digest_detail(c.get("data_used"))}
            yield {"type": "doc_search", "label": "Consulting the QP-8D procedure",
                   "detail": f"{len(c.get('citations') or [])} passage(s) matched"}
            yield {"type": "composing", "label": "Drafting the 8D report"}
            yield {"type": "result", "data": c}
            yield {"type": "done"}
            return

    con = connect()
    try:
        t0 = time.monotonic()
        rc_digest, rc_data = dig_fpy_root_cause(con, body)
        # ground D3 (containment) in the ACTUAL current hold status, never an
        # assumed one - the report must say what is true right now
        run = q1(con, "SELECT id FROM runs WHERE run_no=?", (rc_data["run_no"],))
        flots = q(con, """SELECT fl.lot_no, fl.qty_produced, fl.status,
                          h.hold_no, h.status hold_status FROM finished_lots fl
                          LEFT JOIN holds h ON h.scope='finished_lot'
                            AND h.scope_id=fl.id AND h.status='open'
                          WHERE fl.run_id=?""", (run["id"],))
        ms0 = int((time.monotonic() - t0) * 1000)
    finally:
        con.close()
    cont_lines = ["Current containment status (live, not assumed):"]
    for f in flots:
        cont_lines.append(
            f"  Finished lot {f['lot_no']} ({f['qty_produced']:.0f} units) - "
            + (f"OPEN HOLD {f['hold_no']} - quarantined, blocked from shipping."
               if f["hold_no"] else
               f"status '{f['status']}' - NOT yet on hold, still shippable."))
    rc_digest = rc_digest + "\n" + "\n".join(cont_lines)
    yield {"type": "tool_call",
           "label": "Querying the root-cause evidence and containment status"}
    yield {"type": "tool_result", "ok": True,
           "label": "Evidence and containment status retrieved",
           "detail": _digest_detail(rc_data), "duration_ms": ms0}
    try:
        yield {"type": "doc_search", "label": "Consulting the QP-8D procedure"}
        yield {"type": "composing", "label": "Drafting the 8D report"}
        d = await kb_ask(question, EIGHT_D_SYSTEM, "containment", rc_digest,
                         compose=True, top_k=15)
        answer = clean(d.get("answer") or "")
        if d.get("status") in ("no_context", "no_retrieval_data") or not answer.strip():
            raise RuntimeError("no_context")
        yield {"type": "result", "data": {
            "answer": answer, "fields": split_8d_sections(answer),
            "citations": parse_citations(d.get("retrieval_results")),
            "data_used": rc_data, "digest": rc_digest,
            "latency_ms": d.get("_latency_ms"), "cached": False}}
    except Exception:
        c = cached_golden(golden)
        if c:
            yield {"type": "fallback", "message": "Showing a captured example "
                                                   "while the live draft recovers."}
            yield {"type": "result", "data": c}
        else:
            yield {"type": "result", "data": {"answer": "", "empty": True,
                   "citations": [], "data_used": rc_data, "digest": rc_digest,
                   "cached": False}}
    yield {"type": "done"}


@router.post("/8d-draft")
async def ai_8d_draft(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    if body.get("stream"):
        bearer = (req.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None
        gen = agent_feature_stream(_8d_question(body), bearer, "ai_8d_draft")
        return StreamingResponse(
            (json.dumps(ev) + "\n" async for ev in gen),
            media_type="application/x-ndjson")
    data = {"answer": "", "empty": True, "citations": [], "data_used": {}, "cached": False}
    async for ev in _8d_draft_events(body):
        if ev["type"] == "result":
            data = ev["data"]
    return data


# --------------------------------------------------------- CTP commit (UC3)
def compute_ctp(con, part_no, qty, expedite=False, expedite_days=5):
    """The capable-to-promise engine: BOM explosion, component gap check,
    the binding constraint (shortfall + the incoming PO that resolves it),
    production lead time from REAL historical run-rate data, and (with
    expedite=True) a what-if that pulls the PO in and re-checks conflict
    against the only other order that would compete for the same shipment."""
    p = q1(con, "SELECT * FROM parts WHERE part_no=?", (part_no,))
    if not p:
        raise HTTPException(404, f"Part {part_no} not found")
    bom = q(con, """SELECT b.qty_per, c.part_no, c.name, c.id cid FROM boms b
                    JOIN parts c ON c.id=b.component_part_id
                    WHERE b.parent_part_id=?""", (p["id"],))
    if not bom:
        raise HTTPException(422, f"{part_no} has no BOM to explode")
    shortages = []
    for b in bom:
        need = b["qty_per"] * qty
        oh = q1(con, """SELECT COALESCE(SUM(s.qty),0) v FROM stock s
                        JOIN locations l ON l.id=s.location_id
                        WHERE s.part_id=? AND l.type!='quarantine'""",
               (b["cid"],))["v"]
        if oh < need:
            shortages.append({"part_no": b["part_no"], "name": b["name"],
                              "cid": b["cid"], "need": round(need, 1),
                              "on_hand": round(oh, 1),
                              "short": round(need - oh, 1)})
    binding = None
    if shortages:
        binding = max(shortages, key=lambda s: s["short"])
        po_line = q1(con, """SELECT po.po_no, po.expected_date, pol.qty
                             FROM purchase_order_lines pol
                             JOIN purchase_orders po ON po.id=pol.po_id
                             WHERE pol.part_id=? AND po.status IN
                             ('confirmed','sent') ORDER BY po.expected_date
                             LIMIT 1""", (binding["cid"],))
        binding["po"] = po_line

    hist = q(con, """SELECT qty_planned, started_at, completed_at FROM runs
                     WHERE part_id=? AND completed_at IS NOT NULL
                       AND started_at IS NOT NULL""", (p["id"],))
    rate = None
    if hist:
        total_qty = sum(h["qty_planned"] for h in hist)
        total_days = sum(max(1, (date.fromisoformat(h["completed_at"][:10]) -
                                 date.fromisoformat(h["started_at"][:10])).days)
                         for h in hist)
        rate = total_qty / total_days if total_days else None
    prod_days = max(1, round(qty / rate)) if rate else 3
    receive_buffer_days = 1
    today = date.today()

    conflict = None
    if binding and binding.get("po"):
        po_expected = date.fromisoformat(binding["po"]["expected_date"])
        applied_expected = po_expected
        if expedite:
            applied_expected = max(today, po_expected - timedelta(days=expedite_days))
        available_date = max(applied_expected, today)
        # in_progress runs are real, live demand on this same component too -
        # excluding them (as an earlier version of this check did) understated
        # the conflict; include them, netted against whatever of THIS
        # component that run has already had issued (run_materials), so a
        # run that already drew its material is not double-counted
        other = q(con, """SELECT r.id, r.run_no, r.qty_planned, r.qty_good,
                          so.so_no, c.name customer_name, b.qty_per
                          FROM runs r JOIN boms b ON b.parent_part_id=r.part_id
                          LEFT JOIN sales_orders so ON so.id=r.sales_order_id
                          LEFT JOIN customers c ON c.id=so.customer_id
                          WHERE b.component_part_id=? AND r.part_id=?
                            AND r.status IN ('released','planned','in_progress')""",
                (binding["cid"], p["id"]))
        for o in other:
            already_issued = q1(con, """SELECT COALESCE(SUM(qty),0) v
                                        FROM run_materials
                                        WHERE run_id=? AND part_id=?""",
                                (o["id"], binding["cid"]))["v"]
            gross_remaining = (o["qty_planned"] - (o["qty_good"] or 0)) * o["qty_per"]
            o["remaining_need"] = max(0.0, gross_remaining - already_issued)
        remaining_need = sum(o["remaining_need"] for o in other)
        po_qty = binding["po"]["qty"] or 0
        headroom = round(po_qty - binding["short"] - remaining_need, 1)
        conflict = {"other_orders": other,
                    "remaining_need_other_orders": round(remaining_need, 1),
                    "po_qty": po_qty, "headroom": headroom,
                    "conflict": headroom < 0,
                    "applied_po_date": applied_expected.isoformat(),
                    "original_po_date": po_expected.isoformat()}
    else:
        available_date = today

    commit_date = available_date + timedelta(days=receive_buffer_days + prod_days)
    alt_safe_date = commit_date + timedelta(days=3)
    return {"part": p, "bom": bom, "shortages": shortages, "binding": binding,
            "prod_days": prod_days, "receive_buffer_days": receive_buffer_days,
            "rate_per_day": round(rate, 1) if rate else None,
            "commit_date": commit_date.isoformat(),
            "alt_safe_date": alt_safe_date.isoformat(),
            "conflict": conflict, "expedite": expedite,
            "expedite_days": expedite_days}


def ctp_digest_text(con, part_no, qty, customer_code, r, requested_date=None) -> str:
    p = r["part"]
    lines = [f"CTP request: {qty:.0f} x {part_no} ({p['name']}).",
             f"Today is {date.today().isoformat()}."]
    # Date comparison is done here in Python, not left to the model - date
    # arithmetic is exactly the kind of judgement an LLM gets wrong silently.
    if requested_date:
        try:
            req_d = date.fromisoformat(requested_date)
            commit_d = date.fromisoformat(r["commit_date"])
            verdict = ("BEATS" if commit_d <= req_d else "MISSES") + \
                      f" the requested date by {abs((commit_d - req_d).days)} day(s)"
            lines.append(f"Requested delivery date: {requested_date}. VERDICT "
                        f"(computed, state exactly this - do not recompute or "
                        f"re-derive it yourself): the commit date "
                        f"{r['commit_date']} {verdict} of {requested_date}.")
        except ValueError:
            lines.append(f"Requested delivery date given as free text: "
                        f"'{requested_date}' - could not be parsed as a date, "
                        f"so do not claim it beats or misses; just state the "
                        f"commit date.")
    if customer_code:
        cust = q1(con, "SELECT * FROM customers WHERE code=?", (customer_code,))
        if cust:
            lines.append(f"Customer: {cust['name']} - {cust['type']} "
                        f"account, PPM target {cust['ppm_target']}."
                        + (" OEM contract - firm-window delivery commitments "
                           "carry contractual weight." if cust["type"] == "oem"
                           else ""))
    if not r["shortages"]:
        lines.append("Material position: every BOM component is available "
                     "on hand right now - no shortage.")
    else:
        lines.append("Material position:")
        for s in r["shortages"]:
            lines.append(f"  {s['part_no']} {s['name']}: need {s['need']:.0f}, "
                        f"on hand {s['on_hand']:.0f}, SHORT {s['short']:.0f}")
    b = r["binding"]
    if b:
        lines.append(f"BINDING CONSTRAINT: {b['part_no']} {b['name']} - short "
                    f"{b['short']:.0f} units.")
        if b.get("po"):
            lines.append(f"  Resolved by incoming {b['po']['po_no']} "
                        f"({b['po']['qty']:.0f} units), "
                        + (f"pulled in (expedited) to "
                           f"{r['conflict']['applied_po_date']}"
                           if r["expedite"] else
                           f"expected {b['po']['expected_date']}") + ".")
        else:
            lines.append("  No open purchase order currently covers this "
                        "shortfall - one would need to be raised.")
    lines.append(f"Historical production rate for {part_no}: "
                + (f"{r['rate_per_day']:.0f} units/day from completed run "
                   "history." if r["rate_per_day"] else
                   "no completed run history - using a 3-day default."))
    lines.append(f"Production lead time for this quantity: {r['prod_days']} "
                f"day(s), plus {r['receive_buffer_days']} day to receive and "
                f"release incoming material.")
    lines.append(f"COMPUTED COMMIT DATE: {r['commit_date']}.")
    lines.append(f"Safer alternative date (buffer against supplier slip): "
                f"{r['alt_safe_date']}.")
    if r["conflict"]:
        c = r["conflict"]
        if c["other_orders"]:
            others = "; ".join(f"{o['so_no'] or o['run_no']} "
                              f"({o['customer_name'] or 'internal'}, "
                              f"{o['qty_planned']-(o['qty_good'] or 0):.0f} "
                              f"units still to build, {o['remaining_need']:.0f} "
                              f"units of this component still needed)"
                              for o in c["other_orders"])
            lines.append(f"Other near-term order(s) also drawing on this same "
                        f"incoming shipment: {others}. Combined remaining "
                        f"need {c['remaining_need_other_orders']:.0f} units.")
        else:
            lines.append("No other near-term order is competing for this "
                        "same incoming shipment.")
        lines.append(f"Headroom on the incoming PO after covering this order "
                    f"and the others: {c['headroom']:.0f} units - "
                    + ("A CONFLICT - not enough to cover both."
                       if c["conflict"] else "no conflict."))
    return "\n".join(lines)


CTP_SYSTEM = (
    ANALYST + "You are the capable-to-promise sales co-pilot. From "
    "the CTP analysis given, answer in this shape: the commit date "
    "and the VERDICT exactly as given (never recompute whether it "
    "beats or misses - state the given verdict verbatim in your "
    "own words), the binding constraint in one sentence naming the "
    "exact component and the incoming PO date, then list the "
    "alternative date(s) with their risk (the computed commit date "
    "= 'on time if the component lands as promised'; the safer "
    "date = 'protects against a supplier slip'). If a conflict "
    "check was run, state it plainly. Confident and concise - this "
    "is being read out on a live phone call. Use only the figures "
    "given.")


def _ctp_detail(r: dict, part_no: str, qty: float, customer_code: str) -> str:
    base = f"part: {part_no}, qty: {qty:.0f}, customer: {customer_code}"
    b = r.get("binding")
    if not b:
        return base + ", material position strong - no shortage"
    return base + f", short {b['short']:.0f} units of {b['part_no']}"


async def _ctp_commit_events(body: dict):
    """Single source of truth for /ctp-commit, streamed or buffered - the
    buffered route below just drains this to its final `result` event."""
    part_no = body.get("part_no") or "TC-70210"
    qty = float(body.get("qty") or 250)
    customer_code = body.get("customer_code") or "MAR"
    expedite = bool(body.get("expedite"))
    golden = body.get("golden") or ("ctp-commit-expedite" if expedite else "ctp-commit")
    question = (body.get("query") or
                f"Can we deliver {qty:.0f} x {part_no} by "
                f"{body.get('requested_date') or 'the date requested'}?")
    yield {"type": "start", "question": question}

    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            yield {"type": "tool_call", "label": "Checking BOM, stock, work-centre "
                                                  "load, open POs and contract priority"}
            yield {"type": "tool_result", "ok": True,
                   "label": "Capability position computed",
                   "detail": _ctp_detail(c.get("ctp") or {}, part_no, qty, customer_code)}
            yield {"type": "composing", "label": "Composing the commit answer"}
            yield {"type": "result", "data": c}
            yield {"type": "done"}
            return

    con = connect()
    try:
        t0 = time.monotonic()
        r = compute_ctp(con, part_no, qty, expedite=expedite)
        digest = ctp_digest_text(con, part_no, qty, customer_code, r,
                                 requested_date=body.get("requested_date"))
        ms0 = int((time.monotonic() - t0) * 1000)
    finally:
        con.close()
    yield {"type": "tool_call", "label": "Checking BOM, stock, work-centre "
                                         "load, open POs and contract priority"}
    yield {"type": "tool_result", "ok": True, "label": "Capability position computed",
           "detail": _ctp_detail(r, part_no, qty, customer_code), "duration_ms": ms0}
    try:
        yield {"type": "composing", "label": "Composing the commit answer"}
        text = await predict_gen(CTP_SYSTEM, "Live plant data (queried now from "
                                 "the ERP):\n" + digest + f"\n\nRequest: {question}")
        yield {"type": "result", "data": {"answer": clean(text), "citations": [],
               "digest": digest, "ctp": r, "cached": False}}
    except Exception:
        c = cached_golden(golden)
        if c:
            yield {"type": "fallback", "message": "Showing a captured example "
                                                   "while the live answer recovers."}
            yield {"type": "result", "data": c}
        else:
            yield {"type": "result", "data": {"answer": "", "empty": True,
                   "citations": [], "digest": digest, "ctp": r, "cached": False}}
    yield {"type": "done"}


@router.post("/ctp-commit")
async def ai_ctp_commit(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    if body.get("stream"):
        bearer = (req.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None
        gen = agent_feature_stream(_ctp_question(body), bearer, "ai_ctp_commit")
        return StreamingResponse(
            (json.dumps(ev) + "\n" async for ev in gen),
            media_type="application/x-ndjson")
    data = {"answer": "", "empty": True, "citations": [], "ctp": {}, "cached": False}
    async for ev in _ctp_commit_events(body):
        if ev["type"] == "result":
            data = ev["data"]
    return data


# -------------------------------------------------------------- playbook
@router.post("/playbook")
async def ai_playbook(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    pno = body.get("part_no") or "TC-30412"
    golden = body.get("golden") or "playbook"
    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            return c
    con = connect()
    try:
        p = q1(con, "SELECT * FROM parts WHERE part_no=?", (pno,))
        if not p:
            raise HTTPException(404, f"Part {pno} not found")
        runs = q(con,"""SELECT run_no, qty_planned, qty_good, qty_scrap, status
                         FROM runs WHERE part_id=? ORDER BY completed_at DESC
                         LIMIT 6""", (p["id"],))
        defs = q(con, """SELECT code, COUNT(*) n, SUM(qty) units FROM defects
                         WHERE part_id=? GROUP BY code ORDER BY units DESC""",
                 (p["id"],))
        bom = q(con, """SELECT b.qty_per, b.station, c.part_no, c.name, c.traceable
                        FROM boms b JOIN parts c ON c.id=b.component_part_id
                        WHERE b.parent_part_id=?""", (p["id"],))
        digest = "\n".join([
            f"Part {p['part_no']} {p['name']} ({p['family']}, "
            f"safety critical: {'yes' if p['safety_critical'] else 'no'}).",
            "BOM: " + "; ".join(f"{b['part_no']} x{b['qty_per']} at {b['station']}"
                                + (" [traceable]" if b["traceable"] else "")
                                for b in bom),
            "Run history: " + "; ".join(
                f"{r['run_no']} [{r['status']}] good {r['qty_good']:.0f} scrap "
                f"{r['qty_scrap']:.0f}" for r in runs),
            "Defect history: " + "; ".join(
                f"{dd['code']} ({dd['n']} events, {dd['units']:.0f} units)"
                for dd in defs),
        ])
    finally:
        con.close()
    system = (GROUNDED + "You are the manufacturing engineering assistant "
              "generating a build playbook (standard-work summary) for a "
              "production run of this part. Ground the process steps, torques, "
              "checks and qualifications in the plant's standard work "
              "instructions and procedures (cite them), and use the live BOM "
              "and defect history to add 'watch-outs' - the failure modes past "
              "runs actually hit. Structure: Purpose, Qualifications required, "
              "Materials and lots, Process steps with control points, Quality "
              "gates, Watch-outs from history, Reset/recovery.")
    try:
        d = await kb_ask(f"Generate the build playbook for {pno} {p['name']}.",
                         system, "work", digest, compose=True, top_k=20)
        answer = clean(d.get("answer") or "")
        if d.get("status") in ("no_context", "no_retrieval_data") or not answer.strip():
            raise RuntimeError("no_context")
        return {"answer": answer, "part_no": pno,
                "citations": parse_citations(d.get("retrieval_results")),
                "data_used": {"runs": len(runs), "defect_codes": len(defs),
                              "bom_lines": len(bom)},
                "digest": digest, "latency_ms": d.get("_latency_ms"),
                "cached": False}
    except HTTPException:
        raise
    except Exception:
        c = cached_golden(golden)
        if c:
            return c
        return {"answer": "", "empty": True, "citations": [], "cached": False}


@router.post("/playbook/save")
async def ai_playbook_save(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    con = connect()
    con.execute("""INSERT INTO playbook_templates (title, part_no, body, saved_by,
                   saved_at) VALUES (?,?,?,?,?)""",
                (body.get("title") or f"Playbook - {body.get('part_no')}",
                 body.get("part_no"), body.get("body") or "", user["name"], now()))
    audit_log(con, user["email"], "save", "playbook", body.get("part_no") or "", "")
    con.commit()
    templates = q(con, "SELECT id, title, part_no, saved_by, saved_at "
                       "FROM playbook_templates ORDER BY saved_at DESC")
    con.close()
    return {"ok": True, "templates": templates}


@router.get("/playbook/templates")
def ai_playbook_templates(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, "SELECT * FROM playbook_templates ORDER BY saved_at DESC")
    con.close()
    return rows


# -------------------------------------------------------------- triage
TRIAGE_FIELDS = {
    "category": {"type": "string",
                 "description": "One of: customer_complaint, in_process_defect, "
                                "supplier_material, machine_breakdown, safety, "
                                "logistics"},
    "severity": {"type": "string",
                 "description": "One of: minor, major, critical. Critical only "
                                "for braking function, structural, high-voltage "
                                "safety or a customer escape."},
    "route_to": {"type": "string",
                 "description": "One of: quality, production, maintenance, "
                                "purchasing, logistics, safety"},
    "immediate_action": {"type": "string",
                         "description": "The single first action per the plant's "
                                        "procedures"},
    "summary": {"type": "string", "description": "One sentence restating the issue"},
}
TRIAGE_SCHEMA = {
    "name": "issue_triage",
    "description": "Triage classification of an incoming plant issue report",
    "parameters": {"type": "object", "properties": TRIAGE_FIELDS,
                   "required": list(TRIAGE_FIELDS)},
}


@router.post("/triage")
async def ai_triage(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Empty message")
    golden = body.get("golden") or "triage"
    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            return c
    system = (GROUNDED + "You are the quality intake assistant triaging an "
              "incoming issue against the plant's procedures.")
    try:
        cls_task = kb_ask("Classify this incoming issue report: " + message,
                          system, "quality", schema=TRIAGE_SCHEMA)
        ans_task = kb_ask("What do the plant's procedures require for this "
                          "issue, step by step: " + message, system, "quality")
        cls, ans = await asyncio.gather(cls_task, ans_task)
        answer = clean(ans.get("answer") or "")
        return {"triage": cls.get("answer_json"), "answer": answer,
                "citations": parse_citations(ans.get("retrieval_results")),
                "cached": False}
    except Exception:
        c = cached_golden(golden)
        if c:
            return c
        return {"triage": None, "answer": "", "empty": True, "citations": [],
                "cached": False}


# ------------------------------------------------------ extract document
EXTRACT_FIELDS = {
    "supplier_name": {"type": "string", "description": "Supplier company name"},
    "items": {"type": "array", "description": "Line items",
              "items": {"type": "object", "properties": {
                  "part_no": {"type": "string",
                              "description": "Tallowa part number if stated, "
                                             "else the supplier's item code"},
                  "description": {"type": "string", "description": "Item description"},
                  "qty": {"type": "number", "description": "Quantity"},
                  "unit_price": {"type": "number",
                                 "description": "Unit price, 0 if absent"}},
                  "required": ["part_no", "description", "qty", "unit_price"]}},
    "currency": {"type": "string", "description": "Currency code, AUD if absent"},
    "notes": {"type": "string",
              "description": "Delivery, lot or CoA commitments stated"},
}
EXTRACT_SCHEMA = {
    "name": "po_draft",
    "description": "Structured purchase-order draft from a supplier document",
    "parameters": {"type": "object", "properties": EXTRACT_FIELDS,
                   "required": list(EXTRACT_FIELDS)},
}


@router.post("/extract-document")
async def ai_extract(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Paste the supplier document text")
    golden = body.get("golden") or "extract-document"
    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            return c
    system = (STYLE + "You extract a purchase-order draft from a supplier "
              "document. Extract only what the document states - never invent "
              "an item, price or quantity.")
    try:
        d = await kb_ask("Extract the purchase order draft from this supplier "
                         "document:\n" + text[:3500], system, "supplier",
                         schema=EXTRACT_SCHEMA)
        draft = d.get("answer_json")
        if not draft:
            raise RuntimeError("no extraction")
        con = connect()
        for item in draft.get("items", []):
            p = q1(con, "SELECT part_no, name, std_cost FROM parts WHERE part_no=?",
                   (item.get("part_no") or "",))
            item["matched_part"] = bool(p)
            if p:
                item["catalogue_name"] = p["name"]
        sup = q1(con, "SELECT code, name FROM suppliers WHERE name LIKE ?",
                 (f"%{(draft.get('supplier_name') or 'zzz').split()[0]}%",))
        con.close()
        draft["matched_supplier"] = sup
        return {"draft": draft, "cached": False}
    except Exception:
        c = cached_golden(golden)
        if c:
            return c
        return {"draft": None, "empty": True, "cached": False}


# ==================================================================
# Ops Assistant - the live retrieval agent over the ERP, driven by the
# platform's own MCP surface. Plans with the model over the same tool
# catalogue an external MCP client sees (auto-generated from the OpenAPI
# doc by mcp.py), executes each step via the MCP dispatch - in-process,
# back through the REST layer, carrying the caller's own bearer so RBAC
# applies to the agent exactly as to a human - streams every step, then
# composes a grounded answer.
# ==================================================================
def _mcp():
    import mcp   # deferred import: mcp.mount(app) runs after this module loads
    return mcp


_ROUTE_CACHE: dict[str, str] | None = None


def _mcp_route(tool: str) -> str:
    """method + path of the REST route an MCP tool actually dispatches to -
    the concrete "MCP endpoint hit" a technical reviewer asked to see,
    distinct from the single public /mcp JSON-RPC frame every call rides
    on. Blank for a name the catalogue doesn't recognise (never fatal)."""
    global _ROUTE_CACHE
    if _ROUTE_CACHE is None:
        _ROUTE_CACHE = {t["name"]: f'{t["method"]} {t["path"]}'
                        for t in _mcp().catalog()}
    return _ROUTE_CACHE.get(tool, "")


DOC_SEARCH_TOOL = ("document_search",
                   "Search the plant's controlled documents (procedures, "
                   "standard work, safety). args: {query}")


# =====================================================================
# ARAG Retrieval Agent - the Ops Assistant's real orchestrator (GM
# directive, 21 Jul 2026: "all use cases must use arag, not directly use
# mcp"). ARAG plans and calls this app's own /mcp as its tool source -
# this module no longer runs the planning loop itself; it only proxies
# the agent's own NDJSON trace, forwarding the caller's JWT so the
# agent's tool calls carry the same RBAC a human would have.
#
# Agent config lives on the data-platform host, a different host to the
# KB (HOST/KB above) - the agent IS a mode:"agent" Knowledge Box, so its
# id doubles as the agent id.
# =====================================================================
AGENT_KEY = ENV.get("ARAG_AGENT_KEY", "")
AGENT_HOST = ENV.get("ARAG_AGENT_BASE_URL", "")
AGENT_ID = ENV.get("ARAG_AGENT_KB_ID", "")

# How long we wait for the live agent before giving up and falling back to
# a cached golden - short enough that a demo never dead-airs on the known
# hard question (which can run past 300s server-side), long enough that the
# confirmed-working simple/moderate questions (~30s) complete live.
AGENT_TIMEOUT_S = float(ENV.get("ARAG_AGENT_TIMEOUT_S", "55"))
HEARTBEAT_S = 3.0

_UUID_SUFFIX = re.compile(
    r"__[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _tool_name(raw: str) -> str:
    """Strip ARAG's Smart-agent '__<registered-agent-uuid>' tool-name suffix."""
    return _UUID_SUFFIX.sub("", raw or "")


# A "context" event's chunk_id looks like "mcp_<registered-agent-uuid>_<tool>",
# e.g. "mcp_2f527fa6-4f88-4260-bd2f-865701d23619_invoices_list_invoices".
_CHUNK_TOOL_RE = re.compile(
    r"^mcp_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}_(.+)$")


def _rows_from_context(ctx: dict) -> list[dict]:
    """Pull the real structured tool-response rows out of an ARAG 'context'
    event's chunks. Each chunk's `text` is a JSON-encoded STRING of exactly
    what our own /mcp tool returned - the real database rows, untouched by
    any LLM narration (found by dumping the raw stream, 22 Jul 2026 - see
    RICH-ANSWER-INVESTIGATION.md). Returns one {tool, rows} dict per chunk
    that parsed as a non-empty array of (non-empty) objects; narrative/doc
    chunks and empty/placeholder samples are silently skipped."""
    out = []
    for chunk in (ctx or {}).get("chunks") or []:
        text = chunk.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            continue
        if not (isinstance(parsed, list) and parsed
                and all(isinstance(r, dict) and r for r in parsed)):
            continue
        m = _CHUNK_TOOL_RE.match(chunk.get("chunk_id") or "")
        tool = _tool_name(m.group(1) if m else (chunk.get("chunk_id") or ""))
        out.append({"tool": tool, "rows": parsed})
    return out


def _tool_json_from_context(ctx: dict, want_tool: str):
    """Like _rows_from_context, but for a composite ai_* tool whose response
    is a single JSON OBJECT (answer/citations/data_used/...), not a list of
    rows - _rows_from_context skips those on purpose. Returns the tool's
    exact response dict, untouched by the agent's own narration, or None if
    that tool was never called (or didn't return valid JSON)."""
    for chunk in (ctx or {}).get("chunks") or []:
        text = chunk.get("text")
        if not isinstance(text, str):
            continue
        m = _CHUNK_TOOL_RE.match(chunk.get("chunk_id") or "")
        tool = _tool_name(m.group(1) if m else (chunk.get("chunk_id") or ""))
        if tool != want_tool:
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# tool name -> plain-English narration for the live step trace. Anything not
# listed falls through to _humanise()'s generic verb+resource guess.
TOOL_LABELS = {
    "trace_list_forward": "Tracing the lot forward to finished lots and shipments",
    "trace_list_backward": "Tracing the lot backward to source materials",
    "shipments_list_shipments": "Checking customer shipments",
    "customers_list_customers": "Looking up customers",
    "customers_get_customers": "Looking up the customer record",
    "lots_list_lots": "Pulling part-lot records",
    "holds_list_holds": "Reviewing quality holds",
    "holds_create_holds": "Placing a quality hold",
    "holds_release": "Releasing a quality hold",
    "defects_list_defects": "Reviewing defects",
    "defects_list_pareto": "Running the defect Pareto",
    "invoices_list_invoices": "Checking invoices",
    "invoices_get_invoices": "Checking the invoice",
    "invoices_status": "Updating the invoice status",
    "ap_invoices_list_ap_invoices": "Checking AP invoices",
    "ap_invoices_get_ap_invoices": "Checking the AP invoice",
    "ap_invoices_similar": "Finding similar AP exceptions",
    "ap_invoices_create_batch_fix": "Preparing the batch fix",
    "runs_list_runs": "Checking production runs",
    "runs_get_runs": "Checking the production run",
    "sales_orders_list_sales_orders": "Checking sales orders",
    "sales_orders_get_sales_orders": "Checking the sales order",
    "purchase_orders_list_purchase_orders": "Checking purchase orders",
    "purchase_orders_get_purchase_orders": "Checking the purchase order",
    "machines_list_machines": "Checking machines",
    "tooling_list_tooling": "Checking tooling",
    "inventory_list_low_stock": "Checking stock levels",
    "inventory_list_movements": "Checking stock movements",
    "operators_list_operators": "Checking people & certifications",
    "suppliers_list_suppliers": "Checking suppliers",
    "suppliers_get_suppliers": "Checking the supplier record",
    "parts_list_parts": "Checking parts",
    "parts_get_parts": "Checking the part record",
    "reports_list_ship_date_performance": "Checking on-time delivery",
    "reports_list_customer_ppm": "Checking customer PPM",
    "reports_list_scrap": "Checking scrap",
    "reports_list_throughput": "Checking throughput",
    "reports_list_margin": "Checking margin",
    "reports_list_utilisation": "Checking utilisation",
    "expedite_requests_list_expedite_requests": "Checking expedite requests",
    "expedite_requests_create_expedite_requests": "Proposing an expedite request",
    "recurring_list_recurring": "Checking release schedules",
    "audit_list_audit": "Checking the audit trail",
    "ai_lot_trace": "Running the lot-traceability analysis",
    "ai_8d_draft": "Drafting the 8D report",
    "ai_ctp_commit": "Checking capable-to-promise",
    "ai_fpy_root_cause": "Analysing the FPY root cause",
    "ai_fault_root_cause": "Analysing the fault root cause",
    "ai_ap_error_explain": "Explaining the AP exception",
    "ai_ap_batch_fix": "Preparing the AP batch fix",
    "ai_briefing": "Preparing the daily briefing",
    "ai_dispatch_actions": "Ranking dispatch actions",
    "document_search": "Reading plant documents",
}

# The three curated MCP prompts (reasoning playbooks, not tool calls) the
# Smart agent can fetch directly - see mcp.py's PROMPTS.
PROMPT_LABELS = {
    "triage-production-run": "Pulling the production-run triage playbook",
    "draft-sales-order-from-history": "Pulling the sales-order drafting playbook",
    "daily-operations-briefing": "Pulling the daily operations briefing",
}

# Grounding-relevance gate (QA finding #4 fix, 2nd pass): a tool succeeding
# is not the same as the question being answered. Pure catalogue/roster
# tools - list-the-set-of-entities calls with no operational content
# (lines_list_lines was the exact failure QA reproduced 3/3 times: it lists
# line codes/names only, no run/hold/status data, but its success alone was
# enough to pass the earlier "did anything succeed" gate) - do not count
# toward "we retrieved real grounding data" on their own. Kept deliberately
# small/conservative: genuinely record-bearing catalogue tools that ARE a
# complete, correct answer to their own question (customers_list_customers
# for "list our customers", parts_list_parts, suppliers_list_suppliers,
# etc.) are NOT excluded - only internal/structural, content-free ones are.
_NON_SUBSTANTIVE_TOOLS = {
    "lines_list_lines", "lines_get_lines", "skills_list_skills",
    "settings_list_settings", "settings_update_settings",
    "notifications_list_notifications", "notifications_read",
    "notifications_create_read_all", "access_tokens_list_access_tokens",
    "access_tokens_create_access_tokens", "attachments_list_attachments",
    "auth_list_me", "auth_create_logout",
}

# Tools that would actually reveal a stoppage/hold/defect if one existed -
# the belt-and-suspenders check below refuses to let a NEGATIVE operational
# claim ("no stoppage", "running normally") through unless one of these
# specifically succeeded. A generic success elsewhere (e.g. runs_list_runs)
# does not license asserting the absence of a problem you never checked for.
_STATUS_VERIFYING_TOOLS = {
    "holds_list_holds", "holds_create_holds", "holds_release",
    "defects_list_defects", "defects_list_pareto", "defects_create_defects",
    "runs_status", "runs_get_runs", "ai_fault_root_cause", "ai_fpy_root_cause",
    "ai_8d_draft", "ai_ctp_commit", "ai_ap_error_explain", "ai_ap_batch_fix",
}

# Phrases that assert an all-clear / absence-of-problem operational status -
# the dangerous direction to be confidently wrong in. Deliberately narrow
# (plain-English patterns actually seen, not a general negation parser).
_NEGATIVE_CLAIM_RE = re.compile(
    r"\bno (stoppage|reported|issues?|problems?|blockers?|holds?)\b"
    r"|\brunning (without|with no|normally|as scheduled)\b"
    r"|\bnothing (is )?holding\b"
    r"|\b(no|not) (currently )?(blocked|held|on hold|stopped)\b",
    re.I)

_VERB_LABELS = {"list": "Checking", "get": "Checking", "create": "Creating",
                "update": "Updating", "status": "Updating", "approve": "Approving",
                "reject": "Rejecting", "complete": "Completing", "receive": "Receiving",
                "release": "Releasing", "similar": "Comparing"}


def _humanise(tool: str) -> str:
    if tool in TOOL_LABELS:
        return TOOL_LABELS[tool]
    m = re.match(r"^([a-z_]+?)_(list|get|create|update|status|approve|reject"
                 r"|complete|receive|release|similar)(_.*)?$", tool)
    if m:
        resource, verb = m.group(1), m.group(2)
        return f"{_VERB_LABELS.get(verb, 'Checking')} {resource.replace('_', ' ')}"
    return "Querying " + tool.replace("ai_", "").replace("_", " ")


def _parse_call_args(value: str) -> tuple[str, str]:
    """'Tool calls: name__uuid(lot='WF-2261')' -> ('name', 'lot = WF-2261')."""
    m = re.search(r"Tool calls?:\s*([A-Za-z0-9_]+(?:__[0-9a-fA-F-]{36})?)\s*"
                  r"\((.*)\)\s*$", value or "", re.S)
    if not m:
        return "", ""
    name = _tool_name(m.group(1))
    argstr = (m.group(2) or "").strip()
    if not argstr or argstr in ("{}", "None"):
        return name, ""
    # Accept both call-style (lot='WF-2261') and Python dict-repr style
    # ('lot': 'WF-2261') - ARAG's trace uses either depending on the step.
    pairs = re.findall(r"['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*[=:]\s*"
                       r"('[^']*'|\"[^\"]*\"|\{[^{}]*\}|[^,{}\[\]]+)", argstr)
    if not pairs:
        return name, argstr[:80]   # unrecognised shape - show it raw rather than hide it
    parts = [f"{k.replace('_', ' ')} = {v.strip().strip(chr(39)+chr(34))}"
             for k, v in pairs[:4] if v.strip() not in ("", "{}", "None", "null")]
    return name, ", ".join(parts)   # all-trivial args (e.g. {'query': {}}) -> ""


# Sentinel/uninformative step values that should never be shown to a user as
# if they were a meaningful result - matched case-insensitively, whole value.
_UNINFORMATIVE_DETAIL = {"no tool used", "none", "null", "", "{}"}


def _friendly_fail_detail(tool: str) -> str:
    """A failed tool step NEVER shows the raw FastAPI/pydantic error payload
    (internal field names, HTTP status codes) - just a plain-English note."""
    return "Couldn't complete this lookup - " + _humanise(tool).lower() + " didn't return usable data."


def _clean_detail(value_s: str) -> str:
    return "" if value_s.strip().lower() in _UNINFORMATIVE_DETAIL else value_s


def _map_arag_event(d: dict, state: dict) -> list[dict]:
    """One raw ARAG NDJSON line -> zero or more typed progress events."""
    out = []
    ctx = d.get("context")
    if ctx:
        for group in _rows_from_context(ctx):
            out.append({"type": "rows", "tool": group["tool"],
                       "label": _humanise(group["tool"]), "rows": group["rows"]})
    step = d.get("step") or {}
    module, title = step.get("module"), step.get("title") or ""
    value, error = step.get("value"), step.get("error")

    if module == "smart" and "Reactive iteration" in title:
        name, argstr = _parse_call_args(value if isinstance(value, str) else "")
        if name and name != "task_complete":
            if state.get("iteration", 0) == 0:
                out.append({"type": "plan",
                            "label": "Planning the lookups over the live ERP"})
            state["iteration"] = state.get("iteration", 0) + 1
            state["pending_tool"] = {"name": name, "args": argstr,
                                     "t0": time.monotonic()}
            out.append({"type": "tool_call", "label": _humanise(name),
                       "detail": argstr, "tool": name,
                       "mcp_kind": "tool", "mcp_route": _mcp_route(name)})
        elif name == "task_complete":
            out.append({"type": "composing",
                        "label": "Reasoning complete - composing the answer"})
    elif module == "mcp":
        pending = state.pop("pending_tool", None)
        dur_ms = int((time.monotonic() - pending["t0"]) * 1000) if pending else None
        value_s = value if isinstance(value, str) else ""
        # The Smart agent can also fetch a curated MCP *prompt* (a reasoning
        # playbook, not a tool call) - no "Tool calls: ..." line precedes it,
        # so there is never a pending_tool for these; give them their own
        # friendly label instead of falling through to the raw agent_path.
        prompt_m = re.search(r"Fetched MCP prompt '([\w-]+)'", value_s)
        # Some tool invocations announce themselves in the MCP step's OWN
        # value ("Used tool: X with arguments: Y") rather than via a
        # preceding "Tool calls: ..." planning line - this is the more
        # common shape in practice, so it takes priority over `pending`.
        used_m = re.search(r"Used tool:\s*(\S+)\s+with arguments:\s*(.*)$",
                          value_s, re.S)
        if prompt_m:
            label = PROMPT_LABELS.get(prompt_m.group(1),
                                      "Pulling the " + prompt_m.group(1).replace("-", " "))
            out.append({"type": "tool_result", "ok": True, "tool": prompt_m.group(1),
                       "label": label, "duration_ms": dur_ms,
                       "mcp_kind": "prompt", "mcp_route": "prompts/get"})
        elif used_m:
            tool = _tool_name(used_m.group(1))
            argstr = used_m.group(2).strip()
            if argstr and argstr not in ("{}", "None"):
                _, argstr = _parse_call_args(f"Tool calls: x({argstr})")
            else:
                argstr = ""
            out.append({"type": "tool_result", "ok": not error, "tool": tool,
                       "label": f"{_humanise(tool)} - "
                                + ("no result" if error else "data retrieved"),
                       # NEVER the raw error payload - a failed call gets a
                       # plain-English note, never internal field/HTTP text.
                       "detail": _friendly_fail_detail(tool) if error else argstr,
                       "duration_ms": dur_ms,
                       "non_substantive": (not error) and tool in _NON_SUBSTANTIVE_TOOLS,
                       "mcp_kind": "tool", "mcp_route": _mcp_route(tool)})
        else:
            tool = (pending or {}).get("name") or _tool_name(step.get("agent_path") or "")
            if error:
                out.append({"type": "tool_result", "ok": False, "tool": tool,
                           "label": f"{_humanise(tool)} - no result",
                           "detail": _friendly_fail_detail(tool),
                           "duration_ms": dur_ms,
                           "mcp_kind": "tool", "mcp_route": _mcp_route(tool)})
            else:
                out.append({"type": "tool_result", "ok": True, "tool": tool,
                           "label": f"{_humanise(tool)} - data retrieved",
                           "detail": _clean_detail(value_s), "duration_ms": dur_ms,
                           "non_substantive": tool in _NON_SUBSTANTIVE_TOOLS,
                           "mcp_kind": "tool", "mcp_route": _mcp_route(tool)})
    elif module == "ask":
        out.append({"type": "doc_search", "label": "Reading plant documents",
                   "detail": value if isinstance(value, str) else ""})
    elif "Reactive mode completed" in title:
        out.append({"type": "composing", "label": "Reasoning complete"})
    elif "Context validation" in title:
        out.append({"type": "composing", "label": "Double-checking the data"})
    elif module == "summarize":
        out.append({"type": "composing", "label": "Composing the grounded answer"})

    ans = d.get("answer")
    if isinstance(ans, str) and ans and ans not in ("Error in generation",
                                                     "Error in context"):
        out.append({"type": "answer", "text": clean(ans)})
    return out


async def _arag_raw_events(question: str, bearer: str | None,
                          queue: "asyncio.Queue"):
    """Background reader: streams ARAG's NDJSON into the queue untouched by
    our own heartbeat/timeout logic, so a slow read never corrupts the
    connection (cancelling a bare aiter_lines() mid-read is not safe)."""
    body = {
        "question": question,
        "headers": {"authorization": f"Bearer {bearer}"} if bearer else {},
        "arguments": {}, "operation": 0,
    }
    headers = {"Authorization": f"Bearer {AGENT_KEY}",
              "Content-Type": "application/json",
              "Accept": "text/event-stream"}
    url = f"{AGENT_HOST}/api/v1/agent/{AGENT_ID}/session/ephemeral"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None)) as cx:
            async with cx.stream("POST", url, headers=headers, json=body) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    await queue.put(("event", d))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await queue.put(("error", str(e)))
    finally:
        await queue.put(("done", None))


async def arag_agent_events(question: str, bearer: str | None, on_context=None):
    """Yields typed progress events: start, plan, tool_call, tool_result,
    doc_search, composing, answer, error - proxied live from the ARAG
    Retrieval Agent's own NDJSON trace, forwarding the caller's bearer so
    the agent's /mcp tool calls carry the same RBAC as the human user.
    on_context(ctx), if given, is called with each raw 'context' payload as
    it arrives - lets a caller recover a specific tool's exact JSON
    response (see _tool_json_from_context) without this function needing
    to know anything about which tool that caller cares about."""
    t0 = time.monotonic()
    yield {"type": "start", "question": question}
    if not (AGENT_KEY and AGENT_HOST and AGENT_ID):
        yield {"type": "error", "stage": "config",
               "message": "The retrieval agent is not configured."}
        return

    queue: "asyncio.Queue" = asyncio.Queue()
    task = asyncio.create_task(_arag_raw_events(question, bearer, queue))
    state: dict = {}
    got_answer = False
    # Safety net against a false-confident answer (QA finding #4, 2 passes):
    # count genuine, SUBSTANTIVE successful retrievals (a tool_result with
    # ok:true whose tool isn't a bare catalogue/roster call, or a doc_search
    # hit) as the interaction runs, and separately note whether a tool that
    # would actually reveal a stoppage/hold/defect succeeded. If the agent
    # reaches a final answer having retrieved nothing substantive, OR it
    # asserts a confident all-clear/negative operational status without ever
    # having successfully checked holds/defects/status for it, that answer
    # is not trustworthy - refuse it and let the route's existing
    # error-triggered fallback (cached golden, or an honest message) take
    # over instead, exactly as it already does for a timeout.
    success_count = 0
    status_verified = False
    try:
        while True:
            elapsed = time.monotonic() - t0
            if elapsed > AGENT_TIMEOUT_S and not got_answer:
                yield {"type": "error", "stage": "timeout",
                       "message": "The retrieval agent is taking longer than "
                                  "expected.",
                       "elapsed_ms": int(elapsed * 1000)}
                task.cancel()
                return
            try:
                kind, payload = await asyncio.wait_for(queue.get(),
                                                       timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "elapsed_ms": int(elapsed * 1000)}
                continue
            if kind == "done":
                if not got_answer:
                    yield {"type": "error", "stage": "no_answer",
                           "message": "The retrieval agent finished without a "
                                      "grounded answer.",
                           "elapsed_ms": int(elapsed * 1000)}
                return
            if kind == "error":
                yield {"type": "error", "stage": "transport",
                       "message": "Could not reach the retrieval agent."}
                return
            if on_context and payload.get("context"):
                on_context(payload["context"])
            for ev in _map_arag_event(payload, state):
                et = ev.get("type")
                if et == "tool_result" and ev.get("ok"):
                    if ev.get("tool") not in _NON_SUBSTANTIVE_TOOLS:
                        success_count += 1
                    if ev.get("tool") in _STATUS_VERIFYING_TOOLS:
                        status_verified = True
                elif et == "doc_search":
                    success_count += 1
                if et == "answer":
                    if success_count == 0:
                        yield {"type": "error", "stage": "no_grounded_data",
                               "message": "The retrieval agent could not "
                                          "retrieve any live data for this "
                                          "question.",
                               "elapsed_ms": int((time.monotonic() - t0) * 1000)}
                        return
                    if (not status_verified
                            and _NEGATIVE_CLAIM_RE.search(ev.get("text") or "")):
                        # Never assert an all-clear ("no stoppage", "running
                        # normally") when nothing that would actually surface
                        # a hold/defect/stoppage was successfully checked -
                        # the exact false-confident-answer pattern QA
                        # reproduced 3/3 times on the line-A1 question.
                        yield {"type": "error", "stage": "unverified_negative",
                               "message": "The retrieval agent could not "
                                          "verify that status against live "
                                          "hold/defect data.",
                               "elapsed_ms": int((time.monotonic() - t0) * 1000)}
                        return
                    got_answer = True
                ev.setdefault("elapsed_ms", int((time.monotonic() - t0) * 1000))
                yield ev
    finally:
        if not task.done():
            task.cancel()


# =====================================================================
# Agent-routed use-case features (GM directive, 21 Jul 2026: "all use
# cases must use arag, not directly use mcp"). The three SE quick-launch
# flows' hero calls (quality/8D, AP auto-fix, CTP) run through the SAME
# live ARAG Retrieval Agent as the Ops Assistant, not a homegrown
# digest-then-raw-LLM-call - the agent plans and calls this app's own
# /mcp, including the composite ai_* tool that does the real deterministic
# work (dig_* + kb_ask/predict_gen, still real, still live) for that use
# case. That tool's exact JSON response is recovered verbatim from the
# agent's own tool-call context (never re-parsed from the agent's prose)
# so the UI still gets the same precise structured fields (data_used,
# ctp, fields, citations...) a direct buffered call would have returned -
# only now genuinely agent-driven, with the agent's real trace on screen.
# =====================================================================
async def agent_feature_stream(question: str, bearer: str | None,
                               want_tool: str):
    """Forwards the real ARAG Retrieval Agent's own NDJSON trace verbatim
    (so the UI shows exactly what the agent is doing - which MCP tool,
    which route, how long it took), then emits one final `result` event
    once the agent answers: the captured exact JSON response from
    `want_tool` if it called it, else a plain prose fallback (still a
    live, honest answer - just without that tool's precise structured
    fields). Never falls back to a cached answer, on a timeout or any
    other failure - GM directive: "nothing cached, must take the time it
    takes." A failure is shown honestly, exactly as arag_agent_events
    reports it, not papered over."""
    captured = {}

    def on_context(ctx):
        data = _tool_json_from_context(ctx, want_tool)
        if data is not None:
            captured["data"] = data

    got_result = False
    async for ev in arag_agent_events(question, bearer, on_context=on_context):
        if ev.get("type") == "answer":
            data = captured.get("data")
            if data is None:
                data = {"answer": ev.get("text") or "", "citations": [],
                        "data_used": {}, "cached": False}
            got_result = True
            yield {"type": "result", "data": data}
        else:
            yield ev
    if not got_result:
        yield {"type": "error",
               "message": "The retrieval agent could not answer this."}
    yield {"type": "done"}


def _fpy_question(body: dict) -> str:
    line = body.get("line") or "A-2"
    return (f"Line {line} had an overnight First Pass Yield (FPY) alert. "
            f"Call the ai_fpy_root_cause tool with body "
            f"{json.dumps({'line': line})} and present the ranked, "
            "correlated root-cause suspects it returns, with their "
            "confidence levels.")


def _ap_explain_question(body: dict) -> str:
    ap_no = body.get("ap_no") or ""
    return (f"AP invoice {ap_no} failed to post. Call the "
            f"ai_ap_error_explain tool with body "
            f"{json.dumps({'ap_no': ap_no})} and explain the failure in "
            "plain English: why it failed, the exact fix, and who is "
            "authorised to apply it.")


def _ap_batch_question(body: dict) -> str:
    ap_no = body.get("ap_no") or ""
    return (f"Are there other AP invoices sharing the same root cause as "
            f"{ap_no}? Call the ai_ap_batch_fix tool with body "
            f"{json.dumps({'ap_no': ap_no})} and propose the batch "
            "correction it finds, including whether it is within the AP "
            "clerk's approval authority.")


def _8d_question(body: dict) -> str:
    line = body.get("line") or "A-2"
    return (f"Draft the 8D containment report for the overnight FPY "
            f"breach on line {line}. Call the ai_8d_draft tool with body "
            f"{json.dumps({'line': line})} and present the drafted "
            "report exactly as it comes back, in full.")


def _ctp_question(body: dict) -> str:
    payload = {"part_no": body.get("part_no") or "TC-70210",
               "qty": float(body.get("qty") or 250),
               "customer_code": body.get("customer_code") or "MAR"}
    if body.get("requested_date"):
        payload["requested_date"] = body["requested_date"]
    if body.get("expedite"):
        payload["expedite"] = True
    return ("Check capable-to-promise for this order. Call the "
            f"ai_ctp_commit tool with body {json.dumps(payload)} and "
            "present its commit date, verdict, binding constraint and "
            "alternatives exactly as it comes back.")


# feature name (as sent by the UI's `golden`/route) -> (MCP tool name,
# question builder). Only the registry ("F") features actually reached
# from the three quick-launch pages route through the live agent this
# way; every other /api/ai/<feature> route keeps its existing buffered
# (deterministic digest + kb_ask/predict_gen) behaviour - unchanged, and
# still used as the composite tool's OWN implementation above.
AGENT_ROUTED_FEATURES = {
    "fpy-root-cause": ("ai_fpy_root_cause", _fpy_question),
    "ap-error-explain": ("ai_ap_error_explain", _ap_explain_question),
    "ap-batch-fix": ("ai_ap_batch_fix", _ap_batch_question),
}


def _adapt_legacy_golden_events(events: list[dict]) -> list[dict]:
    """Cached goldens captured before this change used the homegrown
    planner's event shape (plan/step/docs/answer/done). Convert them to the
    live schema so the frontend only ever has to understand one vocabulary.
    Already-new-shaped events (tool_call/tool_result/composing/...) pass
    through untouched."""
    out = []
    for ev in events:
        t = ev.get("type")
        if t == "plan" and "steps" in ev:
            names = ", ".join(_humanise(s["tool"]) for s in ev.get("steps", []))
            out.append({"type": "plan", "label": "Planning the lookups",
                       "detail": names})
            for s in ev.get("steps", []):
                out.append({"type": "tool_call", "tool": s["tool"],
                           "label": _humanise(s["tool"]),
                           "detail": ", ".join(f"{k} = {v}" for k, v in
                                               (s.get("args") or {}).items()),
                           "mcp_kind": "tool", "mcp_route": _mcp_route(s["tool"])})
        elif t == "step" and "tool" in ev:
            out.append({"type": "tool_result", "ok": True, "tool": ev["tool"],
                       "label": f"{_humanise(ev['tool'])} - "
                                f"{ev.get('rows', 0)} row(s) found",
                       "non_substantive": ev["tool"] in _NON_SUBSTANTIVE_TOOLS,
                       "mcp_kind": "tool", "mcp_route": _mcp_route(ev["tool"])})
            sample = ev.get("sample")
            # The old homegrown planner's cached goldens already carry real
            # row samples (up to 6) - reuse them for the rich table so the
            # fallback path gets the same structured view as a live run, not
            # just prose. Skip placeholder/empty samples (e.g. [{}]).
            if isinstance(sample, list) and sample and all(
                    isinstance(r, dict) and r for r in sample):
                out.append({"type": "rows", "tool": ev["tool"],
                           "label": _humanise(ev["tool"]), "rows": sample})
        elif t == "docs":
            titles = ", ".join(h.get("title", "") for h in ev.get("hits", []))
            out.append({"type": "doc_search", "label": "Reading plant documents",
                       "detail": titles})
        elif t == "answer":
            g = ev.get("grounding") or {}
            # Humanise the tool list here too - this is the ONLY grounding
            # footer that ever shows raw tool names if left unfixed, since
            # the live answer path (_map_arag_event) never attaches a
            # "tools" list at all.
            out.append({"type": "answer", "text": ev.get("text", ""),
                       "tools": [_humanise(t2) for t2 in (g.get("tools") or [])],
                       "documents": g.get("documents")})
        elif t == "done":
            out.append({"type": "done", "latency_ms": ev.get("latency_ms")})
        else:
            out.append(ev)   # already new-shape (or start/error) - pass through
    return out


async def agent_plan(question: str) -> list[dict]:
    tools = _mcp().read_tools() + [DOC_SEARCH_TOOL]
    names = {n for n, _ in tools}
    tool_desc = "\n".join(f"- {n}: {d}" for n, d in tools)
    instruction = (
        "You plan data lookups for a question about a parts plant. The "
        "available query tools are the plant platform's own MCP tools:\n"
        + tool_desc + "\n\nReturn ONLY a JSON array of 1 to 4 steps, e.g. "
        '[{"tool": "runs_list_runs", "args": {"status": "quality_hold"}, '
        '"why": "find held runs"}]. args are the tool\'s path and query '
        "parameters as a flat object. Choose the fewest tools that answer "
        "the question. Question: ")
    raw = await predict_gen(instruction, question)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        raise RuntimeError("no plan")
    steps = json.loads(m.group(0))
    out = []
    for s in steps[:4]:
        if isinstance(s, dict) and s.get("tool") in names:
            out.append({"tool": s["tool"], "args": s.get("args") or {},
                        "why": s.get("why") or ""})
    if not out:
        raise RuntimeError("empty plan")
    return out


def fallback_plan(question: str) -> list[dict]:
    ql = question.lower()
    steps = []
    lot = re.search(r"\b((?:WF|CS|MC|LK|CJ|KP|TB|RCV|TC-[ASMH])-?\d+)\b",
                    question, re.I)
    if lot:
        steps.append({"tool": "trace_list_forward",
                      "args": {"lot": lot.group(1).upper()},
                      "why": "trace the named lot"})
    run = re.search(r"\bRUN-\d+\b", question, re.I)
    if run:
        steps.append({"tool": "runs_get_runs",
                      "args": {"run_no": run.group(0).upper()},
                      "why": "inspect the named run"})
    if any(w in ql for w in ("hold", "quarantine", "containment", "recall")):
        steps.append({"tool": "holds_list_holds", "args": {}, "why": "list holds"})
    if any(w in ql for w in ("defect", "fault", "ppm", "complaint")):
        steps.append({"tool": "defects_list_defects", "args": {},
                      "why": "list defects"})
    if any(w in ql for w in ("stock", "reorder", "material", "shortage")):
        steps.append({"tool": "inventory_list_low_stock", "args": {},
                      "why": "stock position"})
    if any(w in ql for w in ("order", "promise", "ship date", "due", "customer")):
        steps.append({"tool": "sales_orders_list_sales_orders", "args": {},
                      "why": "open orders"})
    if any(w in ql for w in ("invoice", "overdue", "payment")):
        steps.append({"tool": "invoices_list_invoices", "args": {},
                      "why": "invoice position"})
    if any(w in ql for w in ("machine", "calibration", "service", "maintenance")):
        steps.append({"tool": "machines_list_machines", "args": {},
                      "why": "machine position"})
    if any(w in ql for w in ("run", "line", "production", "schedule")) and not run:
        steps.append({"tool": "runs_list_runs", "args": {}, "why": "open runs"})
    if not steps:
        steps = [{"tool": "runs_list_runs", "args": {}, "why": "plant state"},
                 {"tool": "holds_list_holds", "args": {}, "why": "holds"}]
    return steps[:4]


async def kb_snippets(query: str) -> list[dict]:
    payload = {"query": query, "features": ["keyword", "semantic"], "top_k": 6,
               "resource_filters": scope_rids("all")}
    async with httpx.AsyncClient(timeout=45) as cx:
        r = await cx.post(f"{HOST}/api/v1/kb/{KB}/find", headers=HDRS, json=payload)
    if r.status_code != 200:
        return []
    hits = []
    for rid, res in (r.json().get("resources") or {}).items():
        for fid, field in (res.get("fields") or {}).items():
            for pid, para in (field.get("paragraphs") or {}).items():
                hits.append({"file": RID_TO_FILE.get(rid, ""),
                             "title": res.get("title"),
                             "score": para.get("score"),
                             "snippet": (para.get("text") or "")[:300]})
    hits.sort(key=lambda h: -(h["score"] or 0))
    seen, out = set(), []
    for h in hits:
        if h["file"] not in seen:
            seen.add(h["file"])
            out.append(h)
    return out[:4]


def compact_val(v):
    """Render a field for the agent digest without mid-truncating nested
    lists of records (e.g. a trace's finished_lots/shipments) - each nested
    record gets its own short summary instead of one blind string cut."""
    if isinstance(v, list):
        if not v:
            return "none"
        if isinstance(v[0], dict):
            return " | ".join(
                ", ".join(f"{k}={str(vv)[:70]}" for k, vv in item.items()
                          if vv not in (None, ""))
                for item in v[:10])
        return ", ".join(str(x)[:60] for x in v[:10])
    if isinstance(v, dict):
        return ", ".join(f"{k}={str(vv)[:70]}" for k, vv in v.items()
                         if vv not in (None, ""))
    return str(v)[:200]


def compact(rows: list, limit=12) -> str:
    out = []
    for r in rows[:limit]:
        if not isinstance(r, dict):
            out.append(str(r)[:200])
            continue
        out.append("\n".join(f"{k}: {compact_val(v)}" for k, v in r.items()
                             if v not in (None, "", [])))
    return "\n".join(out) if out else "(no rows)"


async def agent_events(question: str, user_name: str, bearer: str | None):
    """Yields NDJSON events: plan, step, docs, answer, done / error."""
    t0 = time.monotonic()
    yield {"type": "start", "question": question}
    try:
        steps = await agent_plan(question)
        planned_by = "model"
    except Exception:
        steps = fallback_plan(question)
        planned_by = "heuristic"
    yield {"type": "plan", "steps": [{"tool": s["tool"], "args": s["args"],
                                      "why": s["why"]} for s in steps],
           "planned_by": planned_by, "transport": "mcp"}
    gathered = []
    for s in steps:
        if s["tool"] == "document_search":
            continue
        res = await _mcp().call_tool_flat(s["tool"], s["args"], bearer)
        text = (res.get("content") or [{}])[0].get("text") or ""
        if res.get("isError"):
            rows = [{"error": text[:200]}]
        else:
            try:
                data = json.loads(text)
            except Exception:
                data = {"raw": text[:400]}
            rows = data if isinstance(data, list) else [data]
        gathered.append((s["tool"], s["args"], rows))
        yield {"type": "step", "surface": "mcp", "tool": s["tool"],
               "args": s["args"], "rows": len(rows), "sample": rows[:6]}
    docs = []
    try:
        docs = await kb_snippets(question)
    except Exception:
        docs = []
    if docs:
        yield {"type": "docs", "hits": docs}
    digest = "\n\n".join(
        f"[{tool} {json.dumps(args)}]\n{compact(rows)}"
        for tool, args, rows in gathered)
    if docs:
        digest += "\n\n[plant documents]\n" + "\n".join(
            f"{d['title']}: {d['snippet']}" for d in docs)
    instruction = (ANALYST + "Answer the question for " + user_name
                   + " using ONLY the query results and document extracts below. "
                     "Name the records (run, lot, order, invoice numbers) you "
                     "relied on. If the data does not answer it, say what is "
                     "missing.")
    try:
        answer = clean(await predict_gen(
            instruction, "Question: " + question + "\n\nQuery results:\n" + digest))
        yield {"type": "answer", "text": answer,
               "grounding": {"tools": [t for t, _, _ in gathered],
                             "documents": [d["title"] for d in docs]}}
    except Exception:
        yield {"type": "error",
               "message": "The assistant could not compose an answer - the "
                          "query results above still stand."}
    yield {"type": "done", "latency_ms": int((time.monotonic() - t0) * 1000)}


@router.post(
    "/ops-assistant",
    description="Ask the operations question over the live plant system. "
                "Streams the agent's own step trace live; falls back to a "
                "cached example (never dead-airs) if the live call errors or "
                "runs long.",
)
async def ai_ops_assistant(req: Request, user: dict = Depends(current_user)):
    # Ask the operations question via the retrieval agent - the agent plans
    # and calls this app's own /mcp as its tool source, grounds, and answers.
    # Streams the agent's own step trace live; falls back to a cached golden
    # (never dead-airs) if the live call errors or runs past AGENT_TIMEOUT_S.
    # (FastAPI renders the docstring at /docs by default - this route gets an
    # explicit `description=` above instead, so the vendor/architecture detail
    # stays here as a comment for maintainers without reaching the public
    # OpenAPI surface. See the QA finding, 23 Jul 2026.)
    body = await req.json()
    question = (body.get("query") or "").strip()
    if not question:
        raise HTTPException(400, "Empty query")
    golden_key = body.get("golden") or "ops-assistant"

    if body.get("mode") == "cached":
        c = cached_golden(golden_key)
        if c:
            async def cached_stream():
                for ev in _adapt_legacy_golden_events(c.get("events", [])):
                    yield json.dumps(ev) + "\n"
            return StreamingResponse(cached_stream(),
                                     media_type="application/x-ndjson")

    bearer = (req.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None

    # Only a genuine TIMEOUT falls back to the cached golden, and only when
    # the golden's OWN captured question actually matches what was asked.
    # The UI sends one fixed `golden` key ("ops-assistant") for every hero
    # question, so a bare key lookup would happily serve the WF-2261
    # flagship golden underneath an unrelated timed-out question (e.g.
    # invoices) - a confident-looking but WRONG answer, precisely the bluff
    # the honest gate exists to prevent (GM/lead finding, 22 Jul). Every
    # other failure stage (no_grounded_data, unverified_negative, no_answer,
    # transport, config) - and a timeout with no matching golden - gets the
    # honest message alone, nothing beneath it.
    _GOLDEN_FALLBACK_STAGES = {"timeout"}

    async def stream():
        answered = False
        try:
            async for ev in arag_agent_events(question, bearer):
                if ev["type"] == "answer":
                    answered = True
                yield json.dumps(ev) + "\n"
                if ev["type"] == "error" and not answered:
                    if ev.get("stage") in _GOLDEN_FALLBACK_STAGES:
                        c = cached_golden(golden_key)
                        if c and _golden_matches_question(c.get("events", []), question):
                            yield json.dumps({
                                "type": "fallback",
                                "message": "Showing a captured example while "
                                          "the live agent recovers.",
                            }) + "\n"
                            for gev in _adapt_legacy_golden_events(c.get("events", [])):
                                yield json.dumps(gev) + "\n"
                    return
        except Exception:
            # Last-resort catch-all (arag_agent_events already handles its
            # own transport errors internally) - stay honest and friendly,
            # never leak a raw Python exception string to the trace.
            yield json.dumps({
                "type": "error",
                "message": "The retrieval agent could not be reached for "
                          "this question.",
            }) + "\n"
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/agent")
async def ai_agent(req: Request, user: dict = Depends(current_user)):
    """One-shot agent run: same pipeline as the ops assistant, buffered."""
    body = await req.json()
    question = (body.get("query") or "").strip()
    if not question:
        raise HTTPException(400, "Empty query")
    golden = body.get("golden") or "agent"
    if body.get("mode") == "cached":
        c = cached_golden(golden)
        if c:
            return c
    bearer = (req.headers.get("authorization") or "").removeprefix("Bearer ").strip() or None
    events = []
    try:
        async for ev in agent_events(question, user["name"], bearer):
            events.append(ev)
    except Exception:
        c = cached_golden(golden)
        if c:
            return c
    answer = next((e["text"] for e in events if e["type"] == "answer"), "")
    return {"answer": answer, "events": events, "cached": False}
