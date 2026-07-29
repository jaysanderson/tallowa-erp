"""Generate the Tallowa Components quality / safety / work-instruction corpus.

Writes data/corpus/*.md - the synthetic document set the Knowledge Copilot,
playbooks and compliance features are grounded in. Tallowa Components is a
fictional Australian tier-1 automotive parts maker; every company, person,
part number and figure in here is invented.

Run:  ../../.venv/bin/python scripts/gen_corpus.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "corpus"

DOCS = {}

DOCS["qm-01-quality-manual.md"] = """# Tallowa Components Quality Manual - QM-01 (Rev H)

Scope: manufacture and dispatch of braking, chassis and e-mobility components at
the Bellbrook plant. Product families: Braking (EPB-40 park brake actuators,
caliper brackets), Chassis (control arms, steering knuckles, hub assemblies),
e-Mobility (high-voltage busbar sets, HV connector housings).

## Quality policy
Tallowa Components ships parts our customers can bolt straight onto a safety
system. Every safety-critical part can be traced from the customer's dock back to
its raw-material lot within fifteen minutes, and no lot ships with an open hold.

## Quality management system
The Tallowa QMS is structured on IATF 16949 and covers:

- Process approach: every production process runs to a released control plan and
  standard work instruction (SWI) with a named process owner.
- Risk-based thinking: PFMEA per part family and line; the top three risk priority
  numbers per line are reviewed at the monthly quality council.
- Control of documented information: SWIs, SOPs, control plans and procedures are
  controlled documents; only the revision in the plant register is used at a station.
- Customer-specific requirements (CSRs): each customer's CSR file is mapped to the
  QMS clause by clause; the CSR summary for each customer is a controlled document.
- Product safety: safety-critical characteristics are marked in the control plan;
  stations making them require current qualification and 100 per cent data capture.

## Key indicators and thresholds
- First time through (FTT): 96.5 per cent target per line, reviewed weekly.
- Customer PPM: under 25 PPM for safety-critical families (braking), under 50 PPM
  overall. A customer scorecard below target for two consecutive months triggers a
  formal improvement plan owned by the Quality Manager.
- Scrap plus rework: under 1.8 per cent of standard production cost; breaches
  raise a cost-exception review.
- Supplier PPM: over 350 PPM rolling quarter puts a raw-material supplier on a
  quality development plan.
- Internal audit: 12-month schedule covering every process; evidence current
  within 90 days; zero overdue major findings.

## Authority
The Plant Manager owns the QMS. The Quality Manager may stop any line, quarantine
any lot and hold any shipment without further approval. A hold is released only by
a quality inspector after the QM-04 disposition is complete and recorded.
"""

DOCS["qm-04-nonconforming-product.md"] = """# QM-04 Control of Nonconforming Product (Rev E)

Applies to any raw material, component, work-in-progress, finished part lot or
packed shipment at Bellbrook that fails a specification, inspection or test.

## Identification and quarantine
1. Tag the item or container with a red NONCONFORMING tag carrying the defect number.
2. Move it to quarantine (warehouse zone Q1). Line-side quarantine is not permitted
   beyond the end of the shift.
3. Record the defect in the defect register the same shift: part number, lot number,
   production run, machine, station, description, severity (minor, major, critical).

## Disposition
A quality inspector assigns one of four dispositions:
- **Rework** - to a nominated station with a rework instruction; reworked parts
  re-enter inspection at the gate that raised the defect. Rework on a safety-critical
  characteristic additionally requires 100 per cent re-test.
- **Scrap** - unrecoverable; scrap cost books to the production run.
- **Use as is** - minor cosmetic only; requires Quality Manager sign-off, and is
  never available for a safety-critical characteristic or a customer-visible surface
  the CSR controls.
- **Quarantine lot** - where a lot-level cause is suspected, the whole lot is held
  and the traceability procedure QM-07 is invoked; if any of the lot has shipped,
  QP-8D containment starts immediately.

## Severity rules
- **Critical**: a defect that could affect braking function, steering, structural
  integrity or high-voltage safety in the customer's vehicle. A critical defect
  found on shipped product triggers QP-8D and customer notification within 24 hours.
- **Major**: function, fit or durability affected; must not ship.
- **Minor**: cosmetic or non-functional; ships only with use-as-is disposition.

## Quality holds
A hold freezes a production run, a lot or a shipment. While open, the held item
cannot be issued, processed, packed, shipped or invoiced. Holds appear on the plant
dashboard and are reviewed daily. Target: no hold older than five working days
without a documented disposition.
"""

DOCS["qm-07-traceability.md"] = """# QM-07 Lot Traceability (Rev F)

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
"""

DOCS["qp-8d-containment.md"] = """# QP-8D Problem Solving, Containment and Customer Escapes (Rev D)

