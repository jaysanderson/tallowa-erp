# Tallowa Components ERP - DoP pass certificate

- **DoP version:** v1.1
- **Gate date:** 2026-07-23
- **Gated by:** qa-reviewer (independent, Sonnet). Full live run at localhost:8061 - every
  surface walked and screenshotted, not a log review and not trusted from any builder's own
  report. The blocking finding from the first pass was re-verified independently against the
  live served schema and the real click-path, not against the fixing engineer's account of it.
- **Verdict:** PASS - ship.
- **Supersedes:** the 2026-07-21 certificate, now **VOID**. This session's MCP-visibility,
  workflow-spine and citation changes materially changed the artifact, which voids a
  certificate under the DoP pipeline rule.

## Why this re-gate happened

Direct reviewer feedback on the previous build: *"I dont see where MCP server is used"*,
*"The UI is there, but I am unable to follow the flow"*, *"I think we need proper workflows
with actions"*, *"maybe we need to beautify it a little"*. Two engineers addressed those
three complaints; this gate judged them as acceptance criteria in their own right, alongside
the standard DoP rules.

### Reviewer complaints - gate verdict

- **"Don't see where MCP is used" - ADDRESSED.** Every ops-assistant trace step now names the
  real MCP tool and the REST route it dispatches to. A new `/integrations` console shows the
  live auto-derived tool catalogue (120 tools) and a polling feed of real MCP calls with
  caller, duration, row count and status. Legible to a technical reviewer without narration.
