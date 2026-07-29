# Tallowa ERP - build state: COMPLETE (2026-07-21)

## Three use-case pass (2026-07-21, this session)
Extended the gated app (did not rebuild, did not break any gated feature) so it can
DEMONSTRATE, live, the 3 use cases in sources/three-use-cases/"3 use cases.pptx" -
GM instruction via the lead. Spec, design decisions and checkpoint trail in
USECASES-STATE.md. Summary:
- **UC1 quality/8D** - new overnight FPY-breach scenario (RUN-1111, line A-2, FPY
  84.3%) with three REAL correlated causes seeded (resin lot KP-7742 first use =
  71% of scrap, machine INJ-01 5-days-overdue PM = 29%, trainee night-shift
  supervisor). New `fpy-root-cause` AI feature (ranked, cited suspects); reused the
  existing generic lot-trace for containment; new POST /api/holds/ (create-hold
  endpoint, quality-gated - didn't exist before, only release did); new POST
  /api/ai/8d-draft (grounded in the LIVE hold status, not assumed) + `eight_d_reports`
  table + POST /api/8d-reports/ (save/approve).
- **UC2 AP invoice auto-fix** - new `ap_invoices` table (23 seeded, distinct from the
  customer-AR `invoices` table), `suppliers.cost_center`, deterministic
  `AP_ERROR_CODES` catalogue (fix/authority never LLM-invented), new KB doc
  fin-ap-authorisation-matrix.md (FIN-AP-01..05). 9 invoices (Coalcliff Steel +
  Meander Castings) share one root cause (stale cost center CC-410); one (BANK-VER)
  honestly stays stuck beyond AP-clerk authority. New `ap-error-explain` /
  `ap-batch-fix` AI features + GET /api/ap-invoices/{ap_no}/similar (deterministic
  grouping) + POST /api/ap-invoices/batch-fix (finance-role, corrects the vendor
  master + posts + logs one audit row per invoice with its policy citation).
- **UC3 CTP sales co-pilot** - real seeded shortage (TC-13080 cut 3300->830, exactly
  170 short against a 250-unit TC-70210 order; PO-2252 is the binding incoming
  supply). New POST /api/ai/ctp-commit: BOM explosion, binding constraint, production
  lead time from REAL historical run-rate data, alternative dates, and (expedite=true)
  a what-if that pulls the PO in and re-checks conflict against the only other
  near-term order on the same component. **Caught and fixed a real bug**: the LLM's
  freehand "beats/misses the requested date" judgement was wrong on the expedite
  case (date arithmetic) - fixed by computing the verdict in Python and instructing
  the model to state it verbatim, never recompute it. RBAC split verified live: sales
  role confirms its own draft order immediately (so_approve extended to allow role
  "sales"); a separate `expedite_requests` table + propose/approve endpoints put the
  schedule-touching PO pull-in behind plant_manager/supervisor ONLY - sales gets a
  403 trying to approve its own request.
- Two new logins: ap@ (Maria Costa, role finance) and sales@ (Nate Ferris, role
  sales). New pages /ap-invoices and /ctp; quality.html extended with the ranked-
  suspects panel, containment action and 8D draft/approve. Zero console/page errors
  across all three flows (Playwright, both page-load and full interactive click-
  through). New endpoints auto-registered as MCP tools (105 -> 120); full MCP smoke
  suite still 29/29 PASS. New dedicated scripts/smoke_usecases.py: 27/27 PASS.
  Goldens: all 43 existing + 6 new (49 total) re-cached live, 0 failures.
  DoP walk and report delivered to the lead; NOT deployed (per instruction - the
  lead redeploys after QA).

Finished by deck-fix-rwa after auto-erp's session limit (handover per lead).
MCP architecture upgrade applied per sources/maintenanceos-analysis/SOURCE-NOTES.md.
Lead-gated PASS (one minor finding) 2026-07-21; finding fixed same day - see
"Post-gate polish" below and APPROVED.md. NOT deployed (GM has not said push).

## Post-gate polish (2026-07-21, this pass)
- **Fixed the gate finding**: `/holds/` (erp.py) now maps status synonyms
  (blocked/held/on_hold/quarantine/...) to the real `open` value, and its
  docstring documents the vocabulary for the MCP tool description the Ops
  Assistant planner reads. Also fixed `compact()` in ai.py, which was
  blind-truncating nested trace fields (finished_lots/shipments) at 160
  chars and silently dropping the second shipment from composed answers -
  it now renders nested records as individual lines. Hero query re-verified
  live 3x: correctly names both shipments (SHP-0341/SHP-0347, both Ellandra,
  640 units) and both blocked quantities (80 + 220 = 300 units, HLD-0143/
  HLD-0144). Goldens re-cached (ops-assistant, agent, audit-assistant,
  lot-trace); MCP smoke suite 29/29 PASS.
- **Refreshed screenshots** for the business-value deck - see shots/ and the
  list at the end of this file.

Task #22: twin of the maintenanceos reference demo, re-grounded to a fictional
**automotive PARTS/components manufacturer (tier-1/2 supplier)** - GM correction
21 Jul superseded the earlier vehicle-OEM framing. Spec: sources/maintenanceos-analysis/
ANALYSIS.md (+ task #22 description). All 45 AI features, re-grounded. Do NOT deploy.

## Brand (LOCKED)
- **Tallowa Components** - fictional Australian tier-1 automotive components maker,
  Bellbrook plant. Trademark check 2026-07-21 (WebSearch): nothing automotive under
  "Tallowa" (Corella rejected - one letter from Corolla; Marlock rejected - Marlok
  Automotive GmbH exists).
- Product families: Braking (TC-30xxx: EPB-40 electric park brake actuator, caliper
  brackets), Chassis (TC-20xxx: control arms, steering knuckles, hub assemblies),
  e-Mobility (TC-70xxx: HV busbar sets, HV connector housings).
- Customers (all fictional): OEMs Ellandra Motors, Marran Automotive, Southbank Truck
  Group + aftermarket AllBrake Distribution, Torrens Trade Parts. Customer part numbers
  map to internal part numbers.
- Raw-material suppliers (fictional): Coalcliff Steel, Currajong Copper, Warrigal
  Fasteners, Meander Castings, Kurrajong Polymers, Torren Bearings, Larkspur Electronics.
- Platform presents as "Tallowa Components - Plant Operations" (own system, ARAG invisible).
- Palette: steel navy #12283A, safety orange #E8752A, paper #F5F3EE, ink #1C2B36.
- Demo logins (@tallowacomponents.com.au, password demo1234): admin@, plant@ (plant
  manager), super@ (production supervisor), line@ (line lead), quality@ (quality inspector).
- Lines: S-1 Stamping, M-1/M-2 CNC Machining, H-1 Heat Treatment, P-1 Surface Coating,
  A-1 Assembly & Test (braking), A-2 Assembly (chassis/e-mobility).

## Hero moments
1. **Lot-trace recall containment**: Warrigal Fasteners raw lot WF-2261 (thread rolling
   out of spec) -> consumed by runs RUN-1088/RUN-1092 -> finished actuator lots
   TC-A-4471/TC-A-4472 -> which customer shipments and OEM POs are affected, what is
   still in stock, containment per QP-8D. Forward AND backward trace.
2. **Ops Assistant live agent** - plans, queries the live ERP, streams steps, grounded answer.
3. Fault-root-cause = defect Pareto; customer PPM on dashboard.

## KB (provisioned)
- KB id **e7c85431-ca4e-425c-86fd-5458abd78b75**, slug tallowa-plant, AU zone
  (aws-ap-southeast-2-1). SOWNER token in apps/tallowa-erp/.env (gitignored).
- Pin generative_model chatgpt-azure-4o-mini on every call; resource_filters scoping
  everywhere; NO graph task.
- 2026-07-21: first corpus (OEM-flavoured, 21 docs) uploaded then SUPERSEDED by the
  parts-maker correction -> purge + reseed with parts-maker corpus (IATF/PPAP/8D).

## Checkpoints
- [x] Brand + trademark check (above; renamed Tallowa Motors -> Tallowa Components)
- [x] App skeleton apps/tallowa-erp/
- [x] KB provisioned + .env written
- [x] Parts-maker corpus generated (24 docs) + KB purged/reseeded (manifest
      data/kb-manifest.json); processing in background - check
      `scripts/seed_kb.py --status` before goldens
- [x] SQLite schema + seed (database.py, seed_db.py -> data/erp.db). Seed counts:
      6 customers, 7 ship-tos, 7 lines, 26 operators, 28 parts, 26 BOM lines,
      14 raw lots, 23 runs, 12 finished lots, 18 sales orders, 7 shipments,
      10 suppliers, 13 POs, 7 invoices, 18 machines, 10 tooling, 20 defects,
      5 holds, 5 recurring, 18 audit rows, 3 attachments. Hero chain intact:
      WF-2261 -> RUN-1088/1092/1101 -> TC-A-4471/4472 -> SHP-0341/0347 -> Ellandra.
- [x] ERP API (erp.py) - auth (HMAC bearer, 5 roles), dashboard, customers,
      lines, operators+skills, runs (+status/complete/time), sales orders
      (+server-computed GST totals, approve/reject), parts+BOM+stock+low-stock,
      lots, trace fwd/bwd core, suppliers, POs (+receive -> creates lots+stock),
      invoices (+print view), shipments, machines, tooling, defects (+pareto),
      holds (+release, quality-only), 7 reports, settings, audit, notifications,
      recurring (+run generator), attachments, access tokens, system reset/info.
- [x] Frontend: shell + login + 24 pages (one route per module + 6 detail
      routes), app.js helpers (aiPanel, NDJSON stream, tables). Swagger at /docs.
- [x] AI endpoints (ai.py) - all 45 registered. 31 config-registry features
      (erp/hybrid modes) + ask, find, agent, ops-assistant (NDJSON step stream),
      lot-trace, playbook, playbook/save(+templates GET), triage (schema),
      extract-document (schema) + /ai/status. Smoke-tested live: ask (cited,
      SWI named), briefing (data_used panel), ops-assistant (model plan ->
      2 live queries -> docs -> grounded answer, 11s), lot-trace (8 citations),
      playbook (8 citations + history digest). Trace API verified: WF-2261 ->
      RUN-1088/1092/1101 -> TC-A-4471/4472 -> SHP-0341/0347 -> 640 shipped /
      300 blocked.
- [x] **MCP surface (mcp.py)** - POST /mcp Streamable HTTP, stateless JSON-RPC;
      **105 tools auto-generated from the app's own OpenAPI doc** (filters: no
      DELETE, /api/system, login, print/download, streaming NDJSON); every
      tools/call dispatched in-process via httpx ASGITransport with the
      caller's JWT passed through, so auth/RBAC/validation apply to agents
      exactly as to humans (unauth call returns the API's own 401). Resources
      tallowa://openapi|dashboard|production-run/{run_no}|customer/{cid};
      prompts triage-production-run, draft-sales-order-from-history,
      daily-operations-briefing. Two deliberate deviations from source, both
      documented in mcp.py: /api/ai/<x> tools named ai_<x>; no public-access
      fallback. scripts/smoke_mcp.py: 29/29 PASS (catalogue, filters, auth
      pass-through, hero trace WF-2261 via MCP, resources, prompts, agent).
- [x] **Ops Assistant re-pointed at the MCP surface** (SOURCE-NOTES delta) -
      plans over mcp.read_tools() (the same catalogue an external client
      sees), executes via mcp.call_tool_flat() carrying the caller's bearer,
      NDJSON stream kept: plan event has transport:"mcp", step events
      surface:"mcp" + mcp tool names. document_search KB step unchanged.
      UI badge updated to "RETRIEVAL AGENT · LIVE MCP".
- [x] Goldens cached - 43/43 in static/cached/ (ops-assistant + agent
      re-captured after the MCP re-point so cached events match live shape)
- [x] Screenshots - 12 shots at 1920x1080 in shots/, every one VIEWED. Three
      defects found and fixed this pass: (1) shell.html loaded app.js AFTER
      the page body, so every page threw "api is not defined" and rendered
      empty panels - script tag moved above {{BODY}} (its footer IIFE only
      touches header elements, which sit above); (2) ops-assistant step
      samples rendered nested objects as [object Object] - added sVal()
      JSON-stringify + truncate; (3) qa_shots.py waited for a visible
      <option> (options in a closed select are never visible to Playwright) -
      state="attached".
- [x] README (narrative + logins + reset + MCP section) + Dockerfile +
      fly.toml + .env.example + .gitignore. NOT deployed (GM has not said push).
- [x] DoP A1-A10 walk + report to lead. Evidence: A1 seeded first paint
      (shots 01-11); A2 own-brand, grep clean of vendor names; A3 24 pages +
      6 detail routes; A4 cited answers (shots 02/05/06); A5 region/infra
      grep CLEAN in static/ + cached/; A6 footer disclosure every page; A7
      fictional entities only; A8 zero pageerrors on 13 routes, zero 5xx in
      server log, designed refusal; A9 proxy round-trip, zero client-side
      keys (sk- grep hits are "risk-" substrings); A10 seed_db reset +
      golden fallback. T2/T5 no fabricated numbers (all computed from seed);
      V1 em-dash grep clean (ai.py hit is the clean() regex that strips them
      from model output); V2 banned words clean.

## Key decisions
- Python FastAPI + SQLite (stdlib sqlite3), static HTML + vanilla JS. No npm.
- API-first: web app only talks to /api/*; Swagger published at /docs.
- ERP shape (parts maker): Customers (OEM+aftermarket) + ship-to plants · internal
  Plant & Lines · Operators + certs · **Production Runs** (RUN-xxxx, lifecycle, line
  schedule, quality gate, completion, cost/margin, time entries) · Sales Orders =
  customer POs (customer part no <-> internal, server-computed subtotal/GST/total) ·
  Parts + BOM per finished part (raw/component/WIP/finished; line-side vs warehouse) ·
  **Shipments** (ASN; lot-level lines -> customer PO refs) · Suppliers · Purchase
  Orders (receipt creates raw lots + stock) · Invoices · Machines & Tooling (presses,
  CNC, furnace, e-coat, test rigs, CMM; dies/fixtures tied to part numbers) · Reports
  (throughput, OEE, scrap/rework, margin by family, customer PPM) · Settings · Audit ·
  System reset · Attachments · Notifications · Recurring (customer release schedules
  auto-generating runs) · Lots (raw + finished) · Defects/quality holds.
- Ops Assistant: NDJSON step stream - plan via predict/chat JSON over the
  platform's own MCP tool catalogue, execute each step through the MCP dispatch
  (in-process, caller's JWT, RBAC applies), compose grounded answer; KB
  document_search step adds citations. (Superseded the original private
  SQLite-whitelist design per SOURCE-NOTES.md - the whitelist tool functions
  were removed from ai.py.)
- ERP-grounded AI features return their data digest alongside the answer.
- 45 endpoint names: as original, with renames: similar-work-orders->similar-runs,
  work-order-timeline->run-timeline, site-access-briefing->plant-access-briefing,
  fleet-compliance->calibration-compliance. All others keep the original's names.
