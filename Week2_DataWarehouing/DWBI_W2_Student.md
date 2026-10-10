# DWBI Week 2 — PakFreight

**Student:** HAFIZ ALI ARIF  
**Roll number:** BSDS_7A_011 
**Date:** 10 October 2026


## Task 1 — Tiers, warehouse properties and marts

### Three tiers

| Tier | Job | PakFreight example | Must not happen |
|---|---|---|---|
| 1. Staging | Land source data and make source-specific quality/unit corrections repeatably. | Keep marine, rail and road raw queries; parse marine dates, convert rail tonnes to kg, remove the Road duplicate/blank/TOTAL rows with recorded steps. | Do not expose raw inconsistent values as trusted business measures or overwrite the source evidence. |
| 2. Storage | Integrate and preserve governed, historical data (EDW; an ODS may hold current operational detail). | Store the integrated shipment history with common keys, dates and kg units. | Do not let each department redefine shipment grain, units or customer independently. |
| 3. Presentation | Shape governed data into dimensional marts/semantic models and reports for business use. | A Shipments star schema and dashboard with mode totals and status counts. | Do not hide cleansing or unit conversion in a visual or report-only calculation. |

### Inmon's four properties

| Property | Satisfied in this case | Broken in this case |
|---|---|---|
| Subject-oriented | A Shipments subject area organizes records around freight shipments. | A report organized only around file names/department extracts has no shared shipment subject. |
| Integrated | All sources map to ShipmentID, ShipDate, Origin, Destination, WeightKG, CostPKR, Status and SourceSystem. | Marine uses dd/mm/yyyy and kg; Rail has title rows, numeric consignment IDs and tonnes; Road uses lowercase IDs and includes non-shipment rows. Appending without standardization does not integrate them. |
| Time-variant | Keep dated shipment facts and effective-dated customer address history so prior-period analysis remains possible. | Overwriting a customer's old address erases what the warehouse knew for earlier periods. |
| Non-volatile | Loaded history is retained; corrections are made through controlled, traceable loads. | Replacing historical records in place or overwriting old addresses destroys the prior state. |

Overwriting an address breaks **time-variance** and the non-volatile history principle: retain effective-dated versions (for example, a Type 2 customer dimension) with start/end dates and a current-row flag.

### EDW or ODS

| Requirement | Best fit |
|---|---|
| a. Truck positions every 2 minutes | ODS / operational stream: current status and low latency matter. |
| b. Freight cost per tonne-km across three years | EDW: integrated multi-year history and consistent measures. |
| c. Whether consignment 45017 left today | ODS: current operational status. |
| d. Mode profitability since 2023 | EDW: historical, integrated analysis. |

### Marts

Independent marts: `Marine file → Operations mart` / `Rail file → Finance mart` / `Road file → Sales mart`.

Dependent alternative: `Marine + Rail + Road → shared staging → integrated EDW → Operations, Finance and Sales marts (shared/conformed dimensions)`.

The independent teams can each choose different rows and rules. They can interpret tonnes as kilograms or include a source total row. They therefore answer the same business question over different populations and units even when each team follows its own local rule.

Raw files pass through staging so source-specific defects are corrected in repeatable, auditable steps before the model sees integrated data.

## Task 2 — Inmon, Kimball and lifecycle

### Comparison

| Dimension | Inmon — top-down | Kimball — bottom-up |
|---|---|---|
| Starting point | Enterprise-wide requirements and integrated warehouse | Business process and first useful dimensional mart |
| First model | Normalized enterprise data warehouse (often 3NF) | Dimensional star schema for a process |
| Delivery sequence | EDW first, dependent marts afterward | Marts iteratively; plan a bus across the enterprise |
| First value | Usually later because enterprise integration precedes marts | Earlier, from the first useful mart |
| Consistency | Central enterprise model, integration and governance | Conformed dimensions, shared definitions and bus matrix |
| Main risk | Long lead time before users see value | Stovepipes if teams fail to conform dimensions/definitions |
| Lifecycle emphasis | SDLC: requirements drive the program | CLDS: data exploration informs and refines requirements |

