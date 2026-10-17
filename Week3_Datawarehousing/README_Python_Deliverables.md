# PakFreight Week 3 — Python deliverables

The completed Excel workbook is `W3_Star_Completed.xlsx`. The workbook formulas are retained and set to recalculate when opened in Excel or LibreOffice.

The Python substitute for the Power BI lab builds the six star tables as CSVs and produces origin- and destination-province × mode weight matrices plus 13 independent reconciliation checks. Route corridor and distance bands are editorial classifications; distance bands use approximate straight-line city coordinates because the source data contains no route-mileage field.

## Run it again

1. Install Python 3.
2. Open Command Prompt or PowerShell.
3. Run: `python build_pakfreight_w3.py --data-dir "C:\Users\HP\Downloads" --output-dir "C:\Users\HP\Documents\Codex\2026-10-10\ok-chatgpt-act-like-a-brillent\outputs"`
4. Check `Python_Reconciliation.csv`: all 13 rows should say `PASS`.

The script needs `openpyxl` to fill the supplied workbook template. Install it with `python -m pip install openpyxl` if Python reports that the module is missing.

`FactShipment.csv` has six integer keys, the degenerate `ShipmentID`, and three numeric measures. Descriptive labels stay in dimensions. The origin matrix matches the assignment's 578,650 kg total; the destination matrix is the Python equivalent of the destination role-playing-dimension analysis.
