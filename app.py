from __future__ import annotations

from io import StringIO
from typing import Dict, List

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from export_excel import build_excel_workbook_bytes
from model import (
    DEFAULT_DISCOUNT_RATES,
    build_lcca_events,
    build_quantities_by_alternative,
    compute_initial_construction_cost,
    compute_layer_quantities,
    compute_lca,
    compute_lcca_npvs,
    lane_area_m2,
)


st.set_page_config(page_title="Integrated LCA-LCCA Pavement App", layout="wide")
st.title("Integrated LCA-LCCA: Porous vs Dense Asphalt (1 lane-km)")
st.caption(
    "Study scope: deterministic agency-cost LCCA + materials-based LCA. "
    "Layer thicknesses are editable trial values for iterative design updates."
)

ALT_NAMES = [
    "A1 Porous + Fiber",
    "A2 Porous - Fiber",
    "A3 Dense + Fiber",
    "A4 Dense - Fiber",
]


@st.cache_data
def default_layers_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Layer name": "BC",
                "Thickness (mm)": 40.0,
                "Density (kg/m3)": 2400.0,
                "Is asphalt?": True,
                "Elastic modulus (MPa)": "",
                "Poisson ratio": "",
            },
            {
                "Layer name": "DBM",
                "Thickness (mm)": 140.0,
                "Density (kg/m3)": 2400.0,
                "Is asphalt?": True,
                "Elastic modulus (MPa)": "",
                "Poisson ratio": "",
            },
            {
                "Layer name": "WMM",
                "Thickness (mm)": 250.0,
                "Density (kg/m3)": 2300.0,
                "Is asphalt?": False,
                "Elastic modulus (MPa)": "",
                "Poisson ratio": "",
            },
            {
                "Layer name": "GSB",
                "Thickness (mm)": 200.0,
                "Density (kg/m3)": 2200.0,
                "Is asphalt?": False,
                "Elastic modulus (MPa)": "",
                "Poisson ratio": "",
            },
            {
                "Layer name": "Subgrade",
                "Thickness (mm)": 0.0,
                "Density (kg/m3)": 2000.0,
                "Is asphalt?": False,
                "Elastic modulus (MPa)": "",
                "Poisson ratio": "",
            },
        ]
    )


@st.cache_data
def default_alt_mix_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Alternative": ALT_NAMES[0], "Binder content (%)": 5.5, "Cellulose fiber content (%)": 0.3},
            {"Alternative": ALT_NAMES[1], "Binder content (%)": 5.5, "Cellulose fiber content (%)": 0.0},
            {"Alternative": ALT_NAMES[2], "Binder content (%)": 5.0, "Cellulose fiber content (%)": 0.3},
            {"Alternative": ALT_NAMES[3], "Binder content (%)": 5.0, "Cellulose fiber content (%)": 0.0},
        ]
    )


