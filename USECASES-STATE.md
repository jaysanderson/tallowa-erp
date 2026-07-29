# Three-use-case build - state

Spec: sources/three-use-cases/"3 use cases.pptx" (6 slides + notes extracted 2026-07-21).
Extends the existing gated Tallowa ERP (apps/tallowa-erp) - do NOT rebuild, do NOT break
gated features, do NOT redeploy (lead redeploys after QA).

## Design decisions (locked before coding)

**UC1 - Quality alert / FPY breach -> 8D root cause** (persona: Linda -> played by the
existing quality@ login, Priya Narayan; no new user needed)
- New overnight FPY-breach scenario on line A-2, part TC-70230 (HV connector housing,
  moulded at station A-2/60 from resin TC-14010) - separate from the existing WF-2261
  fastener hero so the two containment stories don't collide.
- New raw lot (first use on this line) + new machine INJ-01 (injection moulding, A-2)
  with overdue PM + a trainee-supervisor shift note -> three correlated suspects.
- Root-cause suspects: new `fpy-root-cause` AI feature (hybrid, computed ranking from
  real seeded defects/machine/shift data, cites QP-8D containment procedure).
- Containment ("contain the bad lot"): REUSE existing generic /api/ai/lot-trace (already
  lot-agnostic) on the new resin lot + a new POST /api/holds/ (create-hold endpoint,
  quality-role-gated - did not exist before, only release existed) to place the
  containment hold live.
- 8D auto-draft: new POST /api/ai/8d-draft (hybrid, grounded in the suspects + trace
  digest, cites QP-8D) + new `eight_d_reports` table + POST /api/8d-reports/ (quality
  role) to save/approve the edited draft - mirrors the existing playbook save pattern.

**UC2 - AP invoice posting-failure auto-fix** (persona: Maria -> new login
ap@tallowacomponents.com.au, role "finance", name Maria Costa)
- New `ap_invoices` table (vendor bills - distinct from the existing customer AR
  `invoices` table) + `suppliers.cost_center` column + setting `ap_clerk_approval_limit`.
