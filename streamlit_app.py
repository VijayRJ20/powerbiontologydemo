#!/usr/bin/env python3
"""
Streamlit UI for Power BI Ontology Extractor.

Browse entities, relationships, DAX measures, and business rules from a .pbix file.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from powerbi_ontology import PowerBIExtractor, OntologyGenerator, SchemaMapper
from powerbi_ontology.export import FabricIQExporter, OntoGuardExporter
from powerbi_ontology.ontology_generator import BusinessRule
from powerbi_ontology.utils.visualizer import OntologyVisualizer

ROOT = Path(__file__).resolve().parent
SAMPLE_PBIX = ROOT / "examples" / "sample_pbix" / "Supply_Chain_Operations.pbix"
OUTPUT_DIR = ROOT / "output"

st.set_page_config(
    page_title="Power BI Ontology Explorer",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap');

    :root {
      --ink: #0f1c24;
      --muted: #5a6b75;
      --sea: #0e7c6b;
      --sea-soft: #d7efe9;
      --sand: #f3eee4;
      --line: #d4cbc0;
    }

    html, body, [class*="css"] {
      font-family: "IBM Plex Sans", sans-serif;
      color: var(--ink);
    }

    .stApp {
      background:
        radial-gradient(1200px 500px at 10% -10%, #e6f4f0 0%, transparent 55%),
        radial-gradient(900px 400px at 100% 0%, #efe8da 0%, transparent 50%),
        linear-gradient(180deg, #faf8f4 0%, #f1ebe3 100%);
    }

    h1, h2, h3 {
      font-family: "IBM Plex Serif", Georgia, serif !important;
      letter-spacing: -0.02em;
    }

    .hero-brand {
      font-family: "IBM Plex Serif", Georgia, serif;
      font-size: 2.4rem;
      font-weight: 600;
      color: var(--ink);
      margin: 0 0 0.35rem 0;
      line-height: 1.15;
    }

    .hero-sub {
      color: var(--muted);
      font-size: 1.05rem;
      max-width: 42rem;
      margin: 0 0 1.5rem 0;
    }

    .metric-strip {
      display: flex;
      gap: 1.5rem;
      flex-wrap: wrap;
      margin: 0.5rem 0 1.25rem 0;
      padding: 0.85rem 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }

    .metric-item .label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }

    .metric-item .value {
      font-family: "IBM Plex Serif", Georgia, serif;
      font-size: 1.75rem;
      font-weight: 600;
      color: var(--sea);
      line-height: 1.2;
    }

    .entity-title {
      font-family: "IBM Plex Serif", Georgia, serif;
      font-size: 1.15rem;
      font-weight: 600;
      margin-bottom: 0.25rem;
    }

    .muted { color: var(--muted); font-size: 0.9rem; }

    div[data-testid="stSidebar"] {
      background: #0f1c24;
    }
    div[data-testid="stSidebar"] * {
      color: #e8ecee !important;
    }
    div[data-testid="stSidebar"] .stButton > button {
      background: var(--sea);
      border: none;
      color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def ensure_sample_pbix() -> Path:
    if SAMPLE_PBIX.exists():
        return SAMPLE_PBIX
    from scripts.build_sample_pbix import main as build_sample

    build_sample()
    return SAMPLE_PBIX


@st.cache_data(show_spinner=False)
def run_extraction(pbix_bytes: bytes, source_label: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pbix", delete=False) as tmp:
        tmp.write(pbix_bytes)
        tmp_path = tmp.name

    extractor = PowerBIExtractor(tmp_path)
    model = extractor.extract()
    ontology = OntologyGenerator(model).generate()

    # Demo analyst enhancement for the sample supply-chain model
    if any(e.name == "Shipment" for e in ontology.entities):
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

    fabric = FabricIQExporter(ontology).export()
    ontoguard = OntoGuardExporter(ontology).export()
    mermaid = OntologyVisualizer(ontology).export_mermaid_diagram()

    drift_note = None
    try:
        mapper = SchemaMapper(ontology, data_source="azure_sql")
        if any(e.name == "Shipment" for e in ontology.entities):
            binding = mapper.create_binding("Shipment", "dbo.shipments")
            drift = mapper.detect_drift(
                binding,
                {
                    "shipment_id": "GUID",
                    "customer_id": "GUID",
                    "warehouse_location": "String",
                    "temperature": "Decimal",
                    "status": "String",
                },
            )
            drift_note = getattr(drift, "severity", str(drift))
    except Exception as exc:  # noqa: BLE001
        drift_note = f"skipped ({exc})"

    return {
        "source_label": source_label,
        "model_name": model.name,
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
                        "description": p.description,
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
                "cross_filter": r.cross_filter_direction,
            }
            for r in model.relationships
        ],
        "measures": [
            {
                "name": m.name,
                "table": m.table,
                "dax_formula": m.dax_formula,
                "description": m.description,
            }
            for m in model.measures
        ],
        "security_rules": [
            {"role": s.role, "table": s.table, "dax_filter": s.dax_filter}
            for s in model.security_rules
        ],
        "ontology_name": ontology.name,
        "business_rules": [
            {
                "name": br.name,
                "entity": br.entity,
                "condition": br.condition,
                "action": br.action,
                "description": br.description,
                "source_measure": br.source_measure,
            }
            for br in ontology.business_rules
        ],
        "fabric_iq": fabric,
        "ontoguard": ontoguard,
        "mermaid": mermaid,
        "drift_note": drift_note,
        # Minimal graph inputs for Plotly rebuild (avoids caching figure objects)
        "graph_nodes": [
            {
                "name": e.name,
                "entity_type": getattr(e, "entity_type", "standard"),
                "property_count": len(e.properties),
            }
            for e in ontology.entities
        ],
        "graph_edges": [
            {
                "from": r.from_entity,
                "to": r.to_entity,
                "cardinality": r.cardinality,
                "relationship_type": r.relationship_type,
            }
            for r in ontology.relationships
        ],
    }


def build_plotly_graph(payload: dict):
    try:
        import networkx as nx
        import plotly.graph_objects as go
    except ImportError:
        return None

    nodes = payload.get("graph_nodes") or []
    edges = payload.get("graph_edges") or []
    if not nodes:
        return None

    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["name"], node_type=n.get("entity_type", "standard"), property_count=n.get("property_count", 0))
    for e in edges:
        G.add_edge(e["from"], e["to"], cardinality=e.get("cardinality", ""), relationship_type=e.get("relationship_type", ""))

    pos = nx.spring_layout(G, seed=42)
    edge_x, edge_y = [], []
    for a, b in G.edges():
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        line=dict(width=1.2, color="#8a9aa3"),
        hoverinfo="none",
        mode="lines",
    )

    node_x, node_y, text, colors = [], [], [], []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        meta = G.nodes[node]
        text.append(f"{node}<br>{meta.get('property_count', 0)} properties")
        colors.append("#0e7c6b")

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=[n for n in G.nodes()],
        textposition="top center",
        hovertext=text,
        hoverinfo="text",
        marker=dict(size=28, color=colors, line=dict(width=1.5, color="#0f1c24")),
    )

    return go.Figure(
        data=[edge_trace, node_trace],
        layout=go.Layout(
            title=dict(text=payload.get("ontology_name", "Ontology"), font=dict(size=16)),
            showlegend=False,
            hovermode="closest",
            margin=dict(b=20, l=10, r=10, t=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            height=520,
        ),
    )


def load_pbix_bytes(path: Path) -> bytes:
    return path.read_bytes()


with st.sidebar:
    st.markdown("### Source")
    source_mode = st.radio(
        "Load ontology from",
        ["Sample Supply Chain .pbix", "Upload your .pbix"],
        label_visibility="collapsed",
    )

    uploaded = None
    if source_mode == "Upload your .pbix":
        uploaded = st.file_uploader("Power BI file", type=["pbix"])

    extract_clicked = st.button("Extract ontology", type="primary", use_container_width=True)

    st.markdown("---")
    st.caption(
        "Extracts entities, relationships, DAX measures, and business rules "
        "from a Power BI semantic model into AI-ready ontology formats."
    )


st.markdown('<p class="hero-brand">Power BI Ontology Explorer</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-sub">Turn a Power BI semantic model into a readable ontology — '
    "entities, relationships, DAX-derived rules, and exportable Fabric IQ / OntoGuard JSON.</p>",
    unsafe_allow_html=True,
)

if extract_clicked or "ontology_payload" not in st.session_state:
    try:
        if source_mode == "Upload your .pbix":
            if uploaded is None:
                if "ontology_payload" not in st.session_state:
                    ensure_sample_pbix()
                    pbix_bytes = load_pbix_bytes(SAMPLE_PBIX)
                    label = str(SAMPLE_PBIX.name)
                    with st.spinner("Extracting sample ontology…"):
                        payload = run_extraction(pbix_bytes, label)
                    st.session_state.ontology_payload = payload
                    st.info("Using sample Supply_Chain_Operations.pbix — upload your own and click Extract to switch.")
            else:
                with st.spinner("Extracting ontology from uploaded .pbix…"):
                    payload = run_extraction(uploaded.getvalue(), uploaded.name)
                st.session_state.ontology_payload = payload
        else:
            ensure_sample_pbix()
            with st.spinner("Extracting ontology from sample .pbix…"):
                payload = run_extraction(load_pbix_bytes(SAMPLE_PBIX), SAMPLE_PBIX.name)
            st.session_state.ontology_payload = payload
    except Exception as exc:  # noqa: BLE001
        st.error(f"Extraction failed: {exc}")
        st.stop()

payload = st.session_state.ontology_payload
fig = build_plotly_graph(payload)

st.markdown(
    f"""
    <div class="metric-strip">
      <div class="metric-item"><div class="label">Model</div><div class="value" style="font-size:1.15rem">{payload['model_name']}</div></div>
      <div class="metric-item"><div class="label">Entities</div><div class="value">{len(payload['entities'])}</div></div>
      <div class="metric-item"><div class="label">Relationships</div><div class="value">{len(payload['relationships'])}</div></div>
      <div class="metric-item"><div class="label">Measures</div><div class="value">{len(payload['measures'])}</div></div>
      <div class="metric-item"><div class="label">Business rules</div><div class="value">{len(payload['business_rules'])}</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(f"Source: `{payload['source_label']}` · Ontology: **{payload['ontology_name']}**"
           + (f" · Schema drift: {payload['drift_note']}" if payload.get("drift_note") else ""))

