# DWBI Week 1 — Tasks 1–5

**Student:** Hafiz ali arif  
**Roll number:** BSDS-7A-011

## Task 1 — Messy sales log

| Problem (example) | Report impact | Owner / fix |
|---|---|---|
| Branch aliases: `1001` LHR-Gulberg; `1002` Lahore Gulberg; `1003` KHI-Clifton; `1005` khi clifton | Splits branch totals | ETL: map aliases to branch IDs. |
| Mixed dates: `1001`, `1002`, `1003`, `1004`, `1009` use five formats | Failed or misread date filters | Source: enforce ISO dates. |
| Duplicate `1004` | Doubles revenue | Source: enforce unique order IDs. |
| Product aliases: `1001` Cola 1.5L; `1002` CL-150; `1003` Cola 1.5 Ltr | Splits product/category totals | ETL: map codes and aliases to a product key. |
| Category variants/blanks: `1001` Beverages, `1002` Bev., `1005` blank, `1014` snacks | Filters omit or split categories | Business: approve canonical categories and blank mappings. |
| Text amounts: `1002` Rs 180; `1006` 2,450; `1013` 9,450 | Numeric sums fail or skip rows | Source: export numeric amounts. |
| Return `1007`: Qty −1, Amount −350 | Gross/net sales can be confused | Business: define how returns affect the metric. |
| Wrong amount `1008`: 2 Cola units = 2 × Rs 180 = Rs 360, not Rs 3,600 | Overstates beverage sales by Rs 3,240 | Source: validate amount against quantity × price. |

**Preventable at entry:** duplicate `1004`—unique order ID check; wrong `1008` amount—quantity × price validation.

### Beverage revenue

Assumptions: `Bev.` means Beverages; product aliases map to the catalogue; blank-category rows are milk, not beverages; `1008` is corrected to Rs 360; the date formats refer to 12 Sep 2026. Counted orders:

`1001` 360 + `1002` 180 + `1003` 540 + `1008` 360 + `1010` 320 + `1015` 960 + `1018` 1,280 + `1021` 360 + `1025` 640 + `1030` 180 + `1031` 320 + `1034` 640 + `1035` 180 = **Rs 6,320**.

Parsed as recorded, these rows total Rs 9,560; correcting `1008` subtracts Rs 3,240. Duplicate `1004` is Snacks and return `1007` is Electronics, so neither changes beverage revenue. **Confidence: medium**; receipt records and approved product/category definitions would raise it. The file should not go straight to a dashboard because its inconsistencies can split categories, lose rows, or distort totals.

## Task 2 — OLTP or OLAP?

| # | Type | Reason |
|---|---|---|
| 1 | OLTP | Records one current checkout. |
| 2 | OLAP | Aggregates category sales over 12 months. |
| 3 | OLTP | Updates one customer now. |
| 4 | OLAP | Compares periods across branches. |
| 5 | OLTP | Posts a current ATM transaction. |
| 6 | OLAP | Analyzes balances across historical months. |
| 7 | OLTP | Updates one order's current status. |
| 8 | OLAP | Ranks branch returns over a quarter. |

**Examples:** A pharmacy records a medicine sale and reduces stock (OLTP: a few immediate writes); its chain compares annual category sales across outlets (OLAP: many historical rows). **Borderline:** a supervisor checks today's sales every ten minutes. One small query may run on OLTP; recurring analysis belongs on a reporting replica/store to protect checkout performance.

The CEO's historical query consumed CPU, memory, and I/O and competed with the short writes and locks OLTP is optimized to process quickly. That resource contention delayed checkout transactions and bill printing.

## Task 3 — History and shared truth

**History:** Overwriting Ali's branch breaks **time-variance**: the current row cannot show that he belonged to Lahore before March. Keep dated employee-branch versions so old sales join to Lahore and later sales to Karachi. Overwriting a customer address could similarly reassign old deliveries to a new region.

