"""Tallowa Components ERP - the /api/* surface (everything except /api/ai/*).

API-first: the web app only ever talks to these endpoints, never the database.
JWT-style bearer auth (HMAC-signed), role-based. Swagger is published at /docs.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from database import connect, q, q1, now, audit_log

ROOT = Path(__file__).resolve().parent

ENV = {}
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            ENV[k.strip()] = v.strip()
import os as _os
ENV.update({k: v for k, v in _os.environ.items()
            if k.startswith(("ARAG_", "KB_", "APP_"))})

SECRET = ENV.get("APP_SECRET", "tallowa-demo-signing-secret").encode()

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------- auth
def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def _verify(token: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
        if hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()[:32] != sig:
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def current_user(authorization: str = Header(default="")) -> dict:
    if authorization.startswith("Bearer "):
        u = _verify(authorization[7:])
        if u:
            return u
    raise HTTPException(401, "Not authenticated")


def require(user: dict, *roles: str):
    if roles and user["role"] not in roles and user["role"] != "admin":
        raise HTTPException(403, f"Requires role: {', '.join(roles)}")


@router.post("/auth/login")
async def login(req: Request):
    body = await req.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    con = connect()
    u = q1(con, "SELECT * FROM users WHERE email=?", (email,))
    ok = u and u["pw_hash"] == hashlib.sha256(("tallowa:" + password).encode()).hexdigest()
    if not ok:
        con.close()
        raise HTTPException(401, "Invalid email or password")
    audit_log(con, email, "login", "user", u["id"], "")
    con.commit()
    con.close()
    token = _sign({"email": u["email"], "name": u["name"], "role": u["role"],
                   "exp": time.time() + 12 * 3600})
    return {"token": token, "user": {"email": u["email"], "name": u["name"],
                                     "role": u["role"]}}


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"], "name": user["name"], "role": user["role"]}


@router.post("/auth/logout")
def logout(user: dict = Depends(current_user)):
    return {"ok": True}


# ------------------------------------------------------------ dashboard
@router.get("/dashboard/summary")
def dashboard(user: dict = Depends(current_user)):
    con = connect()
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    month_ago = (date.today() - timedelta(days=30)).isoformat()

    runs_open = q1(con, "SELECT COUNT(*) n FROM runs WHERE status IN "
                        "('planned','released','in_progress','quality_hold')")["n"]
    stopped = q(con, "SELECT code,name,stoppage_reason FROM lines WHERE status!='running'")
    holds_open = q1(con, "SELECT COUNT(*) n FROM holds WHERE status='open'")["n"]
    late_pos = q(con, """SELECT po.po_no, s.name supplier, po.expected_date
                         FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id
                         WHERE po.status IN ('sent','confirmed','partial')
                         AND po.expected_date < ?""", (today,))
    throughput = q1(con, "SELECT COALESCE(SUM(qty_good),0) n FROM runs "
                         "WHERE completed_at >= ?", (week_ago,))["n"]
    wip = q1(con, "SELECT COALESCE(SUM(actual_cost),0) v FROM runs "
                  "WHERE status IN ('in_progress','quality_hold')")["v"]
    rev = q1(con, "SELECT COALESCE(SUM(subtotal),0) v FROM invoices "
                  "WHERE issued_on >= ? AND status != 'draft'", (month_ago,))["v"]
    cost = q1(con, "SELECT COALESCE(SUM(actual_cost),0) v FROM runs "
                   "WHERE completed_at >= ?", (month_ago,))["v"]
    margin_pct = round((rev - cost) / rev * 100, 1) if rev else None
    due_week = q1(con, """SELECT COUNT(*) n FROM sales_orders WHERE status IN
                          ('approved','in_production') AND promised_date <= ?""",
                  ((date.today() + timedelta(days=7)).isoformat(),))["n"]
    low_stock = q1(con, """SELECT COUNT(*) n FROM (
                     SELECT p.id FROM parts p
                     LEFT JOIN stock s ON s.part_id=p.id
                     LEFT JOIN locations l ON l.id=s.location_id AND l.type!='quarantine'
                     WHERE p.reorder_point > 0
                     GROUP BY p.id
                     HAVING COALESCE(SUM(CASE WHEN l.id IS NULL THEN 0 ELSE s.qty END),0)
                            < p.reorder_point)""")["n"]
    ftt = q1(con, """SELECT ROUND(100.0*SUM(qty_good)/NULLIF(SUM(qty_good+qty_scrap),0),1) v
                     FROM runs WHERE completed_at >= ?""", (month_ago,))["v"]
    shipped = q1(con, """SELECT COALESCE(SUM(sl.qty),0) n FROM shipment_lines sl
                         JOIN shipments sh ON sh.id=sl.shipment_id
                         WHERE sh.shipped_on >= ?""", (month_ago,))["n"]
    cust_defect_qty = q1(con, """SELECT COALESCE(SUM(qty),0) n FROM defects
                                 WHERE source='customer' AND found_at >= ?""",
                         (month_ago,))["n"]
    ppm = round(cust_defect_qty / shipped * 1_000_000) if shipped else 0
    overdue = q(con, "SELECT inv_no, total FROM invoices WHERE status='overdue'")
    open_defects = q1(con, "SELECT COUNT(*) n FROM defects WHERE status='open'")["n"]
    con.close()
    return {
        "open_runs": runs_open, "stopped_lines": stopped,
        "quality_holds": holds_open, "late_supplier_pos": late_pos,
        "throughput_7d": throughput, "wip_value": round(wip, 2),
        "margin_pct_30d": margin_pct, "orders_due_7d": due_week,
        "low_stock_parts": low_stock, "ftt_pct_30d": ftt,
        "customer_ppm_30d": ppm, "overdue_invoices": overdue,
        "open_defects": open_defects,
        "revenue_30d": round(rev, 2),
    }


# ------------------------------------------------------------ customers
@router.get("/customers/")
def customers(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """
      SELECT c.*,
        (SELECT COUNT(*) FROM sales_orders so WHERE so.customer_id=c.id
          AND so.status IN ('approved','in_production','submitted')) open_orders,
        (SELECT COALESCE(SUM(total),0) FROM invoices i WHERE i.customer_id=c.id
          AND i.status IN ('sent','overdue')) outstanding
      FROM customers c ORDER BY c.name""")
    month_ago = (date.today() - timedelta(days=30)).isoformat()
    for r in rows:
        shipped = q1(con, """SELECT COALESCE(SUM(sl.qty),0) n FROM shipment_lines sl
            JOIN shipments sh ON sh.id=sl.shipment_id
            WHERE sh.customer_id=? AND sh.shipped_on >= ?""", (r["id"], month_ago))["n"]
        dq = q1(con, """SELECT COALESCE(SUM(qty),0) n FROM defects
            WHERE source='customer' AND customer_id=? AND found_at >= ?""",
                (r["id"], month_ago))["n"]
        r["ppm_30d"] = round(dq / shipped * 1_000_000) if shipped else 0
    con.close()
    return rows


@router.get("/customers/{cid}")
def customer(cid: int, user: dict = Depends(current_user)):
    con = connect()
    c = q1(con, "SELECT * FROM customers WHERE id=?", (cid,))
    if not c:
        con.close()
        raise HTTPException(404, "Customer not found")
    c["ship_tos"] = q(con, "SELECT * FROM ship_tos WHERE customer_id=?", (cid,))
    c["parts"] = q(con, """SELECT cp.customer_part_no, cp.price, p.part_no, p.name
                           FROM customer_parts cp JOIN parts p ON p.id=cp.part_id
                           WHERE cp.customer_id=?""", (cid,))
    c["sales_orders"] = q(con, """SELECT so_no, customer_po, status, ordered_on,
                                  promised_date, total FROM sales_orders
                                  WHERE customer_id=? ORDER BY ordered_on DESC""", (cid,))
    c["invoices"] = q(con, """SELECT inv_no, status, issued_on, due_on, total, paid_on
                              FROM invoices WHERE customer_id=?
                              ORDER BY issued_on DESC""", (cid,))
    c["complaints"] = q(con, """SELECT defect_no, code, description, severity, qty,
                                found_at, status FROM defects
                                WHERE source='customer' AND customer_id=?
                                ORDER BY found_at DESC""", (cid,))
    con.close()
    return c


# ---------------------------------------------------------- plant, lines
@router.get("/lines/")
def lines(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """
      SELECT l.*, p.name plant_name,
        (SELECT COUNT(*) FROM machines m WHERE m.line_id=l.id) machines,
        (SELECT COUNT(*) FROM runs r WHERE r.line_id=l.id AND r.status IN
          ('released','in_progress','quality_hold')) active_runs
      FROM lines l JOIN plants p ON p.id=l.plant_id ORDER BY l.code""")
    con.close()
    return rows


@router.get("/lines/{lid}")
def line(lid: int, user: dict = Depends(current_user)):
    con = connect()
    l = q1(con, "SELECT * FROM lines WHERE id=?", (lid,))
    if not l:
        con.close()
        raise HTTPException(404, "Line not found")
    l["machines"] = q(con, "SELECT * FROM machines WHERE line_id=?", (lid,))
    l["runs"] = q(con, """SELECT r.run_no, r.status, r.qty_planned, r.qty_good,
                          r.scheduled_start, r.scheduled_end, p.part_no, p.name part_name
                          FROM runs r JOIN parts p ON p.id=r.part_id
                          WHERE r.line_id=? ORDER BY r.scheduled_start DESC LIMIT 20""",
                 (lid,))
    l["operators"] = q(con, "SELECT emp_no, name, role, shift FROM operators "
                            "WHERE line_id=? AND status='active'", (lid,))
    con.close()
    return l


# ------------------------------------------------------------ operators
@router.get("/operators/")
def operators(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT o.*, l.code line_code FROM operators o
                     LEFT JOIN lines l ON l.id=o.line_id ORDER BY o.emp_no""")
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=60)).isoformat()
    for r in rows:
        certs = q(con, """SELECT s.code, s.name, os.certified_on, os.expires_on
                          FROM operator_skills os JOIN skills s ON s.id=os.skill_id
                          WHERE os.operator_id=?""", (r["id"],))
        for c in certs:
            c["state"] = ("expired" if c["expires_on"] < today
                          else "expiring" if c["expires_on"] <= soon else "current")
        r["certs"] = certs
    con.close()
    return rows