tab_overview, tab_entities, tab_graph, tab_measures, tab_rules, tab_export = st.tabs(
    ["Overview", "Entities", "Graph", "DAX measures", "Business rules", "Export"]
)

with tab_overview:
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("What was unlocked")
        st.write(
            "This semantic model was an informal ontology trapped in a `.pbix` file. "
            "Extraction recovered tables as entities, joins as relationships, and DAX filters "
            "as candidate business rules."
        )
        rel_df = pd.DataFrame(payload["relationships"])
        if not rel_df.empty:
            rel_df["edge"] = (
                rel_df["from_entity"]
                + "."
                + rel_df["from_property"]
                + " → "
                + rel_df["to_entity"]
                + "."
                + rel_df["to_property"]
            )
            st.dataframe(
                rel_df[["name", "edge", "cardinality"]],
                use_container_width=True,
                hide_index=True,
            )
    with right:
        st.subheader("Security / RLS")
        if payload["security_rules"]:
            st.dataframe(pd.DataFrame(payload["security_rules"]), use_container_width=True, hide_index=True)
        else:
            st.caption("No RLS roles found in this model.")
        st.code(payload["mermaid"], language="mermaid")

with tab_entities:
    names = [e["name"] for e in payload["entities"]]
    selected = st.selectbox("Entity", names)
    entity = next(e for e in payload["entities"] if e["name"] == selected)
    st.markdown(
        f'<div class="entity-title">{entity["name"]}</div>'
        f'<div class="muted">Primary key: {entity.get("primary_key") or "—"} · '
        f'{entity.get("description") or "No description"}</div>',
        unsafe_allow_html=True,
    )
    props = pd.DataFrame(entity["properties"])
    st.dataframe(props, use_container_width=True, hide_index=True)

