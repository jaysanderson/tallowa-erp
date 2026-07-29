# Tallowa Components - Plant Operations

An API-first ERP for **Tallowa Components**, a fictional Australian tier-1
automotive parts maker (Bellbrook plant: braking, chassis and e-mobility
components), with 49 grounded AI features woven invisibly through it. Twin of
the MaintenanceOS reference demo, re-grounded from field services to component
manufacturing. Everything - companies, people, parts, lots, figures - is
synthetic.

Three fully-worked, live agentic-orchestration use cases are seeded on top of
the base ERP - see **Three use-case demo script** below: an overnight quality
alert that resolves to a ranked root cause and an auto-drafted 8D report; a
batch of AP posting failures resolved as one shared-root-cause fix; and a
capable-to-promise sales co-pilot that commits a real delivery date live,
with a genuine RBAC split between the sales role and the production planner.

## Run it

```bash
cd apps/tallowa-erp
../../.venv/bin/python -m uvicorn app:app --port 8061
# open http://127.0.0.1:8061
```

`.env` (gitignored) carries the retrieval host, KB id and service token - all
calls are proxied server-side; no key ever reaches the browser. The SQLite
store (`data/erp.db`) seeds itself on first boot.

## Demo logins (shown on the sign-in card, password `demo1234`)

| Login | Role |
|---|---|
| admin@tallowacomponents.com.au | Administrator |
| plant@tallowacomponents.com.au | Plant manager |
| super@tallowacomponents.com.au | Production supervisor |
| line@tallowacomponents.com.au | Line lead |
| quality@tallowacomponents.com.au | Quality inspector |
| ap@tallowacomponents.com.au | Finance - AP clerk (Maria Costa) |
| sales@tallowacomponents.com.au | Sales (Nate Ferris) |

## Three use-case demo script

The pitch these three use cases prove: one natural-language question -> the
Ops Assistant/MCP layer queries many ERP subsystems in parallel -> a grounded,
ranked, actionable answer -> every state-changing action still needs a
human's approval (RBAC). Each is its own route, its own login, its own seeded
scenario - script them in this order, or run any one standalone.

### UC1 - Quality alert -> 8D root cause (sign in as `quality@`)
**Seeded scenario:** overnight on line A-2, RUN-1111 (HV connector housings)
ran at FPY 84.3 per cent against the 96.5 per cent target - a real breach, not
a demo number. Three real, correlated causes are seeded: raw lot **KP-7742**
(polymer resin, first use on this line, 71 per cent of the scrap), machine
**INJ-01** (preventive maintenance five days overdue, 29 per cent of the
scrap), and a first-night trainee night-shift supervisor (operator note on
Ravi Fenn). The finished lot **TC-A-4900** (354 units) is still in stock, not
yet shipped - not yet contained.

1. Go to **Quality** (Defects & holds), scroll to "Overnight FPY alert - Line
   A-2". Click **What happened overnight?** - three ranked, confidence-labelled
   suspects (HIGH/MEDIUM/LOW) in seconds, cited against QP-8D and QM-04/07 -
   not a flat defect Pareto.
2. Click **Contain finished lot TC-A-4900** - places a real hold (quality-role
   gated) that blocks it from shipping. This is the "contain the bad lot"
   moment; the same lot is also traceable end to end from **Traceability**
   (search `KP-7742`).
3. Click **Draft the 8D report** - the D2/D3/D4 sections auto-fill from the
   evidence, grounded in the *live* hold status (not an assumed one). Edit the
   text box, then **approve** - filed and logged, no blank-page 8D under
   deadline.

### UC2 - AP invoice posting-failure auto-fix (sign in as `ap@`)
**Seeded scenario:** 23 vendor invoices failed to post this morning, each with
a cryptic 4-6 character error code. **9 of them share one root cause** - the
vendor master records for Coalcliff Steel and Meander Castings still point at
cost center CC-410, closed in the plant's cost-center restructure (error
`GL-4102`). 13 more are distinct one-off failures. One (`BANK-VER`, Bellbrook
Gauge & Rig) genuinely needs treasury sign-off and stays stuck this cycle -
an honest limit, not a bug.

1. Go to **AP invoices**. Type `AP-8801`, click **Explain** - plain English
   (no accounting degree needed), the exact fix, and the policy that
   authorises it (cited from `fin-ap-authorisation-matrix.md`).