@router.get("/skills/")
def skills(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT s.*, COUNT(os.id) holders FROM skills s
                     LEFT JOIN operator_skills os ON os.skill_id=s.id
                     GROUP BY s.id ORDER BY s.code""")
    con.close()
    return rows


# ----------------------------------------------------------------- runs
RUN_TRANSITIONS = {
    "planned": ["released", "cancelled"],
    "released": ["in_progress", "planned", "cancelled"],
    "in_progress": ["quality_hold", "completed"],
    "quality_hold": ["in_progress", "cancelled"],
}


@router.get("/runs/")
def runs_list(status: str = "", line: str = "", part: str = "",
              user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT r.*, p.part_no, p.name part_name, p.family, l.code line_code,
             so.so_no, c.name customer_name
             FROM runs r JOIN parts p ON p.id=r.part_id
             LEFT JOIN lines l ON l.id=r.line_id
             LEFT JOIN sales_orders so ON so.id=r.sales_order_id
             LEFT JOIN customers c ON c.id=so.customer_id WHERE 1=1"""
    args = []
    if status:
        sql += " AND r.status=?"; args.append(status)
    if line:
        sql += " AND l.code=?"; args.append(line)
    if part:
        sql += " AND p.part_no=?"; args.append(part)
    sql += " ORDER BY CASE r.status WHEN 'quality_hold' THEN 0 WHEN 'in_progress' THEN 1 \
            WHEN 'released' THEN 2 WHEN 'planned' THEN 3 ELSE 4 END, r.scheduled_start DESC"
    rows = q(con, sql, tuple(args))
    con.close()
    return rows


@router.get("/runs/{run_no}")
def run_detail(run_no: str, user: dict = Depends(current_user)):
    con = connect()
    r = q1(con, """SELECT r.*, p.part_no, p.name part_name, p.family, p.safety_critical,
                   l.code line_code, l.name line_name, so.so_no, so.customer_po,
                   c.name customer_name
                   FROM runs r JOIN parts p ON p.id=r.part_id
                   LEFT JOIN lines l ON l.id=r.line_id
                   LEFT JOIN sales_orders so ON so.id=r.sales_order_id
                   LEFT JOIN customers c ON c.id=so.customer_id
                   WHERE r.run_no=?""", (run_no,))
    if not r:
        con.close()
        raise HTTPException(404, "Run not found")
    rid = r["id"]
    r["materials"] = q(con, """SELECT rm.qty, rm.cost, p.part_no, p.name part_name,
                               p.traceable, rl.lot_no, s.name supplier_name
                               FROM run_materials rm JOIN parts p ON p.id=rm.part_id
                               LEFT JOIN raw_lots rl ON rl.id=rm.raw_lot_id
                               LEFT JOIN suppliers s ON s.id=rl.supplier_id
                               WHERE rm.run_id=?""", (rid,))
    r["time_entries"] = q(con, """SELECT rt.*, o.name operator_name FROM run_time rt
                                  JOIN operators o ON o.id=rt.operator_id
                                  WHERE rt.run_id=?""", (rid,))
    r["finished_lots"] = q(con, """SELECT lot_no, qty_produced, qty_shipped, status,
                                   produced_on FROM finished_lots WHERE run_id=?""", (rid,))
    r["defects"] = q(con, """SELECT defect_no, code, severity, qty, disposition,
                             status, found_at FROM defects WHERE run_id=?""", (rid,))
    r["holds"] = q(con, """SELECT hold_no, reason, status, placed_at FROM holds
                           WHERE scope='run' AND scope_id=?""", (rid,))
    labour = sum(t["minutes"] for t in r["time_entries"])
    r["labour_minutes"] = labour
    con.close()
    return r


@router.post("/runs/{run_no}/status")
async def run_status(run_no: str, req: Request, user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor", "line_lead")
    body = await req.json()
    new = body.get("status")
    con = connect()
    r = q1(con, "SELECT * FROM runs WHERE run_no=?", (run_no,))
    if not r:
        con.close()
        raise HTTPException(404, "Run not found")
    allowed = RUN_TRANSITIONS.get(r["status"], [])
    if new not in allowed:
        con.close()
        raise HTTPException(422, f"Cannot move {r['status']} -> {new}; allowed: {allowed}")
    open_hold = q1(con, "SELECT id FROM holds WHERE scope='run' AND scope_id=? "
                        "AND status='open'", (r["id"],))
    if new == "in_progress" and r["status"] == "quality_hold" and open_hold:
        con.close()
        raise HTTPException(422, "Run has an open quality hold - release it first")
    sets = {"status": new}
    if new == "in_progress" and not r["started_at"]:
        sets["started_at"] = now()
    con.execute(f"UPDATE runs SET {','.join(k+'=?' for k in sets)} WHERE id=?",
                (*sets.values(), r["id"]))
    audit_log(con, user["email"], "status", "run", run_no, f"{r['status']} -> {new}")
    con.commit()
    con.close()
    return {"ok": True, "status": new}


@router.post("/runs/{run_no}/complete")
async def run_complete(run_no: str, req: Request, user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor", "line_lead")
    body = await req.json()
    con = connect()
    r = q1(con, "SELECT r.*, p.part_no FROM runs r JOIN parts p ON p.id=r.part_id "
                "WHERE r.run_no=?", (run_no,))
    if not r:
        con.close()
        raise HTTPException(404, "Run not found")
    if r["status"] != "in_progress":
        con.close()
        raise HTTPException(422, "Only an in-progress run can be completed")
    good = float(body.get("qty_good") or 0)
    scrap = float(body.get("qty_scrap") or 0)
    if good <= 0:
        con.close()
        raise HTTPException(422, "qty_good required")
    lot_no = f"TC-A-{9000 + r['id']}"
    fg = q1(con, "SELECT id FROM locations WHERE code='FG-1'")
    con.execute("""INSERT INTO finished_lots (lot_no, part_id, run_id, qty_produced,
                   produced_on, status, location_id) VALUES (?,?,?,?,?,?,?)""",
                (lot_no, r["part_id"], r["id"], good, date.today().isoformat(),
                 "in_stock", fg["id"]))
    con.execute("""UPDATE runs SET status='completed', qty_good=?, qty_scrap=?,
                   completed_at=?, actual_cost=std_cost*1.0 WHERE id=?""",
                (good, scrap, now(), r["id"]))
    con.execute("""INSERT INTO stock (part_id, location_id, qty) VALUES (?,?,?)
                   ON CONFLICT(part_id, location_id) DO UPDATE SET qty=qty+?""",
                (r["part_id"], fg["id"], good, good))
    audit_log(con, user["email"], "complete", "run", run_no,
              f"{good} good, {scrap} scrap; finished lot {lot_no}")
    con.commit()
    con.close()
    return {"ok": True, "finished_lot": lot_no}


@router.post("/runs/{run_no}/time-entries")
async def run_time_add(run_no: str, req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    con = connect()
    r = q1(con, "SELECT id FROM runs WHERE run_no=?", (run_no,))
    if not r:
        con.close()
        raise HTTPException(404, "Run not found")
    op = q1(con, "SELECT id FROM operators WHERE emp_no=?", (body.get("emp_no"),))
    if not op:
        con.close()
        raise HTTPException(404, "Operator not found")
    con.execute("""INSERT INTO run_time (run_id, operator_id, station, minutes,
                   entered_at, note) VALUES (?,?,?,?,?,?)""",
                (r["id"], op["id"], body.get("station"),
                 float(body.get("minutes") or 0), now(), body.get("note")))
    audit_log(con, user["email"], "time_entry", "run", run_no,
              f"{body.get('minutes')} min at {body.get('station')}")
    con.commit()
    con.close()
    return {"ok": True}


# ---------------------------------------------------------- sales orders
@router.get("/sales-orders/")
def sales_orders(status: str = "", user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT so.*, c.name customer_name, c.code customer_code,
             st.name ship_to_name
             FROM sales_orders so JOIN customers c ON c.id=so.customer_id
             LEFT JOIN ship_tos st ON st.id=so.ship_to_id WHERE 1=1"""
    args = []
    if status:
        sql += " AND so.status=?"; args.append(status)
    sql += " ORDER BY so.ordered_on DESC"
    rows = q(con, sql, tuple(args))
    con.close()
    return rows


@router.get("/sales-orders/{so_no}")
def sales_order(so_no: str, user: dict = Depends(current_user)):
    con = connect()
    so = q1(con, """SELECT so.*, c.name customer_name, c.code customer_code,
                    st.name ship_to_name, st.city ship_to_city
                    FROM sales_orders so JOIN customers c ON c.id=so.customer_id
                    LEFT JOIN ship_tos st ON st.id=so.ship_to_id
                    WHERE so.so_no=?""", (so_no,))
    if not so:
        con.close()
        raise HTTPException(404, "Sales order not found")
    so["lines"] = q(con, """SELECT sol.*, p.part_no, p.name part_name
                            FROM sales_order_lines sol JOIN parts p ON p.id=sol.part_id
                            WHERE sol.sales_order_id=?""", (so["id"],))
    so["runs"] = q(con, """SELECT run_no, status, qty_planned, qty_good,
                           scheduled_start, scheduled_end FROM runs
                           WHERE sales_order_id=?""", (so["id"],))
    so["shipments"] = q(con, """SELECT shp_no, status, shipped_on, carrier
                                FROM shipments WHERE sales_order_id=?""", (so["id"],))
    con.close()
    return so


@router.post("/sales-orders/")
async def sales_order_create(req: Request, user: dict = Depends(current_user)):
    body = await req.json()
    con = connect()
    cust = q1(con, "SELECT * FROM customers WHERE code=?", (body.get("customer_code"),))
    if not cust:
        con.close()
        raise HTTPException(404, "Customer not found")
    gst_rate = float(q1(con, "SELECT value FROM settings WHERE key='gst_rate'")["value"])
    n = q1(con, "SELECT COUNT(*) n FROM sales_orders")["n"]
    so_no = f"SO-{3441 + n}"
    lines = body.get("lines") or []
    if not lines:
        con.close()
        raise HTTPException(422, "At least one line required")
    sub = 0.0
    resolved = []
    for ln in lines:
        p = q1(con, "SELECT * FROM parts WHERE part_no=?", (ln.get("part_no"),))
        if not p:
            con.close()
            raise HTTPException(404, f"Part {ln.get('part_no')} not found")
        cp = q1(con, """SELECT * FROM customer_parts WHERE customer_id=? AND part_id=?""",
                (cust["id"], p["id"]))
        price = float(ln.get("unit_price") or (cp and cp["price"]) or p["price"] or 0)
        qty = float(ln.get("qty") or 0)
        sub += qty * price
        resolved.append((p, cp, qty, price))
    gst = round(sub * gst_rate, 2)
    cur = con.execute(
        """INSERT INTO sales_orders (so_no, customer_id, customer_po, status,
           ordered_on, promised_date, subtotal, gst, total, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (so_no, cust["id"], body.get("customer_po"), "draft",
         date.today().isoformat(), body.get("promised_date"),
         round(sub, 2), gst, round(sub + gst, 2), body.get("notes")))
    soid = cur.lastrowid
    for p, cp, qty, price in resolved:
        con.execute("""INSERT INTO sales_order_lines (sales_order_id, part_id,
                       customer_part_no, qty, unit_price, line_total)
                       VALUES (?,?,?,?,?,?)""",
                    (soid, p["id"], cp and cp["customer_part_no"], qty, price,
                     round(qty * price, 2)))
    audit_log(con, user["email"], "create", "sales_order", so_no,
              f"{len(resolved)} lines, total {round(sub+gst,2)}")
    con.commit()
    con.close()
    return {"ok": True, "so_no": so_no, "subtotal": round(sub, 2), "gst": gst,
            "total": round(sub + gst, 2)}


@router.post("/sales-orders/{so_no}/approve")
def so_approve(so_no: str, user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor", "sales")
    con = connect()
    so = q1(con, "SELECT * FROM sales_orders WHERE so_no=?", (so_no,))
    if not so:
        con.close()
        raise HTTPException(404, "Sales order not found")
    if so["status"] not in ("draft", "submitted"):
        con.close()
        raise HTTPException(422, f"Cannot approve a {so['status']} order")
    con.execute("UPDATE sales_orders SET status='approved' WHERE id=?", (so["id"],))
    audit_log(con, user["email"], "approve", "sales_order", so_no, "")
    con.commit()
    con.close()
    return {"ok": True}


@router.post("/sales-orders/{so_no}/reject")
async def so_reject(so_no: str, req: Request, user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor")
    body = await req.json()
    con = connect()
    so = q1(con, "SELECT * FROM sales_orders WHERE so_no=?", (so_no,))
    if not so:
        con.close()
        raise HTTPException(404, "Sales order not found")
    con.execute("UPDATE sales_orders SET status='rejected', notes=? WHERE id=?",
                (body.get("reason") or so["notes"], so["id"]))
    audit_log(con, user["email"], "reject", "sales_order", so_no,
              body.get("reason") or "")
    con.commit()
    con.close()
    return {"ok": True}


# ------------------------------------------------------ parts, stock, BOM
@router.get("/parts/")
def parts(family: str = "", category: str = "", user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT p.*, s.name supplier_name,
             (SELECT COALESCE(SUM(st.qty),0) FROM stock st
               JOIN locations l ON l.id=st.location_id
               WHERE st.part_id=p.id AND l.type != 'quarantine') on_hand,
             (SELECT COALESCE(SUM(st.qty),0) FROM stock st
               JOIN locations l ON l.id=st.location_id
               WHERE st.part_id=p.id AND l.type='quarantine') quarantined
             FROM parts p LEFT JOIN suppliers s ON s.id=p.preferred_supplier_id
             WHERE 1=1"""
    args = []
    if family:
        sql += " AND p.family=?"; args.append(family)
    if category:
        sql += " AND p.category=?"; args.append(category)
    sql += " ORDER BY p.part_no"
    rows = q(con, sql, tuple(args))
    for r in rows:
        r["low_stock"] = bool(r["reorder_point"] and r["on_hand"] < r["reorder_point"])
    con.close()
    return rows


@router.get("/parts/{part_no}")
def part_detail(part_no: str, user: dict = Depends(current_user)):
    con = connect()
    p = q1(con, """SELECT p.*, s.name supplier_name FROM parts p
                   LEFT JOIN suppliers s ON s.id=p.preferred_supplier_id
                   WHERE p.part_no=?""", (part_no,))
    if not p:
        con.close()
        raise HTTPException(404, "Part not found")
    pid = p["id"]
    p["bom"] = q(con, """SELECT b.qty_per, b.station, c.part_no, c.name comp_name,
                         c.std_cost, c.traceable FROM boms b
                         JOIN parts c ON c.id=b.component_part_id
                         WHERE b.parent_part_id=?""", (pid,))
    p["where_used"] = q(con, """SELECT par.part_no, par.name FROM boms b
                                JOIN parts par ON par.id=b.parent_part_id
                                WHERE b.component_part_id=?""", (pid,))
    p["stock"] = q(con, """SELECT l.code, l.name, l.type, st.qty FROM stock st
                           JOIN locations l ON l.id=st.location_id
                           WHERE st.part_id=? AND st.qty>0""", (pid,))
    p["raw_lots"] = q(con, """SELECT rl.lot_no, rl.received_on, rl.qty_received,
                              rl.qty_remaining, rl.status, s.name supplier_name
                              FROM raw_lots rl LEFT JOIN suppliers s ON s.id=rl.supplier_id
                              WHERE rl.part_id=? ORDER BY rl.received_on DESC""", (pid,))
    p["finished_lots"] = q(con, """SELECT lot_no, qty_produced, qty_shipped, status,
                                   produced_on FROM finished_lots WHERE part_id=?
                                   ORDER BY produced_on DESC""", (pid,))
    p["customers"] = q(con, """SELECT c.name, cp.customer_part_no, cp.price
                               FROM customer_parts cp JOIN customers c ON c.id=cp.customer_id
                               WHERE cp.part_id=?""", (pid,))
    con.close()
    return p


@router.get("/inventory/low-stock")
def low_stock(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """
      SELECT p.part_no, p.name, p.reorder_point, p.reorder_qty, p.std_cost,
             s.name supplier_name,
             COALESCE((SELECT SUM(st.qty) FROM stock st
               JOIN locations l ON l.id=st.location_id
               WHERE st.part_id=p.id AND l.type!='quarantine'),0) on_hand
      FROM parts p LEFT JOIN suppliers s ON s.id=p.preferred_supplier_id
      WHERE p.reorder_point > 0""")
    out = [r for r in rows if r["on_hand"] < r["reorder_point"]]
    con.close()
    return out


@router.get("/inventory/movements")
def movements(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT sm.*, p.part_no, lf.code from_code, lt.code to_code
                     FROM stock_movements sm JOIN parts p ON p.id=sm.part_id
                     LEFT JOIN locations lf ON lf.id=sm.from_location_id
                     LEFT JOIN locations lt ON lt.id=sm.to_location_id
                     ORDER BY sm.moved_at DESC LIMIT 100""")
    con.close()
    return rows


# ----------------------------------------------------------------- lots
@router.get("/lots/")
def lots(kind: str = "", status: str = "", user: dict = Depends(current_user)):
    con = connect()
    out = {}
    if kind in ("", "raw"):
        sql = """SELECT rl.*, p.part_no, p.name part_name, s.name supplier_name
                 FROM raw_lots rl JOIN parts p ON p.id=rl.part_id
                 LEFT JOIN suppliers s ON s.id=rl.supplier_id WHERE 1=1"""
        args = []
        if status:
            sql += " AND rl.status=?"; args.append(status)
        out["raw"] = q(con, sql + " ORDER BY rl.received_on DESC", tuple(args))
    if kind in ("", "finished"):
        sql = """SELECT fl.*, p.part_no, p.name part_name, r.run_no
                 FROM finished_lots fl JOIN parts p ON p.id=fl.part_id
                 LEFT JOIN runs r ON r.id=fl.run_id WHERE 1=1"""
        args = []
        if status:
            sql += " AND fl.status=?"; args.append(status)
        out["finished"] = q(con, sql + " ORDER BY fl.produced_on DESC", tuple(args))
    con.close()
    return out


# ------------------------------------------------------------ trace core
def trace_forward(con, lot_no: str) -> dict | None:
    """Raw lot -> runs -> finished lots -> shipments -> customers."""
    rl = q1(con, """SELECT rl.*, p.part_no, p.name part_name, s.name supplier_name
                    FROM raw_lots rl JOIN parts p ON p.id=rl.part_id
                    LEFT JOIN suppliers s ON s.id=rl.supplier_id
                    WHERE rl.lot_no=?""", (lot_no,))
    if not rl:
        return None
    runs = q(con, """SELECT DISTINCT r.run_no, r.status, r.qty_good, r.qty_scrap,
                     r.completed_at, rm.qty consumed_qty, p.part_no, p.name part_name
                     FROM run_materials rm JOIN runs r ON r.id=rm.run_id
                     JOIN parts p ON p.id=r.part_id
                     WHERE rm.raw_lot_id=?""", (rl["id"],))
    run_ids = [r["run_no"] for r in runs]
    flots, shipments = [], []
    for rn in run_ids:
        run = q1(con, "SELECT id FROM runs WHERE run_no=?", (rn,))
        for fl in q(con, """SELECT fl.*, p.part_no FROM finished_lots fl
                            JOIN parts p ON p.id=fl.part_id WHERE fl.run_id=?""",
                    (run["id"],)):
            fl["run_no"] = rn
            hold = q1(con, """SELECT hold_no, reason, status FROM holds
                              WHERE scope='finished_lot' AND scope_id=? AND status='open'""",
                      (fl["id"],))
            fl["open_hold"] = hold
            flots.append(fl)
            for sl in q(con, """SELECT sl.qty, sh.shp_no, sh.shipped_on, sh.status,
                                c.name customer_name, st.name ship_to_name, st.city,
                                so.so_no, so.customer_po
                                FROM shipment_lines sl
                                JOIN shipments sh ON sh.id=sl.shipment_id
                                JOIN customers c ON c.id=sh.customer_id
                                LEFT JOIN ship_tos st ON st.id=sh.ship_to_id
                                LEFT JOIN sales_orders so ON so.id=sh.sales_order_id
                                WHERE sl.finished_lot_id=?""", (fl["id"],)):
                sl["finished_lot"] = fl["lot_no"]
                shipments.append(sl)
    exposure = {
        "shipped_qty": sum(s["qty"] for s in shipments),
        "unshipped_qty": sum((f["qty_produced"] or 0) - (f["qty_shipped"] or 0)
                             for f in flots),
        "customers": sorted({s["customer_name"] for s in shipments}),
        "ship_tos": sorted({s["ship_to_name"] for s in shipments if s["ship_to_name"]}),
    }
    hold = q1(con, """SELECT hold_no, reason, status, placed_at FROM holds
                      WHERE scope='raw_lot' AND scope_id=?""", (rl["id"],))
    return {"raw_lot": rl, "hold": hold, "runs": runs, "finished_lots": flots,
            "shipments": shipments, "exposure": exposure}


def trace_backward(con, lot_no: str) -> dict | None:
    """Finished lot -> run -> raw material lots + suppliers."""
    fl = q1(con, """SELECT fl.*, p.part_no, p.name part_name FROM finished_lots fl
                    JOIN parts p ON p.id=fl.part_id WHERE fl.lot_no=?""", (lot_no,))
    if not fl:
        return None
    run = q1(con, """SELECT r.*, l.code line_code FROM runs r
                     LEFT JOIN lines l ON l.id=r.line_id WHERE r.id=?""",
             (fl["run_id"],))
    materials = q(con, """SELECT rm.qty, p.part_no, p.name part_name, p.traceable,
                          rl.lot_no, rl.received_on, rl.coa_ref, rl.status lot_status,
                          s.name supplier_name
                          FROM run_materials rm JOIN parts p ON p.id=rm.part_id
                          LEFT JOIN raw_lots rl ON rl.id=rm.raw_lot_id
                          LEFT JOIN suppliers s ON s.id=rl.supplier_id
                          WHERE rm.run_id=?""", (fl["run_id"],))
    shipments = q(con, """SELECT sl.qty, sh.shp_no, sh.shipped_on, c.name customer_name,
                          st.name ship_to_name FROM shipment_lines sl
                          JOIN shipments sh ON sh.id=sl.shipment_id
                          JOIN customers c ON c.id=sh.customer_id
                          LEFT JOIN ship_tos st ON st.id=sh.ship_to_id
                          WHERE sl.finished_lot_id=?""", (fl["id"],))
    return {"finished_lot": fl, "run": run, "materials": materials,
            "shipments": shipments}


@router.get("/trace/forward")
def api_trace_forward(lot: str, user: dict = Depends(current_user)):
    con = connect()
    t = trace_forward(con, lot)
    con.close()
    if not t:
        raise HTTPException(404, f"Raw lot {lot} not found")
    return t


@router.get("/trace/backward")
def api_trace_backward(lot: str, user: dict = Depends(current_user)):
    con = connect()
    t = trace_backward(con, lot)
    con.close()
    if not t:
        raise HTTPException(404, f"Finished lot {lot} not found")
    return t


# ------------------------------------------------------------- suppliers
@router.get("/suppliers/")
def suppliers(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT s.*,
        (SELECT COUNT(*) FROM purchase_orders po WHERE po.supplier_id=s.id
          AND po.status IN ('sent','confirmed','partial')) open_pos,
        (SELECT COUNT(*) FROM raw_lots rl WHERE rl.supplier_id=s.id
          AND rl.status='quarantine') quarantined_lots
        FROM suppliers s ORDER BY s.name""")
    con.close()
    return rows


@router.get("/suppliers/{code}")
def supplier(code: str, user: dict = Depends(current_user)):
    con = connect()
    s = q1(con, "SELECT * FROM suppliers WHERE code=?", (code,))
    if not s:
        con.close()
        raise HTTPException(404, "Supplier not found")
    s["purchase_orders"] = q(con, """SELECT po_no, status, ordered_on, expected_date,
                                     received_on, total FROM purchase_orders
                                     WHERE supplier_id=? ORDER BY ordered_on DESC""",
                             (s["id"],))
    s["lots"] = q(con, """SELECT rl.lot_no, rl.received_on, rl.qty_received,
                          rl.qty_remaining, rl.status, p.part_no
                          FROM raw_lots rl JOIN parts p ON p.id=rl.part_id
                          WHERE rl.supplier_id=? ORDER BY rl.received_on DESC""",
                  (s["id"],))
    s["parts"] = q(con, "SELECT part_no, name FROM parts WHERE preferred_supplier_id=?",
                   (s["id"],))
    con.close()
    return s


# ------------------------------------------------------- purchase orders
@router.get("/purchase-orders/")
def purchase_orders(status: str = "", user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT po.*, s.name supplier_name, s.code supplier_code
             FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id WHERE 1=1"""
    args = []
    if status:
        sql += " AND po.status=?"; args.append(status)
    rows = q(con, sql + " ORDER BY po.ordered_on DESC", tuple(args))
    today = date.today().isoformat()
    for r in rows:
        r["late"] = bool(r["status"] in ("sent", "confirmed", "partial")
                         and r["expected_date"] and r["expected_date"] < today)
    con.close()
    return rows


@router.get("/purchase-orders/{po_no}")
def purchase_order(po_no: str, user: dict = Depends(current_user)):
    con = connect()
    po = q1(con, """SELECT po.*, s.name supplier_name, s.code supplier_code
                    FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id
                    WHERE po.po_no=?""", (po_no,))
    if not po:
        con.close()
        raise HTTPException(404, "Purchase order not found")
    po["lines"] = q(con, """SELECT pol.*, p.part_no, p.name part_name, p.traceable
                            FROM purchase_order_lines pol JOIN parts p ON p.id=pol.part_id
                            WHERE pol.po_id=?""", (po["id"],))
    po["lots"] = q(con, """SELECT lot_no, received_on, qty_received, status
                           FROM raw_lots WHERE po_id=?""", (po["id"],))
    con.close()
    return po


@router.post("/purchase-orders/{po_no}/receive")
async def po_receive(po_no: str, req: Request, user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor", "line_lead")
    con = connect()
    po = q1(con, "SELECT * FROM purchase_orders WHERE po_no=?", (po_no,))
    if not po:
        con.close()
        raise HTTPException(404, "Purchase order not found")
    if po["status"] not in ("sent", "confirmed", "partial"):
        con.close()
        raise HTTPException(422, f"Cannot receive a {po['status']} PO")
    wh = q1(con, "SELECT id FROM locations WHERE code='WH-RAW'")
    lines = q(con, """SELECT pol.*, p.part_no, p.traceable FROM purchase_order_lines pol
                      JOIN parts p ON p.id=pol.part_id WHERE pol.po_id=?""", (po["id"],))
    created = []
    for ln in lines:
        outstanding = ln["qty"] - ln["received_qty"]
        if outstanding <= 0:
            continue
        con.execute("UPDATE purchase_order_lines SET received_qty=qty WHERE id=?",
                    (ln["id"],))
        con.execute("""INSERT INTO stock (part_id, location_id, qty) VALUES (?,?,?)
                       ON CONFLICT(part_id, location_id) DO UPDATE SET qty=qty+?""",
                    (ln["part_id"], wh["id"], outstanding, outstanding))
        con.execute("""INSERT INTO stock_movements (part_id, from_location_id,
                       to_location_id, qty, reason, ref, moved_at)
                       VALUES (?,NULL,?,?,?,?,?)""",
                    (ln["part_id"], wh["id"], outstanding, "receipt", po_no, now()))
        if ln["traceable"]:
            n = q1(con, "SELECT COUNT(*) n FROM raw_lots")["n"]
            lot_no = f"RCV-{4000 + n}"
            con.execute("""INSERT INTO raw_lots (lot_no, part_id, supplier_id, po_id,
                           received_on, qty_received, qty_remaining, coa_ref, status)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (lot_no, ln["part_id"], po["supplier_id"], po["id"],
                         date.today().isoformat(), outstanding, outstanding,
                         f"CoA-{lot_no}", "available"))
            created.append(lot_no)
    con.execute("UPDATE purchase_orders SET status='received', received_on=? WHERE id=?",
                (date.today().isoformat(), po["id"]))
    audit_log(con, user["email"], "receive", "purchase_order", po_no,
              f"lots created: {', '.join(created) or 'none (non-traceable)'}")
    con.commit()
    con.close()
    return {"ok": True, "lots_created": created}


# -------------------------------------------------------------- invoices
@router.get("/invoices/")
def invoices(status: str = "", user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT i.*, c.name customer_name FROM invoices i
             JOIN customers c ON c.id=i.customer_id WHERE 1=1"""
    args = []
    if status:
        sql += " AND i.status=?"; args.append(status)
    rows = q(con, sql + " ORDER BY i.issued_on DESC", tuple(args))
    con.close()
    return rows


@router.get("/invoices/{inv_no}")
def invoice(inv_no: str, user: dict = Depends(current_user)):
    con = connect()
    inv = q1(con, """SELECT i.*, c.name customer_name, c.payment_terms,
                     so.so_no, so.customer_po, sh.shp_no
                     FROM invoices i JOIN customers c ON c.id=i.customer_id
                     LEFT JOIN sales_orders so ON so.id=i.sales_order_id
                     LEFT JOIN shipments sh ON sh.id=i.shipment_id
                     WHERE i.inv_no=?""", (inv_no,))
    if not inv:
        con.close()
        raise HTTPException(404, "Invoice not found")
    if inv["shipment_id"]:
        inv["lines"] = q(con, """SELECT sl.qty, p.part_no, p.name part_name,
                                 fl.lot_no, sol.unit_price
                                 FROM shipment_lines sl
                                 JOIN parts p ON p.id=sl.part_id
                                 LEFT JOIN finished_lots fl ON fl.id=sl.finished_lot_id
                                 LEFT JOIN sales_order_lines sol
                                   ON sol.sales_order_id=? AND sol.part_id=sl.part_id
                                 WHERE sl.shipment_id=?""",
                        (inv["sales_order_id"], inv["shipment_id"]))
    con.close()
    return inv


@router.get("/invoices/{inv_no}/print")
def invoice_print(inv_no: str, token: str = ""):
    # print view opens in a new tab; token passed as a query param
    if not (token and _verify(token)):
        raise HTTPException(401, "Not authenticated")
    con = connect()
    i = q1(con, """SELECT i.*, c.name customer_name, so.customer_po
                   FROM invoices i JOIN customers c ON c.id=i.customer_id
                   LEFT JOIN sales_orders so ON so.id=i.sales_order_id
                   WHERE i.inv_no=?""", (inv_no,))
    if not i:
        con.close()
        raise HTTPException(404, "Invoice not found")
    lines = q(con, """SELECT sl.qty, p.part_no, p.name part_name, sol.unit_price
                      FROM shipment_lines sl JOIN parts p ON p.id=sl.part_id
                      LEFT JOIN sales_order_lines sol
                        ON sol.sales_order_id=? AND sol.part_id=sl.part_id
                      WHERE sl.shipment_id=?""",
              (i["sales_order_id"], i["shipment_id"]))
    con.close()
    rows = "".join(
        f"<tr><td>{l['part_no']}</td><td>{l['part_name']}</td>"
        f"<td style='text-align:right'>{l['qty']:.0f}</td>"
        f"<td style='text-align:right'>${(l['unit_price'] or 0):,.2f}</td>"
        f"<td style='text-align:right'>${(l['qty']*(l['unit_price'] or 0)):,.2f}</td></tr>"
        for l in lines)
    html = f"""<!doctype html><html><head><title>{i['inv_no']}</title><style>
      body{{font-family:Georgia,serif;max-width:720px;margin:3em auto;color:#1C2B36}}
      table{{width:100%;border-collapse:collapse;margin-top:1.5em}}
      td,th{{border-bottom:1px solid #ccc;padding:8px;text-align:left;font-size:14px}}
      .tot{{text-align:right;font-size:15px;margin-top:1em}}
      .muted{{color:#777;font-size:12px}}</style></head><body>
      <h2 style="letter-spacing:1px">TALLOWA COMPONENTS</h2>
      <p class="muted">Bellbrook Plant - Accounts Receivable<br>ABN 00 000 000 000 (fictional)</p>
      <h3>Tax invoice {i['inv_no']}</h3>
      <p>To: <strong>{i['customer_name']}</strong><br>
      Customer PO: {i['customer_po'] or '-'}<br>
      Issued {i['issued_on']} - Due {i['due_on']}</p>
      <table><tr><th>Part</th><th>Description</th><th>Qty</th><th>Unit</th><th>Total</th></tr>
      {rows}</table>
      <p class="tot">Subtotal ${i['subtotal']:,.2f} &nbsp; GST ${i['gst']:,.2f} &nbsp;
      <strong>Total AUD ${i['total']:,.2f}</strong></p>
      <p class="muted">Synthetic demonstration document - all entities fictional.</p>
      <script>window.print&&setTimeout(()=>window.print(),300)</script></body></html>"""
    return HTMLResponse(html)


@router.post("/invoices/{inv_no}/status")
async def invoice_status(inv_no: str, req: Request, user: dict = Depends(current_user)):
    require(user, "plant_manager")
    body = await req.json()
    new = body.get("status")
    if new not in ("draft", "sent", "paid", "overdue"):
        raise HTTPException(422, "Bad status")
    con = connect()
    i = q1(con, "SELECT * FROM invoices WHERE inv_no=?", (inv_no,))
    if not i:
        con.close()
        raise HTTPException(404, "Invoice not found")
    con.execute("UPDATE invoices SET status=?, paid_on=? WHERE id=?",
                (new, date.today().isoformat() if new == "paid" else i["paid_on"],
                 i["id"]))
    audit_log(con, user["email"], "status", "invoice", inv_no, f"-> {new}")
    con.commit()
    con.close()
    return {"ok": True}


# ------------------------------------------------------------- shipments
@router.get("/shipments/")
def shipments(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT sh.*, c.name customer_name, st.name ship_to_name,
                     so.so_no, so.customer_po
                     FROM shipments sh JOIN customers c ON c.id=sh.customer_id
                     LEFT JOIN ship_tos st ON st.id=sh.ship_to_id
                     LEFT JOIN sales_orders so ON so.id=sh.sales_order_id
                     ORDER BY sh.shipped_on DESC""")
    for r in rows:
        r["lines"] = q(con, """SELECT sl.qty, p.part_no, fl.lot_no
                               FROM shipment_lines sl JOIN parts p ON p.id=sl.part_id
                               LEFT JOIN finished_lots fl ON fl.id=sl.finished_lot_id
                               WHERE sl.shipment_id=?""", (r["id"],))
    con.close()
    return rows


# ------------------------------------------------------ machines, tooling
@router.get("/machines/")
def machines(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT m.*, l.code line_code FROM machines m
                     LEFT JOIN lines l ON l.id=m.line_id ORDER BY m.asset_no""")
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=14)).isoformat()
    for r in rows:
        r["service_state"] = ("overdue" if r["next_service_due"] < today
                              else "due_soon" if r["next_service_due"] <= soon
                              else "ok")
        r["calibration_state"] = ("overdue" if r["next_calibration_due"] < today
                                  else "due_soon" if r["next_calibration_due"] <= soon
                                  else "ok")
    con.close()
    return rows


@router.get("/tooling/")
def tooling(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT t.*, p.part_no, l.code line_code FROM tooling t
                     LEFT JOIN parts p ON p.id=t.part_id
                     LEFT JOIN lines l ON l.id=t.line_id ORDER BY t.tool_no""")
    for r in rows:
        if r["service_interval_shots"]:
            r["life_used_pct"] = round(100 * r["shots_since_service"]
                                       / r["service_interval_shots"], 1)
    con.close()
    return rows


# ---------------------------------------------------- quality: defects
@router.get("/defects/")
def defects(status: str = "", source: str = "", severity: str = "",
            user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT d.*, p.part_no, r.run_no, rl.lot_no raw_lot_no,
             fl.lot_no finished_lot_no, m.asset_no machine_no, c.name customer_name
             FROM defects d LEFT JOIN parts p ON p.id=d.part_id
             LEFT JOIN runs r ON r.id=d.run_id
             LEFT JOIN raw_lots rl ON rl.id=d.raw_lot_id
             LEFT JOIN finished_lots fl ON fl.id=d.finished_lot_id
             LEFT JOIN machines m ON m.id=d.machine_id
             LEFT JOIN customers c ON c.id=d.customer_id WHERE 1=1"""
    args = []
    if status:
        sql += " AND d.status=?"; args.append(status)
    if source:
        sql += " AND d.source=?"; args.append(source)
    if severity:
        sql += " AND d.severity=?"; args.append(severity)
    rows = q(con, sql + " ORDER BY d.found_at DESC", tuple(args))
    con.close()
    return rows


@router.get("/defects/pareto")
def defect_pareto(days: int = 90, user: dict = Depends(current_user)):
    con = connect()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = q(con, """SELECT code, COUNT(*) events, SUM(qty) units,
                     SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END) critical
                     FROM defects WHERE found_at >= ?
                     GROUP BY code ORDER BY units DESC""", (since,))
    con.close()
    return rows


@router.post("/defects/")
async def defect_create(req: Request, user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor", "line_lead", "quality")
    body = await req.json()
    con = connect()
    n = q1(con, "SELECT COUNT(*) n FROM defects")["n"]
    dno = f"DEF-{900 + n}"
    run = q1(con, "SELECT id FROM runs WHERE run_no=?", (body.get("run_no") or "",))
    part = q1(con, "SELECT id FROM parts WHERE part_no=?", (body.get("part_no") or "",))
    con.execute("""INSERT INTO defects (defect_no, source, run_id, part_id, station,
                   code, description, severity, qty, disposition, found_by, found_at,
                   status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'open')""",
                (dno, body.get("source") or "in_process", run and run["id"],
                 part and part["id"], body.get("station"), body.get("code"),
                 body.get("description"), body.get("severity") or "minor",
                 float(body.get("qty") or 0), body.get("disposition") or "rework",
                 user["name"], now()))
    audit_log(con, user["email"], "defect", "defect", dno,
              body.get("description") or "")
    con.commit()
    con.close()
    return {"ok": True, "defect_no": dno}


# ------------------------------------------------------ quality: holds
HOLD_STATUS_ALIASES = {
    "blocked": "open", "block": "open", "held": "open", "hold": "open",
    "on_hold": "open", "on-hold": "open", "onhold": "open",
    "quarantine": "open", "quarantined": "open", "active": "open",
}


@router.get("/holds/")
def holds(status: str = "", user: dict = Depends(current_user)):
    """List quality holds. status: 'open' for holds currently blocking or
    quarantining material on site (aliases blocked, held, on_hold, quarantine
    also accepted), or 'released' for holds that have been cleared."""
    con = connect()
    sql = "SELECT * FROM holds WHERE 1=1"
    args = []
    if status:
        status = HOLD_STATUS_ALIASES.get(status.strip().lower(), status)
        sql += " AND status=?"; args.append(status)
    rows = q(con, sql + " ORDER BY placed_at DESC", tuple(args))
    for r in rows:
        label = None
        if r["scope"] == "raw_lot":
            x = q1(con, "SELECT lot_no FROM raw_lots WHERE id=?", (r["scope_id"],))
            label = x and x["lot_no"]
        elif r["scope"] == "finished_lot":
            x = q1(con, "SELECT lot_no FROM finished_lots WHERE id=?", (r["scope_id"],))
            label = x and x["lot_no"]
        elif r["scope"] == "run":
            x = q1(con, "SELECT run_no FROM runs WHERE id=?", (r["scope_id"],))
            label = x and x["run_no"]
        r["scope_label"] = label
    con.close()
    return rows


HOLD_SCOPE_TABLE = {"raw_lot": ("raw_lots", "lot_no"),
                    "finished_lot": ("finished_lots", "lot_no"),
                    "run": ("runs", "run_no")}


@router.post("/holds/")
async def hold_create(req: Request, user: dict = Depends(current_user)):
    """Place a new quality hold/quarantine (containment action). scope: one of
    raw_lot, finished_lot, run; scope_no: that record's lot/run number."""
    require(user, "quality")
    body = await req.json()
    scope = body.get("scope") or ""
    scope_no = (body.get("scope_no") or "").strip()
    reason = (body.get("reason") or "").strip()
    if scope not in HOLD_SCOPE_TABLE or not scope_no or not reason:
        raise HTTPException(422, "scope (raw_lot/finished_lot/run), scope_no and "
                                  "reason are required")
    table, col = HOLD_SCOPE_TABLE[scope]
    con = connect()
    rec = q1(con, f"SELECT id FROM {table} WHERE {col}=?", (scope_no,))
    if not rec:
        con.close()
        raise HTTPException(404, f"{scope} {scope_no} not found")
    existing = q1(con, """SELECT hold_no FROM holds WHERE scope=? AND scope_id=?
                          AND status='open'""", (scope, rec["id"]))
    if existing:
        con.close()
        return {"ok": True, "hold_no": existing["hold_no"], "already_open": True}
    n = q1(con, "SELECT COUNT(*) n FROM holds")["n"]
    hold_no = f"HLD-{146 + n:04d}"
    con.execute("""INSERT INTO holds (hold_no, scope, scope_id, reason, placed_by,
                   placed_at, status) VALUES (?,?,?,?,?,?,'open')""",
                (hold_no, scope, rec["id"], reason, user["name"], now()))
    if scope == "finished_lot":
        con.execute("UPDATE finished_lots SET status='hold' WHERE id=?", (rec["id"],))
    audit_log(con, user["email"], "hold", scope, scope_no, reason)
    con.commit()
    con.close()
    return {"ok": True, "hold_no": hold_no, "already_open": False}


@router.post("/holds/{hold_no}/release")
async def hold_release(hold_no: str, req: Request, user: dict = Depends(current_user)):
    require(user, "quality")
    body = await req.json()
    con = connect()
    h = q1(con, "SELECT * FROM holds WHERE hold_no=?", (hold_no,))
    if not h:
        con.close()
        raise HTTPException(404, "Hold not found")
    if h["status"] != "open":
        con.close()
        raise HTTPException(422, "Hold already released")
    con.execute("""UPDATE holds SET status='released', released_at=?, released_by=?
                   WHERE id=?""", (now(), user["name"], h["id"]))
    audit_log(con, user["email"], "release_hold", "hold", hold_no,
              body.get("reason") or "")
    con.commit()
    con.close()
    return {"ok": True}


# --------------------------------------------------------------- reports
@router.get("/reports/throughput")
def report_throughput(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT l.code line, strftime('%Y-%W', r.completed_at) week,
                     SUM(r.qty_good) good, SUM(r.qty_scrap) scrap
                     FROM runs r JOIN lines l ON l.id=r.line_id
                     WHERE r.completed_at IS NOT NULL
                     GROUP BY l.code, week ORDER BY week""")
    con.close()
    return rows


@router.get("/reports/scrap")
def report_scrap(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT p.family, SUM(r.qty_scrap) scrap_units,
                     ROUND(SUM(r.qty_scrap*p.std_cost),2) scrap_cost,
                     ROUND(100.0*SUM(r.qty_scrap)/NULLIF(SUM(r.qty_good+r.qty_scrap),0),2)
                       scrap_pct
                     FROM runs r JOIN parts p ON p.id=r.part_id
                     WHERE r.completed_at IS NOT NULL GROUP BY p.family""")
    con.close()
    return rows


@router.get("/reports/margin")
def report_margin(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT p.family, p.part_no, p.name,
                     SUM(sol.qty) units, ROUND(SUM(sol.line_total),2) revenue,
                     ROUND(SUM(sol.qty*p.std_cost),2) std_cost,
                     ROUND(100.0*(SUM(sol.line_total)-SUM(sol.qty*p.std_cost))
                           /NULLIF(SUM(sol.line_total),0),1) margin_pct
                     FROM sales_order_lines sol
                     JOIN sales_orders so ON so.id=sol.sales_order_id
                     JOIN parts p ON p.id=sol.part_id
                     WHERE so.status IN ('fulfilled','in_production','approved')
                     GROUP BY p.part_no ORDER BY revenue DESC""")
    con.close()
    return rows


@router.get("/reports/customer-ppm")
def report_ppm(days: int = 90, user: dict = Depends(current_user)):
    con = connect()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = q(con, "SELECT id, code, name, ppm_target FROM customers")
    for r in rows:
        shipped = q1(con, """SELECT COALESCE(SUM(sl.qty),0) n FROM shipment_lines sl
                             JOIN shipments sh ON sh.id=sl.shipment_id
                             WHERE sh.customer_id=? AND sh.shipped_on >= ?""",
                     (r["id"], since))["n"]
        dq = q1(con, """SELECT COALESCE(SUM(qty),0) n FROM defects
                        WHERE source='customer' AND customer_id=? AND found_at >= ?""",
                (r["id"], since))["n"]
        r["shipped"] = shipped
        r["defect_units"] = dq
        r["ppm"] = round(dq / shipped * 1_000_000) if shipped else 0
        r["within_target"] = r["ppm"] <= r["ppm_target"] if shipped else True
    con.close()
    return rows


@router.get("/reports/ship-date-performance")
def report_sla(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT so.so_no, so.promised_date, c.name customer_name,
                     MIN(sh.shipped_on) first_ship
                     FROM sales_orders so JOIN customers c ON c.id=so.customer_id
                     LEFT JOIN shipments sh ON sh.sales_order_id=so.id
                     WHERE so.status='fulfilled' GROUP BY so.id""")
    for r in rows:
        r["on_time"] = bool(r["first_ship"] and r["promised_date"]
                            and r["first_ship"] <= r["promised_date"])
    at_risk = q(con, """SELECT so.so_no, so.promised_date, so.status,
                        c.name customer_name,
                        (SELECT COUNT(*) FROM runs r WHERE r.sales_order_id=so.id
                          AND r.status IN ('planned','released','in_progress',
                          'quality_hold')) open_runs
                        FROM sales_orders so JOIN customers c ON c.id=so.customer_id
                        WHERE so.status IN ('approved','in_production')
                        ORDER BY so.promised_date""")
    con.close()
    return {"history": rows, "open_orders": at_risk}


@router.get("/reports/utilisation")
def report_utilisation(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT o.name, o.emp_no, l.code line, o.shift,
                     COALESCE(SUM(rt.minutes),0)/60.0 hours_logged
                     FROM operators o LEFT JOIN run_time rt ON rt.operator_id=o.id
                     LEFT JOIN lines l ON l.id=o.line_id
                     WHERE o.status='active' GROUP BY o.id
                     ORDER BY hours_logged DESC""")
    con.close()
    return rows


# ------------------------------------------------- settings, audit, misc
@router.get("/settings/")
def settings_get(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, "SELECT * FROM settings")
    con.close()
    return {r["key"]: r["value"] for r in rows}


@router.put("/settings/")
async def settings_put(req: Request, user: dict = Depends(current_user)):
    require(user, "admin")
    body = await req.json()
    con = connect()
    for k, v in body.items():
        con.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=?", (k, str(v), str(v)))
        audit_log(con, user["email"], "setting", "settings", k, str(v))
    con.commit()
    con.close()
    return {"ok": True}


@router.get("/audit/")
def audit(entity: str = "", limit: int = 100, user: dict = Depends(current_user)):
    con = connect()
    sql = "SELECT * FROM audit WHERE 1=1"
    args = []
    if entity:
        sql += " AND entity=?"; args.append(entity)
    rows = q(con, sql + " ORDER BY at DESC LIMIT ?", (*args, min(limit, 500)))
    con.close()
    return rows


@router.get("/notifications/")
def notifications(user: dict = Depends(current_user)):
    con = connect()
    role = user["role"]
    rows = q(con, """SELECT * FROM notifications
                     WHERE role=? OR ?='admin' ORDER BY created_at DESC""",
             (role, role))
    con.close()
    return rows


@router.post("/notifications/{nid}/read")
def notification_read(nid: int, user: dict = Depends(current_user)):
    con = connect()
    con.execute("UPDATE notifications SET read=1 WHERE id=?", (nid,))
    con.commit()
    con.close()
    return {"ok": True}


@router.post("/notifications/read-all")
def notifications_read_all(user: dict = Depends(current_user)):
    con = connect()
    con.execute("UPDATE notifications SET read=1")
    con.commit()
    con.close()
    return {"ok": True}


# ------------------------------------------------------------- recurring
@router.get("/recurring/")
def recurring(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, """SELECT rc.*, p.part_no, p.name part_name, c.name customer_name,
                     l.code line_code, r.run_no last_run_no
                     FROM recurring rc JOIN parts p ON p.id=rc.part_id
                     LEFT JOIN customers c ON c.id=rc.customer_id
                     LEFT JOIN lines l ON l.id=rc.line_id
                     LEFT JOIN runs r ON r.id=rc.last_generated_run_id
                     ORDER BY rc.next_run_date""")
    con.close()
    return rows


@router.post("/recurring/run")
def recurring_run(user: dict = Depends(current_user)):
    require(user, "plant_manager", "supervisor")
    con = connect()
    today = date.today().isoformat()
    due = q(con, "SELECT * FROM recurring WHERE active=1 AND next_run_date <= ?",
            (today,))
    created = []
    for rc in due:
        n = q1(con, "SELECT COUNT(*) n FROM runs")["n"]
        run_no = f"RUN-{1111 + n}"
        p = q1(con, "SELECT * FROM parts WHERE id=?", (rc["part_id"],))
        cur = con.execute(
            """INSERT INTO runs (run_no, part_id, qty_planned, line_id, status,
               scheduled_start, scheduled_end, std_cost, notes)
               VALUES (?,?,?,?, 'planned', ?, ?, ?, ?)""",
            (run_no, rc["part_id"], rc["qty"], rc["line_id"],
             rc["next_run_date"],
             (date.fromisoformat(rc["next_run_date"]) + timedelta(days=4)).isoformat(),
             round((p["std_cost"] or 0) * rc["qty"], 2),
             f"Auto-generated from schedule: {rc['name']}"))
        days = {"weekly": 7, "fortnightly": 14, "monthly": 30}.get(rc["cadence"], 7)
        con.execute("""UPDATE recurring SET next_run_date=?, last_generated_run_id=?
                       WHERE id=?""",
                    ((date.fromisoformat(rc["next_run_date"])
                      + timedelta(days=days)).isoformat(), cur.lastrowid, rc["id"]))
        audit_log(con, user["email"], "generate", "run", run_no,
                  f"from schedule {rc['name']}")
        created.append(run_no)
    con.commit()
    con.close()
    return {"ok": True, "created": created}


# ----------------------------------------------------------- attachments
@router.get("/attachments/")
def attachments(entity: str = "", entity_id: int = 0,
                user: dict = Depends(current_user)):
    con = connect()
    sql = "SELECT * FROM attachments WHERE 1=1"
    args = []
    if entity:
        sql += " AND entity=?"; args.append(entity)
    if entity_id:
        sql += " AND entity_id=?"; args.append(entity_id)
    rows = q(con, sql, tuple(args))
    con.close()
    return rows


@router.get("/attachments/{aid}/download")
def attachment_download(aid: int, token: str = ""):
    if not (token and _verify(token)):
        raise HTTPException(401, "Not authenticated")
    con = connect()
    a = q1(con, "SELECT * FROM attachments WHERE id=?", (aid,))
    con.close()
    if not a:
        raise HTTPException(404, "Attachment not found")
    return FileResponse(ROOT / a["path"], media_type=a["content_type"],
                        filename=a["filename"])


# --------------------------------------------------------- access tokens
@router.get("/access-tokens/")
def access_tokens(user: dict = Depends(current_user)):
    require(user, "admin")
    con = connect()
    rows = q(con, "SELECT id, name, created_at, last_used, "
                  "substr(token,1,12)||'...' token_preview FROM access_tokens")
    con.close()
    return rows


@router.post("/access-tokens/")
async def access_token_create(req: Request, user: dict = Depends(current_user)):
    require(user, "admin")
    body = await req.json()
    con = connect()
    tok = "tc_live_" + secrets.token_hex(8)
    con.execute("INSERT INTO access_tokens (name, token, created_at) VALUES (?,?,?)",
                (body.get("name") or "API token", tok, now()))
    audit_log(con, user["email"], "create", "access_token", body.get("name") or "", "")
    con.commit()
    con.close()
    return {"ok": True, "token": tok,
            "note": "Shown once - store it in your integration's secret store."}


@router.delete("/access-tokens/{tid}")
def access_token_delete(tid: int, user: dict = Depends(current_user)):
    require(user, "admin")
    con = connect()
    con.execute("DELETE FROM access_tokens WHERE id=?", (tid,))
    audit_log(con, user["email"], "delete", "access_token", tid, "")
    con.commit()
    con.close()
    return {"ok": True}


# ------------------------------------------------------ AP invoices (UC2)
# Deterministic error-code catalogue - the fix and authority are FACTS the
# plant's AP policy sets, never left for the model to invent. The AI layer
# (ai.py) only phrases these in plain English and grounds the policy citation
# in the KB corpus; every figure here is used exactly as written.
AP_ERROR_CODES = {
    "GL-4102": {"label": "GL cost centre closed",
        "root_cause_group": "vendor_master_cost_center",
        "plain_english": "The vendor master record for this supplier still "
            "points at cost centre CC-410, which was closed when the plant's "
            "cost centres were restructured. Every invoice from that vendor "
            "fails GL validation until the vendor master is corrected - this "
            "is a vendor-master problem, not a per-invoice one.",
        "fix": "Update the vendor master's cost centre from CC-410 to CC-430, "
            "then re-post. This one correction clears every failed invoice "
            "from the same vendor, not just this one.",
        "authority": "AP clerk - correcting a vendor master field and "
            "reposting the affected invoices is within the AP clerk's "
            "standing delegation (FIN-AP-03), provided each invoice is under "
            "the per-invoice approval limit.",
        "policy_ref": "FIN-AP-03", "escalate": False},
    "PO-QTY-VAR": {"label": "PO quantity/price variance beyond tolerance",
        "root_cause_group": None,
        "plain_english": "The invoiced quantity or unit price sits outside "
            "the 2 per cent three-way-match tolerance against the purchase "
            "order line.",
        "fix": "Confirm the correct quantity/price with the buyer, adjust "
            "the invoice to match the PO (or raise a PO amendment), then "
            "re-post.",
        "authority": "AP clerk can adjust and re-post within the tolerance "
            "uplift once the buyer confirms in writing (FIN-AP-01).",
        "policy_ref": "FIN-AP-01", "escalate": False},
    "DUP-CHK": {"label": "Possible duplicate invoice number",
        "root_cause_group": None,
        "plain_english": "This vendor invoice number is a close match to one "
            "already posted this quarter - the system held it rather than "
            "risk a double payment.",
        "fix": "Compare against the prior invoice; if genuinely new, clear "
            "the duplicate flag with a note; if it is a duplicate, reject it "
            "and notify the vendor.",
        "authority": "AP clerk can clear the flag once confirmed genuine "
            "(FIN-AP-02).",
        "policy_ref": "FIN-AP-02", "escalate": False},
    "TAX-INV": {"label": "GST code mismatch", "root_cause_group": None,
        "plain_english": "The GST code on one or more lines does not match "
            "the vendor's registered GST treatment.",
        "fix": "Correct the line GST code to the vendor's registered "
            "treatment and re-post.",
        "authority": "AP clerk, standing delegation (FIN-AP-04).",
        "policy_ref": "FIN-AP-04", "escalate": False},
    "3WM-FAIL": {"label": "Three-way match failure - goods not yet receipted",
        "root_cause_group": None,
        "plain_english": "The invoice references a purchase order line with "
            "no goods receipt recorded yet, so the three-way match (PO, "
            "receipt, invoice) cannot complete.",
        "fix": "Hold until the goods receipt is posted, or confirm with the "
            "warehouse that receipt is outstanding and expedite it.",
        "authority": "AP clerk can hold the invoice; only the warehouse can "
            "complete the goods receipt (FIN-AP-01).",
        "policy_ref": "FIN-AP-01", "escalate": False},
    "CURR-RND": {"label": "Rounding tolerance breach", "root_cause_group": None,
        "plain_english": "The invoice total is a few cents outside the "
            "automatic rounding tolerance against the PO and GST calculation.",
        "fix": "Recalculate and correct the rounding on the invoice line, "
            "then re-post.",
        "authority": "AP clerk, standing delegation (FIN-AP-04).",
        "policy_ref": "FIN-AP-04", "escalate": False},
    "BANK-VER": {"label": "New bank details pending verification",
        "root_cause_group": None,
        "plain_english": "The vendor recently changed their bank details. "
            "Banking changes are held for independent verification before "
            "any payment can be released, as a fraud-prevention control.",
        "fix": "Treasury must complete the callback verification with the "
            "vendor before the hold can be released.",
        "authority": "Requires treasury/controller sign-off (FIN-AP-05) - the "
            "AP clerk cannot clear a banking-detail hold, regardless of "
            "amount. This one stays outside today's batch.",
        "policy_ref": "FIN-AP-05", "escalate": True},
}


@router.get("/ap-invoices/")
def ap_invoices_list(status: str = "", user: dict = Depends(current_user)):
    con = connect()
    sql = """SELECT ai.*, s.name supplier_name, s.code supplier_code
             FROM ap_invoices ai JOIN suppliers s ON s.id=ai.supplier_id
             WHERE 1=1"""
    args = []
    if status:
        sql += " AND ai.status=?"; args.append(status)
    rows = q(con, sql + " ORDER BY ai.ap_no", tuple(args))
    limit = float(q1(con, "SELECT value FROM settings WHERE "
                         "key='ap_clerk_approval_limit'")["value"])
    for r in rows:
        cat = AP_ERROR_CODES.get(r["error_code"], {})
        r["error_label"] = cat.get("label")
        r["within_clerk_authority"] = (not cat.get("escalate")
                                       and r["amount"] <= limit)
    con.close()
    return rows


@router.get("/ap-invoices/{ap_no}")
def ap_invoice_detail(ap_no: str, user: dict = Depends(current_user)):
    con = connect()
    row = q1(con, """SELECT ai.*, s.name supplier_name, s.code supplier_code,
                     s.cost_center, po.po_no FROM ap_invoices ai
                     JOIN suppliers s ON s.id=ai.supplier_id
                     LEFT JOIN purchase_orders po ON po.id=ai.po_id
                     WHERE ai.ap_no=?""", (ap_no,))
    con.close()
    if not row:
        raise HTTPException(404, "AP invoice not found")
    cat = AP_ERROR_CODES.get(row["error_code"], {})
    row["catalogue"] = cat
    return row


def ap_similar_group(con, ap_no: str) -> dict | None:
    """Deterministic shared-root-cause grouping - the 'are there others like
    this?' step. No LLM involved: this is a plain SQL group-by, reused by
    both the /similar endpoint and the ai.py batch-fix narrative digest."""
    row = q1(con, "SELECT * FROM ap_invoices WHERE ap_no=?", (ap_no,))
    if not row:
        return None
    cat = AP_ERROR_CODES.get(row["error_code"], {})
    group = cat.get("root_cause_group")
    limit = float(q1(con, "SELECT value FROM settings WHERE "
                         "key='ap_clerk_approval_limit'")["value"])
    if not group:
        return {"ap_no": ap_no, "root_cause_group": None, "similar": [],
                "note": "This failure does not share a root cause with any "
                        "other invoice in today's queue - it is a one-off."}
    rows = q(con, """SELECT ai.ap_no, ai.amount, ai.status, ai.error_code,
                     s.name supplier_name, s.code supplier_code
                     FROM ap_invoices ai JOIN suppliers s ON s.id=ai.supplier_id
                     WHERE ai.root_cause_group=? ORDER BY ai.ap_no""", (group,))
    total = sum(r["amount"] for r in rows)
    all_within = all(r["amount"] <= limit and not cat.get("escalate")
                     for r in rows)
    return {"ap_no": ap_no, "root_cause_group": group, "similar": rows,
            "count": len(rows), "total_amount": round(total, 2),
            "approval_limit": limit, "all_within_clerk_authority": all_within}


@router.get("/ap-invoices/{ap_no}/similar")
def ap_invoice_similar(ap_no: str, user: dict = Depends(current_user)):
    con = connect()
    out = ap_similar_group(con, ap_no)
    con.close()
    if out is None:
        raise HTTPException(404, "AP invoice not found")
    return out


@router.post("/ap-invoices/batch-fix")
async def ap_batch_fix(req: Request, user: dict = Depends(current_user)):
    """Correct the shared root cause and post the whole batch in one approval
    act - the deck's 'reviews one proposed correction covering all 9
    invoices ... clicks approve' step."""
    require(user, "finance", "admin")
    body = await req.json()
    ap_nos = body.get("ap_nos") or []
    new_cost_center = (body.get("new_cost_center") or "CC-430").strip()
    if not ap_nos:
        raise HTTPException(422, "ap_nos required")
    con = connect()
    limit = float(q1(con, "SELECT value FROM settings WHERE "
                         "key='ap_clerk_approval_limit'")["value"])
    rows = q(con, f"""SELECT * FROM ap_invoices WHERE ap_no IN
                     ({','.join('?'*len(ap_nos))})""", tuple(ap_nos))
    if len(rows) != len(ap_nos):
        con.close()
        raise HTTPException(404, "One or more AP invoices not found")
    groups = {r["root_cause_group"] for r in rows}
    if groups != {"vendor_master_cost_center"}:
        con.close()
        raise HTTPException(422, "All invoices in a batch fix must share the "
                                  "vendor_master_cost_center root cause")
    over_limit = [r["ap_no"] for r in rows if r["amount"] > limit]
    if over_limit:
        con.close()
        raise HTTPException(403, f"Over the AP clerk approval limit "
                                  f"(${limit:,.2f}): {', '.join(over_limit)} - "
                                  f"needs controller sign-off")
    supplier_ids = {r["supplier_id"] for r in rows}
    policy_ref = AP_ERROR_CODES["GL-4102"]["policy_ref"]
    for sid in supplier_ids:
        con.execute("UPDATE suppliers SET cost_center=? WHERE id=?",
                    (new_cost_center, sid))
    ts = now()
    for r in rows:
        con.execute("""UPDATE ap_invoices SET status='posted', posted_on=?,
                       approved_by=?, approved_at=?, policy_ref=?
                       WHERE id=?""",
                    (ts, user["name"], ts, policy_ref, r["id"]))
        audit_log(con, user["email"], "batch_fix_post", "ap_invoice", r["ap_no"],
                  f"Vendor master cost centre corrected CC-410 -> "
                  f"{new_cost_center}; posted per {policy_ref}; "
                  f"${r['amount']:,.2f}")
    con.commit()
    con.close()
    return {"ok": True, "posted": len(rows),
            "total_amount": round(sum(r["amount"] for r in rows), 2),
            "policy_ref": policy_ref}


# --------------------------------------------------- expedite requests (UC3)
@router.get("/expedite-requests/")
def expedite_requests_list(status: str = "", user: dict = Depends(current_user)):
    con = connect()
    sql = "SELECT * FROM expedite_requests WHERE 1=1"
    args = []
    if status:
        sql += " AND status=?"; args.append(status)
    rows = q(con, sql + " ORDER BY requested_at DESC", tuple(args))
    con.close()
    return rows


@router.post("/expedite-requests/")
async def expedite_request_create(req: Request, user: dict = Depends(current_user)):
    """Propose pulling a confirmed PO's expected date in - the 'supplier rush
    request' half of the CTP commit act. Creating it is a proposal only; it
    takes no effect on the schedule until a production planner approves it."""
    require(user, "sales", "plant_manager", "supervisor", "admin")
    body = await req.json()
    po_no = body.get("po_no")
    con = connect()
    po = q1(con, "SELECT * FROM purchase_orders WHERE po_no=?", (po_no,))
    if not po:
        con.close()
        raise HTTPException(404, f"PO {po_no} not found")
    cur = con.execute("""INSERT INTO expedite_requests (po_no, part_no,
                       requested_by, requested_at, current_expected,
                       requested_expected, reason, linked_so_no, status)
                       VALUES (?,?,?,?,?,?,?,?,'pending')""",
                (po_no, body.get("part_no"), user["name"], now(),
                 po["expected_date"], body.get("requested_expected"),
                 body.get("reason"), body.get("linked_so_no")))
    audit_log(con, user["email"], "propose_expedite", "purchase_order", po_no,
              f"Requested pull-in to {body.get('requested_expected')}")
    con.commit()
    rid = cur.lastrowid
    con.close()
    return {"ok": True, "id": rid, "status": "pending"}


@router.post("/expedite-requests/{rid}/approve")
def expedite_request_approve(rid: int, user: dict = Depends(current_user)):
    """Schedule-touching action - production-planner authority only (plant
    manager / supervisor), never the sales role that proposed it."""
    require(user, "plant_manager", "supervisor")
    con = connect()
    r = q1(con, "SELECT * FROM expedite_requests WHERE id=?", (rid,))
    if not r:
        con.close()
        raise HTTPException(404, "Expedite request not found")
    if r["status"] != "pending":
        con.close()
        raise HTTPException(422, f"Already {r['status']}")
    con.execute("UPDATE purchase_orders SET expected_date=? WHERE po_no=?",
               (r["requested_expected"], r["po_no"]))
    con.execute("""UPDATE expedite_requests SET status='approved',
                   approved_by=?, approved_at=? WHERE id=?""",
                (user["name"], now(), rid))
    audit_log(con, user["email"], "approve_expedite", "purchase_order",
              r["po_no"], f"Pulled in to {r['requested_expected']}"
              + (f" (linked to {r['linked_so_no']})" if r["linked_so_no"] else ""))
    # deliberately independent of the linked sales order's own approval -
    # Hans (sales) commits to the customer on the call via his own
    # /sales-orders/{so_no}/approve call; the production planner's sign-off
    # here only ever touches the production schedule (the PO date), never
    # the customer-facing order status - two separate authorities, two
    # separate approval acts.
    con.commit()
    con.close()
    return {"ok": True}


# -------------------------------------------------------- 8D reports (UC1)
@router.get("/8d-reports/")
def eight_d_reports_list(user: dict = Depends(current_user)):
    con = connect()
    rows = q(con, "SELECT * FROM eight_d_reports ORDER BY created_at DESC")
    con.close()
    return rows


@router.post("/8d-reports/")
async def eight_d_report_save(req: Request, user: dict = Depends(current_user)):
    """Save (and, for a quality user, approve) an edited 8D draft - Linda
    edits the AI's draft and approves instead of writing from scratch."""
    body = await req.json()
    approve = bool(body.get("approve"))
    if approve:
        require(user, "quality")
    con = connect()
    n = q1(con, "SELECT COUNT(*) n FROM eight_d_reports")["n"]
    report_no = f"8D-{4400 + n}"
    ts = now()
    con.execute("""INSERT INTO eight_d_reports (report_no, line_code,
                   window_start, window_end, fpy, problem, root_cause,
                   containment, corrective_action, body, status, created_by,
                   created_at, approved_by, approved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (report_no, body.get("line_code"), body.get("window_start"),
                 body.get("window_end"), body.get("fpy"), body.get("problem"),
                 body.get("root_cause"), body.get("containment"),
                 body.get("corrective_action"), body.get("body"),
                 "approved" if approve else "draft", user["name"], ts,
                 user["name"] if approve else None, ts if approve else None))
    audit_log(con, user["email"], "approve" if approve else "save",
              "eight_d_report", report_no, "")
    con.commit()
    con.close()
    return {"ok": True, "report_no": report_no,
            "status": "approved" if approve else "draft"}


# ---------------------------------------------------------------- system
@router.post("/system/reset")
def system_reset(user: dict = Depends(current_user)):
    require(user, "admin")
    import seed_db
    seed_db.main()
    return {"ok": True, "note": "Demo data reset to the seeded state."}


@router.get("/system/info")
def system_info(user: dict = Depends(current_user)):
    con = connect()
    counts = {}
    for t in ["customers", "parts", "runs", "sales_orders", "shipments",
              "raw_lots", "finished_lots", "defects", "holds"]:
        counts[t] = q1(con, f"SELECT COUNT(*) n FROM {t}")["n"]
    con.close()
    return {"app": "Tallowa Components - Plant Operations", "records": counts}
