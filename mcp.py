"""Tallowa Components - hosted MCP surface (twin of maintenanceOS mcp-core).

Mounts POST /mcp (Streamable HTTP, stateless JSON-RPC 2.0) on the same app
that serves the REST API. The tool catalogue is AUTO-GENERATED from this
app's own OpenAPI document - the MCP layer never reimplements business
logic. Every tools/call is dispatched back through the REST handlers
in-process (httpx ASGITransport), so auth, RBAC and validation apply to
agents exactly as they do to humans; the caller's Authorization: Bearer
token is passed straight through.

Source parity (sources/maintenanceos-analysis/SOURCE-NOTES.md):
  - same catalogue filter: no DELETEs, no /api/system, no login, no
    binary/print/download, no streaming-NDJSON routes
  - same deterministic tool naming (tag_verb_resource; {id}/action ->
    tag_action), with one deliberate deviation: /api/ai/<feature> POST
    routes become `ai_<feature>` (cleaner than ai_create_<feature>)
  - MCP resources (tallowa://openapi|dashboard|production-run/{run_no}|
    customer/{cid}) and three curated prompts
  - stateless: no session id; each POST is independent; GET /mcp returns a
    friendly probe. The original's config-gated public-access fallback is
    NOT ported - the in-app agent always carries a live JWT.
"""
import json
import re
import time
from collections import deque

import erp
import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response

PROTOCOL_DEFAULT = "2025-03-26"

_APP: FastAPI | None = None
_CLIENT: httpx.AsyncClient | None = None
_CATALOG: list[dict] | None = None   # [{name, method, path, summary, description, path_params, query_params, has_body}]

# Bounded ring buffer of recent tool dispatches - the "watch it happen" feed
# for the Integrations console. Pure observability, not a business record -
# no DB migration, and a process restart clearing it is fine (the console
# re-seeds itself with plausible prior traffic, see _seed_call_log below).
_CALL_LOG: "deque[dict]" = deque(maxlen=250)


# ------------------------------------------------------------ tool naming
def _snake(s: str) -> str:
    return re.sub(r"^_|_$", "", re.sub(r"[^a-z0-9]+", "_", s.lower()))


def tool_name_for(method: str, path: str) -> str:
    segments = [s for s in path.split("/") if s]
    if segments and segments[0] == "api":
        segments = segments[1:]
    # deviation: /api/ai/<feature> -> ai_<feature>
    if len(segments) == 2 and segments[0] == "ai" and not segments[1].startswith("{"):
        if method == "POST":
            return "ai_" + _snake(segments[1])
    last = segments[-1] if segments else "root"
    prev = segments[-2] if len(segments) > 1 else ""
    tag = _snake(segments[0]) if segments else "api"
    if not last.startswith("{") and prev.startswith("{"):
        return f"{tag}_{_snake(last)}"
    resource = next((s for s in reversed(segments) if not s.startswith("{")), "root")
    if method == "GET":
        verb = "get" if last.startswith("{") else "list"
    elif method == "POST":
        verb = "create"
    elif method == "PUT":
        verb = "update"
    elif method == "PATCH":
        verb = "patch"
    else:
        verb = method.lower()
    return f"{tag}_{verb}_{_snake(resource)}"


# ------------------------------------------------------------ catalogue
EXCLUDE_PATHS = {"/api/auth/login"}
EXCLUDE_PREFIXES = ("/api/system",)
EXCLUDE_SUFFIXES = ("/print", "/download")
# streaming NDJSON routes - not callable as a buffered tool (the buffered
# twin of ops-assistant, /api/ai/agent, IS a tool)
EXCLUDE_STREAMING = {"/api/ai/ops-assistant"}


def _build_catalog(app: FastAPI) -> list[dict]:
    spec = app.openapi()
    out, taken = [], set()
    for path, methods in (spec.get("paths") or {}).items():
        if not path.startswith("/api/"):
            continue
        if path in EXCLUDE_PATHS or path in EXCLUDE_STREAMING:
            continue
        if any(path == p or path.startswith(p + "/") for p in EXCLUDE_PREFIXES):
            continue
        if any(path.endswith(s) for s in EXCLUDE_SUFFIXES):
            continue
        for method, op in methods.items():
            m = method.upper()
            if m == "DELETE" or m not in ("GET", "POST", "PUT", "PATCH"):
                continue
            params = op.get("parameters") or []
            name = tool_name_for(m, path)
            i = 2
            while name in taken:
                name = f"{tool_name_for(m, path)}_{i}"
                i += 1
            taken.add(name)
            out.append({
                "name": name,
                "method": m,
                "path": path,
                "summary": op.get("summary") or "",
                "description": op.get("description") or "",
                "path_params": [p for p in params if p.get("in") == "path"],
                "query_params": [p for p in params if p.get("in") == "query"],
                "has_body": m in ("POST", "PUT", "PATCH"),
            })
    return out


