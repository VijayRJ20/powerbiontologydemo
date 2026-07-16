#!/usr/bin/env python3
"""
Run Power BI ontology extraction on the sample Supply_Chain_Operations.pbix.

Usage:
  python scripts/build_sample_pbix.py
  python run_extract_ontology.py

Outputs land in ./output/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from powerbi_ontology import PowerBIExtractor, OntologyGenerator, ContractBuilder, SchemaMapper
from powerbi_ontology.export import FabricIQExporter, OntoGuardExporter
from powerbi_ontology.ontology_generator import BusinessRule

PBIX = ROOT / "examples" / "sample_pbix" / "Supply_Chain_Operations.pbix"
OUT = ROOT / "output"


def _summarize(model, ontology) -> dict:
    return {
        "model_name": model.name,
        "source_file": str(model.source_file),
        "entities": [
            {
                "name": e.name,
                "primary_key": e.primary_key,
                "properties": [p.name for p in e.properties],
            }
            for e in model.entities
        ],
        "relationships": [
            {
                "name": r.name,
                "from": f"{r.from_entity}.{r.from_property}",
                "to": f"{r.to_entity}.{r.to_property}",
                "cardinality": r.cardinality,
            }
            for r in model.relationships
        ],
        "measures": [
            {
                "name": m.name,
                "table": m.table,
                "dax": m.dax_formula,
            }
            for m in model.measures
        ],
        "ontology": {
            "name": ontology.name,
            "entity_count": len(ontology.entities),
            "relationship_count": len(ontology.relationships),
            "business_rule_count": len(ontology.business_rules),
            "business_rules": [
                {
                    "name": br.name,
                    "entity": br.entity,
                    "condition": br.condition,
                    "action": br.action,
                    "source_measure": br.source_measure,
                }
                for br in ontology.business_rules
            ],
        },
    }


def main() -> None:
    if not PBIX.exists():
        print(f"Sample PBIX missing: {PBIX}")
        print("Building it now via scripts/build_sample_pbix.py ...")
        from scripts.build_sample_pbix import main as build

        build()

    OUT.mkdir(exist_ok=True)

    print("=" * 72)
    print("PowerBI Ontology Extractor — sample run")
    print("=" * 72)
    print(f"Input: {PBIX}\n")

    print("1) Extract semantic model from .pbix")
    extractor = PowerBIExtractor(str(PBIX))
    model = extractor.extract()
    print(f"   entities={len(model.entities)} relationships={len(model.relationships)} measures={len(model.measures)}")

    print("2) Generate ontology")
    ontology = OntologyGenerator(model).generate()
    print(
        f"   ontology={ontology.name} entities={len(ontology.entities)} "
        f"rules={len(ontology.business_rules)}"
    )

    print("3) Add analyst business rule (the missing ~30%)")
    ontology.add_business_rule(
        BusinessRule(
            name="RerouteApproval",
            entity="Shipment",
            condition="Shipment.RiskScore > 80",
            action="RerouteShipment",
            description="High-risk shipments require manager approval for rerouting",
            priority=1,
        )
    )

    print("4) Schema binding + drift check")
    mapper = SchemaMapper(ontology, data_source="azure_sql")
    binding = mapper.create_binding("Shipment", "dbo.shipments")
    current_schema = {
        "shipment_id": "GUID",
        "customer_id": "GUID",
        "warehouse_location": "String",
        "temperature": "Decimal",
        "status": "String",
    }
    drift = mapper.detect_drift(binding, current_schema)
    print(f"   drift severity={getattr(drift, 'severity', drift)}")

    print("5) Semantic contract for AI agent")
    contract = ContractBuilder(ontology).build_contract(
        agent_name="SupplyChainMonitor",
        permissions={
            "read": ["Shipment", "Customer", "Warehouse"],
            "write": {"Shipment": ["Status"]},
            "execute": ["RerouteShipment", "NotifyCustomer"],
            "role": "Operations_Manager",
        },
    )
    print(f"   contract agent={contract.agent_name}")

    print("6) Export Fabric IQ + OntoGuard + summary")
    fabric = FabricIQExporter(ontology).export()
    ontoguard = OntoGuardExporter(ontology).export()
    summary = _summarize(model, ontology)

    fabric_path = OUT / "supply_chain_fabric_iq.json"
    ontoguard_path = OUT / "supply_chain_ontoguard.json"
    summary_path = OUT / "extracted_ontology_summary.json"
    model_path = OUT / "semantic_model.json"

    fabric_path.write_text(json.dumps(fabric, indent=2), encoding="utf-8")
    ontoguard_path.write_text(json.dumps(ontoguard, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Lightweight model dump for inspection
    model_dump = {
        "name": model.name,
        "entities": [
            {
                "name": e.name,
                "description": e.description,
                "primary_key": e.primary_key,
                "properties": [
                    {
                        "name": p.name,
                        "data_type": p.data_type,
                        "required": p.required,
                        "unique": p.unique,
                    }
                    for p in e.properties
                ],
            }
            for e in model.entities
        ],
        "relationships": [
            {
                "name": r.name,
                "from_entity": r.from_entity,
                "from_property": r.from_property,
                "to_entity": r.to_entity,
                "to_property": r.to_property,
                "cardinality": r.cardinality,
            }
            for r in model.relationships
        ],
        "measures": [
            {"name": m.name, "table": m.table, "dax_formula": m.dax_formula}
            for m in model.measures
        ],
        "security_rules": [
            {"role": s.role, "table": s.table, "dax_filter": s.dax_filter}
            for s in model.security_rules
        ],
    }
    model_path.write_text(json.dumps(model_dump, indent=2), encoding="utf-8")

    print()
    print("Wrote:")
    for p in (summary_path, model_path, fabric_path, ontoguard_path):
        print(f"  - {p}")
    print()
    print("Ontology snapshot:")
    print(json.dumps(summary["ontology"], indent=2))
    print("=" * 72)
    print("Done. Open output/extracted_ontology_summary.json to review.")


if __name__ == "__main__":
    main()
