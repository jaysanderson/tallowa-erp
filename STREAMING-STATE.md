# ARAG Streaming Progress UI - Ops Assistant

GM directive (Jay, 22 Jul 2026): "while the arag is retrieving the answer, use the
streaming response to let the user know what's going on, being as detailed as
possible, while still looking great."

**Status: PASSED the final re-gate (all 6 findings fixed and confirmed live,
including the round-2 loophole close).** One small fast-follow QA
recommended after the pass (non-blocking) - the mismatched-golden fallback -
is now also fixed and verified locally, see bottom of this file. Awaiting
the lead's spot-verify + redeploy for that one. The lead's own dashboard
curation of the MCP node's exposed Functions (removing get-by-id tools that
need an id the planner doesn't have, e.g. `lines_get_lines` - the
root cause of why this failure mode fires at all) is explicit follow-up, not
on the critical path - the app-side gate below catches the bad outcome
regardless of what the agent composes or which tools it's allowed to call.

### Round-2 fix: the "any success" gate had a loophole (22 Jul 2026)

QA reproduced 3/3: the line-A1 question gets exactly ONE trivial success
(`lines_list_lines` - lists the plant's lines, carries no
stoppage/hold/status data) plus 4 failed `lines_get_lines` calls. The
original gate ("did any tool succeed") counted that one bare catalogue
success and passed the answer through - and the agent still asserted
"line A-1 running, no stoppage" despite a real open hold (HLD-0145,
RUN-1101, station 60) existing in the seeded data.

**Fixed with two layers, both conservative by design** (verified `list our
customers` and the WF-2261 trace still pass through untouched afterward):

1. **Tightened the success gate from "any success" to "a substantive
   success."** Added `_NON_SUBSTANTIVE_TOOLS` - a small, explicit denylist of
   pure catalogue/roster/internal-plumbing tools (`lines_list_lines`,
   `lines_get_lines`, `skills_list_skills`, `settings_*`, `notifications_*`,
   `access_tokens_*`, `attachments_list_attachments`, `auth_list_me`,
   `auth_create_logout`) that no longer count toward `success_count` on
   their own. Deliberately NOT a broad allowlist - genuinely record-bearing
   catalogue tools that ARE a complete, correct answer to their own question
   (`customers_list_customers` for "list our customers",
   `parts_list_parts`, `suppliers_list_suppliers`, etc.) are untouched and
   still count.
2. **Belt-and-suspenders: a negative-claim guard.** Added
   `_STATUS_VERIFYING_TOOLS` (the tools that would actually reveal a
   stoppage/hold/defect if one existed - `holds_list_holds`,
   `holds_create_holds`, `holds_release`, `defects_list_defects`,
   `defects_list_pareto`, `defects_create_defects`, `runs_status`,
   `runs_get_runs`, `ai_fault_root_cause`, `ai_fpy_root_cause`) and
   `_NEGATIVE_CLAIM_RE` (plain-English patterns for an all-clear/absence
   claim - "no stoppage/reported/issues/problems/blockers/holds", "running
   without/with no/normally/as scheduled", "nothing (is) holding", "not
   currently blocked/held/on hold/stopped"). If the composed answer matches
   that pattern AND none of `_STATUS_VERIFYING_TOOLS` succeeded, the answer
   is refused (routes through the same fallback path) regardless of whether
   some OTHER, unrelated tool happened to succeed - a generic success
   elsewhere never licenses asserting the absence of a problem nothing
   actually checked for. Unit-tested the regex against 8 realistic phrasings
   (5 negative, 3 legitimate) before wiring it in - no false positives.

**Verified: ran the exact line-A1 question 3x live** (curl, full event
trace inspected each time, then once more in-browser for the visual). All
3/3: one success (`lines_list_lines`, now correctly excluded), 4 failures,
`success_count` reaches 0, gate fires `no_grounded_data`, safety net holds -
**never once asserted the false "no stoppage" claim**, honest state (and the
cached golden fallback) rendered every time instead. Also re-verified "List
our customers." live (`customers_list_customers` still counts, real answer
passes through untouched) and the WF-2261 golden replay (unaffected -
doesn't go through this gate at all, it's a direct cached-events replay).

