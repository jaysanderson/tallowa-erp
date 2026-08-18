"""Smoke test for the three use-case flows (UC1 quality/8D, UC2 AP batch-fix,
UC3 CTP co-pilot). Run with the app up on :8061, fresh seed (data/erp.db just
rebuilt) - these flows mutate state (holds, invoices, orders), so re-seed
before re-running.

    ../../.venv/bin/python seed_db.py && \
    ../../.venv/bin/python -m uvicorn app:app --port 8061 &
    ../../.venv/bin/python scripts/smoke_usecases.py
"""
import sys
from datetime import date, timedelta

import requests

BASE = "http://localhost:8061"

# Nine days out, like the demo types: far enough that the base plan misses it
# (binding PO lands at seed+11) and the 5-day expedite pull-in beats it. A
# hardcoded date rots - it drifted into the past once and turned the BEATS
# assertion into a permanent failure while the product was behaving correctly.
REQUESTED_DATE = (date.today() + timedelta(days=9)).isoformat()
FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def login(email):
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": "demo1234"}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def main():
    quality = login("quality@tallowacomponents.com.au")
    finance = login("ap@tallowacomponents.com.au")
    sales = login("sales@tallowacomponents.com.au")
    plant = login("plant@tallowacomponents.com.au")

    # ---------------------------------------------------------------- UC1
    r = requests.post(f"{BASE}/api/ai/fpy-root-cause", headers=H(quality),
                      json={"line": "A-2"}, timeout=90)
    d = r.json()
    check("UC1 fpy-root-cause 200", r.status_code == 200)
    check("UC1 fpy-root-cause cited", len(d.get("citations", [])) > 0,
          str(len(d.get("citations", []))))
    check("UC1 fpy-root-cause names KP-7742", "KP-7742" in d.get("answer", ""))
    check("UC1 fpy-root-cause names INJ-01", "INJ-01" in d.get("answer", ""))

    r = requests.post(f"{BASE}/api/ai/lot-trace", headers=H(quality),
                      json={"lot": "KP-7742"}, timeout=90)
    check("UC1 lot-trace on new resin lot 200", r.status_code == 200)

    r = requests.post(f"{BASE}/api/holds/", headers=H(quality), json={
        "scope": "finished_lot", "scope_no": "TC-A-4900",
        "reason": "smoke test containment"})
    check("UC1 create hold 200", r.status_code == 200, str(r.json()))
    hold_no = r.json().get("hold_no")

    r = requests.post(f"{BASE}/api/ai/8d-draft", headers=H(quality),
                      json={"line": "A-2"}, timeout=90)
    d = r.json()
    check("UC1 8d-draft 200", r.status_code == 200)
    check("UC1 8d-draft mentions the live hold", bool(hold_no) and hold_no in d.get("answer", ""),
          hold_no)
    r = requests.post(f"{BASE}/api/8d-reports/", headers=H(quality),
                      json={"body": d.get("answer", ""), "approve": True})
    check("UC1 8d-report save+approve 200", r.status_code == 200, str(r.json()))

    # ---------------------------------------------------------------- UC2
    r = requests.post(f"{BASE}/api/ai/ap-error-explain", headers=H(finance),
                      json={"ap_no": "AP-8801"}, timeout=90)
    d = r.json()
    check("UC2 ap-error-explain 200", r.status_code == 200)
    check("UC2 ap-error-explain cited", len(d.get("citations", [])) > 0)
    check("UC2 ap-error-explain names the policy", "FIN-AP-03" in d.get("answer", ""))
    check("UC2 ap-error-explain AU spelling (cost centre, not center)",
          "cost center" not in d.get("answer", "").lower(), d.get("answer", ""))

    r = requests.get(f"{BASE}/api/ap-invoices/AP-8801/similar", headers=H(finance))
    sim = r.json()
    check("UC2 similar group = 9", sim.get("count") == 9, str(sim.get("count")))
    check("UC2 all within clerk authority", sim.get("all_within_clerk_authority") is True)

    ap_nos = [x["ap_no"] for x in sim["similar"]]
    r = requests.post(f"{BASE}/api/ap-invoices/batch-fix", headers=H(finance),
                      json={"ap_nos": ap_nos})
    check("UC2 batch-fix posts 9", r.status_code == 200 and r.json().get("posted") == 9,
          str(r.json()))

    r = requests.post(f"{BASE}/api/ap-invoices/batch-fix", headers=H(sales),
                      json={"ap_nos": ["AP-8810"]})
    check("UC2 batch-fix wrong role rejected (403)", r.status_code == 403)

    r = requests.get(f"{BASE}/api/ap-invoices/AP-8823/similar", headers=H(finance))
    check("UC2 escalation case has no group", r.json().get("root_cause_group") is None)

    # matches the GM's deck ("22 of 23 resolved before 8:30 AM") - exactly one
    # honest escalation (AP-8823, treasury BANK-VER), everything else clears
    rows = requests.get(f"{BASE}/api/ap-invoices/", headers=H(finance)).json()
    within = [x for x in rows if x["within_clerk_authority"]]
    escalated = [x for x in rows if not x["within_clerk_authority"]]
    check("UC2 22 of 23 within clerk authority", len(within) == 22, str(len(within)))
    check("UC2 exactly 1 escalated (AP-8823 only)",
          [x["ap_no"] for x in escalated] == ["AP-8823"], str(escalated))

    # ---------------------------------------------------------------- UC3
    r = requests.post(f"{BASE}/api/ai/ctp-commit", headers=H(sales), json={
        "part_no": "TC-70210", "qty": 250, "customer_code": "MAR",
        "requested_date": REQUESTED_DATE}, timeout=90)
    d = r.json()
    check("UC3 ctp-commit 200", r.status_code == 200)
    check("UC3 binding constraint identified", d["ctp"]["binding"] is not None)
    check("UC3 short qty = 170",
          d["ctp"]["binding"] and d["ctp"]["binding"]["short"] == 170,
          str(d["ctp"].get("binding")))
    check("UC3 verdict states MISSES", "MISSES" in d.get("answer", "").upper())

    r2 = requests.post(f"{BASE}/api/ai/ctp-commit", headers=H(sales), json={
        "part_no": "TC-70210", "qty": 250, "customer_code": "MAR",
        "expedite": True, "requested_date": REQUESTED_DATE}, timeout=90)
    d2 = r2.json()
    check("UC3 expedite re-run 200", r2.status_code == 200)
    check("UC3 expedite commit date earlier",
          d2["ctp"]["commit_date"] < d["ctp"]["commit_date"],
          f"{d2['ctp']['commit_date']} vs {d['ctp']['commit_date']}")
    check("UC3 expedite verdict states BEATS", "BEATS" in d2.get("answer", "").upper())
    # Honest failure surfacing: PO-2252 does not have enough for this order
    # AND RUN-1100 (in progress, same component) AND RUN-1105 - the co-pilot
    # must say so, not report a false "no conflict" to make the sale look clean
    check("UC3 conflict correctly found (in-progress run counted)",
          d2["ctp"]["conflict"]["conflict"] is True,
          str(d2["ctp"]["conflict"]["headroom"]))
    check("UC3 conflict headroom = -570 (RUN-1100 + RUN-1105 both counted)",
          d2["ctp"]["conflict"]["headroom"] == -570.0,
          str(d2["ctp"]["conflict"]["headroom"]))
    run_nos = {o["run_no"] for o in d2["ctp"]["conflict"]["other_orders"]}
    check("UC3 conflict includes in-progress RUN-1100", "RUN-1100" in run_nos, str(run_nos))

    r = requests.post(f"{BASE}/api/sales-orders/", headers=H(sales), json={
        "customer_code": "MAR", "customer_po": "SMOKE-CTP-01",
        "promised_date": d2["ctp"]["commit_date"],
        "lines": [{"part_no": "TC-70210", "qty": 250}]})
    so_no = r.json().get("so_no")
    check("UC3 draft SO created", r.status_code == 200 and bool(so_no), str(r.json()))

    r = requests.post(f"{BASE}/api/sales-orders/{so_no}/approve", headers=H(sales))
    check("UC3 sales role can confirm own order", r.status_code == 200)

    r = requests.post(f"{BASE}/api/expedite-requests/", headers=H(sales), json={
        "po_no": "PO-2252", "part_no": "TC-13080",
        "requested_expected": d2["ctp"]["conflict"]["applied_po_date"],
        "reason": "smoke test", "linked_so_no": so_no})
    check("UC3 expedite request proposed", r.status_code == 200, str(r.json()))
    rid = r.json().get("id")

    r = requests.post(f"{BASE}/api/expedite-requests/{rid}/approve", headers=H(sales))
    check("UC3 sales CANNOT approve own expedite (403)", r.status_code == 403)

    r = requests.post(f"{BASE}/api/expedite-requests/{rid}/approve", headers=H(plant))
    check("UC3 production planner approves expedite", r.status_code == 200)

    r = requests.get(f"{BASE}/api/purchase-orders/PO-2252", headers=H(plant))
    check("UC3 PO expected date pulled in",
          r.json()["expected_date"] == d2["ctp"]["conflict"]["applied_po_date"])

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("ALL USE-CASE SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
