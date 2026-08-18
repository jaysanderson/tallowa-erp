"""Smoke test for the hosted MCP surface + the MCP-driven Ops Assistant.

Run with the app up on :8061:
    ../../.venv/bin/python scripts/smoke_mcp.py
"""
import json
import sys

import requests

BASE = "http://localhost:8061"
FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def rpc(method, params=None, token=None, rid=1):
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    r = requests.post(f"{BASE}/mcp", headers=headers, timeout=120,
                      json={"jsonrpc": "2.0", "id": rid, "method": method,
                            "params": params or {}})
    return r.json()


def main():
    # login as plant manager
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "plant@tallowacomponents.com.au", "password": "demo1234"})
    check("login", r.status_code == 200, str(r.status_code))
    token = r.json().get("token")

    # initialize
    d = rpc("initialize", {"protocolVersion": "2025-03-26",
                           "capabilities": {}, "clientInfo": {"name": "smoke"}})
    check("initialize", d.get("result", {}).get("serverInfo", {}).get("name")
          == "tallowa-plant")

    # tools/list
    d = rpc("tools/list")
    tools = {t["name"]: t for t in d.get("result", {}).get("tools", [])}
    check("tools/list count", len(tools) >= 90, f"{len(tools)} tools")
    for expect in ("runs_list_runs", "runs_get_runs", "trace_list_forward",
                   "holds_list_holds", "ai_briefing", "ai_fault_root_cause",
                   "sales_orders_create_sales_orders", "runs_status"):
        check(f"tool present: {expect}", expect in tools)
    for absent_path in ("/api/auth/login", "/api/system/reset",
                        "/api/ai/ops-assistant"):
        check(f"excluded: {absent_path}",
              not any(absent_path == t.get("_p") for t in tools.values()))
    check("no delete tools",
          not any(n.startswith(("access_tokens_delete",)) or "_delete_" in n
                  for n in tools))
    check("no print/download tools",
          not any(n.endswith(("_print", "_download")) for n in tools))

    # tools/call without auth -> HTTP 401 surfaced as isError
    d = rpc("tools/call", {"name": "runs_list_runs", "arguments": {}})
    res = d.get("result", {})
    check("unauth call isError", res.get("isError") is True
          and "401" in (res.get("content") or [{}])[0].get("text", ""))

    # tools/call with auth
    d = rpc("tools/call", {"name": "runs_list_runs",
                           "arguments": {"query": {"status": "quality_hold"}}},
            token=token)
    res = d.get("result", {})
    body = (res.get("content") or [{}])[0].get("text", "")
    ok = not res.get("isError") and "RUN-" in body
    check("runs_list_runs (quality_hold)", ok, body[:80])

    # tools/call with path param - the hero run
    d = rpc("tools/call", {"name": "runs_get_runs",
                           "arguments": {"path": {"run_no": "RUN-1088"}}},
            token=token)
    body = (d.get("result", {}).get("content") or [{}])[0].get("text", "")
    check("runs_get_runs RUN-1088", "RUN-1088" in body)

    # hero trace through MCP
    d = rpc("tools/call", {"name": "trace_list_forward",
                           "arguments": {"query": {"lot": "WF-2261"}}},
            token=token)
    body = (d.get("result", {}).get("content") or [{}])[0].get("text", "")
    check("trace WF-2261 forward", "TC-A-4471" in body and "SHP-" in body,
          body[:100])

    # resources
    d = rpc("resources/list")
    uris = [x["uri"] for x in d.get("result", {}).get("resources", [])]
    check("resources/list", "tallowa://dashboard" in uris
          and "tallowa://openapi" in uris)
    d = rpc("resources/read", {"uri": "tallowa://dashboard"}, token=token)
    txt = (d.get("result", {}).get("contents") or [{}])[0].get("text", "")
    check("resources/read dashboard", "open_runs" in txt or "runs" in txt,
          txt[:80])
    d = rpc("resources/read", {"uri": "tallowa://production-run/RUN-1092"},
            token=token)
    txt = (d.get("result", {}).get("contents") or [{}])[0].get("text", "")
    check("resources/read run template", "RUN-1092" in txt)

    # prompts
    d = rpc("prompts/list")
    names = [p["name"] for p in d.get("result", {}).get("prompts", [])]
    check("prompts/list", set(names) == {"triage-production-run",
                                         "draft-sales-order-from-history",
                                         "daily-operations-briefing"})
    d = rpc("prompts/get", {"name": "triage-production-run",
                            "arguments": {"run_no": "RUN-1088"}})
    msg = (d.get("result", {}).get("messages") or [{}])[0]
    check("prompts/get render",
          "RUN-1088" in msg.get("content", {}).get("text", ""))

    # Ops Assistant live - MCP-driven, streamed
    r = requests.post(f"{BASE}/api/ai/ops-assistant",
                      headers={"authorization": f"Bearer {token}"},
                      json={"query": "Which runs are on quality hold and is "
                            "any customer shipment exposed?"},
                      stream=True, timeout=180)
    # The ops assistant now streams the hosted retrieval agent's own trace
    # (start / tool_call / tool_result / composing / answer) - the old
    # in-app planner vocabulary (plan.transport, step.surface) is gone
    # since the ARAG rearchitecture.
    events = [json.loads(line) for line in r.iter_lines() if line]
    types = [e["type"] for e in events]
    tool_ok = [e for e in events
               if e["type"] == "tool_result" and e.get("ok") is not False]
    answer = next((e for e in events if e["type"] == "answer"), {})
    check("ops-assistant event flow",
          types and types[0] == "start" and "answer" in types,
          "->".join(types))
    check("ops-assistant live tool retrievals", len(tool_ok) >= 1,
          f"{len(tool_ok)} ok tool_result event(s)")
    check("ops-assistant grounded answer", len(answer.get("text", "")) > 80,
          answer.get("text", "")[:100].replace("\n", " "))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURES: {FAILS}")
        sys.exit(1)
    print("ALL MCP SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