**One observation worth flagging, not fixed** (out of this task's scope):
the frontend hardcodes `golden:'ops-assistant'` for every live question
(`ops-assistant.html`'s `run()`), so ANY question's fallback shows the same
WF-2261 cached example regardless of what was actually asked - for the
line-A1 question the fallback message is honest but the example content is
about an unrelated customer-shipment question. Pre-existing, not introduced
by this fix; per-question goldens would need a separate change if wanted.

### Real-world confirmation of the exact failure mode (22 Jul 2026)

Ran "What is holding up production on line A-1 right now?" live (the
question the lead named as likely to hit finding 1's root cause). It did,
exactly as predicted: one real success ("Checking lines - data retrieved"),
then four consecutive failures, each a clean friendly line ("Checking lines -
no result / Couldn't complete this lookup - checking lines didn't return
usable data.") - no raw HTTP/pydantic payload, no stuck spinner across any of
the five steps. The agent's own summarize step was already honest here
("Not enough data to answer this.") given the mostly-failed retrieval, so
this particular run didn't need the safety net's intercept (`success_count`
was 1, not 0) - but it's a clean real-world demonstration of fixes 1, 2 and 4
together on the exact scenario described, end to end, no crash, no false
confidence.

### QA findings and app-side fixes (22 Jul 2026, `ai.py` / `app.js` / `ops-assistant.html`)

1. **BLOCKER (A8) - raw HTTP error leaked into the trace**, e.g.
   `[HTTP 422] {"detail":[{"type":"missing","loc":["query","lot"]...}]}` and
   `Missing path param: lid`. **Fixed**: added `_friendly_fail_detail(tool)` -
   a failed tool step now always shows "Couldn't complete this lookup - X
   didn't return usable data", never the raw FastAPI/pydantic payload,
   regardless of which of the three `_map_arag_event` branches (`used_m`
   inline error, `prompt_m`, or the `pending`/`agent_path` fallback) hits it.
2. **BLOCKER (A8) - stuck spinner on multi-step goldens.** Root cause: the
   frontend tracked a single `liveToolCard` reference
   (`ops-assistant.html`), but `_adapt_legacy_golden_events` fans out ALL
   `tool_call` events for a golden before any `tool_result` (the WF-2261
   flagship golden has exactly 2 steps - `trace_list_forward`,
   `lots_list_lots` - so the second `tool_call` always overwrote the
   reference to the first, leaving it spinning forever). **Fixed**: replaced
   the single reference with `pendingByTool` - a map of tool name -> a queue
   of pending card elements (a small array per tool, in case the same tool
   is called twice) - so each `tool_result` resolves the correct, matching
   card regardless of arrival order. Verified: the WF-2261 fallback trace now
   shows both steps completed cleanly, no stuck spinner.
3. **MAJOR - cached-fallback grounding footer leaked raw tool names**, e.g.
   "Grounded in live queries: trace_list_forward, lots_list_lots". **Fixed**:
   `_adapt_legacy_golden_events`'s `answer` branch now runs `g.get("tools")`
   through `_humanise()` before attaching, matching every other place tool
   names reach the UI. Verified via curl: now reads "Tracing the lot forward
   to finished lots and shipments, Pulling part-lot records".
4. **MINOR - "No tool used" sentinel shown as a contradictory detail line**
   under a "data retrieved" heading. **Fixed**: added `_clean_detail()` /
   `_UNINFORMATIVE_DETAIL`, suppressing that sentinel the same way empty
   `{}`/`None` args were already suppressed.
5. **MINOR (pre-existing shared code) - `app.js` `md()` rendered mixed
   numbered+bulleted lists as all "1."** Root cause (found by testing, not
   guessing): TWO separate bugs compounded - (a) an indented sub-bullet under
   a numbered item closed and reopened the list, and (b) the loose-list
   pattern real AI answers use (a blank line between each numbered item) ALSO
   closed the list. Either alone would restart `<ol>` numbering at 1 for
   every item. **Fixed both**: indented bullets now fold into the previous
   `<li>` as a `<br>&bull;` detail line instead of breaking the list; a blank
   line while a list is open is now skipped rather than closing it (only a
   genuine non-list, non-blank line closes it). Verified in the live DOM: a
   4-item numbered list with indented sub-bullets and blank lines between
   items now renders as one `<ol>` numbering 1-4 correctly.
6. **BLOCKER (T2) - false-confident answer, app-side safety net.** Added a
   `success_count` tracker in `arag_agent_events`'s consumer loop: every
   `tool_result` event with `ok:true`, or any `doc_search` event, increments
   it. **The exact detectable signal, as asked**: when the final `answer`
   event arrives, if `success_count` is still `0` (every tool call errored,
   or none were ever attempted), the answer is NOT rendered - instead an
   `error` event (`stage: "no_grounded_data"`) is yielded, which routes
   through the *same* fallback path already built for timeouts (honest
   message, then the cached golden if one exists). Verified with a direct
   unit test of `_map_arag_event` against three synthetic traces (all fed
   through the real function, not reimplemented): all-tool-calls-errored ->
   blocked; one real success -> passes through; zero tool calls attempted at
   all -> also blocked (an edge case beyond just "errored", worth having).
   Also confirmed live: a genuinely successful run (multiple real tool
   successes) passed its answer through untouched, so the net only catches
   the failure case, not real answers.

All six re-verified together in one final combined pass (the WF-2261
fallback scenario, `AGENT_TIMEOUT_S` temporarily set to 3s to force it
quickly then restored to the real 55s default): clean completed steps (no
stuck spinner), humanised grounding footer, correct list numbering, and a
friendly error line all present in the same screenshot.

## Decisions from the lead's review (22 Jul 2026)

1. **The 3-use-case migration to this pattern is ON HOLD.** It's genuine
   follow-up scope (question templates per use case, keeping the
   deterministic math as MCP tools the agent calls rather than app-computed
   hybrid narration, per-use-case cached goldens), `fpy-root-cause` is
   inherently multi-hop and may hit the same slowness as WF-2261, and Jay
   separately asked for a deck of the 3 use cases using their CURRENT
   (deterministic) implementation via screenshots - so `/quality`,
   `/ap-invoices` and `/ctp` stay exactly as they are for now while a
   deck-builder captures them live. Do not touch those pages/routes.
2. **The WF-2261 live timeout is accepted, not urgent.** The graceful
   fallback (honest message + full cached answer) carries the demo. The lead
   may still curate the MCP node's registered-agent Functions in the
   dashboard to get it completing live, but that's no longer blocking
   anything.
3. **The `doc_search` gap (unexercised, no KB context wired) is accepted as
   known** - renders automatically with no code change if a KB context item
   is added back later.

## What changed

- `ai.py` - the Ops Assistant (`POST /api/ai/ops-assistant`) now streams the
  ARAG Retrieval Agent's own NDJSON trace live, instead of running the
  homegrown `agent_plan()`/`agent_events()` loop (which stays in the file,
  unused by this route, still backing `POST /api/ai/agent` - not migrated
  this pass, see "Migrating the 3 use cases" below).
- `static/pages/ops-assistant.html` - a rebuilt, detailed, polished live step
  trace: spinner-to-tick/cross transitions, elapsed timers, a persistent
  "Working - Ns elapsed" ticker fed by heartbeats even when ARAG itself goes
  quiet, and a collapsible "How this was answered" trace once the answer
  lands.
- `.env` / `.env.example` - fixed `ARAG_AGENT_BASE_URL` (was still pointing at
  the wrong, `rag.progress.cloud` host from an earlier pass - the agent
  surface is on `dp.progress.cloud`); documented the four `ARAG_AGENT_*` vars.

## The proxy approach

`arag_agent_events(question, bearer)` in `ai.py`:

1. `POST {ARAG_AGENT_BASE_URL}/api/v1/agent/{ARAG_AGENT_KB_ID}/session/ephemeral`
   with the PAT (`ARAG_AGENT_KEY`) as Bearer, and the **caller's own JWT**
   forwarded in the request body's `headers.authorization` field - this is
   what makes the agent's `/mcp` tool calls carry the logged-in user's RBAC,
   not a static service credential.
2. A background `asyncio.Task` reads ARAG's raw NDJSON via `httpx`
   (`client.stream(...)`) and pushes each parsed line onto an `asyncio.Queue`,
   untouched. This is deliberate: cancelling a bare `aiter_lines()` read
   mid-flight (e.g. via `asyncio.wait_for` timeout) is not safe, but
   cancelling a pending `queue.get()` is - so all the heartbeat/timeout logic
   lives in the *consumer* loop, never touching the live HTTP read directly.
3. The consumer loop `await`s the queue with a 3s timeout (`HEARTBEAT_S`). No
   event within 3s -> yield a synthetic `heartbeat` event (elapsed time only,
   no new step) so the UI never looks dead even when ARAG itself is silent
   for a while (confirmed this happens for 10-25s stretches even on
   successful runs).
4. An overall wall-clock budget (`AGENT_TIMEOUT_S`, default 55s, env
   `ARAG_AGENT_TIMEOUT_S`) - short enough that the confirmed-working
   simple/moderate questions (~15-50s observed) complete live, well short of
   the flagship WF-2261 question's ~300s server-side stall. Past the budget,
   the task is cancelled and an honest `error` event fires.
5. `POST /api/ai/ops-assistant` catches that `error` (or any transport
   exception) and, if no real answer landed yet, streams a `fallback` note
   plus the cached golden's events (adapted - see below) right after, so the
   stream never just stops.

## Event mapping

Raw ARAG NDJSON -> typed events via `_map_arag_event()`:

| ARAG shape | -> | our type | notes |
|---|---|---|---|
| `step.module="smart"`, title `Reactive iteration N/M`, value `Tool calls: X(args)` | -> | `plan` (once, first iteration) then `tool_call` | strips the `__<registered-agent-uuid>` suffix ARAG appends to tool names; parses args from either `key=value` or Python dict-repr `'key': value` shape (both occur) |
| `step.module="mcp"`, value `Used tool: X with arguments: Y` | -> | `tool_result` | **the more common shape in practice** - some tool calls announce themselves here directly rather than via a preceding `tool_call`, so this is checked first |
| `step.module="mcp"`, value `Fetched MCP prompt 'name'` | -> | `tool_result` | the Smart agent can pull one of the app's 3 curated MCP *prompts* (reasoning playbooks) instead of calling a tool - given its own friendly label (`PROMPT_LABELS`) rather than falling through to a raw path |
| `step.module="mcp"`, `error` set | -> | `tool_result` (`ok:false`) | red-styled in the UI |
| `step.module="ask"` | -> | `doc_search` | untested live - see "known gap" below |
| title `Reactive mode completed` / `Context validation` / `module="summarize"` | -> | `composing` | multiple composing events are normal and expected (shows the real multi-stage reasoning, matches "as detailed as possible") |
| top-level `answer` (not the `"Error in generation"/"Error in context"` sentinels) | -> | `answer` | |
| task/stream ends with no answer, or wall-clock budget exceeded | -> | `error` | triggers the golden fallback |

`_tool_name()` -> friendly label via `TOOL_LABELS` (curated overrides for the
tools/prompts most likely to show up in a demo - trace, shipments, customers,
holds, AP batch-fix, CTP, 8D, FPY root cause, etc.) with a generic
verb-by-CRUD-prefix fallback (`_humanise()`) for anything else, covering all
120 catalogued tools.

## Known gap

`doc_search` (KB-context) events are implemented but **unexercised** - the
agent's `ask` (KB) context item was removed during the earlier feasibility
work to isolate the MCPHTTPDriver bug, and the agent-mode KB it would read
from has zero synced documents. The live traces observed so far only exercise
the MCP tool-call and MCP-prompt paths. If a working KB context item is added
back to the agent (needs the dashboard-provisioned nucliadb auth key - the
same limitation found in the original feasibility work), `doc_search` events
will render automatically with no further code change.

## Verified locally (screenshots viewed, not just captured)

1. **Live, successful run** ("List our customers.") - real ARAG trace end to
   end: heartbeats while ARAG was quiet, a `plan` step, a real tool call
   (`customers_list_customers`) with a spinner-to-tick transition, multiple
   `composing` steps, then a real grounded answer naming six actual seeded
   customers with contact details - proves the whole architecture (ARAG
   plans, calls `/mcp` with the forwarded user JWT, grounds, answers).
2. **Live, harder run** ("Which orders are at risk of missing their promised
   dates and why?") - a genuinely detailed 11-step trace: two MCP-prompt
   fetches, a real tool error (`Checking the sales order - no result` /
   `Missing path param: so_no`, rendered in red with a cross icon), several
   successful tool calls and prompt fetches, ending in an honest low-
   confidence answer ("Not enough data to answer this.") with the
   collapsible "How this was answered (11 step(s))" trace working correctly
   (expand/collapse, no layout issues once the reparent animation settles).
3. **Graceful timeout fallback** (WF-2261 flagship question, `AGENT_TIMEOUT_S`
   temporarily set to 3s for this one test to force it quickly, then restored
   to the real 55s default) - "The retrieval agent is taking longer than
   expected." then "Showing a captured example while the live agent
   recovers." then the FULL cached-golden answer renders correctly via the
   legacy-event adapter: real shipment numbers (SHP-0341/SHP-0347, Ellandra
   Motors, 640 units total), the WF-2261 quarantine status, grounding line
   and collapsible trace (5 steps) - confirms the demo never dead-airs on the
   one question that reliably times out live.
4. **Cached-mode direct replay** (`"mode":"cached"`) - verified via curl, the
   `_adapt_legacy_golden_events()` converter correctly turns the old
   `plan/step/docs/answer/done` shape (what the existing `ops-assistant.json`
   golden was captured in) into the new typed vocabulary the frontend
   understands, so the frontend never needs two code paths.

## What's needed to migrate the 3 use cases

The 3 use-case flows (`fpy-root-cause`, `ap-error-explain` + `ap-batch-fix`,
`ctp-commit`) currently still run their own deterministic digs
(`ai.py`'s per-feature handlers calling the DB/costing logic directly, then
narrating via `predict_gen`) - they don't call the ARAG agent at all yet.
Migrating them to this same pattern involves:

1. Deciding the question phrasing each use case sends to the agent (they're
   currently invoked with structured args - e.g. `{line, query}` for FPY,
   `{ap_no}` for AP - not a free-text question; each needs a template that
   turns its structured input into a natural-language question for
   `arag_agent_events()`).
2. Deciding what streams to the UI per use case - probably the same live
   trace component, reused (it's already generic, not ops-assistant-specific
   in its JS logic beyond the DOM ids), just mounted on each use-case's page.
3. **Keeping the deterministic math as MCP tools, not app-side bypasses** -
   per the GM directive, the CTP date math and AP authority-limit logic must
   stay deterministic, but as something the ARAG agent *calls* via `/mcp`
   (they're already exposed as tools - `ai_ctp_commit`, `ai_ap_batch_fix`,
   `ai_fpy_root_cause` are in the 120-tool catalogue), not something the app
   computes and hands to the agent pre-digested. The agent should be the one
   deciding to call `ai_ctp_commit`, not the app calling it directly and
   asking ARAG to narrate the result - that's exactly the "hybrid" pattern
   the GM directive is moving away from.
4. Each use case needs its own cached golden captured via the live streaming
   path once its question and trace are working, same as `ops-assistant.json`.
5. The known multi-hop-question slowness (the WF-2261 pattern) likely applies
   to some of these too, particularly `fpy-root-cause` (a root-cause chain is
   inherently multi-hop) - the same 55s-timeout-then-fallback pattern should
   carry over unchanged.

This is a genuine follow-up scope, not a quick add-on to this task - happy to
take it next if wanted.

## Fast-follow: mismatched-golden fallback (22 Jul 2026, post-pass)

QA's non-blocking recommendation after the pass: the `no_grounded_data` case
(agent genuinely couldn't retrieve anything, e.g. line-A1) was rendering the
honest message AND the cached WF-2261 customer-shipment example beneath it -
a non-sequitur under a line-A1 question, since the golden is hardcoded to
one specific question (`ops-assistant.html` always sends
`golden:'ops-assistant'` regardless of what was actually asked). Fixed in
`ai_ops_assistant` (`ai.py`): only the `timeout` error stage still triggers
the cached-golden fallback (that one's a genuine, still-working slow run of
presumably the same flagship question the golden represents); every other
failure stage (`no_grounded_data`, `unverified_negative`, `no_answer`,
`transport`, `config`, and the outer catch-all exception) now shows the
honest message alone, nothing beneath it. Also cleaned up the outer
catch-all to give a friendly message instead of a raw Python exception
string, while I was in there.

**Verified locally, both required cases:**
- Line-A1 fallback now shows "The retrieval agent could not retrieve any
  live data for this question." completely alone - confirmed via curl (no
  `fallback`/golden events in the stream at all) and visually in-browser (no
  WF-2261 content anywhere on the page beneath the message). One live run
  during this verification pass happened to genuinely succeed instead -
  correctly returned the REAL hold (production on line A-1 on hold due to
  quality issues, run RUN-1101, fastener lot WF-2261, station 60,
  containment disposition pending) - a nice confirmation that a real
  success still renders normally when the agent does happen to retrieve the
  right data.
- WF-2261 timeout still shows its matching golden - confirmed via curl
  (`AGENT_TIMEOUT_S` temporarily forced to 3s to trigger it quickly): error
  stage `timeout` -> `fallback` note -> the full WF-2261 cached answer,
  unchanged from before.
- Regression: "List our customers." still passes through live with its real
  answer, no error/fallback events at all.

Not deployed - the lead said no full re-gate needed for this targeted
change, just a spot-verify before redeploy.