- 23 seeded AP invoices, all status=failed: 9 share one root cause (vendor-master cost
  center CC-410, closed, on Coalcliff Steel + Meander Castings - both should be CC-430),
  13 have distinct one-off error codes Maria can fix individually, 1 (BANK-VER) genuinely
  needs treasury/controller sign-off beyond her authority - stays stuck (honest limit,
  matches deck's "22 of 23 resolved").
- Deterministic error-code catalogue (AP_ERROR_CODES dict in ai.py - fix instructions and
  authority thresholds are NOT LLM-invented) + new KB corpus doc
  fin-ap-authorisation-matrix.md for the policy citation.
- Flow: POST /api/ai/ap-error-explain (hybrid, plain-English + fix + cited policy) ->
  GET /api/ap-invoices/{ap_no}/similar (deterministic shared-root-cause group + approval
  limit check) -> POST /api/ai/ap-batch-fix (hybrid narrative proposing the batch) ->
  POST /api/ap-invoices/batch-fix (finance role, corrects the vendor master cost center +
  posts all 9 + logs one audit row per invoice with its policy citation).

**UC3 - Capable-to-promise (CTP) sales co-pilot** (persona: Hans -> new login
sales@tallowacomponents.com.au, role "sales", name Nate Ferris)
- Seed a real shortage: TC-13080 (busbar insulation moulding, feeds TC-70210) stock cut
  from 3300 to 830 -> exactly 170 short against a 250-unit TC-70210 order (250*4=1000
  needed). New PO-2252 (Kurrajong Polymers, qty 2600, expected in 11 days) is the binding
  incoming supply - the binding constraint. The "big order behind it" is the ALREADY
  seeded RUN-1100 (in-progress, 820 units, same component) - no new seed needed for that,
  reused as-is.
- New POST /api/ai/ctp-commit (custom endpoint like lot-trace): computes shortfall,
  binding component + PO date, production lead time from REAL historical run-rate data
  (not fabricated), commit date, alternative dates with risk, and (if body.expedite=true)
  re-runs with the PO pulled in and a real conflict check against RUN-1100's remaining
  need for the same component.
- Approval split (the RBAC story): sales role can create+confirm the draft sales order
  (extended so_approve to allow role "sales"); a NEW `expedite_requests` table + POST
  /api/expedite-requests/ (propose, sales role) + POST /api/expedite-requests/{id}/approve
  (plant_manager/supervisor/admin ONLY - "the production planner approves anything that
  touches the schedule") pulls PO-2252's expected_date in.

## Checkpoints
- [x] Schema + seed changes (database.py, seed_db.py) - verified live: RUN-1111 FPY
      84.29%, resin defects 47/66 (71%), machine defects 19/66 (29%), TC-13080 stock
      830 (170 short against a 250-unit order), PO-2252 binding constraint, 23 AP
      invoices (9 GL-4102 group + 13 individual + 1 BANK-VER escalation)
- [x] erp.py: POST /api/holds/ (create), AP_ERROR_CODES catalogue + /ap-invoices/*
      (list/detail/similar/batch-fix), /expedite-requests/* (propose/approve, RBAC
      split from so_approve), so_approve extended to allow role "sales", /8d-reports/*
- [x] ai.py: dig_fpy_root_cause + "fpy-root-cause" feature, POST /ai/8d-draft (grounded
      in LIVE hold status, not assumed), dig_ap_error_explain + "ap-error-explain",
      dig_ap_batch_fix + "ap-batch-fix", compute_ctp + POST /ai/ctp-commit (deterministic
      date-beats/misses verdict computed in Python, not left to the model - caught and
      fixed a real LLM date-comparison error during testing)
- [x] Corpus doc fin-ap-authorisation-matrix.md (FIN-AP-01..05) generated + uploaded,
      25/25 resources PROCESSED, citations confirmed live
- [x] Frontend: quality.html (ranked suspects panel, contain-the-lot action, 8D
      draft/edit/approve), new /ap-invoices page, new /ctp page (with a
      production-planner "pending schedule changes" panel closing the RBAC loop),
      nav links added. Zero console/page errors across all three flows (Playwright).
- [x] Goldens cached for all 43 existing + 6 new features (fpy-root-cause, 8d-draft,
      ap-error-explain, ap-batch-fix, ctp-commit, ctp-commit-expedite)
- [x] Full smoke suite re-run after golden refresh: MCP 29/29 PASS (120 tools now,
      was 105), new scripts/smoke_usecases.py 27/27 PASS
- [x] DoP walk (A-gates, S, V, T2) + README "Three use-case demo script" section
- [x] Report to lead

STATUS: DONE. All three use cases demoable live, end to end, gated per DoP. See the
final message to the lead for the full report.

## QA fix pass (2026-07-21, same session)
Three findings from the lead's QA gate, all fixed and re-verified live before this
handoff:
1. **MAJOR - CTP conflict check undercounted.** compute_ctp()'s conflict query
   excluded `in_progress` runs, so RUN-1100's real remaining demand (1,720 units of
   the same component) was invisible and the what-if wrongly reported "no conflict".
   Fixed: query now includes `in_progress` alongside `released`/`planned`, netted
   against material already issued to that run (run_materials), so a run that
   already drew its material is not double-counted. Live result now: headroom -570,
   conflict=True, against RUN-1100 (SO-3433, Marran's OWN other order) and RUN-1105
   (SO-3434, Korrawin) - exactly the number QA predicted. This is a genuine
   improvement, not a downgrade: the co-pilot now demonstrates honest-failure
   surfacing (a named excellence marker) instead of a false "all clear". README UC3
   narrative and scripts/smoke_usecases.py rewritten to match the honest outcome.
2. **MAJOR - AP resolution count.** Was 21 of 23 (2 escalations: AP-8823 BANK-VER +
   AP-8813 over the $5,000 clerk limit at $5,200). GM's deck says 22 of 23. Fixed by
   trimming AP-8813 from $5,200 to $4,950 (still individually distinct, 3WM-FAIL,
   just now within the clerk's authority) - the ONLY honest escalation left is
   AP-8823 (treasury BANK-VER), matching the deck exactly. Live-verified: 22 within
   authority, 1 escalated.
3. **MINOR (V1) - US spelling.** "cost center" -> "cost centre" throughout
   AP_ERROR_CODES (erp.py), the ap-batch-fix audit log text, and
   data/corpus/fin-ap-authorisation-matrix.md. KB doc deleted and re-uploaded
   (old rid ffdebf89..., new rid 2cfefdf0...), confirmed PROCESSED, live grounded
   answers now say "cost centre" (verified via a new smoke_usecases.py assertion).

Re-verified after all three fixes: scripts/smoke_usecases.py 30/30 PASS (added 6 new
assertions for the fixes), scripts/smoke_mcp.py 29/29 PASS, all 49 goldens re-cached
live. Still NOT deployed - the lead redeploys after their own spot-check.

All three use-case flows work end-to-end live (verified via direct API calls and
Playwright UI clicks): UC1 ranked suspects -> contain -> 8D draft -> approve; UC2
explain -> similar group -> batch-fix narrative -> approve & post (9 invoices,
$23,782.80, policy FIN-AP-03); UC3 commit -> what-if expedite -> propose (draft SO +
expedite request) -> two independent approvals (sales confirms the order immediately,
production planner approves the schedule change separately/later - verified sales
CANNOT approve the expedite request, 403).