def catalog() -> list[dict]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = _build_catalog(_APP)
    return _CATALOG


def _input_schema(t: dict) -> dict:
    props, req = {}, []
    if t["path_params"]:
        pp = {p["name"]: (p.get("schema") or {"type": "string"})
              for p in t["path_params"]}
        props["path"] = {"type": "object", "properties": pp,
                         "required": [p["name"] for p in t["path_params"]]}
        req.append("path")
    if t["query_params"]:
        qp = {p["name"]: (p.get("schema") or {"type": "string"})
              for p in t["query_params"]}
        props["query"] = {"type": "object", "properties": qp}
    if t["has_body"]:
        props["body"] = {"type": "object",
                         "description": "JSON request body (see the OpenAPI "
                         "doc at /openapi.json for the accepted fields)"}
    schema = {"type": "object", "properties": props}
    if req:
        schema["required"] = req
    return schema


def _tool_desc(t: dict) -> str:
    d = " - ".join(x for x in (t["summary"], t["description"]) if x)
    return d or f"{t['method']} {t['path']}"


# ------------------------------------------------------------ call log
def _row_count(result: dict) -> int | None:
    """Best-effort row count from a dispatched tool's own JSON response, so
    the console feed reads as real traffic (row counts) rather than a bare
    status line."""
    if result.get("isError"):
        return None
    try:
        data = json.loads((result.get("content") or [{}])[0].get("text", ""))
    except Exception:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for k in ("items", "rows", "results"):
            if isinstance(data.get(k), list):
                return len(data[k])
    return None


def _summarise_args(args: dict) -> str:
    """Flatten path/query/body into one short display string. A bearer
    token never travels in args (it is a header), so there is nothing to
    redact here - kept short regardless, for a tidy feed."""
    parts = []
    for group in ("path", "query"):
        for k, v in (args.get(group) or {}).items():
            if v not in (None, ""):
                parts.append(f"{k}={v}")
    body = args.get("body")
    if isinstance(body, dict) and body:
        parts.append("body: {" + ", ".join(list(body.keys())[:5]) + "}")
    return ", ".join(parts)[:160]


def _record_call(name: str, method: str, path: str, args: dict,
                 duration_ms: int, ok: bool, row_count: int | None,
                 bearer: str | None, source: str) -> None:
    caller = "Unauthenticated"
    if bearer:
        u = erp._verify(bearer)
        if u:
            caller = u.get("name") or u.get("email") or "Unknown"
    _CALL_LOG.appendleft({
        "ts": time.time(), "tool": name, "method": method, "path": path,
        "args": _summarise_args(args), "duration_ms": duration_ms, "ok": ok,
        "row_count": row_count, "caller": caller, "source": source,
    })


def recent_calls(limit: int = 40) -> list[dict]:
    """Newest-first recent dispatches, for the Integrations console feed."""
    return list(_CALL_LOG)[:limit]


# Plausible prior traffic across tools genuinely in the catalogue - used
# only to seed the console on a fresh process so it never opens empty
# (table-stakes gate 1). Real calls push these out within minutes of any
# live demo activity.
_SEED_TOOL_HINTS = [
    ("runs_list_runs", 14, "Morgan Riley"),
    ("holds_list_holds", 3, "Priya Narayan"),
    ("invoices_list_invoices", 22, "Maria Costa"),
    ("customers_list_customers", 6, "Nate Ferris"),
    ("parts_list_parts", 48, "Sam Patterson"),
    ("suppliers_list_suppliers", 6, "Morgan Riley"),
    ("purchase_orders_list_purchase_orders", 11, "Dana Okafor"),
    ("ap_invoices_list_ap_invoices", 9, "Maria Costa"),
    ("shipments_list_shipments", 7, "Nate Ferris"),
    ("defects_list_defects", 5, "Priya Narayan"),
]


def _seed_call_log() -> None:
    if _CALL_LOG:
        return
    by_name = {t["name"]: t for t in catalog()}
    now = time.time()
    seeded = [(name, rows, caller) for name, rows, caller in _SEED_TOOL_HINTS
             if name in by_name]
    for i, (name, rows, caller) in enumerate(seeded):
        t = by_name[name]
        _CALL_LOG.appendleft({
            "ts": now - (len(seeded) - i) * 191 - 30,
            "tool": name, "method": t["method"], "path": t["path"],
            "args": "", "duration_ms": 95 + (i * 47) % 240, "ok": True,
            "row_count": rows, "caller": caller, "source": "retrieval agent",
        })


