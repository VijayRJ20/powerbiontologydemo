#!/usr/bin/env python3
"""
Build examples/sample_pbix/Supply_Chain_Operations.pbix from the repo fixture.

Real .pbix binaries are not committed to the GitHub repo (only .gitkeep).
This script packs tests/fixtures/sample_model.json into a valid .pbix ZIP
so the extractor can run end-to-end locally.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample_model.json"
OUT_DIR = ROOT / "examples" / "sample_pbix"
OUT_PBIX = OUT_DIR / "Supply_Chain_Operations.pbix"


def enrich_model(model: dict) -> dict:
    """Add entities/measures that match the README supply-chain story."""
    model = dict(model)
    model["name"] = "Supply_Chain_Operations"

    tables = {t["name"]: t for t in model.get("tables", [])}

    if "IoTSensor" not in tables:
        tables["IoTSensor"] = {
            "name": "IoTSensor",
            "description": "IoT sensors attached to shipments",
            "columns": [
                {"name": "SensorID", "dataType": "string", "isKey": True, "isNullable": False},
                {"name": "ShipmentID", "dataType": "string", "isNullable": False},
                {"name": "Temperature", "dataType": "double", "isNullable": True},
                {"name": "Vibration", "dataType": "double", "isNullable": True},
                {"name": "ReadingTime", "dataType": "datetime", "isNullable": True},
            ],
            "measures": [
                {
                    "name": "High Vibration Alerts",
                    "expression": "CALCULATE(COUNT(IoTSensor[SensorID]), IoTSensor[Vibration] > 5)",
                    "description": "Count of high vibration sensor readings",
                }
            ],
        }

    if "ComplianceRule" not in tables:
        tables["ComplianceRule"] = {
            "name": "ComplianceRule",
            "description": "Compliance rules for shipments",
            "columns": [
                {"name": "RuleID", "dataType": "string", "isKey": True, "isNullable": False},
                {"name": "RuleName", "dataType": "string", "isNullable": False},
                {"name": "ThresholdTemp", "dataType": "double", "isNullable": True},
                {"name": "ThresholdVibration", "dataType": "double", "isNullable": True},
            ],
            "measures": [],
        }

    # Extra DAX measure on Shipment if missing
    shipment = tables.get("Shipment")
    if shipment is not None:
        measure_names = {m["name"] for m in shipment.get("measures", [])}
        if "Delayed Shipments" not in measure_names:
            shipment.setdefault("measures", []).append(
                {
                    "name": "Delayed Shipments",
                    "expression": "CALCULATE(COUNT(Shipment[ShipmentID]), Shipment[Status] = \"Delayed\")",
                    "description": "Count of delayed shipments",
                }
            )

    model["tables"] = list(tables.values())

    relationships = list(model.get("relationships", []))
    existing = {(r.get("fromTable"), r.get("toTable")) for r in relationships}
    if ("IoTSensor", "Shipment") not in existing:
        relationships.append(
            {
                "name": "IoTSensor_Shipment",
                "fromTable": "IoTSensor",
                "fromColumn": "ShipmentID",
                "toTable": "Shipment",
                "toColumn": "ShipmentID",
                "fromCardinality": "many",
                "toCardinality": "one",
                "crossFilteringBehavior": "singleDirection",
                "isActive": True,
            }
        )
    model["relationships"] = relationships
    return model


def main() -> None:
    if not FIXTURE.exists():
        raise SystemExit(f"Fixture not found: {FIXTURE}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = enrich_model(json.loads(FIXTURE.read_text(encoding="utf-8")))

    with zipfile.ZipFile(OUT_PBIX, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("DataModel/model.bim", json.dumps(model, indent=2))
        zf.writestr(
            "Report/report.json",
            json.dumps(
                {
                    "name": "Supply Chain Operations",
                    "pages": [{"name": "Overview", "displayName": "Overview"}],
                },
                indent=2,
            ),
        )
        zf.writestr(
            "Version",
            "1.0",
        )

    print(f"Created: {OUT_PBIX}")
    print(f"  Tables: {[t['name'] for t in model['tables']]}")
    print(f"  Relationships: {len(model['relationships'])}")


if __name__ == "__main__":
    main()
