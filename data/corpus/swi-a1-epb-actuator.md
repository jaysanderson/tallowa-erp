# SWI-A1-014 Standard Work - EPB-40 Actuator Final Assembly and Test (Rev G)

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