Invoked for any critical defect, any confirmed out-of-spec raw-material lot, any
customer escape (defective parts found at or beyond the customer's dock), or any
defect trend crossing its control limit. Follows the eight disciplines (8D).

## Timeline obligations
- D0-D3 (team formed, problem described, interim containment): within **24 hours**
  of the trigger. For a customer escape, the customer receives the containment
  statement inside the same 24 hours - most CSRs make this contractual.
- D4 (root cause verified): within 10 working days.
- D5-D6 (corrective action selected and implemented): within 20 working days.
- D7-D8 (prevent recurrence, close): within 30 working days.

## Containment (D3) for a suspect lot
1. Quarantine remaining suspect stock everywhere it sits: raw store, line-side,
   work-in-progress, finished store, packed-not-shipped.
2. Run the QM-07 trace. Backward: bound the suspect window by raw lot and run.
   Forward: list every finished lot, shipment, customer purchase order and
   receiving plant affected.
3. Sort or certify everything inside the window: unshipped stock is 100 per cent
   inspected before release; shipped lots are notified to the customer with
   quantities, lot numbers, ship dates and delivery references.
4. Notify the raw-material supplier the same day where a supplier lot is implicated;
   invoke the SQA-STD obligations (sorting support, 8D in 10 working days, costs).
5. The Quality Manager sets the containment level within 48 hours:
   - Level 1: certified-stock arrangement - customer works from sorted stock.
   - Level 2: customer-site sorting by Tallowa or a third party.
   - Level 3: recall of shipped lots for replacement, with a clean-point date and
     break-point lot numbers agreed with the customer.

## Records
Every 8D is registered with the defect number, the affected raw and finished lots
and the shipment list attached. Mock containment drills run quarterly.
"""

DOCS["qp-ppap.md"] = """# QP-PPAP Production Part Approval Process (Rev C)

No production shipment of a new or changed part without an approved PPAP.

## When PPAP is required
- New part or new customer part number.
- Engineering change affecting form, fit, function or a controlled characteristic.
- New, moved or substantially rebuilt tooling, die or production line.
- Process change (new machine, new heat-treat recipe, new plating chemistry).
- Sub-supplier or raw-material source change on a traceable input.
- Production restart after more than 12 months dormant.

## Submission levels
Default is Level 3 (full submission with samples) unless the customer's CSR says
otherwise. Ellandra Motors requires Level 3 on safety-critical parts and Level 2
elsewhere; aftermarket customers accept Level 1 (warrant only) for catalogue parts.

## The Tallowa PPAP file
Design records and change documents; process flow; PFMEA; control plan;
measurement system analysis (gauge R&R under 10 per cent on controlled
characteristics); dimensional results on 5 parts per cavity or stream; material
certs; performance and durability test results; initial process capability
(Cpk at least 1.67 on safety-critical characteristics, 1.33 on other controlled
characteristics, from at least 25 subgroups); appearance approval where the CSR
requires it; sample parts; and the part submission warrant (PSW).

## Rules
- The PSW is signed by the Quality Manager only after every element passes.
- Interim approval is an exception with an expiry date and an open-point plan; it
  is tracked on the compliance dashboard and never extended silently.
- A part shipped without current PPAP approval is a level A nonconformance
  against ourselves - it is treated exactly like a customer escape.
"""

DOCS["qp-spc-control-plans.md"] = """# QP-SPC Control Plans and Statistical Process Control (Rev D)

## Control plans
Every production process runs to a released control plan listing: the operation,
machine, characteristic, specification, gauge, sample size and frequency, control
method, and the reaction plan when a result trends or fails. Safety-critical
characteristics are flagged SC in the plan; SC data capture is 100 per cent and
automatic wherever the equipment allows.

## SPC rules at Bellbrook
- Variable data is charted X-bar and R at the frequency in the control plan.
- A point outside control limits, seven consecutive points one side of centre, or
  a run of six rising or falling: stop, contain the parts since the last good
  check, execute the reaction plan, record the event against the run.
- Capability: Cpk at least 1.67 on SC characteristics, at least 1.33 on other
  controlled characteristics, computed monthly per part and machine. A capability
  breach opens a quality investigation and may not be closed by widening limits.

## Reaction plan basics
Contain first (parts since last good check into quarantine), then correct the
process, then verify with five consecutive good subgroups before releasing the
line. All three steps are recorded; the shift quality inspector countersigns.

## Gauge control
Only gauges in calibration (CAL-01) may make an accept decision. Gauge R&R is
re-run after any gauge repair and at least every 24 months on SC gauges.
"""

DOCS["swi-a1-epb-actuator.md"] = """# SWI-A1-014 Standard Work - EPB-40 Actuator Final Assembly and Test (Rev G)

Station: Assembly line A-1, stations 30 to 60. Takt: 4.5 minutes.
Part: TC-30412 EPB-40 electric park brake actuator (customer part ELL-88412-B,
Ellandra Motors; safety-critical family).

## Operator requirements
Torque-critical qualification TQ-1 current at stations 40 and 50. One fitment
audit per operator per month.

## Materials (per unit, from the effective BOM)
Housing TC-31020 (machined, in-house lot); motor and ECU set TC-31110 (Larkspur
Electronics - traceable, lot scan mandatory); gear set TC-31140; spindle assembly
TC-31160; case screws TC-31210 M5 x 4 (Warrigal Fasteners - traceable, single
use); output fastener TC-31215 M8 x 1 (Warrigal Fasteners - traceable).

## Sequence
1. Station 30: scan the run number, housing lot and motor set lot. The station
   will not advance without every traceable scan (QM-07).
2. Station 40: seat gear set and spindle; grease dose 2.4 g plus or minus 0.2 g
   from the metered dispenser.
3. Station 50: fit case screws, DC tool sequence 6 Nm plus or minus 0.5 Nm, four
   screws, star order. Fit output fastener: **24 Nm plus or minus 2 Nm**. The tool
   records every trace curve against the unit serial. Apply the yellow witness mark.
4. Station 60: end-of-line rig - full apply-release cycle, current draw window
   1.9 to 2.6 A, actuation time under 900 ms, park-hold load test. The rig writes
   the serial's result; a fail routes the unit to the quarantine chute, not the tote.

## Quality checks
- An out-of-window torque locks the station and raises a defect automatically.
- EOL rig fail on braking function is a **critical** defect (QM-04).
- First-off and last-off of every shift go to the CMM room for the SC dimension set.

## Known failure mode
Torque retention loss on the output fastener traced to out-of-spec thread rolling
on a supplier fastener lot presents as a passed initial torque with a loosened
joint at re-test. Two or more units in a shift showing this pattern: stop, escalate
to quality the same shift, and place the fastener raw lot on hold - QP-8D
containment applies, including forward trace of every run that consumed the lot.
"""

DOCS["swi-m1-knuckle-machining.md"] = """# SWI-M1-006 Standard Work - Steering Knuckle CNC Machining (Rev E)

Station: Machining line M-1, cells 1 to 3. Cycle: 7.2 minutes per part.
Part: TC-20140 steering knuckle (customer part MAR-55140, Marran Automotive;
safety-critical family). Input: forged blank TC-11040 (Meander Castings -
traceable).

## Operator requirements
Machine induction MI-M1; in-process gauging authorisation; TQ-1 not required
(no torque joints at this line).

## Sequence
1. Scan the run number and the forged blank lot label before loading the first
   blank of each pallet (QM-07).
2. Load blank to fixture F-2014; verify datum contact lamps all green.
3. Op 10 mill datum faces; op 20 bore kingpin and hub bores; op 30 drill and tap
   caliper mounts; op 40 deburr and wash.
4. In-process gauge every 5th part: hub bore diameter 72.000 to 72.019 mm; kingpin
   bore taper per gauge card; caliper mount true position within 0.15 mm (SC).
5. Every part passes the crack-detection bench (eddy current) after washing - a
   reject is a **critical** defect, tag and quarantine.

## Tool life
Bore finishing insert: 60 parts, forced change by the cell controller. Tap set:
400 holes. A broken-tap part is scrap - never weld-repaired.

## SPC
Hub bore diameter is charted X-bar and R per QP-SPC; the reaction plan contains
parts back to the last good check. First-off after any insert change goes to the
CMM room before the cell resumes.
"""

DOCS["swi-s1-busbar-stamping.md"] = """# SWI-S1-011 Standard Work - HV Busbar Stamping and Plating (Rev D)

Stations: Stamping line S-1 press 2 (630 t), then Surface line P-1 plating cell.
Part: TC-70210 HV busbar set (customer part MAR-77210, Marran Automotive
e-mobility). Input: copper strip coil TC-12010 (Currajong Copper - traceable).

## Operator requirements
Press operation and die setting qualification PR-1 at S-1; plating and chemical
handling qualification PL-1 at P-1.

## Stamping
1. Scan run number and copper coil lot at coil load (QM-07).
2. Die TB-7021 with die protection sensors active - a die-protection fault stops
   the press; never bypass a sensor to clear a misfeed.
3. Burr height maximum 0.05 mm, checked every 30 minutes with the burr gauge;
   over-burr stops the run and quarantines parts back to the last good check.
4. Stamped blanks travel in covered totes - copper surface contamination causes
   plating rejects.

## Plating (P-1)
5. Tin plate to 3 to 6 microns, measured five parts per rack on the XRF gauge
   (SC characteristic - 100 per cent racks logged).
6. Bake per the line recipe; hydrogen embrittlement relief is not required for
   copper but the bake drives adhesion - never skip it to catch up a schedule.
7. Post-plate inspection under the bench lamp: blisters, bare patches or
   discolouration are major defects.

## Electrical test
8. Every busbar set passes the hipot bench: 3 kV DC, 60 seconds, leakage under
   1 mA, plus continuity across every leg. A hipot fail is a **critical** defect
   (high-voltage safety) - quarantine chute, QM-04 applies.
"""

DOCS["swi-h1-heat-treat.md"] = """# SWI-H1-004 Standard Work - Heat Treatment of Control Arm Pins (Rev C)

Station: Heat treatment line H-1, sealed quench furnace F-1.
Parts: TC-21150 control arm pin sets and TC-20140 knuckles (stress relieve cycle).

## Operator requirements
Heat-treat operation qualification HT-1. The furnace runs only with a qualified
operator on shift; recipes are locked and changed only through ECN-01.

## Sequence
1. Scan the run number and input lot for every basket; baskets carry lot tags
   through the whole cycle (QM-07).
2. Load per the basket map - never stack above the fill line; uneven packing
   causes soft spots.
3. Select the locked recipe for the part number. Carburise-harden cycle for pin
   sets: austenitise 860 degrees C, oil quench, temper 180 degrees C for 2 hours.
4. The furnace chart records the full cycle against the run number; a chart
   excursion outside the recipe band quarantines the whole basket set.
5. Hardness check per lot: three parts, 58 to 62 HRC case, core 32 to 40 HRC.
   Out-of-window hardness is a **major** defect; suspected mixed baskets escalate
   to quality - never re-sort by feel.
6. Post-temper, parts rest to below 40 degrees C before handling to the next line.

## Quench oil
Quench oil condition is sampled monthly (see the quench oil SDS summary for
handling). Water contamination above 0.1 per cent takes the furnace out of
service - a wet quench is a fire and a scrapped basket.
"""

DOCS["sop-line-startup.md"] = """# SOP-OPS-001 Line Start-up and Pre-shift Checks (Rev F)

Applies to every production line at Bellbrook at the start of every shift.

## Line lead pre-shift routine (before first part)
1. Walk the line: guards closed, e-stops reset and tested at first and last
   station, walkways clear, no red-tagged equipment inside the line envelope.
2. Confirm the shift roster against station qualifications - every torque-critical,
   press, heat-treat and plating station must be crewed by a currently qualified
   operator (TRN-002). Unqualified crewing is a stop condition.
3. Check andon and station screens are live; DC torque tools completed their
   overnight self-test; presses completed the die-protection check cycle.
4. Review open quality holds affecting the line; confirm held runs and lots are
   physically blocked from the sequence.
5. Confirm line-side material against the first four hours of the schedule; raise
   any shortage to material control before start, not after.
6. Record the start-up check in the line log; the line may not release its first
   part until the check is recorded.

## Safety non-negotiables
- Lockout-tagout per LOTO-01 for any intervention past a guard.
- No phone use inside the line envelope.
- PPE per the area matrix at all times; visitors only with an access briefing.

## Handover
Outgoing line leads record: parts completed, stoppages over 5 minutes with cause,
open defects raised, tooling concerns. The incoming lead reads the log before
their walk.
"""

DOCS["sop-final-inspection-despatch.md"] = """# SOP-QG-002 Final Inspection, Packing and Despatch (Rev E)

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
"""

DOCS["sop-receiving-inspection.md"] = """# SOP-REC-003 Receiving and Incoming Inspection (Rev E)

Applies to all production material arriving at the Bellbrook warehouse.

## Receipt
1. Check the delivery against the purchase order: part number, quantity, container
   count. Over-delivery beyond 5 per cent is refused.
2. For traceable inputs: verify each container carries the supplier lot label and
   the shipment carries a CoA per lot (SQA-STD). Missing CoA: the lot goes to
   quarantine Q1, a supplier nonconformance is raised, and material control is
   notified - the lot is not available to production.
3. Book the receipt; stock and raw lot records update on booking.

## Incoming inspection
- Skip-lot inspection applies to suppliers in good standing: 1 lot in 5 sampled
  to the incoming plan for that part.
- Suppliers on a quality development plan: every lot sampled until released.
- Steel and copper: mill cert values checked against specification every lot;
  fasteners on safety-critical joints: thread gauge plus hardness sample every lot,
  and a thread-rolling profile check on the sampled lots.
- Sample failures quarantine the lot and raise a defect; the supplier is notified
  within 24 hours.

## Quarantine rules
Zone Q1 is physically segregated racking with red location labels. Quarantined
stock is system-blocked - it cannot be picked, issued or counted as available.
Only a quality inspector can release from Q1, with the release reason recorded.

## FIFO
All lots issue first-in-first-out. The system enforces FIFO for traceable inputs;
a FIFO override needs material control approval and lands in the audit trail.
"""

DOCS["safety-loto-01.md"] = """# LOTO-01 Lockout-Tagout Procedure (Rev D)

Applies to any energy isolation at Bellbrook: electrical, pneumatic, hydraulic,
thermal, gravity and stored spring energy.

## When LOTO is required
Any body part past a fixed guard; any work on presses, dies, robot cells,
conveyors, the heat-treat furnace and quench system, plating line pumps and
rectifiers, or compactors. Clearing a simple misfeed from outside the guard with
the machine in manual inch mode is not LOTO work; anything more is.

## The six steps
1. Notify the line lead and affected operators.
2. Shut down by the normal stop.
3. Isolate every energy source at its isolation point.
4. Apply your personal lock and tag - one lock per person, every person on the
   job locks on. Group lock boxes are used for press and furnace work.
5. Release stored energy: bleed air, block raised rams and die sets, allow thermal
   drain-down on furnace work, discharge where required.
6. Verify: attempt a start at the controls; test for dead where electrical.

## Rules
- Only the person who applied a lock removes it. A lock left by an absent worker
  is removed only by the site manager after a documented contact attempt.
- Presses additionally require die safety blocks before any hand enters the die
  space - no exception, even with the ram locked.
- Furnace entry is confined-space work on top of LOTO: permit, gas test, attendant.
- Plating line: isolate rectifiers and dose pumps; chemical lines are bled to the
  catch tank before a joint is broken (see the process chemical SDS summaries).

Violations are a stop-work matter and are reported to the site manager the same day.
"""

DOCS["safety-ppe-matrix.md"] = """# SAF-PPE-002 PPE Area Matrix (Rev D)

Minimum PPE by area at Bellbrook. Task-specific SWIs may add to this.

## All production areas (base requirement)
Safety glasses, safety footwear, hi-vis vest or shirt, no rings or exposed metal
jewellery, long hair contained.

## Area additions
- **Stamping S-1**: hearing protection (mandatory zone, 89 dBA), cut-resistant
  gloves level C for blank and strip handling, die-setter helmet during die changes.
- **Machining M-1 and M-2**: no gloves at rotating spindles; coolant-resistant
  apron at wash stations; mist zone respirator per the health monitoring plan.
- **Heat treatment H-1**: heat-rated gloves and gauntlets at furnace and quench,
  face shield at the quench station, no synthetic outer layers inside the furnace
  aisle.
- **Surface coating P-1**: chemical splash goggles and face shield at dosing,
  chemical-rated gloves and apron in the plating aisle, antistatic footwear in the
  solvent store.
- **Assembly A-1 and A-2**: knuckle-protection gloves; hearing protection within
  the EOL rig enclosure.
- **Quality and CMM room**: base requirement only.
- **Warehouse and yard**: hi-vis, forklift zones pedestrian-segregated, licence
  per the certification matrix.

## Visitors and contractors
Escorted visitors: glasses, footwear covers or safety footwear, hi-vis.
Contractors follow the contractor induction plus the area matrix; a plant access
briefing is issued before first entry (SEC-04).
"""

DOCS["sds-tm-q60-quench-oil.md"] = """# SDS Summary - TM-Q60 Quench Oil (Rev B)

Product: TM-Q60 accelerated quench oil, heat-treat line H-1. Internal summary;
full manufacturer SDS in the document register.

## Hazards
- Combustible liquid (flash point 178 degrees C). A wet quench (water above 0.1
  per cent) can cause violent oil expulsion and fire - see SWI-H1-004.
- Mist and fume from hot oil irritate airways; hot oil causes severe burns.
- Slippery underfoot; harmful to aquatic life - never to stormwater.

## Handling
Heat-rated gloves and face shield at the quench station. Top-ups only through the
closed transfer pump with the furnace at standby. Monthly condition sample through
the sample valve, never by dipping.

## Spill response
Small spill: absorbent socks from the H-1 spill station; used absorbents to the
hydrocarbon waste drum. Large spill or any spill reaching a drain: evacuate the
aisle, bund the drains with mats, call the emergency number.

## Fire
Do not use water on a quench oil fire. The furnace hood suppression handles the
quench tank; hand extinguishers in the aisle are foam and CO2.

## First aid
- Hot oil burn: cool with running water 20 minutes, do not remove adhered
  clothing, medical attention.
- Mist exposure with symptoms: fresh air, report to first aid.

## Storage
Bunded store, below 40 degrees C, away from oxidisers. Waste oil is a licensed
disposal stream.
"""

DOCS["sds-tm-p410-plating-cleaner.md"] = """# SDS Summary - TM-P410 Alkaline Plating Cleaner (Rev B)

Product: TM-P410 alkaline soak cleaner, surface line P-1 pre-treatment. Internal
summary; full manufacturer SDS in the document register.

## Hazards
- Corrosive to skin and eyes (sodium hydroxide base). Serious eye damage risk at
  dosing and filter changes.
- Reacts exothermically with acids - never dose into or after the acid dip tank
  circuit; a mixed transfer line is a scald and splash event.
- Attacks aluminium fittings - steel and poly only in this circuit.

## Handling
Chemical splash goggles plus face shield, chemical-rated gloves and apron at
dosing. Dose through the closed metering pump only; drum tipping is not permitted.
Eyewash and drench shower at the P-1 dosing bay are flushed weekly.

## Spill response
Bund the spill with the caustic spill kit (P-1 station), neutralise with the
citric granules, collect to the labelled caustic waste drum. Any splash on a
person overrides the spill: drench first, contain second.

## First aid
- Skin: drench shower, remove contaminated clothing, rinse 20 minutes, medical
  attention for any burn.
- Eyes: eyewash 20 minutes minimum, urgent medical attention - do not delay for
  transport, continue rinsing en route.

## Storage
Segregated from acids in the bunded chemical store; below 30 degrees C.
"""

DOCS["sqa-std-supplier-quality.md"] = """# SQA-STD Supplier Quality Agreement - Standard Terms (Rev F)

Applies to every raw-material and component supplier to Tallowa Components unless
a negotiated agreement supersedes it.

## Part and material approval
No production shipment before approval: dimensional and material report, mill or
material certs, process capability (Cpk at least 1.33 on designated
characteristics), and an approved control plan. Changes to process, tooling,
sub-supplier or site require prior written approval - an unapproved change
discovered in product is a level A nonconformance.

## Lot requirements
- Every shipment of a traceable input carries the supplier lot number on each
  container label and a certificate of analysis (CoA) per lot.
- Maximum one lot per container; mixed-lot containers are rejected at receiving.
- Lot size must not exceed one production week at the supplier.
- Fasteners for safety-critical joints additionally certify thread-rolling
  process parameters per lot on the CoA.

## Performance expectations
- Delivered quality: under 350 PPM rolling quarter.
- Delivery: 98 per cent on-time-in-full against the confirmed date.
- A missed level: quality development plan; two consecutive missed quarters:
  new-business hold.

## Nonconformance and escapes
On a confirmed lot escape the supplier: responds with containment within 24
hours, supports sorting at Tallowa or at our customers, returns a verified 8D
within 10 working days, and bears sorting cost, replacement freight and any
customer campaign cost their lot caused (QP-8D). Chargebacks are itemised on a
supplier debit note.

## Audit rights
Tallowa may audit the supplier's process with five working days notice, and
without notice following a critical escape.
"""

DOCS["cal-01-calibration.md"] = """# CAL-01 Calibration of Measurement and Test Equipment (Rev E)

Covers every device at Bellbrook whose reading accepts or rejects product.

## Intervals
- DC torque tools (station-mounted): monthly verification on the joint simulator,
  annual full calibration.
- Hand click wrenches: quarterly verification; annual calibration; a dropped
  wrench is re-verified before further use.
- CMMs (2 machines, quality room): annual external calibration (accredited
  laboratory), monthly artefact check with the reference sphere and step gauge.
- EPB end-of-line test rigs: annual vendor calibration, weekly golden-unit run -
  the golden actuator's results must sit inside its control band.
- Hipot benches: annual external calibration; daily resistor-standard check.
- XRF plating gauges: six-monthly calibration against reference foils.
- Hardness testers: annual calibration; daily test-block check.
- Eddy-current crack bench: six-monthly calibration; per-shift reference-flaw check.
- Furnace thermocouples and chart loggers: system accuracy test quarterly,
  temperature uniformity survey annually.

## Rules
- Every device carries a calibration label: asset number, date done, date due.
  A device past due is withdrawn at once - using an overdue device is a stop-work
  quality event.
- Results are recorded in the equipment register against the asset number.
- An out-of-tolerance result at calibration triggers an impact review: every
  acceptance decision made by that device since its last passed check is
  assessed; affected lots are handled under QM-04, including shipped lots.

## Responsibility
Maintenance and tooling owns the schedule; quality engineering owns impact
reviews. The calibration board is reviewed weekly - target: zero overdue devices,
nothing within 7 days of due unbooked.
"""

DOCS["trn-002-cert-matrix.md"] = """# TRN-002 Training and Certification Matrix (Rev G)

Qualification is a condition of station assignment. The roster check at line
start-up (SOP-OPS-001) enforces this every shift.

## Certifications and renewal
- **TQ-1 Torque-critical qualification**: required at every torque-critical
  assembly station (EPB output fastener, case screw sequences, chassis joint
  rigs). Renew every 12 months: practical assessment on the joint simulator plus
  three consecutive passed fitment audits.
- **PR-1 Press operation and die setting**: stamping line presses and die
  changes. Renew every 24 months; includes die-protection systems and die safety
  blocks.
- **HT-1 Heat-treat operation**: furnace and quench operation. Renew every 24
  months; includes wet-quench response and chart interpretation.
- **PL-1 Plating and chemical handling**: dosing, bath control and filter
  changes at P-1. Renew every 12 months; includes the caustic and acid SDS set.
- **CMM-1 CMM operation**: program execution and first-off release. Renew every
  24 months.
- **WC-2 Weld certification**: manual respot and weld inspection at the control
  arm cell. Renew every 24 months by destructive-test coupon assessment.
- **MI-x Machine inductions**: per line (MI-S1, MI-M1, MI-M2, MI-H1, MI-P1,
  MI-A1, MI-A2). No renewal, but retraining after any 6-month absence.
- **FL Forklift licence**: statutory high-risk work licence, verified on file;
  yard induction annually.
- **QI Quality inspector authorisation**: issued by the Quality Manager;
  authorises defect disposition, hold release and lot release; reviewed annually.

## Expiry management
Expiries within 60 days appear on the workforce planning report. An expired
certification removes the operator from eligible crewing the day it lapses -
there is no grace period on TQ-1, HT-1 or PL-1.

## Records
Certification records: holder, issue date, expiry, assessor, evidence reference -
retained for the employment period plus seven years.
"""

DOCS["ecn-01-engineering-change.md"] = """# ECN-01 Engineering Change Procedure (Rev D)

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
"""

DOCS["sec-04-plant-access.md"] = """# SEC-04 Plant Access and Visitor Briefing (Rev C)

Issued to every visitor and contractor before first entry to the Bellbrook
production floor.

## Access basics
- Sign in at main reception; wear the issued pass visibly at all times.
- Visitors are escorted at all times. Contractors may work unescorted only within
  their permit area after contractor induction.
- Pedestrian routes are the green walkways; never step outside them on the floor.
  Forklift zones are marked in yellow hatching - pedestrians give way.

## PPE
Minimum on the floor: safety glasses, safety footwear (or covers for short
escorted visits), hi-vis. Area-specific PPE per the PPE matrix - your escort
carries it. The plating aisle and furnace aisle are no-entry for visitors.

## Rules on the floor
- Photography only with a signed permit from the site manager.
- No phone use inside line envelopes; take calls in the marked refuge bays.
- Never reach past a guard, into a press, or under raised tooling - for any reason.
- Emergency: continuous siren means evacuate; follow the green exit arrows to the
  assembly area at the main car park; your escort accounts for you.
- Andon towers: flashing red at a station means stay clear of that station.

## Contractor energy work
Any work on plant equipment requires a permit to work plus LOTO-01 lockout with
the contractor's own locks. The permit issuer walks the isolation with the
contractor before work starts.
"""

DOCS["csr-ellandra-summary.md"] = """# CSR-ELL Customer-Specific Requirements Summary - Ellandra Motors (Rev D)

Controlled summary of Ellandra Motors' supplier requirements as they apply to
Tallowa Components. The customer's full manual is held in the document register.

## Commercial and delivery
- Releases arrive by EDI weekly with a firm 2-week window and a 6-week forecast;
  firm quantities are contractual. Short shipment against a firm release requires
  same-day notification to the Ellandra plant scheduler.
- On-time-in-full target 98 per cent measured at the Ellandra dock; below target
  two consecutive months triggers a supplier review meeting.
- Premium freight caused by Tallowa is at Tallowa's cost and is reported monthly
  whether or not Ellandra noticed.

## Quality
- PPM target: 15 PPM on braking family parts, 35 PPM other. Measured on Ellandra's
  receiving and line-fallout data, reconciled monthly.
- PPAP Level 3 on safety-critical parts (EPB-40 actuator family), Level 2
  otherwise. Interim approvals expire at 90 days, no silent extensions.
- 8D: containment statement within 24 hours of notification, full verified 8D
  within 10 working days, evidence of read-across to sibling parts.
- Safety-critical characteristics: 100 per cent data capture with serial-level
  retrieval on request; records retained fifteen years.

## Labelling and logistics
- Labels per Ellandra spec ELL-LBL-7: customer part number, quantity, Tallowa lot
  number, ship date, purchase order reference on every container.
- One lot per container; advance shipping notice at truck departure.

## Escalation contacts
Named contacts are maintained in the customer record - scheduler, SQE (supplier
quality engineer) and buyer. The SQE receives all 8D communication.
"""

DOCS["wty-01-field-returns.md"] = """# WTY-01 Warranty and Field Return Feedback (Rev C)

How customer plant fallout and field warranty data return to Bellbrook and feed
quality action.

## Customer claims
OEM customers submit claims with: customer part number, quantity, Tallowa lot
number where known, defect description, and returned parts where retained. Claims
are coded to the plant defect taxonomy so field failures and in-plant defects
Pareto on the same axes, and every confirmed claim updates that customer's PPM.

## Part return and teardown
Safety-relevant returns (braking family, HV parts) come back to the plant within
10 working days for teardown by quality engineering. Teardown findings are
recorded against the part number and, through traceability, against the
production run and raw-material lot where a lot cause is suspected - a confirmed
lot cause invokes QP-8D containment including forward trace of the remaining lot.

## Trend rules
- Any safety-relevant claim: individual engineering review within 5 working days.
- Claim rate for a part exceeding three times its 12-month baseline in a month:
  automatic quality investigation.
- The emerging-issue watchlist is reviewed weekly by quality engineering; every
  item carries an owner and a due date.

## Feedback into the plant
Confirmed root causes update the PFMEA, the affected standard work instruction,
the control plan and, where relevant, incoming inspection plans. The monthly
quality council reviews warranty cost by product family and the top five Paretos,
in-plant and field side by side.
"""

DOCS["fin-ap-authorisation-matrix.md"] = """# FIN-AP Accounts Payable Authorisation Matrix (Rev B)

Who may correct and re-post a failed vendor invoice at Bellbrook, and under what
authority. Applies to every posting failure raised in the AP queue, whatever the
error code.

## FIN-AP-01 Three-way match variance
A purchase-order-referenced invoice must match the PO line and the goods receipt
within a 2 per cent quantity/price tolerance. Outside tolerance, the AP clerk may
adjust and re-post once the buyer confirms the correct figure in writing. Where
no goods receipt exists yet, the AP clerk may hold the invoice pending receipt but
may not post it early.

## FIN-AP-02 Duplicate invoice handling
An invoice number matching or closely resembling one already posted this quarter
is held automatically. The AP clerk may clear the flag once the prior invoice is
checked and the new one confirmed genuine; a confirmed duplicate is rejected and
the vendor notified, never silently discarded.

## FIN-AP-03 Vendor master data changes and cost-centre correction
A vendor master field (cost centre, GL mapping, payment terms) may be corrected
by the AP clerk within their standing delegation, provided every invoice the
correction affects is individually under the AP clerk per-invoice approval limit
(see the limit table below). One vendor-master correction may clear every failed
invoice from that vendor sharing the same cause - this is the intended behaviour,
not a control gap, provided each affected invoice is logged individually with the
policy reference and the correcting user at the time it is reposted. Any invoice
in the batch that exceeds the per-invoice limit is excluded and escalated to the
controller; the rest of the batch proceeds.

## FIN-AP-04 GST and rounding corrections
GST code mismatches and rounding-tolerance breaches against the PO/GST
calculation are within the AP clerk's standing delegation to correct and re-post,
with no additional sign-off required.

## FIN-AP-05 Banking detail changes - segregation of duties
Any change to a vendor's bank details triggers an automatic payment hold pending
independent verification by treasury (a callback to a previously known contact,
never the number on the change notice). This hold cannot be cleared by the AP
clerk regardless of invoice amount or vendor history - it is a segregation-of-
duties control against payment-diversion fraud, not a data-quality check, and
sits outside every other authorisation tier in this matrix.

## Approval and delegation limits
- AP clerk: corrects and re-posts any invoice up to $5,000 per invoice under
  FIN-AP-01 to FIN-AP-04, with no cap on the number of invoices in one batch
  provided each is individually within the limit.
- Above $5,000 per invoice, or any FIN-AP-05 banking-detail hold at any amount:
  controller sign-off required - the AP clerk escalates rather than actioning it.
- Every correction, whatever the authority level, is logged to the audit trail
  with the policy reference, the amount, and the approving user - this is what
  the controller and external audit review at period close.
"""

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.md"):
        f.unlink()
    for name, text in DOCS.items():
        (OUT / name).write_text(text.strip() + "\n")
    print(f"wrote {len(DOCS)} corpus docs to {OUT}")


if __name__ == "__main__":
    main()
