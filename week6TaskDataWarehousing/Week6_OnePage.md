# Week 6 — Data Quality and Query Optimization

## Method and result

I used Python with pandas to read the three source files, normalize them to the eight-column shipment contract, and keep source file and line references. The marine dates were parsed as `dd/MM/yyyy`; the rail sheet was read below its two title rows, its stripped `RL-` prefix restored, and tonnes converted to kilograms; road IDs/statuses were normalized and the blank line and `TOTAL` footer were retained through extraction. I rejected rows with unparseable dates, unusable weights, or missing shipment identifiers, and removed duplicate shipment IDs only after trim and uppercase. I conformed customer aliases to 40 businesses, created a 90-day Jan–Mar date dimension, and wrote the fact and reject outputs.

The supplied files do not reconcile to the assignment’s stated counts. The road CSV contains 710 parsed data records: 706 records with IDs, three blank-ID records (including the empty line), and one `TOTAL` footer. The brief instead says there are 708 road rows while also requiring the blank line and footer to be staged. Preserving the actual file produces 1,286 extracted rows, 24 rejected, 60 duplicate removals, and 1,202 fact rows. The row identity balances exactly at 1,286 = 1,202 + 24 + 60, but cannot also equal the workbook target of 1,284 = 1,200 + 24 + 60. I have not discarded two source records to force that target.

## Rejects and Unknown members

The 24 rejects carry their source file, line, original values, and a reason in `RejectLog.csv`, so a corrected source row can be resubmitted. A bad date cannot receive the required date key; a nonnumeric or nonpositive weight is not a valid physical measure; and a blank shipment identifier cannot establish the fact grain. A credit note is different: its negative freight cost is valid and remains in the fact as a negative amount.

Valid shipments with unresolved descriptive values still load at key `-1`. The 14 unresolved origins are Keti Bandar Jetty (3), Kotri Junction (3), Wagah Border (2), Taftan Crossing (2), Torkham Gate (2), and Chaman Border (2). The 7 unresolved statuses are `held at customs` (4), `RTO` (2), and `Hold` (1). These are lookup failures, not broken shipments. Deleting the 14 origin rows would hide freight that was actually moved; the supplied target says that loss would be 195,150 kg.

## Customer, duplicates, and performance

The registry contains 46 rows but six businesses have alternate spellings/IDs. Conforming those aliases yields 40 businesses plus the Unknown row in `DimCustomer`; this is a dimension correction, so it does not change fact weight or cost. Deduplication uses the normalized ShipmentID. A same-day/lane/weight/customer definition is unsafe: it collapses distinct road shipments `RD-5216` with `RD-5337`, and `RD-5409` with `RD-5332`.

For the intended 1,200-row fact, I would index `DateKey`: 31 values across 1,200 rows (2.58% selectivity, about 38.7 rows per date) and it is filtered on every dashboard page. This costs one maintained index entry per inserted fact row (1,200 entries for a 1,200-row load), plus index page maintenance. `ShipmentID` is unique but not used for dashboard filtering; `ModeKey` has only three values and offers poor selectivity. A star path answers weight by province with one city join and 1,200 probes; the three-join snowflake path passes 3,600 probes.

## Workbook note

The workbook includes the task answers and records the source-derived counts. Its T7 checks that depend on the conflicting road/staging/fact row counts cannot all pass without either changing the provided CSV or silently removing rows. The cost/weight results from the actual preserved rows are also different from the stated target totals.

