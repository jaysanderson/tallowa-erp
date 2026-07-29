# SWI-M1-006 Standard Work - Steering Knuckle CNC Machining (Rev E)

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
