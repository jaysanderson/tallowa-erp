"""Tallowa Components ERP - SQLite store.

Single-file schema + helpers. The web app never touches this directly - it goes
through the /api/* surface (API-first, same shape as the reference build).
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "erp.db"

SCHEMA = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, role TEXT, pw_hash TEXT);

CREATE TABLE customers (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, type TEXT, contact_name TEXT,
  email TEXT, phone TEXT, city TEXT, state TEXT, payment_terms INTEGER,
  ppm_target INTEGER, status TEXT DEFAULT 'active');

CREATE TABLE ship_tos (
  id INTEGER PRIMARY KEY, customer_id INTEGER, name TEXT, address TEXT,
  city TEXT, state TEXT);

CREATE TABLE plants (id INTEGER PRIMARY KEY, code TEXT, name TEXT, city TEXT);

CREATE TABLE lines (
  id INTEGER PRIMARY KEY, plant_id INTEGER, code TEXT, name TEXT,
  process_type TEXT, takt_seconds INTEGER, status TEXT DEFAULT 'running',
  stoppage_reason TEXT);

CREATE TABLE operators (
  id INTEGER PRIMARY KEY, emp_no TEXT UNIQUE, name TEXT, role TEXT,
  line_id INTEGER, shift TEXT, hourly_rate REAL, status TEXT DEFAULT 'active',
  notes TEXT);

CREATE TABLE skills (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, renew_months INTEGER);

CREATE TABLE operator_skills (
  id INTEGER PRIMARY KEY, operator_id INTEGER, skill_id INTEGER,
  certified_on TEXT, expires_on TEXT);

CREATE TABLE parts (
  id INTEGER PRIMARY KEY, part_no TEXT UNIQUE, name TEXT, family TEXT,
  category TEXT, uom TEXT DEFAULT 'ea', std_cost REAL, price REAL,
  reorder_point REAL, reorder_qty REAL, traceable INTEGER DEFAULT 0,
  safety_critical INTEGER DEFAULT 0, preferred_supplier_id INTEGER);

CREATE TABLE customer_parts (
  id INTEGER PRIMARY KEY, customer_id INTEGER, part_id INTEGER,
  customer_part_no TEXT, price REAL);

CREATE TABLE boms (
  id INTEGER PRIMARY KEY, parent_part_id INTEGER, component_part_id INTEGER,
  qty_per REAL, station TEXT, note TEXT);

CREATE TABLE locations (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, type TEXT, line_id INTEGER);

CREATE TABLE stock (
  id INTEGER PRIMARY KEY, part_id INTEGER, location_id INTEGER, qty REAL,
  UNIQUE(part_id, location_id));

CREATE TABLE stock_movements (
  id INTEGER PRIMARY KEY, part_id INTEGER, from_location_id INTEGER,
  to_location_id INTEGER, qty REAL, reason TEXT, ref TEXT, moved_at TEXT);

CREATE TABLE raw_lots (
  id INTEGER PRIMARY KEY, lot_no TEXT UNIQUE, part_id INTEGER, supplier_id INTEGER,
  po_id INTEGER, received_on TEXT, qty_received REAL, qty_remaining REAL,
  coa_ref TEXT, status TEXT DEFAULT 'available');

CREATE TABLE runs (
  id INTEGER PRIMARY KEY, run_no TEXT UNIQUE, part_id INTEGER, qty_planned REAL,
  qty_good REAL DEFAULT 0, qty_scrap REAL DEFAULT 0, line_id INTEGER,
  status TEXT DEFAULT 'planned', priority TEXT DEFAULT 'normal',
  scheduled_start TEXT, scheduled_end TEXT, sales_order_id INTEGER,
  started_at TEXT, completed_at TEXT, std_cost REAL DEFAULT 0,
  actual_cost REAL DEFAULT 0, notes TEXT);

CREATE TABLE run_materials (
  id INTEGER PRIMARY KEY, run_id INTEGER, part_id INTEGER, raw_lot_id INTEGER,
  qty REAL, cost REAL);

CREATE TABLE run_time (
  id INTEGER PRIMARY KEY, run_id INTEGER, operator_id INTEGER, station TEXT,
  minutes REAL, entered_at TEXT, note TEXT);

CREATE TABLE finished_lots (
  id INTEGER PRIMARY KEY, lot_no TEXT UNIQUE, part_id INTEGER, run_id INTEGER,
  qty_produced REAL, qty_shipped REAL DEFAULT 0, produced_on TEXT,
  status TEXT DEFAULT 'in_stock', location_id INTEGER);

CREATE TABLE sales_orders (
  id INTEGER PRIMARY KEY, so_no TEXT UNIQUE, customer_id INTEGER,
  customer_po TEXT, status TEXT DEFAULT 'draft', ship_to_id INTEGER,
  ordered_on TEXT, promised_date TEXT, subtotal REAL DEFAULT 0,
  gst REAL DEFAULT 0, total REAL DEFAULT 0, notes TEXT, lost_reason TEXT);

CREATE TABLE sales_order_lines (
  id INTEGER PRIMARY KEY, sales_order_id INTEGER, part_id INTEGER,
  customer_part_no TEXT, qty REAL, unit_price REAL, line_total REAL);

CREATE TABLE shipments (
  id INTEGER PRIMARY KEY, shp_no TEXT UNIQUE, sales_order_id INTEGER,
  customer_id INTEGER, ship_to_id INTEGER, status TEXT DEFAULT 'staged',
  shipped_on TEXT, carrier TEXT, asn_ref TEXT);

CREATE TABLE shipment_lines (
  id INTEGER PRIMARY KEY, shipment_id INTEGER, finished_lot_id INTEGER,
  part_id INTEGER, qty REAL, so_line_id INTEGER);

CREATE TABLE suppliers (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, category TEXT,
  tier INTEGER DEFAULT 2, contact_name TEXT, email TEXT, city TEXT, state TEXT,
  rating REAL, on_time_pct REAL, ppm INTEGER, status TEXT DEFAULT 'active',
  cost_center TEXT);

CREATE TABLE purchase_orders (
  id INTEGER PRIMARY KEY, po_no TEXT UNIQUE, supplier_id INTEGER,
  status TEXT DEFAULT 'draft', ordered_on TEXT, expected_date TEXT,
  received_on TEXT, total REAL DEFAULT 0);

CREATE TABLE purchase_order_lines (
  id INTEGER PRIMARY KEY, po_id INTEGER, part_id INTEGER, qty REAL,
  unit_cost REAL, received_qty REAL DEFAULT 0);

CREATE TABLE invoices (
  id INTEGER PRIMARY KEY, inv_no TEXT UNIQUE, customer_id INTEGER,
  sales_order_id INTEGER, shipment_id INTEGER, status TEXT DEFAULT 'draft',
  issued_on TEXT, due_on TEXT, subtotal REAL, gst REAL, total REAL, paid_on TEXT);

CREATE TABLE machines (
  id INTEGER PRIMARY KEY, asset_no TEXT UNIQUE, name TEXT, type TEXT,
  line_id INTEGER, make TEXT, commissioned_on TEXT, last_service TEXT,
  next_service_due TEXT, last_calibration TEXT, next_calibration_due TEXT,
  status TEXT DEFAULT 'running');

CREATE TABLE tooling (
  id INTEGER PRIMARY KEY, tool_no TEXT UNIQUE, name TEXT, type TEXT,
  part_id INTEGER, line_id INTEGER, shots_since_service INTEGER DEFAULT 0,
  service_interval_shots INTEGER, last_service TEXT, next_service_due TEXT,
  status TEXT DEFAULT 'in_service');

CREATE TABLE defects (
  id INTEGER PRIMARY KEY, defect_no TEXT UNIQUE, source TEXT, run_id INTEGER,
  finished_lot_id INTEGER, raw_lot_id INTEGER, part_id INTEGER,
  machine_id INTEGER, station TEXT, code TEXT, description TEXT, severity TEXT,
  qty REAL, disposition TEXT, found_by TEXT, found_at TEXT,
  status TEXT DEFAULT 'open', closed_at TEXT, customer_id INTEGER);

CREATE TABLE holds (
  id INTEGER PRIMARY KEY, hold_no TEXT UNIQUE, scope TEXT, scope_id INTEGER,
  reason TEXT, placed_by TEXT, placed_at TEXT, released_at TEXT,
  released_by TEXT, status TEXT DEFAULT 'open');

CREATE TABLE recurring (
  id INTEGER PRIMARY KEY, name TEXT, customer_id INTEGER, part_id INTEGER,
  qty REAL, line_id INTEGER, cadence TEXT, next_run_date TEXT,
  active INTEGER DEFAULT 1, last_generated_run_id INTEGER);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE audit (
  id INTEGER PRIMARY KEY, at TEXT, user_email TEXT, action TEXT, entity TEXT,
  entity_id TEXT, detail TEXT);

CREATE TABLE notifications (
  id INTEGER PRIMARY KEY, role TEXT, kind TEXT, title TEXT, body TEXT,
  link TEXT, created_at TEXT, read INTEGER DEFAULT 0);

CREATE TABLE attachments (
  id INTEGER PRIMARY KEY, entity TEXT, entity_id INTEGER, filename TEXT,
  content_type TEXT, size INTEGER, path TEXT, uploaded_at TEXT);

CREATE TABLE access_tokens (
  id INTEGER PRIMARY KEY, name TEXT, token TEXT UNIQUE, created_at TEXT,
  last_used TEXT);

CREATE TABLE playbook_templates (
  id INTEGER PRIMARY KEY, title TEXT, part_no TEXT, body TEXT, saved_by TEXT,
  saved_at TEXT);

CREATE TABLE eight_d_reports (
  id INTEGER PRIMARY KEY, report_no TEXT UNIQUE, line_code TEXT,
  window_start TEXT, window_end TEXT, fpy REAL, problem TEXT, root_cause TEXT,
  containment TEXT, corrective_action TEXT, body TEXT, status TEXT DEFAULT 'draft',
  created_by TEXT, created_at TEXT, approved_by TEXT, approved_at TEXT);

CREATE TABLE ap_invoices (
  id INTEGER PRIMARY KEY, ap_no TEXT UNIQUE, supplier_id INTEGER, po_id INTEGER,
  vendor_invoice_no TEXT, amount REAL, status TEXT DEFAULT 'failed',
  error_code TEXT, received_on TEXT, due_on TEXT, root_cause_group TEXT,
  posted_on TEXT, approved_by TEXT, approved_at TEXT, policy_ref TEXT, notes TEXT);

CREATE TABLE expedite_requests (
  id INTEGER PRIMARY KEY, po_no TEXT, part_no TEXT, requested_by TEXT,
  requested_at TEXT, current_expected TEXT, requested_expected TEXT, reason TEXT,
  linked_so_no TEXT, status TEXT DEFAULT 'pending', approved_by TEXT,
  approved_at TEXT);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def q(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def q1(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_log(con, user_email, action, entity, entity_id, detail=""):
    con.execute(
        "INSERT INTO audit (at, user_email, action, entity, entity_id, detail) "
        "VALUES (?,?,?,?,?,?)",
        (now(), user_email, action, entity, str(entity_id), detail))