# ------------------------------------------------------------ dispatch
def _client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_APP),
            base_url="http://tallowa.internal", timeout=120)
    return _CLIENT


async def _dispatch(t: dict, args: dict, bearer: str | None) -> dict:
    """Fill the path template, attach query/body + bearer, call in-process."""
    url = t["path"]
    path_args = (args.get("path") or {}) if isinstance(args, dict) else {}
    for m in re.findall(r"\{([^}]+)\}", url):
        if m not in path_args or path_args[m] in (None, ""):
            return {"isError": True,
                    "content": [{"type": "text", "text": f"Missing path param: {m}"}]}
        url = url.replace("{%s}" % m, str(path_args[m]))
    headers = {}
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"
    query = {k: v for k, v in ((args.get("query") or {}).items()
                               if isinstance(args, dict) else []) if v is not None}
    body = args.get("body") if isinstance(args, dict) else None
    try:
        r = await _client().request(
            t["method"], url, params=query or None,
            json=body if (t["has_body"] and body is not None) else None,
            headers=headers)
    except Exception as e:
        return {"isError": True,
                "content": [{"type": "text", "text": f"Dispatch failed: {e}"}]}
    text = r.text
    if 200 <= r.status_code < 300:
        return {"content": [{"type": "text", "text": text}]}
    return {"isError": True,
            "content": [{"type": "text", "text": f"[HTTP {r.status_code}] {text}"}]}


