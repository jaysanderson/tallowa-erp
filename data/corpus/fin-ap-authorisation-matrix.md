# FIN-AP Accounts Payable Authorisation Matrix (Rev B)

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