- **"Can't follow the flow" - ADDRESSED.** All three use cases carry a five-step workflow
  spine with live status, a factual result per step, the query and latency behind it, and
  named authority pills on human-decision gates. All three walked end to end; the blocked
  state was confirmed for an unauthorised role (a line lead sees "Sign in as the AP clerk to
  approve", not a button).
- **"Beautify it a little" - ADDRESSED.** Judged as genuinely more polished rather than merely
  more populated. The one polish defect found at gate (duplicated citation pills) was fixed
  and re-verified across four surfaces.

## Changes since the voided certificate

- MCP visibility: named tool + route on every ops-assistant trace step; trace header states
  the architecture; new `/integrations` console (live catalogue + call feed); `mcp.py` call
  recording via a bounded ring buffer; two auth-gated read-only endpoints excluded from the
  public schema.
- Workflow spines: shared `workflowStepper` / `wfTrace` helpers in `static/app.js`, wired into
  `quality.html`, `ap-invoices.html` and `ctp.html` with explicit authority gating.
- Vendor chrome removed: the ops-assistant pill read "AGENTIC RAG - LIVE ERP" (a live breach
  in the prior certified build), now "LIVE ERP - MCP-GROUNDED".
- Vendor-neutral OpenAPI description on `/api/ai/ops-assistant` (see A2 below).
- Citation de-duplication in `citesHtml()`.
- One banned word removed from a cached golden.

## Findings raised at gate and closed

1. **MAJOR / blocking - vendor name leaked into the public API docs.** FastAPI took the
   `ai_ops_assistant` docstring as its OpenAPI description, rendering *"via the ARAG Retrieval
   Agent"* at `/docs` - one click from the sidebar "API reference" link, and precisely where a
   technical reviewer hunting for the MCP layer would go next. **Closed:** explicit
   vendor-neutral `description=` on the decorator, engineering detail preserved as a `#`
   comment where FastAPI cannot pick it up. Re-verified by fetching the live `/openapi.json`
   and scanning all 120 paths for the full breach vocabulary - zero hits - and by clicking the
   sidebar link as a visitor would.
2. **Minor - citation-pill duplication.** The same source filename repeated up to eight times
   on one panel. **Closed:** grouped by resource id with an "x N" count, so the
   repeat-citation signal is preserved rather than discarded, and all snippets merged into the
   tooltip. Verified on four surfaces, including the two originally checked by code-reading
   only.
3. **Minor - banned word.** "unlock" in `static/cached/finance-exceptions.json`. **Closed:**
   changed to "release", matching phrasing already used in the same golden. Full re-sweep of
   the banned-word list across `static/` and all `.py` files is clean.

## Rule-by-rule verdict (DoP v1.1)

| Gate | Verdict | Note |
|---|---|---|
| T1-T6 | PASS (N/A) | Demo app, not a product-claim artifact; no accuracy, certification or market-sizing claims. See open item below re T6. |
| S1 no client-side secrets | PASS | KB token and agent key confirmed server-side only. |
| S2 no hosting-region / infra string | PASS | Re-swept clean. |
| S3 anonymised customer names | PASS (N/A) | Fully synthetic cast. |
| S4 no real brand / personal identifiers | PASS | |
| S5 USD pricing | PASS | Per the precedent recorded in the prior certificate: the USD rule targets GTM artifacts, not an in-character Australian manufacturer's own AUD invoices. |
| S6 outbound = draft | PASS (N/A) | Nothing outbound. |
| V1 AU English / no em dashes | PASS | |
| V2 banned words | PASS | Re-verified after the fix. |
| V3 de-AI pass | PASS | |
| V4 room test | PASS | |
| D1-D4 (decks) | N/A | |
| A1 seeded first paint | PASS | |
| A2 no vendor chrome / no exposed ARAG naming | PASS | The one breach found this gate is closed and independently re-verified against the live served schema and the actual click-path. |
| A3 one route per use case | PASS | |
| A4 cited / grounded answer reachable | PASS | |
| A5 no region string customer-facing | PASS | |
| A6 discreet synthetic disclosure | PASS | |
| A7 no real identifiers | PASS | |
| A8 visible polish | PASS | Zero console errors, zero server tracebacks. See unresolved note below. |
| A9 server-side proxy round-trip | PASS | |
| A10 documented 30-second reset | PASS | Reset control exercised and confirmed clean. |
| M1-M3, C1-C3 | N/A | |
| E1 evidence attached | PASS | Screenshots, live greps and direct API calls throughout - not "looks fine". |

## Regression checks (things already passing, re-confirmed)

- **Honest safety gate intact.** With `ARAG_AGENT_KEY` revoked, the assistant renders "The
  retrieval agent finished without a grounded answer" rather than faking success. Surfacing
  MCP did not weaken the refusal logic, and non-substantive tool calls still render neutral,
  never as a green tick.
- **Markdown numbered-list fix holds** on newly generated live content.
- **Cross-panel number consistency** reconciles on all three use-case pages.

## Known state - not gate conditions

- **`ARAG_AGENT_KEY` is a revoked PAT (401).** The live retrieval agent is down; the app
  refuses honestly rather than fabricating. Escalated to the GM. Not a defect, but the live
  ops-assistant path cannot be demonstrated until a fresh PAT is in place.
- **Unresolved, not found:** a small red element near the AP-invoices "Explain a failure"
  input, seen once in a lead screenshot, was never reproduced across two gates despite
  targeted checks at clean and post-reset states. Recorded honestly as unreproduced rather
  than passed off as a phantom or failed on no evidence.

## Open items carried forward (not blocking)

- **T6 / locked facts:** if Tallowa is ever pointed at a real account brief rather than its
  synthetic cast, T6 will need a locked-facts table and a cross-artifact consistency check.
- **Prompt hardening:** no generation prompt carries a banned-word avoid-list, so a future
  regeneration could reintroduce "unlock". Deliberately deferred rather than changed mid-gate,
  since ~47 of 49 cached goldens run through the shared base prompt and would all become
  re-verification liabilities. Written up at
  `apps/tallowa-erp/dop-evidence/2026-07-23/prompt-hardening-backlog.md`.
- **Ops Assistant prompt is not version-controlled.** It lives on the retrieval agent's own
  hosted config rather than in this repo, so that slice of behaviour cannot be reviewed or
  reverted through the normal process.
- **MCP tool surface is uncurated:** 120 auto-derived tools. Honest and now visible on the
  console, but an unfocused surface for an agent to plan over. Worth curating before a
  customer-facing session.

## Evidence

Under `apps/tallowa-erp/dop-evidence/2026-07-23/`:

- `docs-03-expanded.png`, `verify-docs-01.png` - the OpenAPI leak, before and after.
- `verify-ap-citations.png`, `verify-quality-citations-02.png`,
  `verify-copilot-02-answered.png`, `verify-playbooks-03-generated.png` - citation fix across
  four surfaces.
- `verify-honestgate-final.png` - honest refusal on the dead credential.
- `ap-authgate-lineuser-03.png` - authority gate blocking an unauthorised role.
- `ctp-05b-committed.png`, `ap-04-approved.png` - full workflow completions.
- `ctp-06-freshafterreset.png` - A10 reset control.
- `dashboard-03-briefing-final.png` - markdown numbering fix on live content.

## Scope note

"Approved" means it passed the gate. It does **not** clear outbound use - hard rule 10 and any
PRD-specific livery rules still apply. This certificate is voided if the artifact or the DoP
materially changes after this date.