# ARAG's Smart-agent node namespaces a registered agent's tools by appending
# "__<registered-agent-uuid>" to the tool name (so multiple registered agents
# under one Smart agent can't collide) - e.g.
# "customers_list_customers__2f527fa6-4f88-4260-bd2f-865701d23619". Our own
# catalogue only knows the plain name, so every call 404'd as "Unknown tool"
# until this was found live via the ARAG dashboard/API (2026-07-21). Strip a
# trailing "__<uuid>" before matching so both callers (a bare MCP client and
# ARAG's Smart agent) resolve to the same tool.
_UUID_SUFFIX = re.compile(
    r"__[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _strip_agent_suffix(name: str) -> str:
    return _UUID_SUFFIX.sub("", name)


async def call_tool(name: str, args: dict, bearer: str | None) -> dict:
    lookup = _strip_agent_suffix(name)
    t = next((x for x in catalog() if x["name"] == lookup), None)
    if not t:
        return {"isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
    t0 = time.monotonic()
    res = await _dispatch(t, args or {}, bearer)
    dur_ms = int((time.monotonic() - t0) * 1000)
    # This is the JSON-RPC tools/call path - the real external caller (the
    # retrieval agent, hitting POST /mcp with the human's own bearer).
    _record_call(t["name"], t["method"], t["path"], args or {}, dur_ms,
                not res.get("isError"), _row_count(res), bearer, "retrieval agent")
    return res


async def call_tool_flat(name: str, flat: dict, bearer: str | None) -> dict:
    """Convenience for the in-app agent: route flat args into path/query."""
    t = next((x for x in catalog() if x["name"] == _strip_agent_suffix(name)), None)
    if not t:
        return {"isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
    path_names = {p["name"] for p in t["path_params"]}
    tpl_names = set(re.findall(r"\{([^}]+)\}", t["path"]))
    args = {"path": {}, "query": {}}
    for k, v in (flat or {}).items():
        if v in (None, ""):
            continue
        if k in path_names or k in tpl_names:
            args["path"][k] = v
        else:
            args["query"][k] = v
    t0 = time.monotonic()
    res = await _dispatch(t, args, bearer)
    dur_ms = int((time.monotonic() - t0) * 1000)
    # In-process call from the app's own legacy buffered agent, not the
    # external retrieval agent - kept distinct in the feed's "caller" column.
    _record_call(t["name"], t["method"], t["path"], args, dur_ms,
                not res.get("isError"), _row_count(res), bearer, "in-app agent")
    return res


def read_tools() -> list[tuple[str, str]]:
    """(name, description) for GET tools outside /api/ai - the planner set."""
    out = []
    for t in catalog():
        if t["method"] != "GET" or t["path"].startswith("/api/ai/"):
            continue
        if t["path"] in ("/api/auth/me", "/api/settings/"):
            continue
        hints = ""
        params = [p["name"] for p in t["path_params"]] + \
                 [p["name"] for p in t["query_params"]]
        if params:
            hints = " args: {" + ", ".join(params) + "}"
        out.append((t["name"], (_tool_desc(t) + hints).strip()))
    return out


# ------------------------------------------------------------ resources
FIXED_RESOURCES = [
    {"uri": "tallowa://openapi", "name": "Tallowa Plant API OpenAPI spec",
     "description": "The full OpenAPI 3 document describing every REST "
     "endpoint of the plant platform.", "mimeType": "application/json"},
    {"uri": "tallowa://dashboard", "name": "Plant dashboard",
     "description": "Live KPI snapshot: open runs, quality holds, customer "
     "PPM, overdue invoices, low stock, line status.",
     "mimeType": "application/json"},
]
RESOURCE_TEMPLATES = [
    {"uriTemplate": "tallowa://production-run/{run_no}",
     "name": "Production run detail",
     "description": "One production run with part, line, sales order, lots, "
     "time entries, defects and costing.", "mimeType": "application/json"},
    {"uriTemplate": "tallowa://customer/{cid}", "name": "Customer detail",
     "description": "A customer with its ship-tos, part numbers, orders, "
     "shipments and invoices.", "mimeType": "application/json"},
]


async def _read_resource(uri: str, bearer: str | None) -> dict:
    if uri == "tallowa://openapi":
        return {"uri": uri, "mimeType": "application/json",
                "text": json.dumps(_APP.openapi())}
    if uri == "tallowa://dashboard":
        api_path = "/api/dashboard/summary"
    else:
        run = re.match(r"^tallowa://production-run/(.+)$", uri)
        cust = re.match(r"^tallowa://customer/(.+)$", uri)
        if run:
            api_path = f"/api/runs/{run.group(1)}"
        elif cust:
            api_path = f"/api/customers/{cust.group(1)}"
        else:
            raise ValueError(f"Unknown resource URI: {uri}")
    headers = {"authorization": f"Bearer {bearer}"} if bearer else {}
    r = await _client().get(api_path, headers=headers)
    if r.status_code >= 400:
        raise ValueError(f"Resource read failed ({r.status_code}): {r.text}")
    return {"uri": uri, "mimeType": "application/json", "text": r.text}


# ------------------------------------------------------------ prompts
PROMPTS = [
    {"name": "triage-production-run",
     "description": "Given a run number, assess state and risk of a "
     "production run and recommend the next control action.",
     "arguments": [{"name": "run_no",
                    "description": "Production run number, e.g. RUN-1088.",
                    "required": True}],
     "render": lambda a: "\n".join([
         f"Triage production run `{a.get('run_no', '')}`.",
         "",
         f"1. Read `tallowa://production-run/{a.get('run_no', '')}` for full context.",
         "2. Assess: schedule position vs the promised date, quality state "
         "(defects, holds), scrap against plan, operator/machine load.",
         "3. Recommend the next control action (release, expedite, hold for "
         "quality, reschedule) and which line or inspector to involve - use "
         "`defects_list_defects` and `holds_list_holds` for open quality "
         "context.",
         "4. If unsure, ask one clarifying question; otherwise summarise the "
         "recommendation and propose the exact tool call(s) you would make. "
         "Do not execute mutations without confirmation."])},
    {"name": "draft-sales-order-from-history",
     "description": "Draft a sales order for a part and volume using "
     "comparable past orders as the anchor.",
     "arguments": [{"name": "part_no",
                    "description": "Internal part number, e.g. TC-30112.",
                    "required": True},
                   {"name": "qty", "description": "Quantity requested.",
                    "required": True}],
     "render": lambda a: "\n".join([
         f"Draft a sales order for {a.get('qty', '')} x `{a.get('part_no', '')}`.",
         "",
         f"1. Read the part via `parts_get_parts` (path part_no={a.get('part_no', '')}) "
         "for pricing, BOM and capacity context.",
         "2. Use `sales_orders_list_sales_orders` to find comparable past "
         "orders of this part and anchor unit price and lead time.",
         "3. Check open capacity with `runs_list_runs` and material cover "
         "with `inventory_list_low_stock`.",
         "4. Output the proposed order as a JSON body suitable for "
         "`sales_orders_create_sales_orders` and explain the reasoning. Do "
         "not create the order - let the human confirm."])},
    {"name": "daily-operations-briefing",
     "description": "Summarise today's plant state: runs at risk, quality "
     "holds, ship-date exposure, overdue invoices, low stock.",
     "arguments": [],
     "render": lambda a: "\n".join([
         "Produce today's operations briefing for the plant manager.",
         "",
         "Gather context via:",
         "- `tallowa://dashboard` for the KPI snapshot",
         "- `runs_list_runs` (status=in_progress and status=quality_hold)",
         "- `holds_list_holds` for open quality holds",
         "- `reports_list_ship_date_performance` for promise-date exposure",
         "- `invoices_list_invoices` for overdue invoices",
         "- `inventory_list_low_stock` for material to chase",
         "",
         "Output: 6-10 bullets, ordered by priority, each carrying the "
         "run / lot / order / invoice numbers a manager can click into. Be "
         "specific, not vague."])},
]


# ------------------------------------------------------------ JSON-RPC
def _bearer_from(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


async def _handle_rpc(msg: dict, bearer: str | None):
    method = msg.get("method") or ""
    params = msg.get("params") or {}
    rid = msg.get("id")
    if rid is None:      # notification - no response
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": code, "message": text}}

    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion")
                   or PROTOCOL_DEFAULT,
                   "capabilities": {"tools": {},
                                    "resources": {"subscribe": False,
                                                  "listChanged": False},
                                    "prompts": {"listChanged": False}},
                   "serverInfo": {"name": "tallowa-plant", "version": "1.0.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": t["name"],
                              "description": _tool_desc(t),
                              "inputSchema": _input_schema(t)}
                             for t in catalog()]})
    if method == "tools/call":
        res = await call_tool(params.get("name") or "",
                              params.get("arguments") or {}, bearer)
        return ok(res)
    if method == "resources/list":
        return ok({"resources": FIXED_RESOURCES})
    if method == "resources/templates/list":
        return ok({"resourceTemplates": RESOURCE_TEMPLATES})
    if method == "resources/read":
        try:
            r = await _read_resource(params.get("uri") or "", bearer)
        except ValueError as e:
            return err(-32602, str(e))
        return ok({"contents": [r]})
    if method == "prompts/list":
        return ok({"prompts": [{"name": p["name"],
                                "description": p["description"],
                                "arguments": p["arguments"]}
                               for p in PROMPTS]})
    if method == "prompts/get":
        p = next((x for x in PROMPTS if x["name"] == params.get("name")), None)
        if not p:
            return err(-32602, f"Unknown prompt: {params.get('name')}")
        text = p["render"](params.get("arguments") or {})
        return ok({"messages": [{"role": "user",
                                 "content": {"type": "text", "text": text}}]})
    return err(-32601, f"Method not found: {method}")


def mount(app: FastAPI) -> None:
    """Register /mcp on the app. Call AFTER all routers are included."""
    global _APP
    _APP = app

    @app.post("/mcp", include_in_schema=False)
    async def mcp_post(request: Request):
        bearer = _bearer_from(request)
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32700,
                                           "message": "Parse error"}},
                                status_code=400)
        if isinstance(payload, list):
            out = [r for m in payload
                   if (r := await _handle_rpc(m, bearer)) is not None]
            if not out:
                return Response(status_code=202)
            return JSONResponse(out)
        res = await _handle_rpc(payload, bearer)
        if res is None:          # notification
            return Response(status_code=202)
        return JSONResponse(res)

    @app.get("/mcp", include_in_schema=False)
    async def mcp_get():
        return JSONResponse({
            "service": "tallowa-plant-mcp",
            "transport": "streamable-http",
            "tools": len(catalog()),
            "message": "POST JSON-RPC 2.0 frames to this URL with an "
                       "`Authorization: Bearer <jwt>` header.",
        })

    # ------------------------------------------------- Integrations console
    # Read-only views over the same catalogue/log this module already owns -
    # kept out of the OpenAPI schema (and so out of the MCP catalogue itself)
    # since they are the admin console, not a plant-data tool.
    @app.get("/api/mcp/catalog", include_in_schema=False)
    def mcp_catalog_api(user: dict = Depends(erp.current_user)):
        tools = catalog()
        return {
            "endpoint": "/mcp",
            "transport": "Streamable HTTP - JSON-RPC 2.0",
            "auth": "Authorization: Bearer <JWT>, forwarded from the signed-in "
                   "user - the same role and permissions apply to every tool "
                   "call as they do in the web app.",
            "tool_count": len(tools),
            "tools": [{"name": t["name"], "method": t["method"], "path": t["path"],
                      "description": _tool_desc(t), "input_schema": _input_schema(t)}
                     for t in tools],
            "resources": FIXED_RESOURCES,
            "resource_templates": RESOURCE_TEMPLATES,
            "prompts": [{"name": p["name"], "description": p["description"],
                        "arguments": p["arguments"]} for p in PROMPTS],
        }

    @app.get("/api/mcp/calls", include_in_schema=False)
    def mcp_calls_api(limit: int = 40, user: dict = Depends(erp.current_user)):
        return {"calls": recent_calls(limit)}

    _seed_call_log()