### Architectures

**Inmon CIF:**

```text
Operational sources → ETL/cleansing → Enterprise DW (normalized, integrated, historical)
                                             ├→ dependent Finance mart → BI
                                             ├→ dependent Operations mart → BI
                                             └→ dependent Sales mart → BI
```

**Kimball Bus:**

```text
Operational sources → ETL → Shipments star ─┐
                            Billing star ─────┼→ shared conformed Date, Customer, Route dimensions → BI
                            Returns star ─────┘
```

### Ten scenarios

| # | Classification | Reason |
|---|---|---|
| 1 | Inmon | The bank requires one enterprise customer definition before reporting, so integration/modeling comes first. |
| 2 | Kimball | A narrow sales mart can deliver a dashboard quickly, with shared dimensions planned for reuse. |
| 3 | Inmon | Multiple source systems plus a long regulatory program favor enterprise integration and governance first. |
| 4 | Kimball | Shipments is built first and Date/Route are conformed for subsequent marts. |
| 5 | Inmon | A normalized core EDW feeding departmental marts is the top-down pattern. |
| 6 | Hybrid | Bronze/silver/gold layering supports enterprise data refinement with dimensional gold outputs. |
| 7 | Inmon | Agreeing the enterprise model before loading is a top-down, model-first approach. |
| 8 | Kimball | A new Returns process reuses the conformed Product dimension. |
| 9 | Hybrid | Reconcile existing marts with enterprise definitions while preserving iterative delivery. |
| 10 | Inmon | Acquired systems must be integrated into a shared enterprise model and definitions. |

### Kimball lifecycle applied to Shipments Iteration 1

1. **Programme planning:** sponsor the COO's initial shipment visibility objective, scope February freight sources and assign steward/engineering ownership.
2. **Business requirements:** agree the grain (one real shipment), measures (kg and freight cost), status definition, dimensions and required mode/route/status questions.
3. **Technical architecture/product selection:** use Power Query for repeatable ingestion and a governed semantic model/report; identify refresh, storage and access requirements.
4. **Dimensional modelling:** define a shipment fact at one shipment per row; use Date, Route, Customer, mode/vehicle and source identifiers as dimensions/attributes as available.
5. **ETL design and development:** stage three files, remove Rail title rows, normalize date/IDs/status, convert Rail tonnes to kg, reject Road's duplicate, blank and TOTAL lines, then append by contract column name.
6. **BI application specification/development:** provide total kg and tonnes, mode and status breakdowns, and filters for date, route and source system.
7. **Deployment:** publish a validated model and report with refresh ownership and reconciliation results.
8. **Maintenance:** monitor source schema, row counts, totals, refresh failures and changes to business definitions.

If only five phases are required, phases 1–5 above satisfy the requirement and the later phases show the rest of the lifecycle.

Iteration 1 should establish **Date** and **Route** dimensions (and Customer if available). Conformed means Billing uses the same governed dimension keys, attributes and meanings, so a date or route selection identifies the same entities in both facts.

**SDLC vs CLDS:** SDLC starts with requirements and then builds a program to satisfy them. CLDS starts by examining available data and revises requirements as the data reveals what can be measured consistently. Freight example: only after profiling the source files does the team learn Rail weight is tonnes, Marine dates need UK parsing, and Road's TOTAL row is not a shipment; these facts change the cleansing rules and meaning of a valid shipment.

> “We built the Shipments mart first, with conformed Date and Route dimensions” is **Kimball/bottom-up**. It could be Inmon only if Shipments were a dependent presentation mart built after a central normalized enterprise warehouse had already integrated the enterprise data and definitions.

## Task 3 — Data Detective

The completed workbook contains the issue log, raw/staged areas, formulas, explicit Road keep/reject reasons, reconciliation, date trap checks, lineage and bus matrix. Key findings:

- Rail's 32.5 tons means **32,500 kg**. The sum for its ten rows is 295.25 t = 295,250 kg.
- Marine is already in kilograms: 206,500 kg across 12 rows.
- Road has 12 genuine trips totaling 76,900 kg. Reject the second `rd-505` copy (Road CSV line 7; staging worksheet row 10), the fully blank line (Road CSV line 15; staging worksheet row 18), and the `TOTAL` aggregate (Road CSV line 16; staging worksheet row 19). Those are three different reasons; retain them in raw evidence and record their reason in the staging sheet.
- Reconciliation: Marine 12/0/12/206,500 kg; Rail 10/0/10/295,250 kg; Road 15/3/12/76,900 kg; all sources 37/3/34/578,650 kg (578.65 t).

### Reproducing the four totals

- **Operations: 661.65 t.** It includes Road's 83,000 kg `TOTAL` row as if it were another shipment, while also summing the 83,000 kg of Road detail (which includes the duplicate). It removes the duplicate 6,100 kg once: 206,500 Marine + 295,250 Rail + (83,000 detail + 83,000 TOTAL − 6,100 duplicate) Road = **661,650 kg**.
- **Finance: 283.70 t.** It treats Rail's 295.25 tonnes as 295.25 kg: 206,500 Marine + 295.25 Rail + 76,900 Road = **283,695.25 kg**, displayed to two decimal tonnes as **283.70 t** (283.69525 t rounds to 283.70 t).
- **Sales: 584.75 t.** It includes the duplicate Road trip but excludes the TOTAL row: 206,500 Marine + 295,250 Rail + (76,900 + 6,100 duplicate) Road = **584,750 kg**.
- **Staging: 578.65 t.** 206,500 + 295,250 + 76,900 = **578,650 kg**.

All three departments trusted their own local extract and rule, so each calculation looked internally consistent. Without common units, a shared definition of a shipment and row-level lineage, the mistakes were difficult to see across departmental boundaries.

An effective control for Operations' mistake is a staging assertion that rejects or quarantines records whose ShipmentID is `TOTAL` or whose required shipment fields are missing, plus a source-to-stage row-count/weight reconciliation that prevents report refresh if an aggregate row appears.

## Task 4 — Repeatable pipeline in Python

Per the requested Python alternative, the transformation is implemented as a runnable pipeline rather than a Power BI PBIX. The script reads the three original files without modifying them, stages each source in memory, standardizes the contract, appends one integrated table, and stops with an error if any reconciliation check fails.

Run it with the bundled Python (or Python with pandas and openpyxl):

```powershell
& 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\HP\Documents\Codex\2026-10-10\ok-chatgpt-act-like-a-brillent\outputs\pakfreight_pipeline.py'
```

The script records these transformations in code: Marine dates parse strictly as `%d/%m/%Y`; Rail skips two title rows, prefixes IDs with `RL-`, and converts tonnes to kilograms; Road uppercases IDs, trims and title-cases statuses, and rejects the duplicate, blank and TOTAL lines with reasons. All sources are projected into the exact eight-column contract before append. The internal source-specific dataframes are staging; only the integrated `Shipments.csv` is the business table, and `staging_audit.csv` preserves source row decisions for audit.

The run produced and validated **34 rows × 8 columns**, with no missing shipment ID/date/weight, unique IDs, exactly three statuses, and **578,650 kg** total. By source: Marine 12 rows / 206,500 kg; Rail 10 / 295,250 kg; Road 12 / 76,900 kg. Status counts are Delivered 22, In Transit 8, Delayed 4. `validation.json` records each assertion as true. The Road rejects are CSV source lines 7 (`rd-505` duplicate), 15 (blank), and 16 (`TOTAL`).

