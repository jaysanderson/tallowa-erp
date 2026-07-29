"""Seed / reset the Tallowa Components ERP database (data/erp.db).

Deterministic synthetic data, date-anchored to today so every view paints live.
Everything - companies, people, part numbers, lots - is fictional.

  ../../.venv/bin/python seed_db.py          # (re)build the database
Also called by POST /api/system/reset (the 30-second reset).
"""
import hashlib
import random
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from database import DB_PATH, SCHEMA

ROOT = Path(__file__).resolve().parent
TODAY = date.today()


def d(offset_days: int) -> str:
    return (TODAY + timedelta(days=offset_days)).isoformat()


def ts(offset_days: int, hour=9, minute=0) -> str:
    base = datetime.combine(TODAY + timedelta(days=offset_days),
                            datetime.min.time(), tzinfo=timezone.utc)
    return (base + timedelta(hours=hour, minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pw(p: str) -> str:
    return hashlib.sha256(("tallowa:" + p).encode()).hexdigest()


def main():
    random.seed(42)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    cur = con.cursor()

    def ins(table, **cols):
        keys = ",".join(cols)
        marks = ",".join("?" * len(cols))
        cur.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})",
                    tuple(cols.values()))
        return cur.lastrowid

    # ---------------------------------------------------------------- users
    for email, name, role in [
        ("admin@tallowacomponents.com.au", "Avery Chen", "admin"),
        ("plant@tallowacomponents.com.au", "Morgan Riley", "plant_manager"),
        ("super@tallowacomponents.com.au", "Dana Okafor", "supervisor"),
        ("line@tallowacomponents.com.au", "Sam Patterson", "line_lead"),
        ("quality@tallowacomponents.com.au", "Priya Narayan", "quality"),
        ("ap@tallowacomponents.com.au", "Maria Costa", "finance"),
        ("sales@tallowacomponents.com.au", "Nate Ferris", "sales"),
    ]:
        ins("users", email=email, name=name, role=role, pw_hash=pw("demo1234"))

    # ------------------------------------------------------------- settings
    for k, v in [("gst_rate", "0.10"), ("currency", "AUD"),
                 ("margin_risk_threshold", "0.15"),
                 ("company_name", "Tallowa Components"),
                 ("plant_name", "Bellbrook Plant"),
                 ("ftt_target", "96.5"), ("ppm_target_sc", "25"),
                 ("ppm_target_overall", "50"),
                 ("ap_clerk_approval_limit", "5000")]:
        ins("settings", key=k, value=v)

    # ------------------------------------------------------------ customers
    C = {}
    for code, name, typ, contact, city, state, terms, ppm_t in [
        ("ELL", "Ellandra Motors", "oem", "Ruth Calloway", "Geelong", "VIC", 30, 15),
        ("MAR", "Marran Automotive", "oem", "Theo Brandt", "Melbourne", "VIC", 30, 25),
        ("SBT", "Southbank Truck Group", "oem", "Ida Larsen", "Brisbane", "QLD", 45, 35),
        ("ABD", "AllBrake Distribution", "aftermarket", "Col Whitford", "Sydney", "NSW", 30, 50),
        ("TTP", "Torrens Trade Parts", "aftermarket", "Mei Tan", "Adelaide", "SA", 14, 50),
        ("KOR", "Korrawin Assemblies", "oem", "Janek Wills", "Albury", "NSW", 30, 35),
    ]:
        C[code] = ins("customers", code=code, name=name, type=typ,
                      contact_name=contact,
                      email=f"purchasing@{code.lower()}-demo.example",
                      phone="03 5550 " + str(random.randint(1000, 9999)),
                      city=city, state=state, payment_terms=terms,
                      ppm_target=ppm_t, status="active")

    ST = {}
    for key, cust, name, addr, city, state in [
        ("ELL-CORIO", "ELL", "Ellandra Corio Assembly", "12 Broughton Way", "Corio", "VIC"),
        ("ELL-WESTH", "ELL", "Ellandra Westhaven Plant", "4 Keel Court", "Werribee", "VIC"),
        ("MAR-ALT", "MAR", "Marran Altona EV Plant", "88 Millers Rd", "Altona", "VIC"),
        ("SBT-DER", "SBT", "Southbank Derrimut Plant", "19 Foundation Dr", "Derrimut", "VIC"),
        ("ABD-DC", "ABD", "AllBrake National DC", "7 Hume Link", "Eastern Creek", "NSW"),
        ("TTP-DC", "TTP", "Torrens Trade Parts DC", "31 Port Rd", "Wingfield", "SA"),
        ("KOR-ALB", "KOR", "Korrawin Albury Plant", "2 Riverina Ave", "Albury", "NSW"),
    ]:
        ST[key] = ins("ship_tos", customer_id=C[cust], name=name, address=addr,
                      city=city, state=state)

    # --------------------------------------------------------- plant, lines
    plant = ins("plants", code="BEL", name="Bellbrook Plant", city="Bellbrook")
    L = {}
    for code, name, ptype, takt, status, reason in [
        ("S-1", "Stamping", "stamping", 8, "running", None),
        ("M-1", "CNC Machining 1", "machining", 432, "running", None),
        ("M-2", "CNC Machining 2", "machining", 380, "stopped",
         "Spindle bearing replacement on MC-M2-01 - maintenance in progress"),
        ("H-1", "Heat Treatment", "heat_treat", 900, "running", None),
        ("P-1", "Surface Coating", "coating", 120, "running", None),
        ("A-1", "Assembly & Test - Braking", "assembly", 270, "running", None),
        ("A-2", "Assembly - Chassis & e-Mobility", "assembly", 300, "running", None),
    ]:
        L[code] = ins("lines", plant_id=plant, code=code, name=name,
                      process_type=ptype, takt_seconds=takt, status=status,
                      stoppage_reason=reason)

    # ------------------------------------------------------------ suppliers
    # cost_center: the plant's GL cost-center mapping on the vendor master.
    # CCS and MCA are still on the OLD code CC-410, closed in the cost-center
    # restructure - the root cause behind the UC2 AP posting-failure batch.
    S = {}
    for code, name, cat, tier, contact, city, state, rating, otp, ppm, cc in [
        ("CCS", "Coalcliff Steel", "steel", 2, "Gus Merrit", "Port Kembla", "NSW", 4.4, 97.8, 120, "CC-410"),
        ("CJC", "Currajong Copper", "copper", 2, "Elena Voss", "Townsville", "QLD", 4.6, 98.9, 60, "CC-430"),
        ("WFA", "Warrigal Fasteners", "fasteners", 2, "Dean Harker", "Dandenong", "VIC", 3.1, 96.2, 610, "CC-430"),
        ("MCA", "Meander Castings", "castings", 2, "Bron Teague", "Launceston", "TAS", 4.2, 95.4, 240, "CC-410"),
        ("KPO", "Kurrajong Polymers", "polymers", 2, "Sunil Rao", "Ballarat", "VIC", 4.5, 99.1, 85, "CC-430"),
        ("TBE", "Torren Bearings", "bearings", 2, "Freya Nilsson", "Salisbury", "SA", 4.7, 99.4, 30, "CC-430"),
        ("LKE", "Larkspur Electronics", "electronics", 1, "Marco Silva", "Clayton", "VIC", 4.5, 97.1, 95, "CC-430"),
        ("HCH", "Halcyon Chemicals", "chemicals", 2, "Tess Bright", "Laverton", "VIC", 4.3, 98.2, 0, "CC-430"),
        ("RPK", "Ridgway Packaging", "packaging", 2, "Owen Slade", "Sunshine", "VIC", 4.1, 96.8, 0, "CC-430"),
        ("BGR", "Bellbrook Gauge & Rig", "equipment", 2, "Hana Kimura", "Bendigo", "VIC", 4.8, 99.0, 0, "CC-430"),
    ]:
        S[code] = ins("suppliers", code=code, name=name, category=cat, tier=tier,
                      contact_name=contact,
                      email=f"sales@{code.lower()}-demo.example",
                      city=city, state=state, rating=rating, on_time_pct=otp,
                      ppm=ppm, status="active", cost_center=cc)

    # ---------------------------------------------------------------- parts
    P = {}

    def part(part_no, name, family, category, std_cost, price=None, rp=0, rq=0,
             traceable=0, sc=0, sup=None):
        P[part_no] = ins("parts", part_no=part_no, name=name, family=family,
                         category=category, uom="ea", std_cost=std_cost,
                         price=price, reorder_point=rp, reorder_qty=rq,
                         traceable=traceable, safety_critical=sc,
                         preferred_supplier_id=S[sup] if sup else None)
        return P[part_no]

    # finished (sellable)
    part("TC-30412", "EPB-40 electric park brake actuator", "braking", "finished", 92.40, 168.00, sc=1, traceable=1)
    part("TC-30450", "Caliper bracket - machined", "braking", "finished", 21.10, 39.50, sc=1, traceable=1)
    part("TC-20110", "Front control arm assembly", "chassis", "finished", 34.60, 61.00, sc=1, traceable=1)
    part("TC-20140", "Steering knuckle - machined", "chassis", "finished", 41.80, 74.00, sc=1, traceable=1)
    part("TC-20160", "Wheel hub assembly", "chassis", "finished", 28.90, 52.00, sc=1, traceable=1)
    part("TC-70210", "HV busbar set - plated", "emobility", "finished", 18.70, 36.00, sc=1, traceable=1)
    part("TC-70230", "HV connector housing", "emobility", "finished", 9.40, 19.80, traceable=1)
    part("TC-30470", "Park brake cable kit", "braking", "finished", 11.20, 22.40, traceable=1)
    # components made in-house
    part("TC-31020", "EPB housing - machined", "braking", "component", 17.30, traceable=1)
    part("TC-21150", "Control arm pin set - heat treated", "chassis", "component", 6.90, traceable=1)
    part("TC-21170", "Hub blank - machined", "chassis", "component", 12.60, traceable=1)
    # bought components
    part("TC-31110", "EPB motor + ECU set", "braking", "component", 31.50, rp=800, rq=2000, traceable=1, sc=1, sup="LKE")
    part("TC-31140", "EPB gear set", "braking", "component", 8.20, rp=1000, rq=2500, sup="LKE")
    part("TC-31160", "EPB spindle assembly", "braking", "component", 6.40, rp=1000, rq=2500, sup="TBE")
    part("TC-31210", "Case screw M5 (single use)", "braking", "component", 0.09, rp=20000, rq=60000, traceable=1, sup="WFA")
    part("TC-31215", "Output fastener M8x1 - thread rolled", "braking", "component", 0.38, rp=8000, rq=24000, traceable=1, sc=1, sup="WFA")
    part("TC-31230", "EPB seal kit", "braking", "component", 1.15, rp=2000, rq=6000, sup="KPO")
    part("TC-13020", "Suspension bushing", "chassis", "component", 2.30, rp=3000, rq=8000, traceable=1, sup="KPO")
    part("TC-13040", "Bearing cartridge 82mm", "chassis", "component", 14.80, rp=600, rq=1500, traceable=1, sup="TBE")
    part("TC-13080", "Busbar insulation moulding", "emobility", "component", 1.60, rp=2500, rq=6000, sup="KPO")
    # raw materials
    part("TC-10010", "Steel coil 2.0mm HSLA", "raw", "raw", 1.42, rp=6000, rq=18000, traceable=1, sup="CCS")
    part("TC-10020", "Steel bar 40mm 4140", "raw", "raw", 3.10, rp=2000, rq=6000, traceable=1, sup="CCS")
    part("TC-11040", "Forged knuckle blank", "raw", "raw", 16.20, rp=500, rq=1200, traceable=1, sup="MCA")
    part("TC-12010", "Copper strip C11000 0.8mm", "raw", "raw", 4.85, rp=1500, rq=4000, traceable=1, sup="CJC")
    part("TC-14010", "Polymer resin PA66-GF30", "raw", "raw", 0.95, rp=1000, rq=3000, sup="KPO")
    part("TC-90010", "Plating chemistry set TM-P410", "raw", "raw", 210.00, rp=6, rq=12, sup="HCH")
    part("TC-90020", "Quench oil TM-Q60 (drum)", "raw", "raw", 640.00, rp=4, rq=8, sup="HCH")
    part("TC-90030", "Export carton set", "raw", "raw", 1.10, rp=800, rq=2400, sup="RPK")

    # -------------------------------------------------------- customer parts
    CP = [
        ("ELL", "TC-30412", "ELL-88412-B", 168.00),
        ("ELL", "TC-30450", "ELL-88450-A", 39.50),
        ("ELL", "TC-30470", "ELL-88470-C", 22.40),
        ("MAR", "TC-70210", "MAR-77210", 36.00),
        ("MAR", "TC-70230", "MAR-77230", 19.80),
        ("MAR", "TC-20140", "MAR-55140", 74.00),
        ("SBT", "TC-20110", "SBT-4110-F", 63.50),
        ("SBT", "TC-20160", "SBT-4160-F", 54.00),
        ("KOR", "TC-70210", "KOR-B7210", 37.20),
        ("ABD", "TC-30412", "AB-EPB40", 179.00),
        ("ABD", "TC-30470", "AB-PBC40", 24.90),
        ("TTP", "TC-20160", "TT-HUB82", 55.60),
    ]
    for cust, pno, cpn, price in CP:
        ins("customer_parts", customer_id=C[cust], part_id=P[pno],
            customer_part_no=cpn, price=price)

    # ----------------------------------------------------------------- BOMs
    BOM = {
        "TC-30412": [("TC-31020", 1, "A-1/30"), ("TC-31110", 1, "A-1/30"),
                     ("TC-31140", 1, "A-1/40"), ("TC-31160", 1, "A-1/40"),
                     ("TC-31210", 4, "A-1/50"), ("TC-31215", 1, "A-1/50"),
                     ("TC-31230", 1, "A-1/40"), ("TC-90030", 0.05, "pack")],
        "TC-31020": [("TC-10020", 0.9, "M-1")],
        "TC-30450": [("TC-10020", 1.4, "M-1")],
        "TC-20110": [("TC-10010", 3.2, "S-1"), ("TC-21150", 1, "A-2/20"),
                     ("TC-13020", 2, "A-2/20"), ("TC-90030", 0.04, "pack")],
        "TC-21150": [("TC-10020", 0.6, "M-2/H-1")],
        "TC-20140": [("TC-11040", 1, "M-1")],
        "TC-20160": [("TC-21170", 1, "A-2/40"), ("TC-13040", 1, "A-2/40"),
                     ("TC-90030", 0.04, "pack")],
        "TC-21170": [("TC-10020", 1.8, "M-2")],
        "TC-70210": [("TC-12010", 1.6, "S-1/P-1"), ("TC-13080", 4, "A-2/60"),
                     ("TC-90030", 0.03, "pack")],
        "TC-70230": [("TC-14010", 0.4, "A-2/60")],
        "TC-30470": [("TC-10010", 0.8, "S-1"), ("TC-31230", 1, "A-1/70")],
    }
    for parent, rows in BOM.items():
        for comp, qty, station in rows:
            ins("boms", parent_part_id=P[parent], component_part_id=P[comp],
                qty_per=qty, station=station, note=None)

    # ------------------------------------------------------------ locations
    LOC = {}
    for code, name, typ, line in [
        ("WH-RAW", "Raw material store", "warehouse", None),
        ("WH-COMP", "Component store", "warehouse", None),
        ("FG-1", "Finished goods store", "finished_store", None),
        ("Q1", "Quarantine", "quarantine", None),
        ("LS-S1", "Line-side S-1", "line_side", "S-1"),
        ("LS-M1", "Line-side M-1", "line_side", "M-1"),
        ("LS-A1", "Line-side A-1", "line_side", "A-1"),
        ("LS-A2", "Line-side A-2", "line_side", "A-2"),
    ]:
        LOC[code] = ins("locations", code=code, name=name, type=typ,
                        line_id=L[line] if line else None)

    # ------------------------------------------------------- operators, skills
    SK = {}
    for code, name, renew in [
        ("TQ-1", "Torque-critical qualification", 12),
        ("PR-1", "Press operation and die setting", 24),
        ("HT-1", "Heat-treat operation", 24),
        ("PL-1", "Plating and chemical handling", 12),
        ("CMM-1", "CMM operation", 24),
        ("WC-2", "Weld certification", 24),
        ("FL", "Forklift licence", 60),
        ("QI", "Quality inspector authorisation", 12),
    ]:
        SK[code] = ins("skills", code=code, name=name, renew_months=renew)

    op_names = ["Jo Marsh", "Ravi Kumar", "Elsie Tran", "Marcus Bell", "Nina Cole",
                "Tom Ishida", "Grace Udo", "Harry Vane", "Lena Sorik", "Pat Doyle",
                "Ada Lindqvist", "Ben Okoye", "Cara Munro", "Dev Sharma", "Eve Sutton",
                "Felix Gray", "Gita Pillai", "Hugh Barnes", "Isla Reid", "Jack Nolan",
                "Kim Seong", "Liv Hansen", "Milo Frost", "Noor Aziz", "Oscar Lim",
                "Pia Weston"]
    line_cycle = ["S-1", "M-1", "M-2", "H-1", "P-1", "A-1", "A-1", "A-2"]
    OPS = []
    for i, name in enumerate(op_names):
        role = ("line_lead" if i in (0, 5, 10, 15, 20) else
                "quality_inspector" if i in (4, 14, 24) else
                "maintenance" if i in (9, 19) else
                "material_handler" if i in (13, 23) else "operator")
        line = line_cycle[i % len(line_cycle)]
        shift = ["day", "afternoon", "night"][i % 3]
        oid = ins("operators", emp_no=f"TC{1001+i}", name=name, role=role,
                  line_id=L[line], shift=shift,
                  hourly_rate=round(random.uniform(34, 52), 2),
                  status="leave" if i == 21 else "active")
        OPS.append((oid, name, role, line))

    # certifications - a few expiring soon, one expired (feeds skill-gap)
    cert_plan = [
        (0, "TQ-1", -300), (0, "FL", -400), (5, "TQ-1", -350), (6, "TQ-1", -340),
        (7, "TQ-1", -710), (15, "TQ-1", -320),      # op 7 TQ-1 expired (>12 months)
        (1, "PR-1", -400), (16, "PR-1", -680),      # op 16 PR-1 expiring soon
        (3, "HT-1", -500), (11, "HT-1", -700),
        (4, "QI", -200), (14, "QI", -100), (24, "QI", -330),  # op 24 QI expiring
        (2, "CMM-1", -300), (12, "CMM-1", -400),
        (8, "PL-1", -340),                            # PL-1 expiring within 60 days
        (10, "WC-2", -400), (18, "WC-2", -500),
        (9, "FL", -900), (13, "FL", -300), (19, "FL", -350), (23, "FL", -200),
    ]
    for op_idx, sk, cert_off in cert_plan:
        renew = next(r for c, r in
                     [("TQ-1", 12), ("PR-1", 24), ("HT-1", 24), ("PL-1", 12),
                      ("CMM-1", 24), ("WC-2", 24), ("FL", 60), ("QI", 12)]
                     if c == sk)
        ins("operator_skills", operator_id=OPS[op_idx][0], skill_id=SK[sk],
            certified_on=d(cert_off), expires_on=d(cert_off + renew * 30))

    # UC1 seed: night-shift supervisor covering A-2 for the first time - one
    # of the three correlated root-cause suspects for the overnight FPY breach
    trainee_id = ins("operators", emp_no="TC1027", name="Ravi Fenn",
                     role="line_lead", line_id=L["A-2"], shift="night",
                     hourly_rate=41.50, status="active",
                     notes="First night rostered as night-shift supervisor on "
                     "A-2 - covering for T. Okonkwo (leave). Onboarded to the "
                     "supervisor role three days ago.")
    OPS.append((trainee_id, "Ravi Fenn", "line_lead", "A-2"))

    # ------------------------------------------------------------- machines
    M = {}
    for asset, name, typ, line, make, svc_off, cal_off in [
        ("PRS-01", "630t progression press", "press", "S-1", "Bardwell Machine Co", 18, 40),
        ("PRS-02", "400t blanking press", "press", "S-1", "Bardwell Machine Co", -6, 60),
        ("MC-M1-01", "CNC mill cell 1", "cnc", "M-1", "Fenwick CNC", 32, 90),
        ("MC-M1-02", "CNC mill cell 2", "cnc", "M-1", "Fenwick CNC", 55, 90),
        ("MC-M1-03", "Eddy-current crack bench", "test_rig", "M-1", "Bellbrook Gauge & Rig", 70, 12),
        ("MC-M2-01", "CNC turn-mill cell", "cnc", "M-2", "Fenwick CNC", 2, 80),
        ("FUR-01", "Sealed quench furnace", "furnace", "H-1", "Halstead Furnaces", 21, 28),
        ("FUR-02", "Temper oven", "furnace", "H-1", "Halstead Furnaces", 44, 70),
        ("PLT-01", "E-coat and plating line", "plating", "P-1", "Meridale Process", 12, 50),
        ("PLT-02", "XRF plating gauge", "test_rig", "P-1", "Bellbrook Gauge & Rig", 120, 34),
        ("ASM-01", "EPB assembly rig", "assembly_rig", "A-1", "Arkline Automation", 26, 55),
        ("TST-01", "EPB end-of-line test rig 1", "test_rig", "A-1", "Bellbrook Gauge & Rig", 62, 9),
        ("TST-02", "EPB end-of-line test rig 2", "test_rig", "A-1", "Bellbrook Gauge & Rig", 62, 41),
        ("TST-03", "Hipot bench", "test_rig", "A-2", "Bellbrook Gauge & Rig", 88, 30),
        ("INJ-01", "HV connector housing injection moulding cell", "injection",
         "A-2", "Bramwell Moulding Systems", -5, 65),
        ("CMM-01", "CMM - quality room 1", "cmm", None, "Meridale Metrology", 150, 75),
        ("CMM-02", "CMM - quality room 2", "cmm", None, "Meridale Metrology", 150, -4),
        ("HRD-01", "Hardness tester", "test_rig", "H-1", "Bellbrook Gauge & Rig", 95, 6),
        ("AGV-01", "Tow AGV - warehouse loop", "agv", None, "Arkline Automation", 9, 180),
    ]:
        M[asset] = ins("machines", asset_no=asset, name=name, type=typ,
                       line_id=L[line] if line else None, make=make,
                       commissioned_on=d(-random.randint(700, 2600)),
                       last_service=d(svc_off - 90), next_service_due=d(svc_off),
                       last_calibration=d(cal_off - 180),
                       next_calibration_due=d(cal_off),
                       status="down" if asset == "MC-M2-01" else "running")

    # -------------------------------------------------------------- tooling
    for tool, name, typ, pno, line, shots, interval, svc_off in [
        ("TB-7021", "Busbar progression die", "die", "TC-70210", "S-1", 41200, 60000, 45),
        ("TB-2011", "Control arm stamping die", "die", "TC-20110", "S-1", 55800, 60000, 8),
        ("F-2014", "Knuckle machining fixture", "fixture", "TC-20140", "M-1", 0, 0, 120),
        ("F-3102", "EPB housing fixture", "fixture", "TC-31020", "M-1", 0, 0, 95),
        ("J-3041", "EPB assembly jig set", "jig", "TC-30412", "A-1", 0, 0, 30),
        ("G-3041", "EPB golden test unit", "gauge", "TC-30412", "A-1", 0, 0, 21),
        ("G-2014", "Knuckle bore gauge set", "gauge", "TC-20140", "M-1", 0, 0, 64),
        ("G-7021", "Busbar burr gauge", "gauge", "TC-70210", "S-1", 0, 0, 33),
        ("TB-3047", "Cable kit blank die", "die", "TC-30470", "S-1", 12300, 50000, 140),
        ("F-2117", "Hub blank fixture", "fixture", "TC-21170", "M-2", 0, 0, 77),
    ]:
        ins("tooling", tool_no=tool, name=name, type=typ, part_id=P[pno],
            line_id=L[line], shots_since_service=shots,
            service_interval_shots=interval, last_service=d(svc_off - 180),
            next_service_due=d(svc_off), status="in_service")

    # ------------------------------------------------- purchase orders + lots
    PO = {}

    def po(no, sup, status, ordered, expected, received, lines):
        total = sum(q_ * c for _, q_, c, _ in lines)
        poid = ins("purchase_orders", po_no=no, supplier_id=S[sup], status=status,
                   ordered_on=d(ordered), expected_date=d(expected),
                   received_on=d(received) if received is not None else None,
                   total=round(total, 2))
        for pno, q_, cost, recq in lines:
            ins("purchase_order_lines", po_id=poid, part_id=P[pno], qty=q_,
                unit_cost=cost, received_qty=recq)
        PO[no] = poid
        return poid

    po("PO-2218", "CCS", "received", -55, -41, -40,
       [("TC-10010", 18000, 1.40, 18000), ("TC-10020", 6000, 3.05, 6000)])
    po("PO-2223", "MCA", "received", -50, -35, -33,
       [("TC-11040", 1200, 16.10, 1200)])
    po("PO-2226", "LKE", "received", -46, -30, -30,
       [("TC-31110", 2000, 31.20, 2000), ("TC-31140", 2500, 8.10, 2500)])
    po("PO-2231", "WFA", "received", -44, -33, -32,
       [("TC-31215", 40000, 0.36, 40000), ("TC-31210", 60000, 0.085, 60000)])
    po("PO-2235", "CJC", "received", -38, -24, -24,
       [("TC-12010", 4000, 4.80, 4000)])
    po("PO-2238", "KPO", "received", -30, -18, -17,
       [("TC-13020", 8000, 2.25, 8000), ("TC-13080", 6000, 1.55, 6000),
        ("TC-31230", 6000, 1.10, 6000)])
    po("PO-2240", "TBE", "received", -26, -12, -12,
       [("TC-13040", 1500, 14.60, 1500), ("TC-31160", 2500, 6.30, 2500)])
    po("PO-2243", "WFA", "received", -14, -7, -5,
       [("TC-31215", 24000, 0.37, 24000)])
    po("PO-2245", "HCH", "confirmed", -10, 3, None,
       [("TC-90010", 12, 208.00, 0), ("TC-90020", 8, 635.00, 0)])
    po("PO-2246", "CCS", "confirmed", -9, -2, None,          # late - supplier delay
       [("TC-10020", 6000, 3.10, 0)])
    po("PO-2247", "MCA", "confirmed", -8, -1, None,          # late - supplier delay
       [("TC-11040", 1200, 16.30, 0)])
    po("PO-2248", "LKE", "sent", -3, 11, None,
       [("TC-31110", 2000, 31.40, 0)])
    po("PO-2249", "RPK", "confirmed", -2, 6, None,
       [("TC-90030", 2400, 1.05, 0)])
    # UC1 seed: resin lot received and put into first use on A-2 overnight
    po("PO-2251", "KPO", "received", -6, -2, -2,
       [("TC-14010", 3000, 0.97, 3000)])
    # UC3 seed: the binding-constraint replenishment for the CTP shortage -
    # confirmed but not yet received, expected in 11 days
    po("PO-2252", "KPO", "confirmed", -3, 11, None,
       [("TC-13080", 2600, 1.62, 0)])

    RL = {}

    def raw_lot(lot_no, pno, sup, po_no, rec, qty, remaining, status="available"):
        RL[lot_no] = ins("raw_lots", lot_no=lot_no, part_id=P[pno],
                         supplier_id=S[sup], po_id=PO[po_no], received_on=d(rec),
                         qty_received=qty, qty_remaining=remaining,
                         coa_ref=f"CoA-{lot_no}", status=status)
        return RL[lot_no]

    raw_lot("CS-8811", "TC-10010", "CCS", "PO-2218", -40, 18000, 6200)
    raw_lot("CS-8812", "TC-10020", "CCS", "PO-2218", -40, 6000, 1450)
    raw_lot("MC-5520", "TC-11040", "MCA", "PO-2223", -33, 1200, 260)
    raw_lot("LK-0912", "TC-31110", "LKE", "PO-2226", -30, 2000, 610)
    raw_lot("LK-0913", "TC-31140", "LKE", "PO-2226", -30, 2500, 940)
    raw_lot("WF-2261", "TC-31215", "WFA", "PO-2231", -32, 40000, 26400, status="quarantine")
    raw_lot("WF-2260", "TC-31210", "WFA", "PO-2231", -32, 60000, 31000)
    raw_lot("CJ-3308", "TC-12010", "CJC", "PO-2235", -24, 4000, 1750)
    raw_lot("KP-7714", "TC-13020", "KPO", "PO-2238", -17, 8000, 4900)
    raw_lot("KP-7715", "TC-13080", "KPO", "PO-2238", -17, 6000, 830)
    raw_lot("KP-7716", "TC-31230", "KPO", "PO-2238", -17, 6000, 3600)
    raw_lot("TB-4402", "TC-13040", "TBE", "PO-2240", -12, 1500, 830)
    raw_lot("TB-4403", "TC-31160", "TBE", "PO-2240", -12, 2500, 1500)
    raw_lot("WF-2289", "TC-31215", "WFA", "PO-2243", -5, 24000, 24000)
    # UC1 hero: first use of this resin lot on A-2 overnight - see RUN-1111
    raw_lot("KP-7742", "TC-14010", "KPO", "PO-2251", -2, 3000, 2832)

    # ------------------------------------------------------- sales orders
    SO = {}

    def so(no, cust, cpo, status, ship_to, ordered, promised, lines,
           notes=None, lost_reason=None):
        sub = sum(q_ * pr for _, q_, pr in lines)
        gst = round(sub * 0.10, 2)
        soid = ins("sales_orders", so_no=no, customer_id=C[cust], customer_po=cpo,
                   status=status, ship_to_id=ST[ship_to] if ship_to else None,
                   ordered_on=d(ordered), promised_date=d(promised),
                   subtotal=round(sub, 2), gst=gst, total=round(sub + gst, 2),
                   notes=notes, lost_reason=lost_reason)
        for pno, q_, pr in lines:
            cpn = next((cp[2] for cp in CP if cp[0] == cust and cp[1] == pno), None)
            ins("sales_order_lines", sales_order_id=soid, part_id=P[pno],
                customer_part_no=cpn, qty=q_, unit_price=pr,
                line_total=round(q_ * pr, 2))
        SO[no] = soid
        return soid

    so("SO-3411", "ELL", "ELL-PO-99120", "fulfilled", "ELL-CORIO", -42, -20,
       [("TC-30412", 400, 168.00)])
    so("SO-3415", "ELL", "ELL-PO-99188", "fulfilled", "ELL-WESTH", -30, -12,
       [("TC-30412", 240, 168.00), ("TC-30450", 300, 39.50)])
    so("SO-3418", "MAR", "MAR-PO-51502", "fulfilled", "MAR-ALT", -28, -10,
       [("TC-70210", 600, 36.00), ("TC-70230", 600, 19.80)])
    so("SO-3421", "SBT", "SBT-PO-77031", "fulfilled", "SBT-DER", -25, -8,
       [("TC-20110", 350, 63.50)])
    so("SO-3424", "ABD", "ABD-PO-1188", "fulfilled", "ABD-DC", -21, -6,
       [("TC-30412", 60, 179.00), ("TC-30470", 200, 24.90)])
    so("SO-3427", "MAR", "MAR-PO-51544", "fulfilled", "MAR-ALT", -18, -4,
       [("TC-20140", 280, 74.00)])
    so("SO-3430", "ELL", "ELL-PO-99231", "in_production", "ELL-CORIO", -12, 4,
       [("TC-30412", 480, 168.00)],
       notes="Weekly EDI release - firm window")
    so("SO-3431", "SBT", "SBT-PO-77102", "in_production", "SBT-DER", -11, 3,
       [("TC-20110", 350, 63.50), ("TC-20160", 200, 54.00)])
    so("SO-3433", "MAR", "MAR-PO-51590", "in_production", "MAR-ALT", -9, 6,
       [("TC-70210", 800, 36.00)])
    so("SO-3434", "KOR", "KOR-PO-8834", "approved", "KOR-ALB", -8, 9,
       [("TC-70210", 300, 37.20)])
    so("SO-3436", "TTP", "TTP-PO-4471", "approved", "TTP-DC", -6, 8,
       [("TC-20160", 150, 55.60)])
    so("SO-3437", "ELL", "ELL-PO-99270", "approved", "ELL-CORIO", -5, 11,
       [("TC-30412", 480, 168.00)],
       notes="Weekly EDI release - firm window")
    so("SO-3438", "ABD", "ABD-PO-1201", "submitted", "ABD-DC", -3, 14,
       [("TC-30470", 400, 24.90)])
    so("SO-3439", "MAR", "MAR-PO-51633", "submitted", "MAR-ALT", -2, 16,
       [("TC-70230", 900, 19.80)])
    so("SO-3440", "KOR", "KOR-RFQ-112", "draft", "KOR-ALB", -1, 21,
       [("TC-70230", 500, 19.80)])
    so("SO-3406", "SBT", "SBT-RFQ-902", "lost", None, -50, -30,
       [("TC-20160", 400, 52.00)],
       lost_reason="Price - incumbent supplier re-quoted 9 per cent under")
    so("SO-3409", "TTP", "TTP-RFQ-118", "lost", None, -45, -28,
       [("TC-30470", 600, 22.40)],
       lost_reason="Lead time - requested 2 weeks, we quoted 5")
    so("SO-3426", "ABD", "ABD-RFQ-77", "rejected", None, -19, -5,
       [("TC-20140", 60, 74.00)],
       notes="Below minimum order quantity for machined family")

    # ------------------------------------------------------------- runs
    RUN = {}

    def run(no, pno, qty, line, status, sstart, send, so_no=None, good=None,
            scrap=0, started=None, completed=None, cost_factor=1.0, notes=None,
            priority="normal"):
        pid = P[pno]
        std = next(v for k, v in
                   [("TC-30412", 92.40), ("TC-30450", 21.10), ("TC-20110", 34.60),
                    ("TC-20140", 41.80), ("TC-20160", 28.90), ("TC-70210", 18.70),
                    ("TC-70230", 9.40), ("TC-30470", 11.20), ("TC-31020", 17.30),
                    ("TC-21150", 6.90), ("TC-21170", 12.60)] if k == pno)
        g = good if good is not None else 0
        RUN[no] = ins("runs", run_no=no, part_id=pid, qty_planned=qty,
                      qty_good=g, qty_scrap=scrap, line_id=L[line], status=status,
                      priority=priority, scheduled_start=d(sstart),
                      scheduled_end=d(send),
                      sales_order_id=SO[so_no] if so_no else None,
                      started_at=ts(started) if started is not None else None,
                      completed_at=ts(completed) if completed is not None else None,
                      std_cost=round(std * qty, 2),
                      actual_cost=round(std * (g + scrap) * cost_factor, 2)
                      if g or scrap else 0,
                      notes=notes)
        return RUN[no]

    # completed history (feeds reports, margin, OEE)
    run("RUN-1074", "TC-70210", 620, "S-1", "completed", -27, -25, "SO-3418",
        good=612, scrap=8, started=-27, completed=-25, cost_factor=1.02)
    run("RUN-1076", "TC-70230", 620, "A-2", "completed", -26, -24, "SO-3418",
        good=605, scrap=15, started=-26, completed=-24, cost_factor=1.05)
    run("RUN-1078", "TC-20110", 360, "A-2", "completed", -24, -21, "SO-3421",
        good=352, scrap=8, started=-24, completed=-21, cost_factor=1.03)
    run("RUN-1080", "TC-31020", 1000, "M-1", "completed", -28, -26, None,
        good=986, scrap=14, started=-28, completed=-26, cost_factor=1.01)
    run("RUN-1082", "TC-21150", 800, "H-1", "completed", -25, -23, None,
        good=792, scrap=8, started=-25, completed=-23, cost_factor=1.04)
    run("RUN-1084", "TC-30470", 280, "A-1", "completed", -23, -22, "SO-3424",
        good=272, scrap=8, started=-23, completed=-22, cost_factor=1.0)
    run("RUN-1088", "TC-30412", 480, "A-1", "completed", -25, -23, "SO-3411",
        good=480, scrap=0, started=-25, completed=-23, cost_factor=1.0)
    run("RUN-1090", "TC-20140", 300, "M-1", "completed", -20, -17, "SO-3427",
        good=291, scrap=9, started=-20, completed=-17, cost_factor=1.06)
    run("RUN-1092", "TC-30412", 470, "A-1", "completed", -16, -14, "SO-3415",
        good=460, scrap=10, started=-16, completed=-14, cost_factor=1.03)
    run("RUN-1094", "TC-30450", 320, "M-1", "completed", -15, -13, "SO-3415",
        good=312, scrap=8, started=-15, completed=-13, cost_factor=1.0)
    run("RUN-1096", "TC-20160", 220, "A-2", "completed", -12, -10, "SO-3421",
        good=214, scrap=6, started=-12, completed=-10, cost_factor=1.08)
    run("RUN-1098", "TC-21170", 400, "M-2", "completed", -11, -9, None,
        good=394, scrap=6, started=-11, completed=-9, cost_factor=1.02)
    # in progress / hold / released / planned
    run("RUN-1100", "TC-70210", 820, "S-1", "in_progress", -2, 2, "SO-3433",
        good=390, scrap=6, started=-2, cost_factor=1.0, priority="high")
    run("RUN-1101", "TC-30412", 490, "A-1", "quality_hold", -3, 2, "SO-3430",
        good=210, scrap=4, started=-3, cost_factor=1.0, priority="high",
        notes="Held - suspect output fastener lot WF-2261 (QP-8D containment)")
    run("RUN-1102", "TC-20110", 360, "A-2", "in_progress", -1, 3, "SO-3431",
        good=140, scrap=2, started=-1)
    run("RUN-1103", "TC-20160", 210, "A-2", "released", 0, 4, "SO-3431")
    run("RUN-1104", "TC-31020", 1000, "M-1", "in_progress", -2, 1, None,
        good=620, scrap=8, started=-2)
    run("RUN-1105", "TC-70210", 320, "S-1", "released", 1, 5, "SO-3434")
    run("RUN-1106", "TC-30412", 480, "A-1", "planned", 3, 7, "SO-3437",
        priority="high",
        notes="Awaiting certified fastener stock - lot WF-2289 incoming inspection")
    run("RUN-1107", "TC-20140", 120, "M-1", "planned", 4, 8, None)
    run("RUN-1108", "TC-30470", 420, "A-1", "planned", 5, 9, "SO-3438")
    run("RUN-1109", "TC-70230", 920, "A-2", "planned", 6, 10, "SO-3439")
    run("RUN-1110", "TC-21150", 800, "H-1", "released", 1, 4, None)
    # UC1 hero: overnight FPY breach on A-2 (found this morning) - see
    # scripts/ai.py dig_fpy_root_cause for the three correlated suspects
    run("RUN-1111", "TC-70230", 420, "A-2", "completed", -1, -1, "SO-3439",
        good=354, scrap=66, started=-1, completed=-1, cost_factor=1.04,
        notes="Overnight run - FPY 84.3 per cent, well under the 96.5 per cent "
        "line target. Quality notified at shift handover.")

    # ------------------------------------------------- run materials (trace)
    def consume(run_no, items):
        for pno, lot, qty in items:
            cost = round(qty * next(
                c for k, c in [("TC-10010", 1.42), ("TC-10020", 3.10),
                               ("TC-11040", 16.20), ("TC-12010", 4.85),
                               ("TC-31110", 31.50), ("TC-31140", 8.20),
                               ("TC-31160", 6.40), ("TC-31210", 0.09),
                               ("TC-31215", 0.38), ("TC-31230", 1.15),
                               ("TC-13020", 2.30), ("TC-13040", 14.80),
                               ("TC-13080", 1.60), ("TC-31020", 17.30),
                               ("TC-21150", 6.90), ("TC-21170", 12.60),
                               ("TC-14010", 0.95)] if k == pno), 2)
            ins("run_materials", run_id=RUN[run_no], part_id=P[pno],
                raw_lot_id=RL.get(lot), qty=qty, cost=cost)

    consume("RUN-1074", [("TC-12010", "CJ-3308", 1000)])
    consume("RUN-1076", [("TC-14010", None, 250), ("TC-13080", "KP-7715", 2480)])
    consume("RUN-1078", [("TC-10010", "CS-8811", 1160), ("TC-21150", None, 360),
                         ("TC-13020", "KP-7714", 720)])
    consume("RUN-1080", [("TC-10020", "CS-8812", 900)])
    consume("RUN-1082", [("TC-10020", "CS-8812", 480)])
    consume("RUN-1084", [("TC-10010", "CS-8811", 230), ("TC-31230", "KP-7716", 280)])
    # HERO chain: RUN-1088 and RUN-1092 consumed fastener lot WF-2261
    consume("RUN-1088", [("TC-31020", None, 480), ("TC-31110", "LK-0912", 480),
                         ("TC-31140", "LK-0913", 480), ("TC-31160", "TB-4403", 480),
                         ("TC-31210", "WF-2260", 1920), ("TC-31215", "WF-2261", 480),
                         ("TC-31230", "KP-7716", 480)])
    consume("RUN-1090", [("TC-11040", "MC-5520", 300)])
    consume("RUN-1092", [("TC-31020", None, 470), ("TC-31110", "LK-0912", 470),
                         ("TC-31140", "LK-0913", 470), ("TC-31160", "TB-4403", 470),
                         ("TC-31210", "WF-2260", 1880), ("TC-31215", "WF-2261", 470),
                         ("TC-31230", "KP-7716", 470)])
    consume("RUN-1094", [("TC-10020", "CS-8812", 450)])
    consume("RUN-1096", [("TC-21170", None, 220), ("TC-13040", "TB-4402", 220)])
    consume("RUN-1098", [("TC-10020", "CS-8812", 720)])
    consume("RUN-1100", [("TC-12010", "CJ-3308", 640)])
    consume("RUN-1101", [("TC-31020", None, 214), ("TC-31110", "LK-0912", 214),
                         ("TC-31215", "WF-2261", 214), ("TC-31210", "WF-2260", 856)])
    consume("RUN-1102", [("TC-10010", "CS-8811", 460), ("TC-21150", None, 142),
                         ("TC-13020", "KP-7714", 284)])
    consume("RUN-1104", [("TC-10020", "CS-8812", 570)])
    consume("RUN-1111", [("TC-14010", "KP-7742", 168)])

    # ------------------------------------------------------- finished lots
    FL = {}

    def flot(lot_no, pno, run_no, qty, shipped, prod, status, loc="FG-1"):
        FL[lot_no] = ins("finished_lots", lot_no=lot_no, part_id=P[pno],
                         run_id=RUN[run_no], qty_produced=qty, qty_shipped=shipped,
                         produced_on=d(prod), status=status,
                         location_id=LOC[loc])
        return FL[lot_no]

    flot("TC-S-7740", "TC-70210", "RUN-1074", 612, 600, -25, "shipped")
    flot("TC-A-7741", "TC-70230", "RUN-1076", 605, 600, -24, "shipped")
    flot("TC-A-2210", "TC-20110", "RUN-1078", 352, 350, -21, "shipped")
    flot("TC-M-3310", "TC-31020", "RUN-1080", 986, 0, -26, "in_stock", "WH-COMP")
    flot("TC-H-2150", "TC-21150", "RUN-1082", 792, 0, -23, "in_stock", "WH-COMP")
    flot("TC-A-3470", "TC-30470", "RUN-1084", 272, 200, -22, "in_stock")
    flot("TC-A-4471", "TC-30412", "RUN-1088", 480, 400, -23, "hold")     # hero lot 1
    flot("TC-M-2140", "TC-20140", "RUN-1090", 291, 280, -17, "shipped")
    flot("TC-A-4472", "TC-30412", "RUN-1092", 460, 240, -14, "hold")     # hero lot 2
    flot("TC-M-3450", "TC-30450", "RUN-1094", 312, 300, -13, "shipped")
    flot("TC-A-2160", "TC-20160", "RUN-1096", 214, 200, -10, "in_stock")
    flot("TC-M-2170", "TC-21170", "RUN-1098", 394, 0, -9, "in_stock", "WH-COMP")
    flot("TC-A-4900", "TC-70230", "RUN-1111", 354, 0, -1, "in_stock")  # UC1 hero -
    # not yet contained; still in stock, not shipped - the live "contain before
    # it ships" action places the hold during the demo

    # ---------------------------------------------------------- shipments
    SHP = {}

    def ship(no, so_no, cust, ship_to, status, shipped, carrier, lines):
        sid = ins("shipments", shp_no=no, sales_order_id=SO[so_no],
                  customer_id=C[cust], ship_to_id=ST[ship_to], status=status,
                  shipped_on=d(shipped) if shipped is not None else None,
                  carrier=carrier, asn_ref=f"ASN-{no[4:]}")
        for lot_no, pno, q_ in lines:
            ins("shipment_lines", shipment_id=sid, finished_lot_id=FL[lot_no],
                part_id=P[pno], qty=q_, so_line_id=None)
        SHP[no] = sid
        return sid

    ship("SHP-0341", "SO-3411", "ELL", "ELL-CORIO", "delivered", -20,
         "Kestrel Freight Lines", [("TC-A-4471", "TC-30412", 400)])
    ship("SHP-0344", "SO-3418", "MAR", "MAR-ALT", "delivered", -10,
         "Kestrel Freight Lines",
         [("TC-S-7740", "TC-70210", 600), ("TC-A-7741", "TC-70230", 600)])
    ship("SHP-0345", "SO-3421", "SBT", "SBT-DER", "delivered", -8,
         "Boab Haulage", [("TC-A-2210", "TC-20110", 350)])
    ship("SHP-0347", "SO-3415", "ELL", "ELL-WESTH", "delivered", -12,
         "Kestrel Freight Lines",
         [("TC-A-4472", "TC-30412", 240), ("TC-M-3450", "TC-30450", 300)])
    ship("SHP-0349", "SO-3424", "ABD", "ABD-DC", "delivered", -6,
         "Boab Haulage",
         [("TC-A-3470", "TC-30470", 200)])
    ship("SHP-0350", "SO-3427", "MAR", "MAR-ALT", "delivered", -4,
         "Kestrel Freight Lines", [("TC-M-2140", "TC-20140", 280)])
    ship("SHP-0352", "SO-3421", "SBT", "SBT-DER", "despatched", -1,
         "Boab Haulage", [("TC-A-2160", "TC-20160", 200)])

    # note: SO-3424 actuators (60) shipped from TC-A-4471 stock is intentionally
    # NOT modelled - ABD units came from TC-A-4471's 400? No: keep clean - the 400
    # on SHP-0341 are the only TC-A-4471 shipments; ABD actuators pending.

    # ----------------------------------------------------------- invoices
    def inv(no, cust, so_no, shp_no, status, issued, paid=None):
        sub = 0
        for r in cur.execute(
                "SELECT sl.qty, sol.unit_price FROM shipment_lines sl "
                "LEFT JOIN sales_order_lines sol ON sol.sales_order_id=? "
                "AND sol.part_id=sl.part_id WHERE sl.shipment_id=?",
                (SO[so_no], SHP[shp_no])).fetchall():
            sub += (r[0] or 0) * (r[1] or 0)
        gst = round(sub * 0.10, 2)
        terms = cur.execute("SELECT payment_terms FROM customers WHERE id=?",
                            (C[cust],)).fetchone()[0]
        ins("invoices", inv_no=no, customer_id=C[cust],
            sales_order_id=SO[so_no], shipment_id=SHP[shp_no], status=status,
            issued_on=d(issued), due_on=d(issued + terms),
            subtotal=round(sub, 2), gst=gst, total=round(sub + gst, 2),
            paid_on=d(paid) if paid is not None else None)

    inv("INV-5211", "ELL", "SO-3411", "SHP-0341", "paid", -20, -2)
    inv("INV-5214", "MAR", "SO-3418", "SHP-0344", "sent", -10)
    inv("INV-5215", "SBT", "SO-3421", "SHP-0345", "overdue", -53)
    inv("INV-5216", "ELL", "SO-3415", "SHP-0347", "sent", -12)
    inv("INV-5217", "ABD", "SO-3424", "SHP-0349", "overdue", -40)
    inv("INV-5218", "MAR", "SO-3427", "SHP-0350", "overdue", -36)
    inv("INV-5219", "SBT", "SO-3421", "SHP-0352", "draft", -1)

    # ----------------------------------------------------- AP invoices (UC2)
    # 23 vendor bills failed to post this morning. 9 share ONE root cause
    # (vendor master still on closed cost center CC-410 - see suppliers CCS,
    # MCA above); 13 have distinct one-off causes; 1 (BANK-VER) genuinely
    # needs treasury sign-off and stays stuck - an honest limit, not a bug.
    def apinv(no, sup, code, amount, po_no=None, notes=None):
        ins("ap_invoices", ap_no=no, supplier_id=S[sup], po_id=PO.get(po_no),
            vendor_invoice_no=f"VI-{no[3:]}-{sup}", amount=amount,
            status="failed", error_code=code, received_on=d(0), due_on=d(14),
            root_cause_group="vendor_master_cost_center" if code == "GL-4102"
            else None, notes=notes)

    for no, sup, amt in [("AP-8801", "CCS", 2140.50), ("AP-8802", "CCS", 1875.20),
                         ("AP-8803", "CCS", 3320.00), ("AP-8804", "CCS", 990.75),
                         ("AP-8805", "CCS", 4410.10), ("AP-8806", "MCA", 2650.40),
                         ("AP-8807", "MCA", 3180.00), ("AP-8808", "MCA", 1225.60),
                         ("AP-8809", "MCA", 3990.25)]:
        apinv(no, sup, "GL-4102", amt)

    apinv("AP-8810", "WFA", "PO-QTY-VAR", 1560.00, "PO-2231")
    apinv("AP-8811", "KPO", "DUP-CHK", 875.40, "PO-2238")
    apinv("AP-8812", "TBE", "TAX-INV", 640.20, "PO-2240")
    apinv("AP-8813", "LKE", "3WM-FAIL", 4950.00, "PO-2248")
    apinv("AP-8814", "HCH", "CURR-RND", 212.05, "PO-2245")
    apinv("AP-8815", "RPK", "PO-QTY-VAR", 340.10, "PO-2249")
    apinv("AP-8816", "BGR", "DUP-CHK", 1100.00)
    apinv("AP-8817", "WFA", "TAX-INV", 780.60, "PO-2243")
    apinv("AP-8818", "KPO", "3WM-FAIL", 2960.00, "PO-2252")
    apinv("AP-8819", "TBE", "CURR-RND", 95.30, "PO-2240")
    apinv("AP-8820", "LKE", "PO-QTY-VAR", 4100.00, "PO-2226")
    apinv("AP-8821", "HCH", "DUP-CHK", 615.90, "PO-2245")
    apinv("AP-8822", "RPK", "TAX-INV", 430.00, "PO-2249")
    apinv("AP-8823", "BGR", "BANK-VER", 8250.00,
         notes="Vendor changed bank details 6 days ago - held for treasury callback verification.")

    # -------------------------------------------------------------- stock
    stock_rows = [
        ("TC-10010", "WH-RAW", 5200), ("TC-10010", "LS-S1", 1000),
        ("TC-10020", "WH-RAW", 1450),                       # below reorder 2000
        ("TC-11040", "WH-RAW", 260),                        # below reorder 500
        ("TC-12010", "WH-RAW", 1300), ("TC-12010", "LS-S1", 450),
        ("TC-14010", "WH-RAW", 1900),
        ("TC-31110", "WH-COMP", 430), ("TC-31110", "LS-A1", 180),  # below 800
        ("TC-31140", "WH-COMP", 940),
        ("TC-31160", "WH-COMP", 1500),
        ("TC-31210", "WH-COMP", 28000), ("TC-31210", "LS-A1", 3000),
        ("TC-31215", "Q1", 26400),                          # quarantined hero lot
        ("TC-31215", "WH-COMP", 24000),                     # new certified lot
        ("TC-31230", "WH-COMP", 3600),
        ("TC-13020", "WH-COMP", 4400), ("TC-13020", "LS-A2", 500),
        ("TC-13040", "WH-COMP", 830),
        ("TC-13080", "WH-COMP", 830),   # UC3 shortage - see PO-2252 (binding constraint)
        ("TC-31020", "WH-COMP", 986),
        ("TC-21150", "WH-COMP", 792),
        ("TC-21170", "WH-COMP", 394),
        ("TC-90010", "WH-RAW", 4),                          # below reorder 6
        ("TC-90020", "WH-RAW", 5),
        ("TC-90030", "WH-RAW", 700),                        # below reorder 800
        ("TC-30412", "FG-1", 300),   # 80 (4471) + 220 (4472) held
        ("TC-30470", "FG-1", 72),
        ("TC-20160", "FG-1", 14),
    ]
    for pno, loc, qty in stock_rows:
        ins("stock", part_id=P[pno], location_id=LOC[loc], qty=qty)

    for i, (pno, loc, qty) in enumerate(stock_rows[:12]):
        ins("stock_movements", part_id=P[pno], from_location_id=None,
            to_location_id=LOC[loc], qty=qty, reason="receipt",
            ref=f"GRN-{2300+i}", moved_at=ts(-random.randint(3, 30)))

    # ------------------------------------------------------------ defects
    DEF = {}

    def defect(no, source, code, desc, severity, qty, dispo, status, found,
               run_no=None, lot=None, raw=None, pno=None, machine=None,
               station=None, cust=None, found_by="Priya Narayan"):
        found_off = found[0] if isinstance(found, tuple) else found
        found_at = ts(*found) if isinstance(found, tuple) else ts(found)
        DEF[no] = ins("defects", defect_no=no, source=source,
                      run_id=RUN.get(run_no), finished_lot_id=FL.get(lot),
                      raw_lot_id=RL.get(raw), part_id=P.get(pno),
                      machine_id=M.get(machine), station=station, code=code,
                      description=desc, severity=severity, qty=qty,
                      disposition=dispo, found_by=found_by, found_at=found_at,
                      status=status,
                      closed_at=ts(found_off + 3) if status == "closed" else None,
                      customer_id=C.get(cust))
        return DEF[no]

    defect("DEF-0862", "in_process", "burr_height", "Burr above 0.05 mm on busbar leg after die wear", "major", 42, "scrap", "closed", -25, run_no="RUN-1074", pno="TC-70210", machine="PRS-01", station="S-1/press 2")
    defect("DEF-0864", "in_process", "plating_blister", "Tin plating blisters on rack 12 - bath contamination", "major", 18, "rework", "closed", -24, run_no="RUN-1074", pno="TC-70210", machine="PLT-01", station="P-1")
    defect("DEF-0866", "in_process", "moulding_short", "Short-shot insulation mouldings", "minor", 15, "scrap", "closed", -24, run_no="RUN-1076", pno="TC-13080", station="A-2/60")
    defect("DEF-0868", "in_process", "hardness_low", "Case hardness 55 HRC - below 58 HRC window, basket 3", "major", 24, "scrap", "closed", -23, run_no="RUN-1082", pno="TC-21150", machine="FUR-01", station="H-1")
    defect("DEF-0870", "final_inspection", "label_error", "Container label carried wrong customer PO reference", "minor", 2, "rework", "closed", -21, run_no="RUN-1078", pno="TC-20110", station="despatch")
    defect("DEF-0872", "in_process", "bore_oversize", "Hub bore 72.024 mm after insert change - reaction plan contained 5 parts", "major", 5, "scrap", "closed", -19, run_no="RUN-1090", pno="TC-20140", machine="MC-M1-01", station="M-1/op20")
    defect("DEF-0874", "in_process", "crack_detect", "Eddy-current reject - forging fold indication", "critical", 3, "scrap", "closed", -18, run_no="RUN-1090", pno="TC-20140", raw="MC-5520", machine="MC-M1-03", station="M-1/crack bench")
    defect("DEF-0876", "receiving", "coa_missing", "Steel bar delivery arrived without CoA - lot quarantined until certs received", "minor", 1, "quarantine_lot", "closed", -16, pno="TC-10020", station="receiving")
    defect("DEF-0878", "in_process", "torque_out_of_window", "Output fastener torque low on 2 units at re-test - units quarantined", "major", 2, "scrap", "closed", -15, run_no="RUN-1092", pno="TC-30412", raw="WF-2261", machine="ASM-01", station="A-1/50")
    defect("DEF-0880", "in_process", "eol_fail_current", "EOL current draw 2.9 A - above window, gear mesh", "major", 4, "rework", "closed", -15, run_no="RUN-1092", pno="TC-30412", machine="TST-01", station="A-1/60")
    defect("DEF-0882", "in_process", "plating_thickness", "Tin 2.4 micron - below 3 micron minimum on XRF, rack 31", "major", 26, "rework", "closed", -11, run_no="RUN-1100", pno="TC-70210", machine="PLT-01", station="P-1")
    defect("DEF-0884", "final_inspection", "packing_mixed_lot", "Two lots staged for one container - repacked at despatch gate", "minor", 1, "rework", "closed", -9, pno="TC-20160", station="despatch")
    defect("DEF-0886", "customer", "short_shipment", "Marran receiving count 6 short against ASN", "minor", 6, "use_as_is", "closed", -8, pno="TC-70210", cust="MAR", found_by="Customer SQE")
    defect("DEF-0888", "in_process", "burr_height", "Busbar burr trending high - die TB-7021 approaching service", "minor", 12, "rework", "open", -3, run_no="RUN-1100", pno="TC-70210", machine="PRS-01", station="S-1/press 2")
    defect("DEF-0891", "customer", "torque_retention", "Ellandra line fallout: 3 actuators with loosened output fastener at fitment re-torque check", "critical", 3, "quarantine_lot", "open", -4, pno="TC-30412", raw="WF-2261", cust="ELL", found_by="Ellandra SQE")
    defect("DEF-0894", "in_process", "torque_retention", "Re-test of held run units: 2 further loosened joints - thread rolling suspect on lot WF-2261", "critical", 2, "quarantine_lot", "open", -3, run_no="RUN-1101", pno="TC-30412", raw="WF-2261", machine="TST-02", station="A-1/60")
    defect("DEF-0895", "in_process", "spindle_vibration", "M-2 turn-mill spindle bearing vibration alarm - line stopped", "major", 0, "rework", "open", -2, machine="MC-M2-01", station="M-2")
    defect("DEF-0896", "customer", "surface_corrosion", "TTP warehouse return - 2 hub assemblies with storage corrosion", "minor", 2, "use_as_is", "open", -2, pno="TC-20160", cust="TTP", found_by="Customer QA")
    defect("DEF-0897", "in_process", "grease_dose", "Grease dose 2.05 g - low side drift on doser", "minor", 8, "rework", "closed", -6, run_no="RUN-1101", pno="TC-30412", machine="ASM-01", station="A-1/40")
    defect("DEF-0898", "receiving", "thread_profile", "Incoming check on new fastener lot WF-2289: thread-rolling profile PASSED - released to stock", "minor", 0, "use_as_is", "closed", -3, pno="TC-31215", raw="WF-2289", station="receiving")
    # UC1 hero: overnight A-2 FPY breach, RUN-1111 - three correlated suspects
    # (resin lot changeover, INJ-01 overdue PM, night-shift trainee supervisor)
    defect("DEF-0900", "in_process", "resin_moisture_void", "Void/short-shot on HV connector housing after resin lot changeover to KP-7742 at 02:10", "major", 14, "scrap", "open", (-1, 2, 20), run_no="RUN-1111", pno="TC-70230", raw="KP-7742", station="A-2/60")
    defect("DEF-0901", "in_process", "resin_moisture_void", "Void/short-shot on HV connector housing - same changeover batch, moisture-sensitive resin suspect", "major", 17, "scrap", "open", (-1, 2, 55), run_no="RUN-1111", pno="TC-70230", raw="KP-7742", station="A-2/60")
    defect("DEF-0902", "in_process", "resin_moisture_void", "Void/short-shot on HV connector housing - third event since changeover, same failure mode", "major", 16, "scrap", "open", (-1, 3, 40), run_no="RUN-1111", pno="TC-70230", raw="KP-7742", station="A-2/60")
    defect("DEF-0903", "in_process", "dimensional_variance", "HV connector housing wall thickness drifting outside tolerance - consistent with tooling wear on an overdue mould", "major", 11, "scrap", "open", (-1, 4, 10), run_no="RUN-1111", pno="TC-70230", machine="INJ-01", station="A-2/60")
    defect("DEF-0904", "in_process", "dimensional_variance", "HV connector housing wall thickness drift - second event, same machine", "major", 8, "scrap", "open", (-1, 5, 20), run_no="RUN-1111", pno="TC-70230", machine="INJ-01", station="A-2/60")

    # -------------------------------------------------------------- holds
    ins("holds", hold_no="HLD-0140", scope="raw_lot", scope_id=RL["MC-5520"],
        reason="Forging fold indications at crack bench (DEF-0874) - lot sampled, released after 100 per cent bench sort",
        placed_by="Priya Narayan", placed_at=ts(-18), released_at=ts(-16),
        released_by="Priya Narayan", status="released")
    ins("holds", hold_no="HLD-0142", scope="raw_lot", scope_id=RL["WF-2261"],
        reason="Suspect thread rolling - torque retention failures in plant and at Ellandra (DEF-0891, DEF-0894). QP-8D containment open.",
        placed_by="Priya Narayan", placed_at=ts(-3, 8, 40), status="open")
    ins("holds", hold_no="HLD-0143", scope="finished_lot", scope_id=FL["TC-A-4471"],
        reason="Contains fastener lot WF-2261 - 80 unshipped units blocked pending 100 per cent re-torque and re-test",
        placed_by="Priya Narayan", placed_at=ts(-3, 9, 10), status="open")
    ins("holds", hold_no="HLD-0144", scope="finished_lot", scope_id=FL["TC-A-4472"],
        reason="Contains fastener lot WF-2261 - 220 unshipped units blocked pending 100 per cent re-torque and re-test",
        placed_by="Priya Narayan", placed_at=ts(-3, 9, 12), status="open")
    ins("holds", hold_no="HLD-0145", scope="run", scope_id=RUN["RUN-1101"],
        reason="Run consumed suspect lot WF-2261 - held at station 60 pending containment disposition",
        placed_by="Dana Okafor", placed_at=ts(-3, 9, 30), status="open")

    # ---------------------------------------------------------- recurring
    ins("recurring", name="Ellandra EPB weekly release", customer_id=C["ELL"],
        part_id=P["TC-30412"], qty=480, line_id=L["A-1"], cadence="weekly",
        next_run_date=d(3), active=1, last_generated_run_id=RUN["RUN-1106"])
    ins("recurring", name="Marran busbar fortnightly release", customer_id=C["MAR"],
        part_id=P["TC-70210"], qty=800, line_id=L["S-1"], cadence="fortnightly",
        next_run_date=d(8), active=1, last_generated_run_id=RUN["RUN-1100"])
    ins("recurring", name="Southbank control arm monthly", customer_id=C["SBT"],
        part_id=P["TC-20110"], qty=350, line_id=L["A-2"], cadence="monthly",
        next_run_date=d(17), active=1, last_generated_run_id=RUN["RUN-1102"])
    ins("recurring", name="EPB housing internal replenishment", customer_id=None,
        part_id=P["TC-31020"], qty=1000, line_id=L["M-1"], cadence="fortnightly",
        next_run_date=d(9), active=1, last_generated_run_id=RUN["RUN-1104"])
    ins("recurring", name="Pin set heat-treat replenishment", customer_id=None,
        part_id=P["TC-21150"], qty=800, line_id=L["H-1"], cadence="fortnightly",
        next_run_date=d(11), active=1, last_generated_run_id=RUN["RUN-1110"])

    # ------------------------------------------------------ notifications
    notes = [
        ("quality", "critical", "Customer escape - Ellandra torque retention",
         "3 actuators with loosened output fasteners at Ellandra Corio. QP-8D opened; lot WF-2261 quarantined.", "/quality"),
        ("plant_manager", "critical", "Containment open on fastener lot WF-2261",
         "Holds placed on lots TC-A-4471 and TC-A-4472 and run RUN-1101. Forward trace complete.", "/traceability"),
        ("supervisor", "warning", "Line M-2 stopped",
         "Spindle bearing replacement on the turn-mill cell - maintenance in progress.", "/machines"),
        ("supervisor", "warning", "Two supplier deliveries late",
         "PO-2246 (steel bar) and PO-2247 (forged blanks) are past their expected dates.", "/purchase-orders"),
        ("plant_manager", "warning", "Three invoices overdue",
         "INV-5215, INV-5217 and INV-5218 are past due - combined value in the finance exceptions report.", "/invoices"),
        ("line_lead", "info", "Certification expiries within 60 days",
         "One PR-1, one PL-1 and one QI authorisation lapse within 60 days; one TQ-1 already expired.", "/operators"),
        ("quality", "info", "Incoming fastener lot WF-2289 released",
         "Thread-rolling profile check passed at receiving - certified stock available for RUN-1106.", "/parts"),
        ("plant_manager", "info", "Low stock on 4 parts",
         "Steel bar, forged blanks, motor sets and cartons are below reorder point.", "/parts"),
        ("quality", "critical", "A-2 overnight FPY breach - RUN-1111",
         "First pass yield 84.3 per cent on A-2 overnight, well under the 96.5 per cent target. Root-cause suspects ready.", "/quality"),
        ("plant_manager", "warning", "23 AP invoices failed to post",
         "9 share one vendor-master cost-center cause (Coalcliff Steel, Meander Castings). See AP invoices.", "/ap-invoices"),
    ]
    for role, kind, title, body, link in notes:
        ins("notifications", role=role, kind=kind, title=title, body=body,
            link=link, created_at=ts(-random.randint(0, 4),
                                     random.randint(6, 16)), read=0)

    # -------------------------------------------------------------- audit
    audit_rows = [
        (-32, "admin@tallowacomponents.com.au", "receive", "purchase_order", "PO-2231", "Received 40,000 output fasteners + 60,000 case screws; lots WF-2261 and WF-2260 created"),
        (-25, "super@tallowacomponents.com.au", "release", "run", "RUN-1088", "Released to A-1 against SO-3411"),
        (-23, "line@tallowacomponents.com.au", "complete", "run", "RUN-1088", "480 good, 0 scrap; finished lot TC-A-4471"),
        (-20, "admin@tallowacomponents.com.au", "despatch", "shipment", "SHP-0341", "400 x TC-30412 to Ellandra Corio; ASN transmitted"),
        (-15, "quality@tallowacomponents.com.au", "defect", "defect", "DEF-0878", "2 units torque retention fail at re-test on RUN-1092"),
        (-14, "line@tallowacomponents.com.au", "complete", "run", "RUN-1092", "460 good, 10 scrap; finished lot TC-A-4472"),
        (-12, "admin@tallowacomponents.com.au", "despatch", "shipment", "SHP-0347", "240 x TC-30412 + 300 x TC-30450 to Ellandra Westhaven"),
        (-4, "quality@tallowacomponents.com.au", "defect", "defect", "DEF-0891", "Customer escape logged from Ellandra SQE notification"),
        (-3, "quality@tallowacomponents.com.au", "hold", "raw_lot", "WF-2261", "Lot quarantined - HLD-0142; QP-8D D0-D3 started"),
        (-3, "quality@tallowacomponents.com.au", "hold", "finished_lot", "TC-A-4471", "HLD-0143 placed - 80 unshipped units blocked"),
        (-3, "quality@tallowacomponents.com.au", "hold", "finished_lot", "TC-A-4472", "HLD-0144 placed - 220 unshipped units blocked"),
        (-3, "super@tallowacomponents.com.au", "hold", "run", "RUN-1101", "HLD-0145 - run held at station 60"),
        (-3, "quality@tallowacomponents.com.au", "trace", "raw_lot", "WF-2261", "Forward trace run: 2 completed runs, 1 held run, 2 shipments, 2 ship-to plants"),
        (-3, "admin@tallowacomponents.com.au", "notify", "customer", "ELL", "Containment statement sent to Ellandra SQE inside 24 hours"),
        (-2, "quality@tallowacomponents.com.au", "receive_check", "raw_lot", "WF-2289", "Thread profile check passed; lot released as certified stock"),
        (-2, "super@tallowacomponents.com.au", "stop", "line", "M-2", "Line stopped - spindle bearing replacement"),
        (-1, "plant@tallowacomponents.com.au", "update", "run", "RUN-1106", "Scheduled against certified lot WF-2289 pending A-1 capacity"),
        (-1, "admin@tallowacomponents.com.au", "despatch", "shipment", "SHP-0352", "200 x TC-20160 to Southbank Derrimut"),
    ]
    for off, email, action, entity, eid, detail in audit_rows:
        ins("audit", at=ts(off, random.randint(7, 17), random.randint(0, 59)),
            user_email=email, action=action, entity=entity, entity_id=eid,
            detail=detail)

    # -------------------------------------------------------- attachments
    att_dir = ROOT / "data" / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    atts = [
        ("raw_lot", RL["WF-2261"], "CoA-WF-2261.txt",
         "CERTIFICATE OF ANALYSIS - Warrigal Fasteners (fictional demo document)\n"
         "Lot WF-2261 - Output fastener M8x1 thread rolled, qty 40,000\n"
         "Material: class 10.9, cert ref WF-MT-9917\n"
         "Thread rolling parameters: recorded per SQA-STD (see supplier record)\n"
         "Hardness sample: PASS. Dimensional sample: PASS.\n"
         "Note: thread-rolling profile trace NOT ATTACHED at receipt - flagged in 8D.\n"),
        ("defect", DEF["DEF-0894"], "8D-DEF-0894-D3-containment.txt",
         "8D REPORT - D0-D3 CONTAINMENT (draft, fictional demo document)\n"
         "Problem: output fastener torque retention loss, EPB-40 actuator.\n"
         "Suspect cause: thread rolling out of spec, supplier lot WF-2261.\n"
         "Containment: lot quarantined all locations; runs RUN-1088/1092/1101 traced;\n"
         "holds on TC-A-4471 (80 u) and TC-A-4472 (220 u); customer notified <24 h;\n"
         "shipped exposure: 400 u SHP-0341 Corio, 240 u SHP-0347 Westhaven.\n"
         "Next: D4 root cause with supplier - thread-roll die wear suspected.\n"),
        ("run", RUN["RUN-1092"], "EOL-summary-RUN-1092.txt",
         "END-OF-LINE TEST SUMMARY (fictional demo document)\n"
         "Run RUN-1092 - TC-30412 EPB-40, 470 built, 460 passed, 10 scrap.\n"
         "Current draw mean 2.21 A (window 1.9-2.6). Actuation mean 762 ms (<900).\n"
         "2 torque-retention rejects at re-test logged as DEF-0878.\n"),
    ]
    for entity, eid, fname, content in atts:
        p = att_dir / fname
        p.write_text(content)
        ins("attachments", entity=entity, entity_id=eid, filename=fname,
            content_type="text/plain", size=p.stat().st_size,
            path=f"data/attachments/{fname}", uploaded_at=ts(-3))

    # ------------------------------------------------------ access tokens
    ins("access_tokens", name="Dealer portal integration (demo)",
        token="tc_live_demo_3f8a1c90d2", created_at=ts(-60), last_used=ts(-1))

    # -------------------------------------------------------- run time
    for run_no, entries in {
        "RUN-1101": [(3, "A-1/30", 190), (6, "A-1/50", 240), (5, "A-1/60", 120)],
        "RUN-1100": [(1, "S-1/press 2", 420), (16, "S-1/press 2", 380)],
        "RUN-1102": [(7, "A-2/20", 260), (8, "A-2/40", 200)],
        "RUN-1104": [(2, "M-1/cell 1", 410), (12, "M-1/cell 2", 940)],  # 940 = anomaly
        "RUN-1088": [(3, "A-1/30", 400), (6, "A-1/50", 430), (5, "A-1/60", 410)],
        "RUN-1092": [(3, "A-1/30", 395), (6, "A-1/50", 445), (5, "A-1/60", 430)],
    }.items():
        for op_idx, station, minutes in entries:
            ins("run_time", run_id=RUN[run_no], operator_id=OPS[op_idx][0],
                station=station, minutes=minutes,
                entered_at=ts(-random.randint(0, 5), random.randint(7, 16)),
                note=None)

    con.commit()
    counts = {}
    for t in ["users", "customers", "ship_tos", "lines", "operators", "skills",
              "operator_skills", "parts", "customer_parts", "boms", "locations",
              "stock", "raw_lots", "runs", "run_materials", "run_time",
              "finished_lots", "sales_orders", "sales_order_lines", "shipments",
              "shipment_lines", "suppliers", "purchase_orders", "invoices",
              "ap_invoices", "machines", "tooling", "defects", "holds",
              "recurring", "notifications", "audit", "attachments"]:
        counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    con.close()
    print("seeded data/erp.db:")
    for t, n in counts.items():
        print(f"  {t:20s} {n}")


if __name__ == "__main__":
    main()
