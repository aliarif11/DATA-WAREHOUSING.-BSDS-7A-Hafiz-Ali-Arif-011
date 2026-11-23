"""PakFreight Week 5 ETL pipeline (Python/pandas track).

The script keeps extracted and transformed frames in `frames` for review. Only
four dimensions, DimRoute, and the final FactShipment are written to the
published folder; intermediate frames are connection-only equivalents.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CONTRACT = ["ShipmentID", "ShipDate", "OriginRaw", "DestRaw",
            "WeightKG", "FreightCostPKR", "StatusRaw"]
MODE = {"marine": 1, "rail": 2, "road": 3}
COLUMNS = {
    "marine": {"Shipment_ID":"ShipmentID", "Ship_Date":"ShipDate", "Origin_Port":"OriginRaw",
                "Dest_Port":"DestRaw", "Weight_KG":"WeightKG", "Cost_PKR":"FreightCostPKR", "Status":"StatusRaw"},
    "road": {"trip_id":"ShipmentID", "trip_date":"ShipDate", "from_city":"OriginRaw",
             "to_city":"DestRaw", "weight_kg":"WeightKG", "cost_pkr":"FreightCostPKR", "status":"StatusRaw"},
    "rail": {"Consignment No":"ShipmentID", "Dispatch Date":"ShipDate", "From Station":"OriginRaw",
             "To Station":"DestRaw", "Weight (Tons)":"WeightTons",
             "Freight Charges (PKR)":"FreightCostPKR", "Status":"StatusRaw"},
}
DIM_FILES = {"DimCity":"DimCity (1).csv", "DimDate":"DimDate (1).csv", "DimMode":"DimMode (1).csv",
             "DimRoute":"DimRoute (1).csv", "DimStatus":"DimStatus (1).csv"}

# The seventeen macro-steps marked in T3. The first ten operate per source;
# the remaining seven operate once after the three source branches are ready.
STEPS = [
    {"name":"ConnectToAllThreeSources", "stage":"Extract", "cadence":"per source"},
    {"name":"LandFaithfulCopyUnchanged", "stage":"Extract", "cadence":"per source"},
    {"name":"LogSourceTimeAndRowCount", "stage":"Extract", "cadence":"per source"},
    {"name":"PromoteHeadersDropJunkRowsAndColumns", "stage":"Transform", "cadence":"per source"},
    {"name":"RenameEveryColumnToContract", "stage":"Transform", "cadence":"per source"},
    {"name":"TrimAndCleanText", "stage":"Transform", "cadence":"per source"},
    {"name":"NormalizeStatusToProperCase", "stage":"Transform", "cadence":"per source"},
    {"name":"ParseDatesWithExplicitLocale", "stage":"Transform", "cadence":"per source"},
    {"name":"ConvertRailTonsAndSetTypes", "stage":"Transform", "cadence":"per source"},
    {"name":"AddModeKeyBySource", "stage":"Transform", "cadence":"per source"},
    {"name":"AppendThreeQueries", "stage":"Transform", "cadence":"once"},
    {"name":"RemoveDuplicatesAfterTrim", "stage":"Transform", "cadence":"once"},
    {"name":"ConformCityNamesLookupKeysUnknownMinusOne", "stage":"Transform", "cadence":"once"},
    {"name":"LoadFourIndependentDimensions", "stage":"Load", "cadence":"once"},
    {"name":"LoadDimRouteAfterCityKeys", "stage":"Load", "cadence":"once"},
    {"name":"LoadFactShipment", "stage":"Load", "cadence":"once"},
    {"name":"ReconcileOrFailRun", "stage":"Load", "cadence":"once"},
]

@dataclass
class RunResult:
    version: str
    fact: pd.DataFrame
    source_tables: dict[str, pd.DataFrame]
    dimensions: dict[str, pd.DataFrame]
    frames: dict[str, pd.DataFrame]
    audit: list[dict]
    source_log: list[dict]
    checks: list[dict]
    unknown_rows: pd.DataFrame
    appended_rows: int


def file_for(source_dir: Path, kind: str, version: str) -> Path:
    ext = "xlsx" if kind == "rail" else "csv"
    candidates = [source_dir / f"{kind}_shipments ({version}).{ext}",
                  source_dir / f"{kind}_shipments.{ext}"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find {kind} source file for version {version} in {source_dir}")


def extract_raw(path: Path, kind: str) -> tuple[pd.DataFrame, int]:
    """Read exactly what the source contains. No row cleaning or normalization."""
    if kind == "rail":
        raw = pd.read_excel(path, sheet_name="Rail", header=None, dtype=object)
        records = max(0, len(raw) - 3)  # two title lines and one header line
    else:
        raw = pd.read_csv(path, header=None, dtype=object, skip_blank_lines=False,
                          keep_default_na=True, encoding="utf-8-sig")
        records = max(0, len(raw) - 1)  # exclude header, retain blank/footer rows
    return raw.copy(deep=True), records


def clean_text(value):
    if pd.isna(value):
        return value
    text = str(value).replace("\x00", " ")
    text = re.sub(r"[\x01-\x1f\x7f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def capture(frames: dict[str, pd.DataFrame], key: str, frame: pd.DataFrame):
    frames[key] = frame.copy(deep=True)


def run_pipeline(source_dir: Path, dims_dir: Path, version: str, out_dir: Path,
                 dump_intermediates: bool = False) -> RunResult:
    frames: dict[str, pd.DataFrame] = {}
    audit: list[dict] = []
    source_log: list[dict] = []
    source_tables: dict[str, pd.DataFrame] = {}
    extracted: dict[str, pd.DataFrame] = {}

    def log_step(step_name, source, before, after, note=""):
        step = next(s for s in STEPS if s["name"] == step_name)
        audit.append({"RunVersion":version, "StepOrder":STEPS.index(step)+1, "StepName":step_name,
                      "Stage":step["stage"], "Cadence":step["cadence"], "Source":source,
                      "RowsBefore":before, "RowsAfter":after, "Note":note})

    for kind in ("marine", "rail", "road"):
        path = file_for(source_dir, kind, version)
        raw, data_row_count = extract_raw(path, kind)
        extracted[kind] = raw
        capture(frames, f"{kind}.LandedFaithfulCopy", raw)
        # These are per-source extract operations, and do not change the rows.
        log_step("ConnectToAllThreeSources", kind, data_row_count, data_row_count, path.name)
        log_step("LandFaithfulCopyUnchanged", kind, data_row_count, data_row_count, "raw frame retained")
        source_log.append({"RunVersion":version, "Source":kind, "File":path.name,
                           "RowsLanded":data_row_count, "LoggedAtUTC":datetime.now(timezone.utc).isoformat()})
        log_step("LogSourceTimeAndRowCount", kind, data_row_count, data_row_count, "written to source log")

    prepared = {}
    for kind in ("marine", "rail", "road"):
        raw = extracted[kind].copy(deep=True)
        before = len(raw) - (3 if kind == "rail" else 1)
        # Step 4: shape headers. Road has two explicit, separately named filters.
        if kind == "rail":
            shaped = raw.iloc[2:].reset_index(drop=True).copy()
            log_step("PromoteHeadersDropJunkRowsAndColumns", kind, before, len(shaped)-1,
                     "SkippedTitleRows, then PromotedHeaders")
            capture(frames, "rail.SkippedTitleRows", shaped)
            headers = shaped.iloc[0].tolist()
            df = shaped.iloc[1:].reset_index(drop=True).copy()
            df.columns = [str(h).strip() for h in headers]
            capture(frames, "rail.PromotedHeaders", df)
        else:
            headers = raw.iloc[0].tolist()
            df = raw.iloc[1:].reset_index(drop=True).copy()
            df.columns = [str(h).strip() for h in headers]
            capture(frames, f"{kind}.PromotedHeaders", df)
            if kind == "road":
                id_col = "trip_id"
                keep = df[id_col].notna() & df[id_col].astype("string").str.strip().ne("")
                old = len(df); df = df.loc[keep].reset_index(drop=True)
                capture(frames, "road.RemovedBlankRows", df)
                after_blank = len(df)
                keep = df[id_col].astype("string").str.strip().str.upper().ne("TOTAL")
                df = df.loc[keep].reset_index(drop=True)
                capture(frames, "road.RemovedTotalRow", df)
                log_step("PromoteHeadersDropJunkRowsAndColumns", kind, before, len(df),
                         f"RemovedBlankRows {old}->{after_blank}; RemovedTotalRow {after_blank}->{len(df)}")
            else:
                log_step("PromoteHeadersDropJunkRowsAndColumns", kind, before, len(df), "headers promoted; no junk rows")

        # Step 5: common contract labels, except rail tons stay honestly named
        # WeightTons until the unit conversion step produces WeightKG.
        df = df.rename(columns=COLUMNS[kind]).copy()
        capture(frames, f"{kind}.RenamedToContract", df)
        log_step("RenameEveryColumnToContract", kind, len(df), len(df),
                 "rail Weight (Tons) retained as WeightTons until converted" if kind == "rail" else "seven-name contract")

        # Step 6: normalize every text field before business-key comparisons.
        for col in ("ShipmentID", "OriginRaw", "DestRaw", "StatusRaw"):
            df[col] = df[col].map(clean_text)
        df["ShipmentID"] = df["ShipmentID"].map(lambda x: x.upper() if isinstance(x, str) else x)
        capture(frames, f"{kind}.TrimmedCleanedText", df)
        log_step("TrimAndCleanText", kind, len(df), len(df), "trim, clean controls, collapse spaces")

        # Step 7: collapse casing variants only after whitespace is clean.
        df["StatusRaw"] = df["StatusRaw"].map(lambda x: x.title() if isinstance(x, str) else x)
        capture(frames, f"{kind}.ProperCaseStatus", df)
        log_step("NormalizeStatusToProperCase", kind, len(df), len(df), "17 raw strings -> 3 values after append")

        # Step 8: a format is stated for each text-date source; rail is an Excel date.
        if kind == "marine":
            df["ShipDate"] = pd.to_datetime(df["ShipDate"].astype(str), format="%d/%m/%Y", errors="raise")
        elif kind == "road":
            df["ShipDate"] = pd.to_datetime(df["ShipDate"].astype(str), format="%Y-%m-%d", errors="raise")
        else:
            df["ShipDate"] = pd.to_datetime(df["ShipDate"], errors="raise")
        capture(frames, f"{kind}.ParsedDatesExplicitly", df)
        log_step("ParseDatesWithExplicitLocale", kind, len(df), len(df),
                 "dd/MM/yyyy en-GB" if kind == "marine" else ("yyyy-MM-dd ISO" if kind == "road" else "native Excel dates"))

        # Step 9: scale rail tons before append; set stable output types.
        if kind == "rail":
            numeric_id = pd.to_numeric(df["ShipmentID"], errors="raise").astype("int64").astype(str)
            df["ShipmentID"] = "RL-" + numeric_id
            df["WeightKG"] = (pd.to_numeric(df["WeightTons"], errors="raise") * 1000).astype("int64")
            df = df.drop(columns=["WeightTons"])
        else:
            df["WeightKG"] = pd.to_numeric(df["WeightKG"], errors="raise").astype("int64")
        df["FreightCostPKR"] = pd.to_numeric(df["FreightCostPKR"], errors="raise").astype("int64")
        df = df[CONTRACT].copy()
        capture(frames, f"{kind}.TypedAndWeightsInKG", df)
        log_step("ConvertRailTonsAndSetTypes", kind, len(df), len(df),
                 "tons x 1,000" if kind == "rail" else "numeric/date types set")

        # Step 10: source metadata creates ModeKey; the source did not omit a defect.
        df["ModeKey"] = MODE[kind]
        prepared[kind] = df[CONTRACT + ["ModeKey"]].copy()
        capture(frames, f"{kind}.AddedModeKey", prepared[kind])
        log_step("AddModeKeyBySource", kind, len(df), len(df), f"ModeKey={MODE[kind]}")
        source_tables[kind] = prepared[kind]

    # Once-only steps 11–13: append, deduplicate by the declared business key,
    # then use left outer lookups so unresolved rows survive under -1.
    appended = pd.concat([prepared[k] for k in ("marine", "rail", "road")], ignore_index=True)
    capture(frames, "FactStaging.Appended", appended)
    log_step("AppendThreeQueries", "FactStaging", len(appended), len(appended), "37 source rows -> append")
    deduped = appended.drop_duplicates(subset=["ShipmentID"], keep="first").reset_index(drop=True)
    capture(frames, "FactStaging.Deduplicated", deduped)
    log_step("RemoveDuplicatesAfterTrim", "FactStaging", len(appended), len(deduped), "subset=['ShipmentID']")

    dims_dir.mkdir(parents=True, exist_ok=True)
    dimensions = {name: pd.read_csv(dims_dir / filename, dtype=str, keep_default_na=False)
                  for name, filename in DIM_FILES.items()}
    city = dimensions["DimCity"]
    alias = (city[["CityKey", "RawAliases"]]
             .assign(RawAliases=lambda x: x["RawAliases"].str.split(" | ", regex=False))
             .explode("RawAliases", ignore_index=True))
    alias["RawSpelling"] = alias["RawAliases"].map(clean_text)
    alias = alias.loc[alias["RawSpelling"].notna() & alias["RawSpelling"].ne("")].copy()
    alias["CityKey"] = pd.to_numeric(alias["CityKey"], errors="raise").astype("int64")
    alias = alias[["RawSpelling", "CityKey"]]
    if alias["RawSpelling"].duplicated().any():
        raise AssertionError("DimCity produced duplicate raw aliases")
    reference = pd.read_csv(source_dir / "alias_lookup.csv", dtype={"CityKey":str})
    actual_pairs = sorted((r.RawSpelling, str(r.CityKey)) for r in alias.itertuples(index=False))
    reference_pairs = sorted((r.RawSpelling, str(r.CityKey)) for r in reference.itertuples(index=False))
    assert len(alias) == 23 and alias.CityKey.nunique() == 14 and actual_pairs == reference_pairs
    capture(frames, "AliasLookup.23NonblankAliases", alias)

    fact = deduped.copy()
    for raw_col, key_col in (("OriginRaw", "OriginCityKey"), ("DestRaw", "DestCityKey")):
        lookup = alias.rename(columns={"RawSpelling":raw_col, "CityKey":key_col})
        fact = fact.merge(lookup, on=raw_col, how="left", validate="many_to_one")
        fact[key_col] = fact[key_col].fillna(-1).astype("int64")
        capture(frames, f"FactStaging.After{key_col}LeftJoin", fact)
    fact = fact[CONTRACT + ["ModeKey", "OriginCityKey", "DestCityKey"]].copy()
    capture(frames, "FactStaging.CityKeysUnknownMinusOne", fact)
    log_step("ConformCityNamesLookupKeysUnknownMinusOne", "FactStaging", len(deduped), len(fact),
             "two left joins; null keys replaced by -1")

    # Steps 14–16 publish the supplied dimensions, then route, then fact.
    out_dir.mkdir(parents=True, exist_ok=True)
    published = out_dir / "published"
    published.mkdir(parents=True, exist_ok=True)
    for name in ("DimCity", "DimDate", "DimMode", "DimStatus"):
        dimensions[name].to_csv(published / f"{name}.csv", index=False)
    log_step("LoadFourIndependentDimensions", "published", 4, 4, "source dimension files loaded unchanged")
    dimensions["DimRoute"].to_csv(published / "DimRoute.csv", index=False)
    log_step("LoadDimRouteAfterCityKeys", "published", len(dimensions["DimRoute"]), len(dimensions["DimRoute"]), "route keys depend on conformed city keys")
    fact.to_csv(published / "FactShipment.csv", index=False, date_format="%Y-%m-%d")
    log_step("LoadFactShipment", "published", len(fact), len(fact), "only final fact is published; intermediates stay internal")

    unknown_mask = fact["OriginCityKey"].eq(-1) | fact["DestCityKey"].eq(-1)
    unknown_rows = fact.loc[unknown_mask, ["ShipmentID", "OriginRaw", "DestRaw", "OriginCityKey", "DestCityKey"]].copy()
    checks = evaluate_checks(fact, source_tables, unknown_rows, version)
    log_step("ReconcileOrFailRun", "published", len(fact), len(fact), "7 required assertions; unknown count is reported")
    result = RunResult(version, fact, source_tables, dimensions, frames, audit, source_log, checks, unknown_rows, len(appended))

    if dump_intermediates:
        intermediate_dir = out_dir / "intermediates"
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for key, frame in frames.items():
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)
            frame.to_csv(intermediate_dir / f"{safe}.csv", index=False)
    pd.DataFrame(audit).to_csv(out_dir / "StepAudit.csv", index=False)
    pd.DataFrame(source_log).to_csv(out_dir / "SourceRunLog.csv", index=False)
    pd.DataFrame(checks).to_csv(out_dir / "T7_Checks.csv", index=False)
    unknown_rows.to_csv(out_dir / "Unknown_Rows.csv", index=False)
    summary = {"version":version, "extracted_rows":sum(x["RowsLanded"] for x in source_log),
               "appended_rows":len(appended), "fact_rows":len(fact), "weight_kg":int(fact.WeightKG.sum()),
               "freight_cost_pkr":int(fact.FreightCostPKR.sum()), "rail_weight_kg":int(fact.loc[fact.ModeKey.eq(2),"WeightKG"].sum()),
               "status_count":int(fact.StatusRaw.nunique()), "latest_date":fact.ShipDate.max().strftime("%Y-%m-%d"),
               "unknown_rows":len(unknown_rows), "delayed_rows":int(fact.StatusRaw.eq("Delayed").sum()),
               "alias_rows":len(alias), "alias_city_keys":int(alias.CityKey.nunique()),
               "all_t7_checks_pass":all(c["Pass"] == "PASS" for c in checks),
               "intermediate_frames_retained":len(frames), "published_tables":["DimCity","DimDate","DimMode","DimStatus","DimRoute","FactShipment"]}
    (out_dir / "RunSummary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return result


def evaluate_checks(fact, source_tables, unknown_rows, version):
    latest = fact.ShipDate.max()
    refresh = version == "2"
    values = [
        ("Contract columns in each query", 7, 7 if all(list(frame.columns[:7]) == CONTRACT for frame in source_tables.values()) else 0),
        ("Rail subtotal in kg", 295250, int(fact.loc[fact.ModeKey.eq(2), "WeightKG"].sum())),
        ("Distinct StatusRaw values", 3, int(fact.StatusRaw.nunique())),
        ("Latest day in ShipDate", 13, int(latest.day) if latest.year == 2026 and latest.month == 2 else f"{latest:%Y-%m-%d}"),
        ("Rows in FactShipment", 35 if refresh else 34, int(len(fact))),
        ("Rows carrying a -1 city key", 1 if refresh else 0, int(len(unknown_rows))),
        ("SUM WeightKG", 584950 if refresh else 578650, int(fact.WeightKG.sum())),
        ("SUM FreightCostPKR", 4860000 if refresh else 4808000, int(fact.FreightCostPKR.sum())),
    ]
    checks = []
    for label, expected, actual in values:
        passed = bool(actual == expected)
        checks.append({"Check":label, "Expected":expected, "Actual":actual, "Pass":"PASS" if passed else "FAIL"})
    # Check 6 is reported, not used to stop a pipeline; unresolved cities are a
    # data-quality event to route to Unknown and log, rather than drop or abort.
    required_assertions = [0,1,2,3,4,6,7]
    for i in required_assertions:
        assert checks[i]["Pass"] == "PASS", f"T7 {checks[i]['Check']} failed: {checks[i]['Actual']} != {checks[i]['Expected']}"
    return checks


def main():
    parser = argparse.ArgumentParser(description="Build and verify the Week 5 PakFreight ETL in Python.")
    parser.add_argument("--input-dir", type=Path, default=Path(r"C:\Users\HP\Downloads\Week5DataWarehousing"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "w5_run")
    parser.add_argument("--base-only", action="store_true", help="run night one only; do this before opening the refresh inputs")
    parser.add_argument("--dump-intermediates", action="store_true", help="write named intermediate frames as CSV for inspection")
    args = parser.parse_args()
    base_out = args.output_dir / "night1"
    base = run_pipeline(args.input_dir, args.input_dir, "1", base_out, args.dump_intermediates)
    # T7 part A must pass before the refresh copies are opened.
    assert all(c["Pass"] == "PASS" for c in base.checks), "Complete and verify T7 Part A before refresh."
    print("NIGHT ONE — T7 Part A:")
    print(json.dumps(json.loads((base_out / "RunSummary.json").read_text()), indent=2))
    print(f"rows routed to Unknown: {len(base.unknown_rows)}")
    if args.base_only:
        print("Base-only run complete. Night-two input files were not opened.")
        return

    # The second set is opened only after the first-night assertions above pass.
    refresh_out = args.output_dir / "night2"
    refresh = run_pipeline(args.input_dir, args.input_dir, "2", refresh_out, args.dump_intermediates)
    # Refresh invariants in the assignment.
    assert len(refresh.fact) == 35
    assert int(refresh.fact.WeightKG.sum()) == 584950
    assert int(refresh.fact.FreightCostPKR.sum()) == 4860000
    assert refresh.fact.StatusRaw.nunique() == 3
    assert len(refresh.unknown_rows) == 1
    assert int(refresh.fact.StatusRaw.eq("Delayed").sum()) == 5
    refresh_summary = json.loads((refresh_out / "RunSummary.json").read_text())
    print("NIGHT TWO — refresh test:")
    print(json.dumps(refresh_summary, indent=2))
    print("rows routed to Unknown (reported, not dropped):")
    print(refresh.unknown_rows.to_string(index=False))

    comparison = []
    first = json.loads((base_out / "RunSummary.json").read_text())
    metrics = ["fact_rows", "weight_kg", "freight_cost_pkr", "status_count", "unknown_rows", "delayed_rows"]
    for metric in metrics:
        comparison.append({"Metric":metric, "Night1":first[metric], "Night2":refresh_summary[metric]})
    pd.DataFrame(comparison).to_csv(args.output_dir / "Refresh_Comparison.csv", index=False)
    (args.output_dir / "Refresh_Proof.txt").write_text(
        "PakFreight Week 5 Python refresh proof\n"
        f"Night 1: {first['fact_rows']} rows | {first['weight_kg']:,} kg | PKR {first['freight_cost_pkr']:,} | Unknown rows {first['unknown_rows']}\n"
        f"Night 2: {refresh_summary['fact_rows']} rows | {refresh_summary['weight_kg']:,} kg | PKR {refresh_summary['freight_cost_pkr']:,} | Unknown rows {refresh_summary['unknown_rows']}\n"
        f"Status values: {refresh_summary['status_count']} | Delayed rows: {refresh_summary['delayed_rows']}\n",
        encoding="utf-8")
    try:
        create_refresh_image(args.output_dir / "Refresh_Comparison.png", first, refresh_summary)
    except Exception as exc:
        print(f"Optional refresh image skipped: {exc}")


def create_refresh_image(path: Path, before: dict, after: dict):
    """Optional screenshot-style proof; Pillow is not needed for the ETL itself."""
    from PIL import Image, ImageDraw, ImageFont
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1500, 730), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=25)
    small = ImageFont.load_default(size=19)
    draw.rounded_rectangle((35,30,1465,125), radius=18, fill="#12243a")
    draw.text((70,58), "PakFreight Week 5  |  Python ETL Refresh Check", fill="white", font=font)
    headers=["Measure","Night 1","Night 2","Expected change"]
    xs=[70,500,770,1050]
    draw.rounded_rectangle((45,160,1455,220), radius=10, fill="#dbe8f5")
    for x,t in zip(xs,headers): draw.text((x,178),t,fill="#15283e",font=small)
    rows=[
      ("FactShipment rows",str(before["fact_rows"]),str(after["fact_rows"]),"+1 new consignment"),
      ("Weight (kg)",f'{before["weight_kg"]:,}',f'{after["weight_kg"]:,}',"+6,300 kg"),
      ("Freight cost (PKR)",f'{before["freight_cost_pkr"]:,}',f'{after["freight_cost_pkr"]:,}',"+52,000 PKR"),
      ("Distinct statuses",str(before["status_count"]),str(after["status_count"]),"stays at 3"),
      ("Rows routed to Unknown",str(before["unknown_rows"]),str(after["unknown_rows"]),"Chaman Border: 1"),
      ("Delayed rows",str(before["delayed_rows"]),str(after["delayed_rows"]),"4 -> 5"),
    ]
    y=250
    for i,row in enumerate(rows):
        fill="#ffffff" if i%2==0 else "#eaf0f6"
        draw.rounded_rectangle((45,y-12,1455,y+55),radius=8,fill=fill)
        for x,t in zip(xs,row): draw.text((x,y+5),t,fill="#20364f",font=small)
        y+=78
    draw.text((70,690),"Every source and transformation frame is retained by name; unresolved cities are logged, not dropped.",fill="#52677f",font=small)
    image.save(path)

if __name__ == "__main__":
    main()
