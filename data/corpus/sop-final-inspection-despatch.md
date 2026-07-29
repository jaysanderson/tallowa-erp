# SOP-QG-002 Final Inspection, Packing and Despatch (Rev E)

Every finished lot passes final inspection before it may be packed, and every
shipment passes the despatch gate before it leaves Bellbrook. The gate is owned
by quality inspection, not by production or logistics.

## Final inspection (per finished lot)
1. Verify the run's quality record is complete: SPC charts closed with no open
   reaction plan, SC data capture complete, first-off and last-off CMM results
   passed, EOL test results present for serialised parts.
2. Sample the lot to the part's outgoing inspection plan; braking-family
   assemblies additionally re-test a sample of 3 serials on the EOL rig.
3. Any failure quarantines the whole lot (QM-04); no partial release.
4. Passed lots receive the green release label: part number, lot number, quantity,
   inspector stamp, date.

## Packing and labelling
- One lot per container unless the customer's CSR allows mixed-lot packing (none
  of our OEM customers do).
- Labels to the customer's specification: customer part number, quantity, lot
  number, ship date, and the customer purchase order reference on every container.
- A label mismatch found at despatch is a major defect and re-checks the whole
  staging lane.

## Despatch gate
1. Match containers against the shipment list: customer order, part, lot, quantity.
2. Confirm no open hold touches any lot on the shipment - the system blocks a
   held lot, and the gate checks anyway.
3. Advance shipping notice transmitted at truck departure; the invoice raises
   from the shipment, never before it.

## Records
Despatch records tie shipment, customer purchase order, lots and quantities - the
forward-trace chain in QM-07 depends on this record being exact.