def _ensure_alternative(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if "Alternative" not in data.columns:
        data["Alternative"] = ALT_NAMES[0]
    data["Alternative"] = data["Alternative"].fillna(ALT_NAMES[0])
    return data


def _auto_maintenance_schedule(initial_costs_df: pd.DataFrame, analysis_period: int) -> pd.DataFrame:
    schedule_templates = [
        {
            "annual_pct": 1.0,
            "annual_desc": "Routine cleaning (annual)",
            "events": [(10, "Surface renewal / thin overlay", 18.0), (15, "Major maintenance", 12.0)],
        },
        {
            "annual_pct": 1.2,
            "annual_desc": "Routine cleaning (annual)",
            "events": [(8, "Surface renewal / thin overlay", 18.0), (14, "Major maintenance", 12.0)],
        },
        {
            "annual_pct": 0.0,
            "annual_desc": "",
            "events": [(5, "Preventive maintenance", 6.0), (10, "Overlay", 22.0), (15, "Preventive maintenance", 6.0)],
        },
        {
            "annual_pct": 0.0,
            "annual_desc": "",
            "events": [(4, "Preventive maintenance", 6.0), (9, "Overlay", 22.0), (14, "Preventive maintenance", 6.0)],
        },
    ]

    rows: List[Dict[str, object]] = []
    for i, (_, ic_row) in enumerate(initial_costs_df.iterrows()):
        alt = ic_row["Alternative"]
        ic_alt = float(ic_row["Initial_cost"])
        tmpl = schedule_templates[i] if i < len(schedule_templates) else schedule_templates[-1]

        annual_pct = float(tmpl["annual_pct"])
        if annual_pct > 0.0:
            for year in range(1, analysis_period):
                rows.append(
                    {
                        "Alternative": alt,
                        "Year": year,
                        "Description": tmpl["annual_desc"],
                        "Cost": (annual_pct / 100.0) * ic_alt,
                    }
                )

        for year, desc, pct in tmpl["events"]:
            if year < analysis_period:
                rows.append(
                    {
                        "Alternative": alt,
                        "Year": year,
                        "Description": desc,
                        "Cost": (float(pct) / 100.0) * ic_alt,
                    }
                )

    return pd.DataFrame(rows)


def _auto_salvage_schedule(initial_costs_df: pd.DataFrame, analysis_period: int, salvage_pct: float) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for _, row in initial_costs_df.iterrows():
        rows.append(
            {
                "Alternative": row["Alternative"],
                "Year": analysis_period,
                "Salvage value": (float(salvage_pct) / 100.0) * float(row["Initial_cost"]),
            }
        )
    return pd.DataFrame(rows)


with st.sidebar:
    st.header("Project Metadata")
    lane_width_m = st.number_input("Lane width (m)", min_value=1.0, value=3.5, step=0.1)
    length_m = st.number_input("Length (m, fixed lane-km)", min_value=1000.0, value=1000.0, step=0.0, disabled=True)
    area_m2 = lane_area_m2(lane_width_m, length_m)
    st.metric("Area (m2)", f"{area_m2:,.2f}")

    analysis_period = st.number_input("Analysis period (years)", min_value=1, value=20, step=1)
    design_traffic_msa = st.number_input("Design traffic (MSA)", min_value=0.1, value=40.0, step=0.1)
    subgrade_cbr = st.number_input("Effective subgrade CBR (%)", min_value=1.0, value=8.0, step=0.1)

st.subheader("Pavement Layers")
st.info("Initial trial (edit as per design iterations)")
layers_df = st.data_editor(
    default_layers_df(),
    num_rows="dynamic",
    use_container_width=True,
    key="layers_editor",
)

st.subheader("Mix Inputs Per Alternative")
alt_mix_df = st.data_editor(
    default_alt_mix_df(),
    num_rows="dynamic",
    use_container_width=True,
    key="mix_editor",
)

st.subheader("Unit Costs")
c1, c2, c3, c4 = st.columns(4)
with c1:
    agg_rate = st.number_input("Aggregate cost (Rs/kg)", min_value=0.0, value=0.0, step=0.1)
with c2:
    binder_rate = st.number_input("Binder cost (Rs/kg)", min_value=0.0, value=0.0, step=0.1)
with c3:
    fiber_rate = st.number_input("Fiber cost (Rs/kg)", min_value=0.0, value=0.0, step=0.1)
with c4:
    laying_rate = st.number_input("Construction/Laying cost (Rs/m2, optional)", min_value=0.0, value=0.0, step=0.1)

st.subheader("Maintenance / Rehab + Salvage (LCCA)")
auto_lcca_schedule = st.toggle(
    "Auto-generate maintenance and salvage from initial cost (porous set higher maintenance)",
    value=True,
)

if auto_lcca_schedule:
    salvage_pct = st.number_input("Salvage at analysis year (% of initial cost)", min_value=0.0, value=15.0, step=0.5)
    st.caption(
        "Auto schedule baseline: A1/A2 (porous) include annual routine cleaning; "
        "A2 has slightly higher annual percentage than A1. A3/A4 (dense) use periodic preventive/overlay events."
    )
    maintenance_df = pd.DataFrame(columns=["Alternative", "Year", "Description", "Cost"])
    salvage_df = pd.DataFrame(columns=["Alternative", "Year", "Salvage value"])
else:
    salvage_pct = 15.0
    common_schedule = st.toggle("Use common maintenance/rehab schedule for all alternatives", value=True)
    if common_schedule:
        maint_common_df = st.data_editor(
            pd.DataFrame(
                [
                    {"Year": 5, "Description": "Routine maintenance", "Cost": 0.0},
                    {"Year": 10, "Description": "Rehabilitation", "Cost": 0.0},
                ]
            ),
            num_rows="dynamic",
            use_container_width=True,
            key="maint_common",
        )
        mc = maint_common_df.copy()
        maintenance_rows: List[Dict[str, object]] = []
        for alt in ALT_NAMES:
            for _, row in mc.iterrows():
                maintenance_rows.append(
                    {
                        "Alternative": alt,
                        "Year": row.get("Year", 0),
                        "Description": row.get("Description", "Maintenance/Rehab"),
                        "Cost": row.get("Cost", 0.0),
                    }
                )
        maintenance_df = pd.DataFrame(maintenance_rows)
    else:
        maintenance_df = st.data_editor(
            pd.DataFrame(
                [
                    {
                        "Alternative": ALT_NAMES[0],
                        "Year": 5,
                        "Description": "Routine maintenance",
                        "Cost": 0.0,
                    }
                ]
            ),
            num_rows="dynamic",
            use_container_width=True,
            key="maint_alt",
        )

    salvage_df = st.data_editor(
        pd.DataFrame(
            [
                {"Alternative": ALT_NAMES[0], "Year": analysis_period, "Salvage value": 0.0},
                {"Alternative": ALT_NAMES[1], "Year": analysis_period, "Salvage value": 0.0},
                {"Alternative": ALT_NAMES[2], "Year": analysis_period, "Salvage value": 0.0},
                {"Alternative": ALT_NAMES[3], "Year": analysis_period, "Salvage value": 0.0},
            ]
        ),
        num_rows="dynamic",
        use_container_width=True,
        key="salvage",
    )

st.subheader("LCA Emission/Energy Factors (Required)")
fg1, fg2, fg3 = st.columns(3)
with fg1:
    agg_gwp = st.number_input("Aggregate GWP (kgCO2e/kg)", min_value=0.0, value=0.0, step=0.001, format="%.6f")
    agg_energy = st.number_input("Aggregate Energy (MJ/kg)", min_value=0.0, value=0.0, step=0.001, format="%.6f")
with fg2:
    binder_gwp = st.number_input("Binder GWP (kgCO2e/kg)", min_value=0.0, value=0.0, step=0.001, format="%.6f")
    binder_energy = st.number_input("Binder Energy (MJ/kg)", min_value=0.0, value=0.0, step=0.001, format="%.6f")
with fg3:
    fiber_gwp = st.number_input("Fiber GWP (kgCO2e/kg)", min_value=0.0, value=0.0, step=0.001, format="%.6f")
    fiber_energy = st.number_input("Fiber Energy (MJ/kg)", min_value=0.0, value=0.0, step=0.001, format="%.6f")

include_non_asphalt_in_lca = st.checkbox(
    "Include non-asphalt layers as aggregate-like material in LCA/LCCA masses",
    value=True,
)

transport_enabled = st.toggle("Enable transport impacts", value=False)
if transport_enabled:
    t1, t2 = st.columns(2)
    with t1:
        t_gwp = st.number_input("Transport GWP (kgCO2e/ton-km)", min_value=0.0, value=0.0, step=0.0001, format="%.6f")
        t_energy = st.number_input("Transport Energy (MJ/ton-km)", min_value=0.0, value=0.0, step=0.0001, format="%.6f")
    with t2:
        d_agg = st.number_input("Aggregate transport distance (km)", min_value=0.0, value=0.0, step=1.0)
        d_binder = st.number_input("Binder transport distance (km)", min_value=0.0, value=0.0, step=1.0)
        d_fiber = st.number_input("Fiber transport distance (km)", min_value=0.0, value=0.0, step=1.0)
else:
    t_gwp = 0.0
    t_energy = 0.0
    d_agg = 0.0
    d_binder = 0.0
    d_fiber = 0.0

run = st.button("Run LCA + LCCA", type="primary")

if run:
    errors: List[str] = []

    if abs(length_m - 1000.0) > 1e-6:
        errors.append("Length must remain 1000 m for 1 lane-km functional unit.")

    layers_df = layers_df.copy()
    if "Layer name" not in layers_df.columns:
        errors.append("Layers table must contain 'Layer name' column.")
    if "Thickness (mm)" not in layers_df.columns or "Density (kg/m3)" not in layers_df.columns:
        errors.append("Layers table must contain 'Thickness (mm)' and 'Density (kg/m3)'.")

    alt_mix_df = _ensure_alternative(alt_mix_df)
    for col in ["Binder content (%)", "Cellulose fiber content (%)"]:
        if col not in alt_mix_df.columns:
            errors.append(f"Mix table missing column: {col}")

    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    try:
        layer_quantities_df = compute_layer_quantities(layers_df, area_m2)

        quantities_by_alt_df = build_quantities_by_alternative(
            quantities_df=layer_quantities_df,
            alternatives_df=alt_mix_df,
            include_non_asphalt_as_aggregate=include_non_asphalt_in_lca,
        )

        unit_costs = {
            "aggregate_cost_per_kg": agg_rate,
            "binder_cost_per_kg": binder_rate,
            "fiber_cost_per_kg": fiber_rate,
            "laying_cost_per_m2": laying_rate,
        }
        initial_costs_df = compute_initial_construction_cost(quantities_by_alt_df, unit_costs, area_m2)

        if auto_lcca_schedule:
            maintenance_df = _auto_maintenance_schedule(initial_costs_df, int(analysis_period))
            salvage_df = _auto_salvage_schedule(initial_costs_df, int(analysis_period), float(salvage_pct))
        else:
            maintenance_df = _ensure_alternative(maintenance_df)
            maintenance_df = maintenance_df[["Alternative", "Year", "Description", "Cost"]].copy()

            salvage_df = _ensure_alternative(salvage_df)
            if "Year" not in salvage_df.columns:
                salvage_df["Year"] = analysis_period

        events_df = build_lcca_events(initial_costs_df, maintenance_df, salvage_df)
        lcca_npvs_df = compute_lcca_npvs(events_df, DEFAULT_DISCOUNT_RATES)

        lca_factors = {
            "aggregate_gwp_per_kg": agg_gwp,
            "aggregate_energy_per_kg": agg_energy,
            "binder_gwp_per_kg": binder_gwp,
            "binder_energy_per_kg": binder_energy,
            "fiber_gwp_per_kg": fiber_gwp,
            "fiber_energy_per_kg": fiber_energy,
            "transport_gwp_per_tkm": t_gwp,
            "transport_energy_per_tkm": t_energy,
        }
        lca_df = compute_lca(
            quantities_by_alt_df=quantities_by_alt_df,
            factors=lca_factors,
            transport_enabled=transport_enabled,
            transport_distances_km={
                "aggregate_distance_km": d_agg,
                "binder_distance_km": d_binder,
                "fiber_distance_km": d_fiber,
            },
        )

    except Exception as exc:
        st.exception(exc)
        st.stop()

    st.success("Computation complete.")

    st.subheader("LCCA Results")
    st.dataframe(lcca_npvs_df, use_container_width=True)
    st.caption("LCCA event schedule used for NPV")
    st.dataframe(events_df.sort_values(["Alternative", "Year"]), use_container_width=True)

    rate_option = st.selectbox("NPV bar chart discount rate", ["NPV_3%", "NPV_4%", "NPV_6%"], index=1)
    fig1, ax1 = plt.subplots(figsize=(8, 4))
    ax1.bar(lcca_npvs_df["Alternative"], lcca_npvs_df[rate_option])
    ax1.set_ylabel("NPV (Rs)")
    ax1.set_title(f"LCCA NPV by Alternative ({rate_option.replace('NPV_', '')} discount)")
    ax1.tick_params(axis="x", rotation=20)
    st.pyplot(fig1)

    st.subheader("LCA Results")
    st.dataframe(lca_df, use_container_width=True)

    fig2, ax2 = plt.subplots(figsize=(8, 4))
    ax2.bar(lca_df["Alternative"], lca_df["GWP_kgCO2e"])
    ax2.set_ylabel("GWP (kg CO2-eq)")
    ax2.set_title("LCA GWP Totals by Alternative")
    ax2.tick_params(axis="x", rotation=20)
    st.pyplot(fig2)

    summary_df = lcca_npvs_df.merge(lca_df[["Alternative", "GWP_kgCO2e", "Energy_MJ"]], on="Alternative", how="left")

    inputs_df = pd.DataFrame(
        [
            {"Input": "Lane width (m)", "Value": lane_width_m},
            {"Input": "Length (m)", "Value": length_m},
            {"Input": "Area (m2)", "Value": area_m2},
            {"Input": "Analysis period (years)", "Value": analysis_period},
            {"Input": "Design traffic (MSA)", "Value": design_traffic_msa},
            {"Input": "Effective subgrade CBR (%)", "Value": subgrade_cbr},
            {"Input": "Note", "Value": "Layer thicknesses are trial values and must be iterated by design."},
        ]
    )

    excel_bytes = build_excel_workbook_bytes(
        inputs_df=inputs_df,
        layers_df=layers_df,
        quantities_df=quantities_by_alt_df,
        lca_df=lca_df,
        lcca_df=lcca_npvs_df,
        summary_df=summary_df,
        extra_sheets={
            "LCCA_Events": events_df,
            "Layer_Quantities": layer_quantities_df,
            "Maintenance": maintenance_df,
        },
    )

    csv_buffer = StringIO()
    summary_df.to_csv(csv_buffer, index=False)

    st.subheader("Downloads")
    st.download_button(
        "Download Excel Workbook",
        data=excel_bytes,
        file_name="lca_lcca_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        "Download CSV Summary",
        data=csv_buffer.getvalue(),
        file_name="lca_lcca_summary.csv",
        mime="text/csv",
    )

    st.caption(
        "LCA factors and unit costs are user-supplied placeholders by design. "
        "No default emission factors or market costs are hard-coded."
    )
