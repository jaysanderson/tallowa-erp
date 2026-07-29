# Prompt-hardening backlog: banned-word avoid-list missing from generation prompts

Filed 23 Jul 2026. Not fixed this pass (deferred per lead ruling - churning a shared
generation prompt mid-gate makes every golden through that path a re-verification
liability at exactly the wrong time). Backlog only.

## (a) Which generation paths lack the avoid-list

**apps/tallowa-erp**
- `ai.py:55-57` - `STYLE`, the single base string every local system prompt is built
  on (`Use Australian English... Never invent a figure... Plain, direct language.`).
  No banned-word instruction (delve, leverage, unlock, seamless, game-changing).
- `ai.py:60-61` - `GROUNDED = STYLE + ...` - inherits the gap.
- `ai.py:1335-1338` - `ANALYST = STYLE + ...` - inherits the gap.
- Every one of the ~30 `feature(...)` registrations at `ai.py:1341-1478` passes
  `system=ANALYST + ...` or `system=GROUNDED + ...` (quality/AP/safety features from
  `ai.py:1485` on) - all inherit the gap through `STYLE`. This is where
  `finance-exceptions` (`ai.py:1430`) lives - the one instance that actually surfaced
  "unlock", in `static/cached/finance-exceptions.json` (fixed this pass, hand-edit only).
- `ai.py:2061` - the CTP commit inline system prompt (`ANALYST + "...capable-to-promise
  sales co-pilot..."`) - same gap, separate call site, not routed through `feature()`.
- `ai.py:3002` (`agent_events`, the legacy buffered `/api/ai/agent` path) - inline
  `ANALYST + "Answer the question for..."` - same gap.
- **Not covered by any local fix**: the live Ops Assistant path
  (`ai.py` `arag_agent_events` / `ai_ops_assistant`) does not use `STYLE`/`ANALYST` at
  all - it calls the external ARAG Retrieval Agent's own hosted session
  (`AGENT_HOST`/`AGENT_ID`, `ai.py:2351` area). That agent's system prompt lives on the
  ARAG dashboard/agent config, outside this repo - a `STYLE` fix here will not reach it.

**apps/racingwa-intelligence**
- `app.py:69` - `SYSTEM_PROMPTS` dict (`default`, `rules`, `briefing`, `guardrail`,
  `member_trainer`, `member_owner`, `member_punter`). Same class of gap: none of the
  seven prompts carries a banned-word instruction. No live instance of a banned word
  found there yet (checked during the nomenclature sweep) - the gap is structural, not
  yet realised.

## (b) The fix

Add one clause to the shared base string each app builds every prompt on, so it is
inherited everywhere instead of patched per-feature:
- Tallowa: append to `STYLE` (`ai.py:55-57`), e.g. "Never use delve, leverage, unlock,
  seamless or game-changing."
- Racing WA: no single shared base today - `SYSTEM_PROMPTS` entries are independent
  strings (`app.py:69`). Fix needs either a new shared prefix constant added to all
  seven, or the clause appended to each individually.
- Tallowa's ARAG-hosted Ops Assistant prompt: fix lives on the ARAG agent's own config
  (dashboard), not in this repo - separate ticket/owner.

## (c) Re-verification blast radius if changed

- Tallowa: changing `STYLE` changes model output for every regeneration through
  `scripts/cache_golden.py`. 49 cached goldens exist under `static/cached/*.json`; 47 of
  them are captured via `run_feature`/CTP paths that inherit `STYLE`
  (all except `ops-assistant.json` and `agent.json`, which are exempt because they run
  live agent traffic, not `predict_gen`/`STYLE`). A `STYLE` edit does not itself alter
  existing golden files (they are static captures), but any golden regenerated
  afterwards will reflect the new prompt and needs re-verification against the DoP
  banned-word check before it ships again.
- Racing WA: 25 goldens total (README, "Two workspaces" section) - `m-*` (member) and
  the stewards set, captured via `scripts/cache_golden.py` in that app. Same logic: a
  prompt-string edit only bites on next regeneration, and only the goldens for personas/
  routes using the edited prompt(s) need re-checking.
- Neither app's live retrieval-agent-driven paths (Tallowa Ops Assistant; any
  equivalent in Racing WA if one exists) are covered by a local prompt edit - those need
  checking/fixing at the agent config level, separately, and aren't part of this
  blast-radius count.

## (d) Status

Not actioned. GM to be briefed by lead as a follow-up (per 23 Jul 2026 ruling), not
folded into either app's current re-gate pass.