**Different sales totals:** Operations' Rs 661.65m might count completed orders by order date; Finance's Rs 283.70m might use recognized net revenue after returns/tax/cut-off; Sales' Rs 584.75m might count booked or representative-credited sales. These can use different scopes without arithmetic errors. A shared staging pipeline makes transformations visible and repeatable. A business data owner, with Finance, Operations, and Sales agreeing, should govern the definition because it drives decisions and comparisons.

A warehouse preserves dated states and applies shared definitions: it prevents Ali's old sales moving branches and reconciles departments' differing extracts. **Non-volatile** means historical facts are stable for analysis rather than being routinely changed by operational transactions; controlled corrections/restatements are possible, such as fixing a validated branch code.

## Task 4 — DW/BI architecture

| Item | Stage | Reason |
|---|---|---|
| A. Remove duplicates | ETL/Staging | Clean incoming data. |
| B. CEO phone dashboard | BI Applications | Presents analysis. |
| C. Branch POS | Source Systems | Captures transactions. |
| D. Sales star schema | Presentation Area | Query-ready model. |
| E. HR staff Excel | Source Systems | Originating data source. |
| F. Map CL-150 to Cola 1.5L | ETL/Staging | Standardizes input. |
| G. Weekly emailed PDF | BI Applications | Delivers a report. |
| H. Finance data mart | Presentation Area | Stores modeled analytics. |

```text
SOURCE SYSTEMS → ETL / STAGING → PRESENTATION AREA → BI APPLICATIONS
C POS, E HR file   A dedupe, F map   D star schema, H mart   B dashboard, G PDF
```

Kitchen metaphor: direct production-table querying is a diner taking food off the stove (contention/incomplete data); loading without validation is serving without tasting (errors reach reports); separate pipelines with different rules are kitchens using different recipes (conflicting totals).

Three goals: **Accessible**—managers should not hand-clean aliases; **consistent**—map Cola aliases once; **adaptable**—new branch names should be handled through governed mappings. HR's Excel may be the authoritative source, but can be stale or uncontrolled. Treat it as a source only after confirming its owner, controlled version, stable IDs, update schedule, definitions, and reconciliations.

## Task 5 — First connection

Before loading: `Sales[ProductID]` identifies the sold product; region name is in `Regions[RegionName]`; use `Products[Category]` for the slicer because category belongs to the product and is not stored in Sales.

Workbook counts: **480 Sales, 15 Products, 4 Regions**. Relationships: Products[ProductID] (one) → Sales[ProductID] (many); Regions[RegionID] (one) → Sales[RegionID] (many). Dimension keys are unique; sales rows repeat them.

**Total Sales: Rs 3,026,990.** Region totals, sorted descending:

| Region | Rs |
|---|---:|
| South | 1,118,940 |
| Central | 943,410 |
| North | 637,340 |
| West | 327,300 |

Chart title: **South leads regional sales at Rs 1,118,940 (Jan–Jun 2026)**. Use `Regions[RegionName]`, `Sales[SalesAmount]`, a `Products[Category]` slicer, and a total card. Category totals (Beverages 82,340; Snacks 58,920; Dairy 157,920; Grocery 965,460; Electronics 1,762,350) sum to Rs 3,026,990. The source workbook is unchanged; filtering changes visuals only. No blank IDs or values were found in the three tables.

Use `Sales[SalesAmount]` for revenue; use `Sales[UnitPrice]` for the transaction price. `Products[UnitPrice]` is catalogue price and can change over time. Power BI panes: Filters (scope data), Visualizations (build/format visuals), Data/Fields (tables and fields), Format (appearance). Left views: Report (build), Data (inspect rows), Model (relationships).

**Task 5 limitation:** Power BI Desktop was unavailable, so I verified workbook totals independently but could not create the `.pbix`, interact with its slicer/card, or capture the required screenshot. A clean related dataset supports fast analysis without burdening checkout OLTP; the same large query at Friday 6pm could contend for resources and slow billing.
