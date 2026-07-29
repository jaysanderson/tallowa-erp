# SOP-REC-003 Receiving and Incoming Inspection (Rev E)

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
