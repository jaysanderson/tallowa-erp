# QM-07 Lot Traceability (Rev F)

Purpose: for any part lot, reach full trace - backward to raw-material lots and
forward to customer shipments - within fifteen minutes of a trace request.

## What is traceable
Every finished part lot is traceable. Raw-material lot control applies to inputs
flagged traceable in the part master: steel coil and bar, forged blanks, fasteners
on safety-critical joints, copper strip, bearing cartridges, elastomer bushings,
actuator motor and ECU sets. Consumables (coolant, packaging) are excluded.

## Lot control through the plant
1. Receiving records the supplier lot number against the purchase order and creates
   a raw lot record with quantity, certificate of analysis (CoA) reference and
   receipt date (SOP-REC-003).
2. Raw lots issue to production FIFO; a lot is never split across unlabelled bins.
3. Every production run records which raw lots it consumed, at issue time, by scan.
   No scan, no issue.
4. Each completed run produces one or more **finished lots** (lot numbers TC-A-xxxx
   for assemblies, TC-M-xxxx machined, TC-S-xxxx stamped). EPB-40 actuators are
   additionally serialised within the lot; the test rig writes each serial's
   end-of-line result.
5. Packing records which finished lots went into which shipment, against the
   customer purchase order line. Shipping labels carry the lot number.

## Trace requests
- **Backward trace** (finished lot to inputs): raw-material lots consumed with
  supplier, receipt date and CoA; the run, line, machines and date it was made.
- **Forward trace** (raw lot to customers): every run that consumed the raw lot,
  every finished lot those runs produced, current location of unshipped stock, and
  every shipment, customer purchase order and receiving plant for shipped stock.

Target: a complete forward trace in under fifteen minutes, exercised quarterly in
a mock containment drill. The 2026 first-quarter drill traced a bushing lot to
three customer shipments in eight minutes.

## Retention
Traceability records: fifteen years from ship date for safety-critical families,
ten years otherwise.
