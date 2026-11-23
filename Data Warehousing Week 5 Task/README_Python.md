# Run the Week 5 Python ETL

The completed assignment workbook is `W5_ETL_Completed.xlsx`. The ETL script uses Python with pandas and openpyxl.

## Install the packages

In PowerShell, run:

```powershell
py -m pip install pandas openpyxl
```

## Run both assignment scenarios

```powershell
py "C:\Users\HP\Documents\Codex\2026-10-10\ok-chatgpt-act-like-a-brillent\outputs\w5\W5_ETL.py" `
  --input-dir "C:\Users\HP\Downloads\Week5DataWarehousing" `
  --output-dir "C:\Users\HP\Documents\Codex\2026-10-10\ok-chatgpt-act-like-a-brillent\outputs\w5\python_results" `
  --dump-intermediates
```

The script checks the first-night data before processing the refresh files. Results include published dimension and fact CSVs, intermediate CSVs, step/source audit logs, unknown-key rows, scenario checks, and run summaries under `python_results\night1` and `python_results\night2`.

If you only want to run the first-night files, add `--base-only` and omit `--dump-intermediates` if you do not need each intermediate step exported.