2. The "Shared root cause" panel appears automatically: 9 invoices, combined
   total, confirmed within the AP clerk's approval limit. Click **Propose the
   batch fix**, then **Approve & post all 9** - the vendor master is
   corrected once, all 9 post, each logged individually with its policy
   citation. Try `AP-8823` afterwards to show the honest escalation case.

### UC3 - Capable-to-promise sales co-pilot (sign in as `sales@`, then `plant@`)
**Seeded scenario:** a 250-unit order of **TC-70210** (HV busbar set) is short
170 units of a component (busbar insulation moulding) - nothing is sitting in
stock for it. The binding incoming supply is **PO-2252** (Kurrajong Polymers),
due in 11 days.

1. Go to **Capable-to-Promise**. Part TC-70210, qty 250, customer Marran
   Automotive, requested date ~10-12 days out. Click **Can we deliver?** - a
   computed commit date, the binding constraint named exactly (component, PO,
   date), and a safer alternative with its risk - under 30 seconds, not 45
   minutes.
2. Click **Re-run the scenario** ("what if we expedite that component?") -
   the PO is pulled in, the commit date moves earlier, and a real conflict
   check runs against every other near-term order on the same component
   (including runs already in progress, not only queued ones). It is not
   clean: **PO-2252 does not have enough for everyone** - RUN-1100 (SO-3433,
   Marran's own other busbar order, already in progress) and RUN-1105
   (SO-3434, Korrawin) still need 1,720 and 1,280 units of it respectively,
   1,150 more than the incoming shipment covers. This is the honest-failure
   moment: the co-pilot will not tell Hans "no conflict" just to make the
   sale sound clean - it surfaces the real supply problem so the human
   decides with full information (raise PO-2252's quantity, split the
   allocation, or accept the risk), rather than committing to a date the
   plant cannot actually keep for everyone.
3. Click **Propose order confirmation + supplier rush request** anyway - one
   proposal act, two separate approvals, both fully informed by the conflict
   above: **Confirm the order** finalises immediately under the sales role's
   own authority (commit on the call); the supplier rush request needs the
   **production planner**, who sees the same conflict warning before
   approving. Sign out and sign in as `plant@` (or `super@`), return to
   **Capable-to-Promise** - the "Pending schedule changes" panel shows it
   waiting; **Approve the schedule change** pulls PO-2252 in. Signing in as
   `sales@` and trying to approve the schedule change yourself returns a
   403 - the RBAC split is real, not cosmetic.

## The demo narrative

**The seeded story:** supplier Warrigal Fasteners shipped output-fastener lot
**WF-2261** with out-of-spec thread rolling. Two in-plant re-test failures and
a customer escape at Ellandra Motors later, the lot is quarantined, two
finished actuator lots and a live run are on hold, and an 8D containment is
running. The whole platform is alive with that story.

### 1. Lead with the recall containment (the wow moment)
- Sign in as `plant@`. The dashboard already shows the holds, the stopped
  line, the critical defects. Click **Brief me** - the AI Daily Briefing names
  HLD-0142/0143/0144, RUN-1101 and the exact next actions from live data.
- Go to **Traceability** (it opens on WF-2261). One click shows: 3 runs
  consumed the lot, 2 finished lots, **640 units shipped to two Ellandra
  plants, 300 blocked on site** - the QM-07 fifteen-minute trace target done
  in seconds.
- Click **Narrate exposure & containment**: a cited narrative that combines
  the live trace with the plant's own 8D and traceability procedures
  (citations shown underneath).

### 2. Ops Assistant - the live agent
- **Ops Assistant** page, first suggestion chip: *"Which customer shipments
  are exposed to fastener lot WF-2261...?"* Watch it plan, query the live ERP
  step by step (every tool call and row count shown), check the plant
  documents, then answer with the exact shipment numbers. This is retrieval
  over the running system, not a canned reply.
- Also strong: *"Which orders are at risk of missing their promised dates and
  why?"* - it connects the held run and the stopped line to specific orders.

### 3. Knowledge Copilot - cited answers from controlled documents
- Ask *"What torque does the EPB-40 output fastener take and what happens if
  a reading is out of window?"* - answer: 24 Nm plus or minus 2, station
  locks, defect raised - with the standard work instruction cited.
- Ask something it cannot know - it declines rather than guessing.

### 4. Build Playbooks
- Pick **TC-30412 EPB-40 actuator**, generate: a run-ready standard-work
  summary grounded in the released SWIs (cited) plus watch-outs from what past
  runs actually hit (the torque-retention failure mode is in there). Save as
  template.

### 5. AI Insights grid
- Ten grounded cards, each querying the ERP at click time: risk watchlist,
  ship-date early warning, margin insight, cost exceptions, audit readiness
  (cited against the quality manual), exec summary, lost quotes, finance
  exceptions, defect Pareto and the WF-2261 exposure card.

### 6. Everywhere else
Contextual assistants sit inside the modules: kitting lists and run timelines
on a production run, account health and quote drafting on a customer, PO
extraction from a pasted supplier document on Purchase orders, calibration
compliance on Machines, certification gap analysis on People, pre-shift
safety and visitor briefings on Plant & lines, the audit-trail assistant on
Audit.

### API-first proof
Open **/docs** - the entire platform surface, ERP and all 45 AI endpoints, as
a published Swagger. "The web app only ever talks to this API."

## The MCP surface (first-class, like the API)

The platform also speaks **MCP**: `POST /mcp` (Streamable HTTP, stateless
JSON-RPC 2.0). The tool catalogue - **120 tools** - is auto-generated from the
app's own OpenAPI document (`mcp.py`); nothing is hand-written per tool, and
the MCP layer never reimplements business logic. Every `tools/call` dispatches
back through the REST handlers in-process, so **auth, RBAC and validation
apply to agents exactly as to humans** - the caller's `Authorization: Bearer`
JWT passes straight through (an unauthenticated tool call returns the same 401
the API gives). Excluded from the catalogue: DELETEs, `/api/system`, login,
print/download, and the streaming NDJSON route.

Also served: MCP **resources** (`tallowa://openapi`, `tallowa://dashboard`,
`tallowa://production-run/{run_no}`, `tallowa://customer/{cid}`) and three
curated **prompts** (`triage-production-run`, `draft-sales-order-from-history`,
`daily-operations-briefing`).

The **Ops Assistant is an MCP client of its own platform**: it plans over this
same tool catalogue and executes each step through the MCP dispatch (that is
what its "RETRIEVAL AGENT · LIVE MCP" tag means), streaming every call. Try it
from outside with any MCP client - point it at `/mcp` with a login token, or:

```bash
curl -s -X POST localhost:8061/mcp -H 'content-type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Smoke-test the whole surface: `../../.venv/bin/python scripts/smoke_mcp.py`
(29 checks: catalogue, filters, auth pass-through, hero trace via MCP,
resources, prompts, and the Ops Assistant round trip).

## 30-second reset

Settings -> **Reset demonstration data** (admin), or:

```bash
../../.venv/bin/python seed_db.py          # rebuild the ERP store
```

The knowledge box reseeds with `scripts/seed_kb.py --purge` then
`scripts/seed_kb.py` (only needed if the document set is damaged - the ERP
reset never touches it). Golden fallbacks for every AI feature live in
`static/cached/` (`scripts/cache_golden.py` refreshes them); if a live call
fails mid-demo the cached result serves automatically.

## Layout

```
app.py            FastAPI entry - pages + routers + MCP mount, Swagger at /docs
erp.py            the ERP API (/api/*) - auth, all modules, trace core, AP invoices,
                   holds create/release, expedite requests, 8D reports
ai.py             the 49 AI features (/api/ai/*) - proxy pattern, scoped retrieval,
                   plus the three use-case flows (fpy-root-cause, 8d-draft,
                   ap-error-explain, ap-batch-fix, ctp-commit)
mcp.py            hosted MCP surface - OpenAPI->tools, in-process dispatch, resources, prompts
database.py       SQLite schema + helpers
seed_db.py        deterministic demo seed (date-anchored, hero chain + the three
                   use-case scenarios included)
scripts/          provision.py, gen_corpus.py, seed_kb.py, cache_golden.py, qa_shots.py
static/           shell + login + one page per module (incl. ap-invoices, ctp),
                   app.js helpers, cached goldens
data/corpus/      the 25-document quality/safety/work-instruction/finance-policy set
```