The data contract and validation assertions serve as the pipeline's interface and quality gate: all transformations are repeatable on refresh, and schema, row-count, status, uniqueness, unit-total or mode-total drift fails the run rather than silently flowing into reports. For daily Road files, the same staging function can be applied to each file in an input folder, with a source-file column added to the audit; every file must pass the same required-column checks before concatenation.


## Task 5 — Latency, drift, lineage and roles

### Freshness

| Consumer | Freshness | Reason |
|---|---|---|
| Dispatcher rerouting a truck around a blocked motorway | Real-time / seconds-to-minutes | A stale position can send the driver into the blockage. |
| CFO monthly cost-per-tonne report | Daily batch (or monthly close snapshot) | Reconciled costs matter more than minute-level updates; daily loading supports close and investigation. |
| Customer tracking a consignment online | Near-real-time | A recent event is useful, but a short ingestion delay is acceptable and operationally practical. |
| Board quarterly mode-profitability review | Weekly or monthly batch | The board needs stable, reconciled quarterly history, not live movement. |

“Always real-time” costs include streaming infrastructure/engineering and monitoring expense, and it pushes partial/unreconciled records into reports before quality checks and close processes finish.

### Schema drift

- Adding `Wagon_Type`: if the Rail query explicitly selects/reorders only the eight contract fields, the new field is silently ignored and the pipeline carries on; that may lose useful data. Detect with a schema-diff alert or unexpected-column check before append.
- Renaming `Freight Charges (PKR)` to `Charges_PKR`: a rename/type step that references the old column will fail refresh with a missing-column error. Detect using required-column assertions and a refresh-failure alert before a report is served.

### Number lineage and investigation

```text
marine_shipments.csv (12 rows, kg) ─┐
rail_shipments.xlsx (skip 2 title rows; 10 records; tonnes × 1,000) ─┼→ source-specific staging
road_shipments.csv (15 raw lines; reject duplicate, blank, TOTAL) ─┘
   → normalize headers/IDs/dates/status/units and add SourceSystem
   → append 12 + 10 + 12 = 34 Shipments rows
   → validate total WeightKG = 206,500 + 295,250 + 76,900 = 578,650
   → semantic measure SUM(WeightKG) → report card filtered to Feb 2026
```

If the CFO's number is low, check in order: **(1)** source/staging completeness and row-level exclusions, including all three Road rejects and missing-file/row counts; **(2)** Rail unit conversion and Marine date locale/period filter; **(3)** the append/model measure and report filter/refresh time. This follows the lineage upstream from the visible number to the source records.

### Role ownership

| Responsibility | Role | Main tier |
|---|---|---|
| Design Shipments star schema | Data architect | Storage/presentation boundary, primarily presentation model design |
| Maintain Power Query pipeline | ETL/data engineer | Staging and storage loading |
| Define official meaning of Delivered | Business/data steward | Cross-tier governance; definition applied in staging/model |
| Build morning dashboard | BI developer | Presentation |
| Keep Rail export in agreed format | Source system owner | Source (upstream of staging) |

The data architect owns the target model and tier contracts; the data engineer owns repeatable transformations; the steward owns definitions; the BI developer owns usable presentation; source owners maintain the input contract. Staging is mainly owned by data engineering with source-owner coordination, storage by the data architect/data engineering, and presentation by the BI developer with steward sign-off. If nobody owns a tier, the departments can each retain a separate rule: one includes the Road TOTAL, one misses Rail's unit, and one double-counts a duplicate.

Skipping validation makes the analyst a business risk because an undetected error can become an authoritative planning input. If 578,650 kg were wrong, PakFreight could misstate mode utilization and award freight volume/profitability decisions to the wrong carrier; an explicit check catches that before the board or operations team acts.

For a departed employee's unreproducible dashboard, first follow **lineage** backward from the card to its measure, filters, integrated table and source rows; next test **latency** (last successful refresh and expected freshness); then inspect **schema drift** and failed/ignored source columns against the recorded query steps. Reconcile the resulting row counts and units before accepting the figure.
