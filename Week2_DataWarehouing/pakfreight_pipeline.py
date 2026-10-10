"""Repeatable PakFreight staging -> integration -> validation pipeline.

Run with the bundled Python or an environment containing pandas and openpyxl:
  python pakfreight_pipeline.py --data-dir <folder-with-source-files> --output-dir <output-folder>
The sources are opened read-only. Road rejects are recorded in staging_audit.csv.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

CONTRACT = ["ShipmentID", "ShipDate", "Origin", "Destination", "WeightKG", "CostPKR", "Status", "SourceSystem"]
FILES = {
    "marine": "marine_shipments.csv",
    "rail": "rail_shipments.xlsx",
    "road": "road_shipments.csv",
}

def clean_status(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.title()

def run(data_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = []

    # Marine: source CSV line = DataFrame row + header line.
    marine = pd.read_csv(data_dir / FILES["marine"], dtype={"Shipment_ID": "string"})
    m = pd.DataFrame({
        "ShipmentID": marine["Shipment_ID"].astype("string").str.strip(),
        "ShipDate": pd.to_datetime(marine["Ship_Date"], format="%d/%m/%Y", errors="raise"),
        "Origin": marine["Origin_Port"].astype("string").str.strip(),
        "Destination": marine["Dest_Port"].astype("string").str.strip(),
        "WeightKG": pd.to_numeric(marine["Weight_KG"], errors="raise"),
        "CostPKR": pd.to_numeric(marine["Cost_PKR"], errors="raise"),
        "Status": clean_status(marine["Status"]),
        "SourceSystem": "Marine",
    })[CONTRACT]
    for i in range(len(m)):
        audit.append({"SourceSystem":"Marine","SourceRow":i+2,"ShipmentID":m.loc[i,"ShipmentID"],"Decision":"KEEP","Reason":"Valid Marine shipment; source weight already kg; date parsed dd/mm/yyyy."})

    # Rail: Excel physical rows 1-2 are titles, row 3 is header, data starts row 4.
    rail = pd.read_excel(data_dir / FILES["rail"], sheet_name="Rail", skiprows=2, dtype={"Consignment No": "string"})
    r = pd.DataFrame({
        "ShipmentID": "RL-" + rail["Consignment No"].astype("string").str.strip(),
        "ShipDate": pd.to_datetime(rail["Dispatch Date"], errors="raise"),
        "Origin": rail["From Station"].astype("string").str.strip(),
        "Destination": rail["To Station"].astype("string").str.strip(),
        "WeightKG": pd.to_numeric(rail["Weight (Tons)"], errors="raise") * 1000,
        "CostPKR": pd.to_numeric(rail["Freight Charges (PKR)"], errors="raise"),
        "Status": clean_status(rail["Status"]),
        "SourceSystem": "Rail",
    })[CONTRACT]
    for i in range(len(r)):
        audit.append({"SourceSystem":"Rail","SourceRow":i+4,"ShipmentID":r.loc[i,"ShipmentID"],"Decision":"KEEP","Reason":"Valid Rail shipment; skipped two title rows; tonnes converted to kg; ID prefixed RL-."})

    # Keep blank CSV lines visible so the excluded row is auditable. CSV physical line = row + header.
    road = pd.read_csv(data_dir / FILES["road"], dtype="string", keep_default_na=False, skip_blank_lines=False)
    road_rows = []
    seen = set()
    for i, raw in road.iterrows():
        line = i + 2
        raw_id = str(raw["trip_id"]).strip()
        sid = raw_id.upper() if raw_id else ""
        if not raw_id and all(not str(v).strip() for v in raw.tolist()):
            decision, reason = "REMOVE", "Blank row: no shipment values."
        elif sid == "TOTAL":
            decision, reason = "REMOVE", "TOTAL aggregate row, not a shipment; would double-count the source subtotal."
        elif sid in seen:
            decision, reason = "REMOVE", "Duplicate ShipmentID; first occurrence retained."
        else:
            seen.add(sid)
            decision, reason = "KEEP", "Valid Road shipment; ID uppercased; source weight already kg."
        audit.append({"SourceSystem":"Road","SourceRow":line,"ShipmentID":sid or "(blank)","Decision":decision,"Reason":reason})
        if decision == "KEEP":
            road_rows.append({
                "ShipmentID": sid,
                "ShipDate": pd.to_datetime(raw["trip_date"], format="%Y-%m-%d", errors="raise"),
                "Origin": raw["from_city"].strip(),
                "Destination": raw["to_city"].strip(),
                "WeightKG": int(raw["weight_kg"]),
                "CostPKR": int(raw["cost_pkr"]),
                "Status": raw["status"].strip().title(),
                "SourceSystem": "Road",
            })
    d = pd.DataFrame(road_rows, columns=CONTRACT)
    shipments = pd.concat([m, r, d], ignore_index=True)[CONTRACT]
    shipments["WeightKG"] = pd.to_numeric(shipments["WeightKG"], errors="raise")
    shipments["CostPKR"] = pd.to_numeric(shipments["CostPKR"], errors="raise").astype("int64")
    shipments["ShipDate"] = pd.to_datetime(shipments["ShipDate"], errors="raise").dt.strftime("%Y-%m-%d")

    expected_rows = {"Marine": 12, "Rail": 10, "Road": 12}
    expected_kg = {"Marine": 206500, "Rail": 295250, "Road": 76900}
    mode_rows = shipments.groupby("SourceSystem").size().to_dict()
    mode_kg = shipments.groupby("SourceSystem")["WeightKG"].sum().astype(int).to_dict()
    status_counts = shipments["Status"].value_counts().to_dict()
    checks = {
        "exact_columns": shipments.columns.tolist() == CONTRACT,
        "row_count_34": len(shipments) == 34,
        "no_missing_key_date_weight": not shipments[["ShipmentID","ShipDate","WeightKG"]].isna().any().any(),
        "unique_shipment_ids": shipments["ShipmentID"].is_unique,
        "exactly_three_statuses": set(status_counts) == {"Delivered","In Transit","Delayed"},
        "status_counts": status_counts == {"Delivered":22,"In Transit":8,"Delayed":4},
        "weight_total_578650kg": int(shipments["WeightKG"].sum()) == 578650,
        "mode_row_counts": mode_rows == expected_rows,
        "mode_weight_totals": mode_kg == expected_kg,
        "road_removed_exactly_three": sum(x["SourceSystem"]=="Road" and x["Decision"]=="REMOVE" for x in audit) == 3,
    }
    if not all(checks.values()):
        raise ValueError("Validation failed: " + json.dumps(checks, ensure_ascii=False))

    shipments.to_csv(output_dir / "Shipments.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(audit).to_csv(output_dir / "staging_audit.csv", index=False, encoding="utf-8-sig")
    summary = {
        "result":"PASS", "rows":len(shipments), "columns":CONTRACT,
        "total_weight_kg":int(shipments["WeightKG"].sum()), "total_weight_tonnes":int(shipments["WeightKG"].sum())/1000,
        "mode_rows":mode_rows, "mode_weight_kg":mode_kg, "status_counts":status_counts,
        "raw_rows":{"Marine":len(m),"Rail":len(r),"Road":len(road)},
        "removed_road_rows":[x for x in audit if x["SourceSystem"]=="Road" and x["Decision"]=="REMOVE"],
        "checks":checks,
    }
    (output_dir / "validation.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build and validate the PakFreight Shipments table.")
    ap.add_argument("--data-dir", type=Path, default=Path(r"C:\Users\HP\Downloads\Week2Datawarehouing"))
    ap.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    print(json.dumps(run(args.data_dir, args.output_dir), indent=2, ensure_ascii=False))
