# ECN-01 Engineering Change Procedure (Rev D)

Controls every change to part design, BOM content, process recipe, tooling or
supplier source at Bellbrook.

## Change classes
- **Class 1 (safety or customer-approval relevant)**: any change touching a
  safety-critical characteristic, a customer-controlled dimension, material
  specification, heat-treat or plating recipe, or a traceable input's source.
  Requires verification evidence, PFMEA and control plan update, customer
  notification or approval where the CSR requires it, and PPAP per QP-PPAP.
  Plant Manager and Quality Manager approve before implementation.
- **Class 2 (form-fit-function internal)**: process or BOM change without
  customer-visible effect. Process engineering and quality approval; PPAP need
  assessed against QP-PPAP.
- **Class 3 (documentation)**: correction with no physical change; document
  owner approval.

## BOM discipline
The BOM is the single source of truth for what a part contains. An input may not
be consumed that is not on the effective BOM revision for that run date.
Deviations (temporary alternate inputs) require a time-boxed concession with
quality approval, recorded against the affected runs and lots.

## Cut-in records
Every class 1 and 2 change records: change number, description, reason, affected
part numbers, old and new revision, cut-in run or lot, and verification evidence.
Customer containments and field actions rely on cut-in records to bound a
campaign - keep them exact.
