"""Cache a golden response for every AI feature's hero question.

Runs each feature live against the local server and stores the JSON in
static/cached/<name>.json. The app falls back to these automatically if a live
call fails mid-demo, so no feature ever dead-airs.

Start the app first, then:  ../../.venv/bin/python scripts/cache_golden.py
Optionally pass feature names to refresh a subset.
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8061"
OUT = ROOT / "static" / "cached"

# feature -> request body for its hero moment
BODIES = {
    "ask": {"query": "What torque does the EPB-40 output fastener take, and what "
                     "happens if a reading is out of window?"},
    "briefing": {},
    "dispatch-actions": {},
    "day-plan": {"line": "A-1"},
    "completion-note": {"run_no": "RUN-1092"},
    "run-timeline": {"run_no": "RUN-1101"},
    "similar-runs": {"run_no": "RUN-1106"},
    "parts-kit": {"run_no": "RUN-1106"},
    "time-anomaly": {},
    "customer-status-update": {"customer": "ELL"},
    "account-health": {"customer": "ELL"},
    "proactive-maintenance": {},
    "dunning-draft": {},
    "lost-quotes": {},
    "recurring-preview": {},
    "demand-reorder": {},
    "skill-gap": {},
    "sla-early-warning": {},
    "margin-insight": {},
    "exec-summary": {},
    "finance-exceptions": {},
    "cost-exceptions": {},
    "risk-watchlist": {},
    "commit-date": {"part_no": "TC-30412", "qty": 480},
    "asset-service": {},
    "quote-risk": {},
    "quote-comms": {"so_no": "SO-3438"},
    "variation-claim": {"so_no": "SO-3437",
                        "change": "Customer wants the remaining quantity expedited "
                                  "by one week and a spec change to the connector "
                                  "boot material."},
    "draft-quote": {"customer": "ELL",
                    "request": "They want 300 more TC-30412 actuators delivered "
                               "in 4 weeks - quote it."},
    "audit-assistant": {"query": "Who placed the holds on lot WF-2261 and in what "
                                 "order did containment happen?"},
    "lots": {},
    "recurring-suggest": {},
    "fault-root-cause": {},
    "compliance-readiness": {},
    "calibration-compliance": {},
    "safety-preflight": {"line": "A-1"},
    "plant-access-briefing": {"line": "A-1"},
    "lot-trace": {"lot": "WF-2261"},
    "playbook": {"part_no": "TC-30412"},
    "triage": {"message": "Ellandra line called - two more actuators from the "
                          "latest delivery failed the fitment re-torque check at "
                          "Corio this morning."},
    "extract-document": {"text": "QUOTATION - Warrigal Fasteners Pty Ltd\n"
                         "Ref WF-Q-4471, valid 30 days.\n"
                         "Item 1: TC-31215 output fastener M8x1 thread rolled, "
                         "class 10.9 - 24,000 pcs @ $0.37 each\n"
                         "Item 2: TC-31210 case screw M5 single-use - 60,000 pcs "
                         "@ $0.085 each\nDelivery 10 working days from order."},
    "agent": {"query": "Which customer shipments are exposed to fastener lot "
                       "WF-2261 and what is still on site?"},
    # ------------------------------------------------ three use-case demo
    "fpy-root-cause": {"line": "A-2",
                       "query": "Line 3 FPY alert - 84.3 per cent overnight on "
                                "A-2. What happened?"},
    "8d-draft": {"line": "A-2"},
    "ap-error-explain": {"ap_no": "AP-8801"},
    "ap-batch-fix": {"ap_no": "AP-8801"},
    "ctp-commit": {"part_no": "TC-70210", "qty": 250, "customer_code": "MAR",
                   "requested_date": "2026-08-01"},
    "ctp-commit-expedite": {"part_no": "TC-70210", "qty": 250,
                            "customer_code": "MAR", "expedite": True,
                            "requested_date": "2026-08-01"},
}
# golden key -> actual endpoint URL, when it differs from the dict key (two
# goldens sharing one endpoint, distinguished only by request body)
ENDPOINT_OVERRIDE = {"ctp-commit-expedite": "ctp-commit"}
STREAMING = {"ops-assistant": {"query": "Which customer shipments are exposed to "
                               "fastener lot WF-2261 and what is still on site?"}}


def main():
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "plant@tallowacomponents.com.au", "password": "demo1234"},
        timeout=30)
    r.raise_for_status()
    hdrs = {"Authorization": "Bearer " + r.json()["token"]}
    ok = fail = 0
    for name, body in BODIES.items():
        if only and name not in only:
            continue
        t0 = time.time()
        try:
            endpoint = ENDPOINT_OVERRIDE.get(name, name)
            rr = requests.post(f"{BASE}/api/ai/{endpoint}", json=body,
                               headers=hdrs, timeout=150)
            d = rr.json()
            good = bool(d.get("answer") or d.get("draft") or d.get("triage")
                        or d.get("events"))
            if rr.status_code == 200 and good and not d.get("empty"):
                (OUT / f"{name}.json").write_text(json.dumps(d, indent=1))
                print(f"  ok   {name} ({time.time()-t0:.1f}s)")
                ok += 1
            else:
                print(f"  FAIL {name}: status={rr.status_code} "
                      f"empty={d.get('empty')}")
                fail += 1
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            fail += 1
    for name, body in STREAMING.items():
        if only and name not in only:
            continue
        t0 = time.time()
        try:
            rr = requests.post(f"{BASE}/api/ai/{name}", json=body, headers=hdrs,
                               stream=True, timeout=150)
            events = [json.loads(ln) for ln in rr.iter_lines() if ln]
            if any(e.get("type") == "answer" for e in events):
                (OUT / f"{name}.json").write_text(
                    json.dumps({"events": events}, indent=1))
                print(f"  ok   {name} ({time.time()-t0:.1f}s, "
                      f"{len(events)} events)")
                ok += 1
            else:
                print(f"  FAIL {name}: no answer event")
                fail += 1
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            fail += 1
    print(f"goldens: {ok} ok, {fail} failed")


if __name__ == "__main__":
    main()