with tab_graph:
    st.subheader("Entity relationship graph")
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Interactive graph unavailable — Mermaid ER diagram shown instead.")
        st.code(payload["mermaid"], language="mermaid")

with tab_measures:
    st.subheader("DAX measures")
    for m in payload["measures"]:
        st.markdown(f"**{m['name']}** · `{m['table']}`")
        if m.get("description"):
            st.caption(m["description"])
        st.code(m["dax_formula"], language="dax")

with tab_rules:
    st.subheader("Business rules")
    st.caption("Auto-derived from DAX filters, plus optional analyst-authored rules.")
    rules_df = pd.DataFrame(payload["business_rules"])
    if rules_df.empty:
        st.info("No business rules extracted.")
    else:
        st.dataframe(rules_df, use_container_width=True, hide_index=True)

with tab_export:
    st.subheader("Download ontology exports")
    OUTPUT_DIR.mkdir(exist_ok=True)

    summary = {
        "model_name": payload["model_name"],
        "ontology_name": payload["ontology_name"],
        "entities": payload["entities"],
        "relationships": payload["relationships"],
        "measures": payload["measures"],
        "business_rules": payload["business_rules"],
    }

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Summary JSON",
            data=json.dumps(summary, indent=2),
            file_name="extracted_ontology_summary.json",
            mime="application/json",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "Fabric IQ JSON",
            data=json.dumps(payload["fabric_iq"], indent=2),
            file_name="fabric_iq_ontology.json",
            mime="application/json",
            use_container_width=True,
        )
    with c3:
        st.download_button(
            "OntoGuard JSON",
            data=json.dumps(payload["ontoguard"], indent=2),
            file_name="ontoguard_ontology.json",
            mime="application/json",
            use_container_width=True,
        )

    if st.button("Also save exports to ./output"):
        (OUTPUT_DIR / "extracted_ontology_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        (OUTPUT_DIR / "supply_chain_fabric_iq.json").write_text(
            json.dumps(payload["fabric_iq"], indent=2), encoding="utf-8"
        )
        (OUTPUT_DIR / "supply_chain_ontoguard.json").write_text(
            json.dumps(payload["ontoguard"], indent=2), encoding="utf-8"
        )
        st.success(f"Saved to {OUTPUT_DIR}")
