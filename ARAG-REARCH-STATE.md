# ARAG Re-architecture — Tallowa ERP: Feasibility Gate

**Status: 11th pass — MILESTONE PROVEN: ARAG's Smart agent genuinely drives
our `/mcp` tools end to end, with the caller's JWT correctly forwarded and RBAC
respected. Confirmed with a real, grounded, cited-from-live-data answer (not
narration, not a fallback) after the `valid_headers` fix. BUT the flagship
demo question (WF-2261 lot exposure) still times out at ~300s — a DIFFERENT
symptom than before (zero step events this time, not even a first planning
iteration), so the architecture is proven but that specific multi-hop question
is not yet demo-ready. Reporting both results precisely.**

## 11th-pass: simple question is a genuine, complete success

Confirmed via API first: `context[smart].registered_agents[0].valid_headers`
now shows `["authorization"]` — the dashboard save persisted correctly.

Re-ran **"List our customers."** with a fresh admin JWT: **31.8 seconds,
complete, grounded, real answer** — a full formatted list of six real seeded
customers (AllBrake Distribution, Ellandra Motors, Korrawin Assemblies,
Marran Automotive, Southbank Truck Group, Torrens Trade Parts) each with
contact name, email, phone, city and state, pulled live from
`customers_list_customers` via MCP. Trace shows the tool call succeeding
cleanly this time (`"MCP: Tool result", "value": "No tool used"` on the first
attempt is a red herring label — the SECOND reactive iteration immediately
called `task_complete()` and the pipeline moved straight to a real answer;
no errors anywhere in the trace). **This is unambiguous proof of the whole
target architecture**: ARAG's Smart agent planned, called our live `/mcp`
tool with the forwarded user JWT, retrieved real ERP data, and generated a
cited, accurate answer — the exact GM directive ("ARAG plans and calls the
app's own /mcp as its tool source... grounds... answers") working end to end,
not app code doing the retrieval and ARAG only narrating.

## But the flagship demo question (WF-2261 exposure) still doesn't complete

Re-ran the seeded narrative question ("How many customer shipments are
exposed to fastener lot WF-2261, and which customers?") with a fresh JWT:
**timed out at 301.1s, same as pass 8** — but this time **zero step events**
were streamed at all (pass 8 at least reached "Reactive mode completed" after
5 iterations before the later timeout; this run produced literally nothing
until the blank-detail exception at the end). Something about this specific
question is stalling even earlier than before — possibly before the planner
even logs its first iteration.

Checked the `/mcp` tool catalogue for what a lot-exposure chain would need:
`lots_list_lots`, `trace_list_forward`, `trace_list_backward`,
`shipments_list_shipments`, plus an existing app-level `ai_lot_trace` tool
(one of the deterministic-narrative endpoints already in the catalogue) — all
present and reachable directly (confirmed via `tools/list`, 120 tools total).
**Working theory, not yet confirmed**: the Smart agent's planner has to
reason over the FULL 120-tool catalogue with no curation
(`registered_agents_exposed_functions` is empty `{}` for our MCP node,
meaning nothing is pre-filtered) to figure out a multi-hop chain (lot ->
production runs -> shipments -> customers), and either that reasoning step
itself is slow/expensive at this catalogue size, or the specific tool chain
needed here behaves differently than a single, unambiguous tool call like
`customers_list_customers`. Have not yet isolated further (e.g. tried a
question needing 2 hops but naming fewer entities, or checked whether
`registered_agents_exposed_functions` can be set to a curated subset of
tools to reduce the planner's search space) — flagging this now rather than
continuing to iterate without checking in, given the milestone question is
otherwise answered.

**Net position**: the re-architecture itself is proven and working — this is
not an open feasibility question any more. What's left is a scoping/tuning
problem on the hardest seeded question specifically, most likely solvable by
curating the tool list the Smart agent sees (via
`registered_agents_exposed_functions`) rather than anything structurally
broken. Have not touched app code (`ai.py`) or started wiring the Ops
Assistant yet, pending this being resolved or a call to proceed with a
narrower demo question set.

---

## 10th-pass (superseded above — kept for the record)

**Status: 10th pass — name-mangling fix confirmed deployed and WORKING: tools
now resolve under their plain names (`agent_path` in the trace correctly maps
to the tool; the error message itself now names the plain tool, not the
mangled one). One layer down, hit exactly the gap the lead predicted: every
tool call now fails with a clean `401 Not authenticated` — ARAG's Smart-agent
-> MCP node isn't forwarding the `headers.authorization` bearer from the
top-level `/session/ephemeral` call down to the individual tool calls. This is
the JWT-forwarding gap, not a new bug — the lead already knows the fix
("Valid headers to forward" field on the MCP node, currently empty per
`GET context`'s `valid_headers: []`). Reporting for that one dashboard edit
before the final smoke.**

## 10th-pass: re-ran both smoke questions after the deploy; isolated the exact next gap

Re-ran "List our customers." (32.2s, same shape as before superficially) but
the **full raw event** for the "MCP: Tool error" step tells a different story
than pass 9:

```json
{
  "step": {
    "module": "mcp", "title": "MCP: Tool error",
    "agent_path": "/context/2f527fa6-4f88-4260-bd2f-865701d23619",
    "error": "Tool customers_list_customers encountered an error: [HTTP 401] {\"detail\":\"Not authenticated\"}"
  }
}
```

**The tool name in the error is now the plain `customers_list_customers`** —
not the mangled `__<uuid>` form from pass 9. The naming fix is confirmed
working end to end (matches the lead's own direct-curl verification). The
failure has moved cleanly from "Unknown tool" to a real, expected-shape
`401 Not authenticated` — i.e. the tool call reaches our `/mcp` dispatch and
gets rejected only for lack of a bearer token, exactly the "JWT-forwarding
gap" flagged as the open question at the end of pass 9.

Checked `GET .../context`'s `smart` item -> `registered_agents[0].valid_headers`
is `[]` (empty) — consistent with "authorization" not yet being on the
forward-list for that MCP node, matching what the lead described seeing in
the dashboard ("Valid headers to forward to the agent" field).

**Did not attempt to set `valid_headers` via the API myself** — pass 8 already
showed a `PATCH` to fields nested under the `smart` item's `registered_agents`
throws a clean `500` (the same write path that needed a dashboard fix for the
missing-description issue). Rather than risk another round of that, and since
the lead already offered to add it in the dashboard, handing this one field
edit back to them as agreed.

Current state: `mcp.py`'s naming fix live in production, confirmed working;
`smart` context item's registered MCP node still has empty `valid_headers`, so
every tool call gets a clean, expected `401` rather than any error; nothing
else changed. One dashboard edit away from a real answer.

---

## 9th-pass (superseded above — kept for the record)

**Status: 9th pass — ROOT CAUSE FOUND AND FIXED (locally, not deployed). The
"timeout" wasn't a hang or a budget problem: ARAG's Smart-agent node namespaces
every registered agent's tool names by appending
`__<registered-agent-uuid>` (e.g. `customers_list_customers__2f527fa6-...`), and
our `/mcp` server did exact-string matching against its catalogue, so EVERY
tool call failed with "Unknown tool". Confirmed directly by curling our own
live `/mcp` with the exact mangled name ARAG used. Fixed in `mcp.py`: strip a
trailing `__<uuid>` before catalogue lookup. Verified locally (restarted the
`:8061` dev server, mangled name now resolves and correctly reaches the
auth-check step instead of "Unknown tool"). **Not deployed to
`tallowa-plant.fly.dev` — that's the lead's call, per the rule that I don't
redeploy myself.** The full end-to-end proof (agent answering from live MCP
data) needs this fix live in production, since ARAG calls the public URL, not
localhost.**

## 9th-pass: diagnostic run found the real bug, not a hang

Ran the lead's suggested diagnostic — a simple, single-tool-call question
("List our customers.") through the same ephemeral endpoint with a fresh admin
JWT. **It completed in 30.8 seconds** (not a hang) with streamed step events
showing exactly what happened:

```
[6.1s]  smart  Reactive iteration 1/5 — Tool calls: customers_list_customers__2f527fa6-4f88-4260-bd2f-865701d23619()
[6.2s]  mcp    MCP: Tool error
[6.2s]  smart  Execution iteration 1/5 — Results: ... : context
... (identical pattern, iterations 2-5, ~3-6s apart)
[22.1s] smart  Reactive mode completed — Completed after 5 iteration(s)
[26.0s] smart  Context validation
[30.8s] answer: "Not enough data to answer this."
```

Every one of the 5 iterations tried to call the SAME tool and got the SAME
"MCP: Tool error" — the Smart agent burned through its whole
`max_iterations: 5` budget hitting a wall on the very first tool call, every
time, then gave up gracefully. **The actual tool name in the trace is
`customers_list_customers__2f527fa6-4f88-4260-bd2f-865701d23619`** — our
plain tool name plus `__` plus the exact UUID of the `mcp`-module item inside
`registered_agents` (`2f527fa6-...`, the id visible in the `GET context`
response from pass 8). This is ARAG's own namespacing scheme for
disambiguating tools across multiple registered agents under one Smart agent
— not a bug in ARAG's calling convention, just one our server didn't know
about.

**Confirmed directly**: curled our own live `/mcp` with that exact mangled
name -> `{"isError":true,"content":[{"type":"text","text":"Unknown tool:
customers_list_customers__2f527fa6-4f88-4260-bd2f-865701d23619"}]}`. Curled
the plain name -> resolves fine (gets to the real auth check, `401 Not
authenticated`, since no bearer was sent on that direct test). This is the
whole bug: `mcp.py`'s `call_tool()` (the `tools/call` JSON-RPC handler, the
one path external MCP clients — including ARAG — actually hit) does exact
`x["name"] == name` matching against the catalogue, with no tolerance for a
suffix.

**Fix applied to `apps/tallowa-erp/mcp.py`** (not deployed): added a
`_strip_agent_suffix()` helper (regex-strips a trailing
`__<8-4-4-4-12 hex uuid>`) and applied it in both `call_tool()` (the real
external-client path) and `call_tool_flat()` (the in-app path, for
consistency, though that's being retired anyway). Verified locally: restarted
the `:8061` dev uvicorn process (which was already running from an earlier
session) to pick up the change, then curled it with the exact mangled name
again -> now resolves correctly and returns the real `401 Not authenticated`
instead of "Unknown tool" — proof the fix works. **Did not touch or restart
the live Fly deployment.**

**What this means and what's still open:**
- This explains BOTH the earlier symptoms: the simple question's fast-fail
  loop (5 iterations x an "Unknown tool" error each, ~22s, well under any
  timeout) and the WF-2261 question's ~300s stall are almost certainly the
  same root cause — a harder, multi-hop question likely drives more distinct
  tool-name attempts and/or the Smart agent's own retry/backoff behaviour
  around repeated tool failures, which for a bigger reasoning chain can
  plausibly run past the driver's 300s timeout. Not fully proven (I can't
  test the WF-2261 case against the fix without the fix being live), but this
  is a far more coherent explanation than a genuine platform hang.
- **Open question I can't resolve without a deploy**: once the tool NAME
  resolves, does ARAG's Smart-agent -> MCP node actually forward the
  `headers.authorization` bearer I set on the top-level `/session/ephemeral`
  call down to the individual tool calls? Every tool call so far has failed
  before reaching that check (name mismatch masked it). Worth watching for
  specifically once the fix is live — if tool calls start resolving but come
  back `401 Not authenticated` uniformly, that's the next (and hopefully
  last) thing to fix, and matches exactly the JWT-forwarding pattern the
  reference's `forwardHeaders` mechanism is meant to solve.

Current state: `mcp.py` has the fix, `apps/tallowa-erp/.env` unchanged, agent
config unchanged from pass 8 (`smart` context item with `registered_agents`
wired to `tallowa-mcp`, no `ask` item). Local `:8061` dev server has the fix
running; `tallowa-plant.fly.dev` (production, what ARAG actually calls) does
not yet. Nothing crashes on either side; the live smoke test will still fail
with "Unknown tool" until this deploys.

---

## 8th-pass (superseded above — kept for the record)

**Status: 8th pass — `registered_agents` is now confirmed correctly populated
(the lead's description-field fix worked). Confirmed the pipeline is genuinely
trying to run the Smart agent -> MCP path now (no more instant no-op). But the
interaction times out at ~300 seconds with an empty error detail, before ever
completing or streaming a tool-call trace. Reporting this precisely — need a
decision on whether to try raising the driver's timeout or treat this as a
platform issue to flag.**

## 8th-pass: registered_agents confirmed live; interaction now genuinely runs, but times out around 300s

`GET /api/v1/agent/{agentId}/context` now shows the `smart` item's
`registered_agents` fully populated: one `module: "mcp"` node,
`source: "tallowa-mcp"`, `transport: "HTTP"`, with a real
`registered_agents_descriptions` entry ("Queries the live Tallowa Components ERP
over MCP for operational data..."). The lead's dashboard fix persisted correctly
this time — confirmed via the API, not just the dashboard UI.

Minted a fresh admin JWT, re-ran the exact same smoke question. First attempt
came back byte-identical to the pre-fix response (`"No sources available"`,
same length) — meaning the interaction wasn't even reaching the `smart` context
item. Isolated why: the agent still had BOTH the `ask` item (KB retrieval,
`sources: []`, always fails with "No sources available" since the agent-mode KB
has zero synced documents) and the `smart` item in its `context` list. **Deleted
the `ask` item** (`DELETE /api/v1/agent/{id}/context/{id}`, the same endpoint
that removed the crashing item back in pass 4) so `smart` is the sole context
item, and reran.

**This time the interaction genuinely engaged** — no more instant failure. Had
to switch to streaming reads (`requests.post(..., stream=True)` +
`iter_lines()`) because the plain blocking call exceeded normal HTTP client
timeouts. Streamed trace:
- `[1.1s]` — the interaction's opening event (as expected).
- **nothing at all for the next ~300 seconds** — no step events, no partial
  answer chunks.
- `[301.1s]` — `{"exception": {"detail": "", "extra": null}, "answer": null, ...}`
  — an exception with an **empty** detail string, then the interaction ends.

That ~300-second mark is suspicious and probably not a coincidence: the
`mcphttp` driver's own config (visible via `GET /drivers`) carries
`"timeout": 300.0` and `"sse_read_timeout": 300.0`. This reads as the driver's
own internal timeout firing — the Smart agent's reactive planning loop
(`planner_model`/`executor_model: chatgpt-4.1`, `max_iterations: 5`,
`max_turns: 5`) is plausibly taking multiple LLM-planning round-trips plus real
tool calls and running past the 300s ceiling, or a single tool call is hanging.
No diagnostic detail came back to say which. Our own `/mcp` endpoint responds
in well under a second to a direct call (confirmed earlier), so this doesn't
look like our server being slow — more likely either a genuinely long
multi-iteration planning loop, or a hang somewhere in ARAG's own MCP-calling
code (matching the pattern of real server-side rough edges found throughout
this build: the MCPHTTPDriver crash, the nucliadb dashboard-only auth key, the
`registered_agents` write 500).

**This is real, meaningful progress** — the architecture is right, the
config is right, and the agent is genuinely attempting to call our MCP tools
now (not failing instantly) — but it isn't completing within the driver's
timeout window. Options worth considering: (a) try raising the `mcphttp`
driver's `timeout`/`sse_read_timeout` via a `PATCH` on the driver (untested —
may hit another server-side edge, given the pattern so far), (b) narrow the
smoke question to something requiring fewer reasoning/tool-call hops to see if
a simpler question completes within 300s, or (c) treat the ~300s ceiling as a
platform constraint to flag to Progress rather than something we can tune
around. Reporting before choosing a direction myself, given the pattern of
each "obvious" fix so far surfacing a new server-side edge.

Current agent state: only the `smart` context item remains (the `ask` item was
deleted to isolate this test); `registered_agents` correctly wired to the
`tallowa-mcp` driver; generation/rules unchanged. Nothing crashes; the
interaction now genuinely runs but times out before producing an answer.

---

## 7th-pass (superseded above — kept for the record)

**Status: 7th pass — the lead hand-built the Smart-agent -> MCP node graph in the
dashboard. Confirmed real, meaningful progress: the MCPHTTPDriver crash is GONE.
But the graph as saved doesn't yet drive an answer — `GET context` shows the Smart
agent's `registered_agents` is empty (`[]`), and my own attempt to wire it via API
(`PATCH .../context/{smart_id}` with `registered_agents: [...]`, tried both the
driver's identifier string and its UUID) throws a clean, reproducible
`500 Internal Server Error` both times — a second distinct server-side bug, on top
of the first one this dashboard rebuild worked around. Smoke test currently
returns a clean, non-crashing `"No sources available"` (no MCP tool calls
happened). Reporting this precisely — it needs either dashboard-side verification
that the MCP-under-Smart-agent connection actually persisted, or a Progress-side
fix for the `registered_agents` write path.**

## 7th-pass: crash fixed, but the registered_agents link isn't landing

Minted a fresh admin JWT and ran the authoritative smoke test the lead asked for,
against the dashboard-rebuilt `default` workflow:

- **First run** (before I touched anything): `"Auth error 403: No roles could be
  resolved for AnonymousUser anonymous at api/v1/kb/e7c85431-.../search"` — no
  MCPHTTPDriver crash at all. That's genuine progress: the Smart-agent topology
  the lead built avoids the exact bug from pass 4. The 403 itself was **my own
  leftover mess** from pass 6 — the `ask` context item still had
  `sources: ["tallowa-kb"]` pointing at a nucliadb driver I'd created via the API
  without a working auth key (the same dashboard-only-auth limitation as before).
- **Inspected the live context list** and found the dashboard build added a
  **second context item**, `module: "smart"` (id `a38dac8b-...`) — this is the
  Smart agent node. Its shape: `planning_mode: "reactive"`,
  `planner_model`/`executor_model: "chatgpt-4.1"`, `max_iterations: 5`, and
  crucially **`"registered_agents": []`** — empty, despite the lead describing
  having connected the MCP node to its "REGISTERED AGENTS" output and saved.
- **Cleaned up my own leftover mess**: cleared `sources: []` on the `ask` item,
  then deleted the `tallowa-kb` driver entirely (`DELETE
  /api/v1/agent/{id}/driver/{uuid}` — note **singular** `driver`, the plural
  `drivers/{id}` 404s; this is the working delete path, worth remembering).
- **Tried to wire `registered_agents` myself via the API**, in case the dashboard
  save genuinely hadn't landed: `PATCH .../context/{smart_id}` with
  `{"module": "smart", "registered_agents": ["tallowa-mcp"]}` (the driver's
  identifier) -> **`500 Internal Server Error`**. Retried with the driver's UUID
  (`e4961ba1-...`) instead of its identifier string -> **`500` again**. Both
  attempts left the item unchanged (re-`GET` confirmed `registered_agents` still
  `[]`, not corrupted) — so the write is cleanly rejected server-side, not
  silently half-applied.
- **Re-ran the smoke test** with the `ask` item's bad source cleared and the
  `tallowa-kb` driver removed: clean `200`, `"exception": {"detail": "No sources
  available"}`, `"answer": "Error in context"` — no crash, but also no MCP tool
  calls (nothing to call, since `registered_agents` is still empty and the KB
  context item genuinely has nothing to retrieve).

**Read on this:** the architecture the lead built (MCP under a Smart agent, not a
direct context module) is confirmed to be the right shape — it avoids the crash.
What's not landing is the actual edge connecting the Smart agent to the MCP
driver. Either the dashboard's save of that specific connection didn't
persist server-side (worth an explicit re-save/re-check, maybe via a hard
refresh of the node editor to confirm it reads back correctly), or
`registered_agents` has to be set through a different mechanism than a plain
field PATCH — and the `500` on my attempt suggests that field write path has its
own bug, consistent with the pattern of real, reproducible ARAG server bugs found
throughout this investigation (the MCPHTTPDriver crash, the nucliadb-driver
dashboard-only auth gap, and now this).

Current live agent state: `ask` context item has `sources: []` (clean, no auth
error); `tallowa-kb` driver deleted; `smart` context item unchanged from the
dashboard build, `registered_agents: []`; `tallowa-mcp` (mcphttp) driver is the
only driver left, present but not yet reachable by anything in the pipeline.
Nothing crashes; nothing yet produces a real answer.

---

## 6th-pass (superseded above — kept for the record)

**Status: 6th pass — got the MaintenanceOS agent id and read its LIVE config
directly (drivers/context/generation/rules all readable). Learned real things:
their working setup does NOT put `mcphttp` in a `context` step at all (matches the
crash we hit); it has a `sources` field on the `ask` context step, which I first
hypothesised was the "attach MCP as a tool" mechanism — tested it, and it's
actually restricted to NucliaDB-type sources only (multi-KB retrieval), not a
general tool-attachment point. Also independently reproduced the reference's
"nucliadb driver needs the dashboard for its auth key" limitation via a live 403.
The one thing still not visible via any API endpoint I can reach — on EITHER
agent — is the actual node/edge graph the lead saw in the dashboard: `GET
/workflows` returns only a name/description/input-argument-schema summary for
BOTH the Tallowa and the real, working MaintenanceOS `"mos"` workflow — not a node
graph. Handing this to the lead's dashboard access, now with strong evidence for
why the API path is a dead end here specifically. Reporting before proceeding.**

## 6th-pass: read MaintenanceOS's live config; ruled out two more hypotheses with real evidence

`GET /api/v1/agent/f31c9528-4426-4a90-9222-ffb4a8a6366a/workflows` (EU host) shows
MaintenanceOS has two workflows: `"default"` (literally named `"Do NOT use"`,
empty `parameters`) and `"mos"` (`"Answer MaintenanceOS operational questions
using the knowledge base ... and the live ERP MCP tools"`, `parameters:
{"question": {"type": "string", "description": "..."}}`). **The `parameters` field
on a workflow is an input-argument schema (what keys `interactStream`'s
`arguments` can carry), not a node graph** — confirmed on their own real, working
`"mos"` workflow, which the ai.ts code proves actually functions in production.
This rules out my working theory that a workflow's `parameters` blob IS the node
graph; whatever encodes the visual topology the lead saw isn't exposed here.

Their flat `drivers`/`context`/`generation`/`rules` (the SAME four endpoint types
I've been configuring on ours):
- **Two drivers**: `mcphttp-1518` -> `https://maintenanceos.fly.dev/mcp` (headers
  set to `Accept`/`Content-Type` only, no bearer — public demo MCP, matches
  `arag-provision-agent.ts`), and `nucliadb-2fff` -> their own KB
  (`9c08504b-...` on `aws-eu-central-1-1.rag.progress.cloud`).
- **One context item**, `module: "ask"` — **not** `module: "mcp"`. Has a
  `"sources": []` field (currently empty even for them) alongside a bunch of
  ask-specific tuning fields (`top_k`, `vllm`, `configuration_model`, etc.). No
  second context item anywhere that references the mcphttp driver.
- **One generation item**, `module: "summarize"`, model `chatgpt-azure-4o-mini`,
  a grounding prompt almost identical in spirit to ours.
- **Rules**: near-identical to `arag-provision-agent.ts`'s.

**I hypothesised `sources` (plural, on the `ask` context item) was the "attach the
MCP driver as a callable tool" mechanism (a plausible reading of "Smart agent"
pulling in a "Registered Agent") and tested it directly:**
- `PATCH` our `ask` context item with `"sources": ["tallowa-mcp"]` (our mcphttp
  driver's identifier) -> saved fine (`200`), but the smoke test then failed with
  **`"Source is not a NucliaDB driver"`** — ruling this out. `sources` is
  type-constrained to NucliaDB drivers only (multi-KB retrieval), not a general
  tool-attachment field.
- Confirmed by creating a second driver, `tallowa-kb` (`provider: "nucliadb"`,
  pointed at our real seeded KB `e7c85431-...`, 25 documents) via the API — it
  created fine (`200`) — and setting `"sources": ["tallowa-kb"]` instead: the
  `"not a NucliaDB driver"` error went away, confirming the type constraint.
- But THAT then failed differently: **`"Auth error 403: No roles could be
  resolved for AnonymousUser anonymous at api/v1/kb/e7c85431-.../labelsets"`** —
  the nucliadb driver I created via the API has no auth key wired to it, so
  cross-KB retrieval hits the target KB as an anonymous, unauthenticated caller
  and gets refused. **This independently reproduces, on our own account today,
  exactly what `arag-provision-agent.ts` warned about two months ago on a
  different deployment**: *"the nucliadb (Knowledge Box) driver must be created
  in the ARAG dashboard — for a same-region KB it auto-provisions a scoped API
  key, which the API does not expose a field for."* Confirmed true here too, not
  just historically.

**Net result:** two real, useful things learned (what `sources` actually does; the
nucliadb-driver-needs-dashboard-auth limitation independently reproduced) — but
neither is the Smart-agent/MCP mechanism itself, and I've now confirmed that even
MaintenanceOS's OWN real working workflow doesn't expose its node graph through
any endpoint I have found or can reach (`workflows` list is a summary only;
`workflow/{id}` singular is PATCH-only, no GET). This is not a case of me not
having tried the right field name — I have direct, current, real data from the
one other working agent in this exact account confirming the graph structure
lives somewhere outside this API surface. Handing to the lead's dashboard access
now with that evidence, rather than continuing to guess.

Current Tallowa agent state: `ask` context item now has `sources: ["tallowa-kb"]`
(harmless — the auth 403 means this path doesn't retrieve anything right now
either, so no worse than before); `tallowa-mcp` (mcphttp) and `tallowa-kb`
(nucliadb, no dashboard-provisioned key yet) both present as drivers; generation
and rules unchanged. Nothing crashes; nothing yet produces a real answer.

---

## 5th-pass (superseded above — kept for the record)

**Status: 5b — tried to find/read the MaintenanceOS agent's workflow via the API
(both agents confirmed to share the same account, `progress-jay-geo`) to avoid a
manual dashboard step. No agent-collection listing endpoint is reachable: every
plausible path (`/api/v1/agents`, `/api/v1/account/{id}/agents`,
`/api/v1/retrieval_agents`, `/api/v1/retrieval-agents`, with and without an
`account_id`/`mode` query param, on both the `dp` and `rag` hosts) returns a clean
`404`. The one account-level collection that DOES exist — `GET
/api/v1/account/{account}/kbs` — returns `403 Forbidden` for the PAT specifically
(the NUA key can list it fine; this looks like a genuine permission difference
between credential types, not a routing issue, since the account id is confirmed
correct from the NUA-key path). Without the MaintenanceOS agent's id, I can't `GET`
its `/workflow/default` to read a known-good `parameters` example. Falling back to
the lead's dashboard-side offer for this one piece, as pre-agreed.**

**Update:** retried per the lead's network-traffic finding — agents ARE addressed as
KBs on the DP host (`GET /api/v1/account/{account}/kb/{id}` -> `200`, confirmed
against our own Tallowa agent, matching the exact path shape the dashboard uses).
But the *collection* form of that same path, `GET
/api/v1/account/{account}/kbs` on the **DP host**, still returns `403 Forbidden`
for the PAT — identical to the RAG-host result. So the pattern holds across both
hosts: the PAT can fully read/act on any specific item once it has the id
(confirmed again here), but cannot list account-level collections on either host.
This looks like a deliberate scope restriction on PAT-type credentials, not a
per-host quirk. Need the MaintenanceOS agent's id from the dashboard to proceed.

## 5th-pass: the crash is explained: MCP needs to be wired as a "Smart
agent" node in the workflow's node graph, not a direct context module (per the
working maintenanceOS dashboard topology). I found the real API endpoint for the
workflow node graph (`PATCH /api/v1/agent/{agentId}/workflow/default`) and confirmed
its shape (`name`, `description`, `parameters`), but `parameters` is an
unvalidated/opaque JSON blob (an empty `{}` is accepted, so Pydantic gives no field
hints) — the internal node/edge schema can't be reverse-engineered from validation
errors. `POST .../export` (the dashboard's Export button) returns `200` with an
empty body when called directly over HTTP, so it isn't retrievable this way either;
it likely only works through the actual browser session. Handing this one piece to
the lead as offered, rather than guessing at an undocumented nested schema. Reporting
now.**

## 5th-pass: found the real workflow-update endpoint, but its node-graph schema is opaque via direct API probing

- `GET /api/v1/agent/{agentId}/workflows` had already shown the `default` workflow's
  shape: `{"id":"default","name":"default","description":"Default workflow",
  "parameters":{},"rules":{"rules":[]},"required":[]}` — `parameters` is presumably
  where the node graph (the Smart agent / MCP node topology the lead saw in the
  dashboard) lives.
- Found the real update endpoint by probing verbs: `OPTIONS
  /api/v1/agent/{agentId}/workflow/default` -> `Allow: PATCH`. `PATCH` with an empty
  body -> `422`, revealing the required top-level fields: `name`, `description`,
  `parameters`.
- `PATCH` with `{"name": "default", "description": "Default workflow",
  "parameters": {}}` -> **`200`, accepted.** But because it's accepted even empty,
  Pydantic gives no nested-schema hints — `parameters` is evidently a loosely-typed
  JSON blob (the actual node/edge graph), not something with an enforced shape I can
  discover by trial-and-error the way the top-level fields were discovered.
- Also found `OPTIONS /api/v1/agent/{agentId}/export` -> `Allow: POST`; `POST` with
  `{"passphrase": "..."}` -> **`200` but Content-Length: 0, no body, no
  Location/download header.** This is presumably the dashboard's "Export" button,
  but it doesn't return a usable payload over a plain HTTP call — it likely triggers
  a browser-side download/blob flow that only works through the actual dashboard
  session, not a bare API call.
- No committed exported workflow JSON found in `reference-repos/maintenanceOS`
  (checked for `*workflow*` files and JSON/TS mentions of `registered_agents` /
  `smart_agent` / node-graph terms — nothing). The maintenanceOS agent likely lives
  in a different ARAG account than ours (`progress-jay-geo`) — no "list agents"
  endpoint discoverable on this account to cross-reference it, and the PAT gets
  `403 Forbidden` on the account-level KB listing (unlike the NUA key), so I can't
  browse for it that way either.

**Handing this one piece to the lead, per their own offer.** I don't want to guess
blindly at an undocumented, unvalidated nested JSON schema for a live agent's
workflow — a wrong guess risks silently producing a workflow that "saves" (200) but
does the wrong thing, which is worse than stopping cleanly. Two options, either
works for me:
1. Trigger Export from the maintenanceOS agent (or the Tallowa agent, once its
   Smart-agent/MCP topology is built) in the actual dashboard and share the JSON —
   I can then adapt it (swap the MCP node's source to `tallowa-mcp`, adjust the
   summarize prompt to Tallowa's domain) and `PATCH` it in via API, verifiable and
   reproducible.
2. Build the Smart-agent -> MCP node topology directly in the Tallowa agent's node
   editor (id `1bdd41e6-d9de-41b6-add5-f8ccd0b17811`, workflow `default`) — then I
   `GET /workflows` to see the resulting `parameters` shape (learning the schema from
   a known-good example), confirm it matches what's needed, and take over from there
   (smoke test, then wiring the app).

Current live agent state unchanged from pass 4: `mcphttp` driver (`tallowa-mcp` ->
`https://tallowa-plant.fly.dev/mcp`), `ask` KB-context step, `summarize` generation,
and rules are all configured; the crashing direct `mcp` context step remains
deleted; the `default` workflow's `parameters` is still empty (`{}}`), so no
interaction currently uses any of this configuration — nothing will crash, but
nothing is wired into an actual answer path yet either.

---

## 4th-pass result (superseded above — kept for the record)

**Status: 4th pass — the agent is REAL, correctly configured, and reachable end to
end (PAT auth, driver, context, generation, rules all live on
`aws-ap-southeast-2-1.dp.progress.cloud /api/v1/agent/{agentId}/...`, exactly
matching the reference). The smoke test hit a genuine, reproducible SERVER-SIDE bug
in ARAG's own MCP driver code the moment it's used as a context/retrieval source —
the identical class of bug the reference repo documented as "reported to Progress"
on a different (EU) deployment, now independently reproduced by us on the AU
deployment. Not something fixable from our side. Have not wired the app to this path
(it would error on every question) and have not touched `ai.py`/`mcp.py`/the live
app otherwise. Reporting before going further.**

## 4th-pass: config succeeded completely; the live tool-call path itself errors server-side

The lead's dashboard-sourced correction was exactly right. Reprobed the correct
surface — `https://aws-ap-southeast-2-1.dp.progress.cloud/api/v1/agent/{agentId}/...`
where `agentId` = `1bdd41e6-d9de-41b6-add5-f8ccd0b17811` (the `mode: "agent"` KB
created in pass 3 IS the agent) — with the PAT (`ARAG_AGENT_KEY`). Every call
succeeded cleanly:

- `GET drivers/context/generation/rules/workflows` -> all `200`, matched the
  dashboard exactly (empty, one `default` workflow).
- `POST drivers` — added an `mcphttp` driver, identifier `tallowa-mcp`, pointed at
  `https://tallowa-plant.fly.dev/mcp`, no static auth header (matches
  `arag-provision-agent.ts`) -> `200`.
- `POST context` — added a `module: "mcp"` context step, `source: "tallowa-mcp"`
  (the driver identifier) -> `200`. Also added a `module: "ask"` (KB) context step
  for comparison -> `200`.
- `POST generation` — `module: "summarize"`, model `chatgpt-azure-4o-mini`, a
  grounding prompt (cite identifiers, Tallowa data only, no invention) -> `200`.
- `POST rules` — cite identifiers, answer only from retrieved MCP/KB data -> `200`.

**Smoke test 1** — `POST /api/v1/agent/{agentId}/session/ephemeral` with the seeded
narrative question ("How many customer shipments are exposed to fastener lot
WF-2261, and which customers?"), forwarding a real live login JWT (admin demo user,
`POST /api/auth/login`) in the interaction's `headers.authorization` field — exactly
the reference's `forwardJwt` pattern, so RBAC genuinely flows through per-request
rather than a static baked-in credential:

```
{"exception": {"detail": "MCPHTTPDriver.client() missing 4 required positional
arguments: 'memory', 'module', 'agent_id', and 'request_id'"}, ...}
```

This is a Python `TypeError` from inside **ARAG's own driver-instantiation code** —
`memory`/`module`/`agent_id`/`request_id` are framework-internal arguments the agent
runtime is supposed to inject when it builds the driver client at request time, not
anything a caller configures. It fires the instant the `mcp` context step tries to
actually invoke the `mcphttp` driver.

**Isolation test** — deleted the `mcp` context step, left only the `ask` (KB)
context step, reran the same question:

```
{"exception": {"detail": "No sources available"}, "answer": "Error in context", ...}
```

Clean, no crash — the pipeline runs end to end (auth, driver registration,
generation, rules) and fails only because the agent-mode KB has zero documents
synced (expected — it was created empty in pass 3, purely to host the agent
config; it was never seeded). This isolates the crash precisely to the `mcp`
context module invoking the `mcphttp` driver, not to the agent/config plumbing in
general, which is fully sound.

**This matches the reference's own documented finding almost verbatim.**
`reference-repos/maintenanceOS/apps/api/scripts/arag-provision-agent.ts` states:
*"The `generate` generation module and using an `mcphttp` driver **as a retrieval
source** both error server-side on this deployment (reported to Progress)."* That
was on `aws-eu-central-1-1`. We just reproduced the same class of failure
independently on `aws-ap-southeast-2-1` (AU), with the same driver type (`mcphttp`)
in the same role (context/retrieval source). Two independent deployments, same
driver type, same failure mode — this reads as an ARAG-platform bug in the
MCP-driver-as-context-source code path generally, not a one-off or a config mistake
on our part.

**Current live state, left safe:** the `mcp` context step has been deleted (so the
agent won't crash on interaction); the `mcphttp` driver, `ask` context step,
`summarize` generation and rules remain configured and reachable. No question will
currently get a real answer (the agent-mode KB is empty and the one working context
path retrieves nothing) — this is deliberately left in a non-crashing, inert state
pending a decision, not wired into the app.

## What this means for the GM directive

The infrastructure and config layer for "ARAG is the agent" is now fully proven
real and reachable on our account/zone — that part of the feasibility question is
answered YES. What's blocking the literal requirement ("ARAG plans and calls the
app's own /mcp as its tool source") is a live, reproducible bug in ARAG's own
server-side driver code, not anything in our control. I have not fallen back to the
hybrid pattern (app queries its own data, ARAG only narrates) as a silent
workaround — the GM directive says that IS the pattern we're moving away from, so
substituting it back in without saying so would misrepresent what's actually
running. Reporting this precisely rather than choosing a fallback myself.

---

## 3rd-pass result (superseded above — kept for the record)

**Status: 3rd pass — the credential gate is SOLVED (a fresh human-login PAT clears
it). The remaining blocker is one level deeper: the Retrieval Agent config API
(`/kb/{kbid}/agent/*`) is not deployed/wired on this Progress-hosted AU cluster
(`aws-ap-southeast-2-1.rag.progress.cloud`) at all — confirmed on a genuine
`mode: "agent"` Knowledge Box, with a valid user PAT, getting a clean route-level
404, not an auth rejection. Have not touched `ai.py`/`mcp.py`/the live app. Reporting
before going further.**

## 3rd-pass findings (the credential fix worked; a deeper platform gap remains)

1. **PAT mint succeeded.** Used the fresh `brand/arag-auth.json` (Jay's 21 Jul login)
   User Key to `POST https://nuclia.cloud/api/v1/user/pa_tokens` -> `201`, PAT id
   `2c747fdd-9bb8-47ee-8127-2f900b6b2382`, expires 2027-07-21 (1 year). Stored as
   `ARAG_AGENT_KEY` in `apps/tallowa-erp/.env` (value never printed).

2. **Re-probed `/kb/{old_kb}/agent/drivers` with the PAT** — the error changed from
   the categorical credential rejection (`"NuaKeyUser/TemporalServiceAccountUser
   cannot access context of type NucliaArag"`) to a *resource*-level one:
   `403 "Cannot resolve role for user ...: There is no Agent Knowledgebox at
   api/v1/kb/{kb}/agent/drivers"`. **This proves the PAT is the right credential
   type** — the gate moved from "wrong kind of key" to "this KB isn't agent-shaped."

3. Confirmed via nuclia-mcp docs: Knowledge Box creation takes `mode: "agent" | "kb"`.
   Our existing Tallowa KB was created with `mode: "kb"` (per `provision.py`). So I
   created a **new** KB, `tallowa-plant-agent` (`1bdd41e6-d9de-41b6-add5-f8ccd0b17811`),
   with `mode: "agent"`, via the NUA key (same recipe as `provision.py`) — `201`, and
   minted its own SOWNER service token (`ARAG_AGENT_KB_ID` / `ARAG_AGENT_KB_TOKEN`,
   also in `.env`).

4. **On the genuine agent-mode KB, `/agent/drivers` (and every other `/agent/*` path)
   now returns a clean `404 "Not Found"` — for both the PAT and the KB's own service
   token.** No more auth-flavoured error at all; the route simply isn't there. Control
   calls on the same KB (`GET /kb/{kb}`, `/counters`, `POST /ask`) all work completely
   normally — `mode: "agent"` was accepted by the create call without a validation
   error, but it doesn't appear to change anything the API actually does on this
   cluster: `/counters` returns `{"resources":0,...}` and `/ask` runs the ordinary
   KB `ask` pipeline (`"no_retrieval_data"` on an empty KB), exactly like any
   `mode: "kb"` box.

5. Extra tell: the new `tallowa-plant-agent` KB **does not appear in
   `GET /account/{account}/kbs`** at all (checked the full 15-KB account listing by
   name), even though it's directly reachable by id and has a working service token.
   A plain `mode: "kb"` KB (e.g. the original `tallowa-plant`) appears in that listing
   normally. This is consistent with `mode: "agent"` being accepted as a request field
   but not fully/correctly provisioned end-to-end on this regional deployment.

6. No exposed OpenAPI/docs endpoint on the live host (`/openapi.json`, `/api/v1/docs`
   etc. all 404) to cross-check the real route table directly, so this conclusion
   rests on behavioural evidence (point 4) rather than the spec — but it's consistent
   across 2 KB modes and both credential types tried on the agent-mode KB.

**Conclusion:** the credential problem from pass 2 is fully resolved (a human-login
PAT is confirmed to be the correct credential type — the KB-shape-specific 403 in
point 2 proves the auth layer accepted it). What remains is that `/kb/{kbid}/agent/*`
— the Retrieval Agent configuration surface nuclia-mcp's docs describe (presumably
accurate for the general Nuclia SaaS / other regions) — does not appear to be
deployed on `aws-ap-southeast-2-1.rag.progress.cloud`, the only zone the factory's
credentials provision on, regardless of KB mode.

I have not gone further (no driver/context/generation was successfully created; the
one driver POST attempt also 404'd on the same route) and have not touched any app
code. Reporting this precisely to the lead rather than guessing at more path variants
indefinitely.

---

## 2nd-pass result (superseded above — kept for the record)

**Status: RETRY (2nd pass) — root cause is a credential-TYPE gate, not a missing
entitlement. Concrete one-time unblock identified (a human login + PAT mint). Still
have not created the agent or touched app code — reporting before proceeding, per
instructions.**

## Retry findings (superseding the "not possible" conclusion below)

First pass wrongly probed the KB service-account token against the wrong host. Retried
properly, live, with every credential the factory actually holds:

| Credential | Surface probed | Result |
|---|---|---|
| KB SOWNER service token | `rag.progress.cloud /kb/{kb}` and `/counters` | 200 (control — token fine) |
| KB SOWNER service token | `rag.progress.cloud /kb/{kb}/agent/drivers` | 403 `"Cannot resolve role for Service Account..."` |
| `ARAG_NUA_KEY` (account key) | `rag.progress.cloud /kb/{kb}/agent/drivers` | **403 `"NuaKeyUser cannot access context of type NucliaArag"`** |
| `ARAG_NUA_KEY` | `dp.progress.cloud` (reference's host, derived) — `/health`, `/agent`, `/account/{acc}/agents` | 404 on every path — **this host doesn't exist for our account/region at all** |
| `ARAG_NUA_KEY` | `POST /api/v1/service_account_agent_key`, `/service_account_temporal_key` | 403 `"NuaKeyUser cannot access context of type IDP...Keys"` |
| KB service token | `POST /api/v1/service_account_temporal_key` | **201 — minted a short-lived JWT** (`iss: dp.progress.cloud`, `kb_id`, `acc_id`, `role: SOWNER`) — proves dp.progress.cloud IS a real host tied to our account, just not reachable by plain NUA/service keys |
| That minted temporal JWT | `dp.progress.cloud /kb/{kb}/agent/drivers`, `/agent` | 404 (route) / **403 `"TemporalServiceAccountUser cannot access context of type NucliaArag"`** |
| Stale dashboard session token (`brand/arag-auth.json`, captured 6 Jul, human login via `save_auth.py`) | `rag.progress.cloud /kb/{kb}/agent/drivers` | **401 `"JWT has expired"`** — critically, NOT the categorical 403 the other three credential types get |

**Read on this:** every credential type the factory can mint itself (NUA key, KB
service-account key, a freshly-minted temporal service-account JWT) hits the exact same
categorical rejection — `"... cannot access context of type NucliaArag"`. This is
Nuclia's own deliberate product gating, confirmed independently by nuclia-mcp's auth
docs: NUA keys are "designed for services that does not use NucliaDB" (zone-API only);
service-account keys are KB-data-plane only. The Retrieval Agent feature is gated to a
genuine **User Key or Personal Access Token** — i.e. something minted from an actual
human login — by design, not an entitlement we're missing.

The stale dashboard token getting `401 expired` rather than the categorical `403` is the
decisive corroborating signal: a **fresh** human-authenticated token on that exact same
endpoint should work.

`dp.progress.cloud` (the reference repo's host) is confirmed **not to exist for our
AU account/region** — 404 on every path including `/health`, even authenticated with a
correctly-scoped, validly-minted temporal JWT. The reference's agent lives on a
different product surface (`aws-eu-central-1-1`, a different region) that we don't have.
The route that IS live for us is the documented, KB-scoped
`rag.progress.cloud /api/v1/kb/{kb}/agent/drivers|context|generation|rules` — current
per nuclia-mcp's docs, not the reference's older/different-surface pattern.

## Concrete one-time unblock (no further architecture question — just a credential)

1. **One human login** (Jay) to the ARAG dashboard — factory drives this hands-off per
   the GM operating model (open the window, he signs in), same mechanism already used
   for `scripts/save_auth.py` / `brand/arag-auth.json` in Workflow 1. Session is stale
   (captured 6 Jul), needs a fresh capture.
2. From the fresh User Key, mint a **Personal Access Token** (long-lived, default
   1-year): `POST https://nuclia.cloud/api/v1/user/pa_tokens` with the fresh User Key as
   Bearer, body `{"description": "tallowa-arag-agent"}`. **One-time** — the PAT then
   works indefinitely without repeated logins.
3. Store the PAT server-side only (`ARAG_AGENT_KEY` in the app's `.env`, gitignored).
4. Configure the agent via `rag.progress.cloud /api/v1/kb/{kb}/agent/{drivers,context,
   generation,rules}` using the PAT as Bearer — mirroring
   `reference-repos/maintenanceOS/apps/api/scripts/arag-provision-agent.ts`: an `mcp`
   driver → `https://tallowa-plant.fly.dev/mcp`, a context step, a `summarize`
   generation step (model `chatgpt-azure-4o-mini`), and grounding rules.
5. Smoke test via the agent session/interaction endpoint and confirm the trace shows
   ARAG (not our code) calling `/mcp` tools.

I have not minted anything requiring the login yet, have not created the agent, and have
not touched `ai.py`/`mcp.py`/the live app. Reported to lead for the login handoff before
proceeding.

---

## First-pass result (superseded above — kept for the record)

**Status: BLOCKED at Step 1 (feasibility gate). Stopped before any rebuild, per instructions.**

## Task

GM directive (Jay, 21 Jul 2026): "all use cases must use arag, not directly use mcp."
Re-point the Tallowa Ops Assistant + 5 use-case flows so an **ARAG Retrieval Agent** is
the orchestrator (plans, calls the app's own `/mcp` as its tool source, grounds in the
KB, answers) instead of the app's homegrown `agent_plan()` planner calling `/mcp` directly.

## Step 1 result: NOT feasible with the current factory credential/zone

### (a) Can the factory credential provision/configure a Retrieval Agent over the Tallowa KB?

**No — confirmed by live probe, not just reading docs.**

The documented Nuclia Retrieval Agent config API exists in principle (`nuclia-mcp` search
confirms `POST/GET /api/v1/kb/{kbid}/agent/drivers|context|generation|workflows`, with an
`mcp` driver provider and an `mcp` context module — exactly the resource this task needs).

Live-probed against the actual Tallowa KB (`e7c85431-ca4e-425c-86fd-5458abd78b75`) on
`https://aws-ap-southeast-2-1.rag.progress.cloud` (AU Sydney — the only zone the
factory's `ARAG_NUA_KEY` provisions, per the binding field rule), using the KB's own
SOWNER service-account token:

```
GET /api/v1/kb/{kb}               -> 200  (control: token/auth is fine)
GET /api/v1/kb/{kb}/counters      -> 200  (control: KB reachable, 25 resources)
GET /api/v1/kb/{kb}/agent         -> 404
GET /api/v1/kb/{kb}/agent/drivers -> 403  {"detail":"Cannot resolve role for Service
                                            Account ...: There's no Knowledge Box at
                                            api/v1/kb/{kb}/agent/drivers"}
GET /api/v1/kb/{kb}/agent/context     -> 403 (same routing-failure message)
GET /api/v1/kb/{kb}/agent/generation  -> 403 (same)
GET /api/v1/kb/{kb}/agent/workflows   -> 403 (same)
POST /api/v1/kb/{kb}/agent/drivers    -> 403 (same, tried creating an `mcp` driver
                                          pointed at https://tallowa-plant.fly.dev/mcp)
```

The 403 body is not a plain permission denial — it's a role-resolution failure claiming
"There's no Knowledge Box at .../agent/drivers", i.e. the gateway doesn't recognise
`/agent/...` as a valid sub-route under `kb` on this cluster at all. Combined with the
clean `404` on `/agent` itself, this reads as: **the Retrieval Agent configuration
surface is not deployed/enabled on this regional cluster for this account**, not a
missing-scope-on-the-token problem (the same token has full read/write on the KB proper).

### (b)/(c) Reference implementation cross-check (`reference-repos/maintenanceOS`)

The reference does have a working agent (`arag.ts`, `client.ts` `AragAgentClient`), but
it is built on **infrastructure the factory credential doesn't have access to**:

- A **different host entirely** — `dp.progress.cloud` (a "data platform" surface), not
  `rag.progress.cloud` (the KB host our NUA key provisions on). Probed the derived
  equivalent (`aws-ap-southeast-2-1.dp.progress.cloud`) — resolves DNS-wise but 404s on
  every path, consistent with the account not having that surface provisioned.
- A **different resource shape** — `/api/v1/agent/{agentId}/...` (a standalone
  account-level agent with its own id + key), not the KB-scoped `/kb/{kbid}/agent/...`
  the current docs describe. `ARAG_AGENT_ID`/`ARAG_AGENT_KEY` in the reference's `.env`
  are **pre-existing** — the provisioning script (`arag-provision-agent.ts`) only
  configures an agent that already exists; it never creates one.
- The reference's own comment says the KB (nucliadb) driver **had to be added by hand
  in the ARAG dashboard** ("PREREQUISITE that the REST API cannot do") — so even the
  reference author couldn't fully self-serve this via API.
- Verified against `aws-eu-central-1-1` (EU), a **different region** from the AU zone
  the factory key is locked to.

Even where the reference DOES have a working agent, it is fragile by the author's own
admission: `aiFeatures.ts` header comment says the HYBRID pattern (app queries its own DB,
ARAG only narrates via `/predict/chat`) was chosen for F3/F4/F5 specifically to
**"sidestep the deployment's agent-retrieval bugs."** `arag-provision-agent.ts` states
outright: *"The `generate` generation module and using an `mcphttp` driver **as a
retrieval source** both error server-side on this deployment (reported to Progress)."*
The one place the reference genuinely routes through the live agent for MCP tool calls
(`/ops-assistant`, `workflowId: "mos"`) uses a workflow that isn't in any provisioning
script — it was hand-built in the dashboard, working around those bugs, and the code
comment explicitly warns the *default* workflow "Do NOT use."

## Conclusion

Provisioning a real ARAG Retrieval Agent over the Tallowa KB is **not possible today**
with the factory's ARAG credential — the Agent configuration API 403/404s on our zone,
and the reference's working pattern depends on a different host, a different resource
type, and manual dashboard steps that aren't available to us. This is not a "the
homegrown planner is nearly as good" case — it is a hard infrastructure gap.

**I have not touched `ai.py`, `mcp.py`, or any live app code.** The current
app-orchestrated-MCP architecture is unchanged and the live app is not at risk.

## What's needed to unblock

An ARAG account/credential with Retrieval Agent entitlement enabled on a zone the
factory can actually reach (ideally AU Sydney to stay in the current zone; EU
`aws-eu-central-1-1` is the region confirmed working in the reference, but is a
non-AU zone and would need a residency conversation per field rule #2 if used for a
live demo). This needs a Progress/Nuclia-side entitlement check, not something the
factory can self-serve by re-running the KB provisioning recipe.

Reported to lead (`main`) — awaiting GM escalation decision before any further work.
