from __future__ import annotations

from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


DEFAULT_DISCOUNT_RATES = (0.03, 0.04, 0.06)


def lane_area_m2(lane_width_m: float, length_m: float = 1000.0) -> float:
    """Return lane area (m2) for given width and length."""
    return float(lane_width_m) * float(length_m)


def _safe_thickness_m(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        txt = value.strip().lower()
        if txt in {"", "na", "n/a", "none", "infinite", "inf", "-"}:
            return 0.0
        try:
            return float(txt) / 1000.0
        except ValueError:
            return 0.0
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def compute_layer_quantities(layers_df: pd.DataFrame, area_m2: float) -> pd.DataFrame:
    """Compute volume and mass per layer for a lane section."""
    df = layers_df.copy()
    df["Thickness_m"] = df["Thickness (mm)"].apply(_safe_thickness_m)
    df["Density (kg/m3)"] = pd.to_numeric(df["Density (kg/m3)"], errors="coerce").fillna(0.0)
    df["Volume_m3"] = area_m2 * df["Thickness_m"]
    df["Mass_kg"] = df["Volume_m3"] * df["Density (kg/m3)"]
    return df


def split_material_masses(
    quantities_df: pd.DataFrame,
    binder_pct: float,
    fiber_pct: float,
    include_non_asphalt_as_aggregate: bool = True,
) -> Dict[str, float]:
    """Split masses into aggregate, binder, fiber for one alternative."""
    binder_frac = max(float(binder_pct), 0.0) / 100.0
    fiber_frac = max(float(fiber_pct), 0.0) / 100.0

    if binder_frac + fiber_frac > 1.0:
        raise ValueError("Binder % + Fiber % cannot exceed 100%.")

    asphalt_mask = quantities_df["Is asphalt?"].astype(bool)
    asphalt_mass_kg = quantities_df.loc[asphalt_mask, "Mass_kg"].sum()

    binder_kg = asphalt_mass_kg * binder_frac
    fiber_kg = asphalt_mass_kg * fiber_frac
    aggregate_asphalt_kg = asphalt_mass_kg - binder_kg - fiber_kg

    aggregate_non_asphalt_kg = 0.0
    if include_non_asphalt_as_aggregate:
        aggregate_non_asphalt_kg = quantities_df.loc[~asphalt_mask, "Mass_kg"].sum()

    aggregate_kg = aggregate_asphalt_kg + aggregate_non_asphalt_kg

    return {
        "asphalt_mix_kg": float(asphalt_mass_kg),
        "aggregate_kg": float(aggregate_kg),
        "binder_kg": float(binder_kg),
        "fiber_kg": float(fiber_kg),
    }


def build_quantities_by_alternative(
    quantities_df: pd.DataFrame,
    alternatives_df: pd.DataFrame,
    include_non_asphalt_as_aggregate: bool = True,
) -> pd.DataFrame:
    """Build material quantities table for each alternative."""
    rows: List[Dict[str, float]] = []
    for _, alt in alternatives_df.iterrows():
        masses = split_material_masses(
            quantities_df=quantities_df,
            binder_pct=float(alt["Binder content (%)"]),
            fiber_pct=float(alt["Cellulose fiber content (%)"]),
            include_non_asphalt_as_aggregate=include_non_asphalt_as_aggregate,
        )
        rows.append(
            {
                "Alternative": alt["Alternative"],
                "Binder content (%)": float(alt["Binder content (%)"]),
                "Cellulose fiber content (%)": float(alt["Cellulose fiber content (%)"]),
                **masses,
            }
        )
    return pd.DataFrame(rows)


def compute_initial_construction_cost(
    quantities_by_alt_df: pd.DataFrame,
    unit_costs: Dict[str, float],
    area_m2: float,
) -> pd.DataFrame:
    """Compute deterministic initial agency construction cost."""
    agg_rate = float(unit_costs.get("aggregate_cost_per_kg", 0.0))
    binder_rate = float(unit_costs.get("binder_cost_per_kg", 0.0))
    fiber_rate = float(unit_costs.get("fiber_cost_per_kg", 0.0))
    laying_rate = float(unit_costs.get("laying_cost_per_m2", 0.0))

    out = quantities_by_alt_df.copy()
    out["Material_cost"] = (
        out["aggregate_kg"] * agg_rate
        + out["binder_kg"] * binder_rate
        + out["fiber_kg"] * fiber_rate
    )
    out["Laying_cost"] = laying_rate * area_m2
    out["Initial_cost"] = out["Material_cost"] + out["Laying_cost"]
    return out[["Alternative", "Material_cost", "Laying_cost", "Initial_cost"]]


def npv_from_events(events_df: pd.DataFrame, discount_rate: float) -> float:
    """Compute NPV from event cashflows where costs are positive, salvage negative."""
    if events_df.empty:
        return 0.0
    years = pd.to_numeric(events_df["Year"], errors="coerce").fillna(0.0)
    costs = pd.to_numeric(events_df["Cost"], errors="coerce").fillna(0.0)
    factors = np.power(1.0 + float(discount_rate), years)
    return float((costs / factors).sum())


def build_lcca_events(
    initial_costs_df: pd.DataFrame,
    maintenance_df: pd.DataFrame,
    salvage_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build full event schedule per alternative for LCCA."""
    rows: List[Dict[str, object]] = []

    for _, row in initial_costs_df.iterrows():
        rows.append(
            {
                "Alternative": row["Alternative"],
                "Year": 0,
                "Description": "Initial construction",
                "Cost": float(row["Initial_cost"]),
            }
        )

    if not maintenance_df.empty:
        m = maintenance_df.copy()
        m = m[m["Alternative"].notna()]
        for _, row in m.iterrows():
            rows.append(
                {
                    "Alternative": row["Alternative"],
                    "Year": float(row["Year"]),
                    "Description": row.get("Description", "Maintenance/Rehab"),
                    "Cost": float(row["Cost"]),
                }
            )

    if not salvage_df.empty:
        s = salvage_df.copy()
        for _, row in s.iterrows():
            rows.append(
                {
                    "Alternative": row["Alternative"],
                    "Year": float(row.get("Year", 20)),
                    "Description": "Salvage value",
                    "Cost": -abs(float(row["Salvage value"])),
                }
            )

    return pd.DataFrame(rows)


def compute_lcca_npvs(
    events_df: pd.DataFrame,
    discount_rates: Iterable[float] = DEFAULT_DISCOUNT_RATES,
) -> pd.DataFrame:
    """Compute NPV sensitivity by alternative and discount rate."""
    rows = []
    for alt in sorted(events_df["Alternative"].dropna().unique()):
        alt_events = events_df[events_df["Alternative"] == alt]
        row = {"Alternative": alt}
        for r in discount_rates:
            row[f"NPV_{int(round(r * 100))}%"] = npv_from_events(alt_events, r)
        rows.append(row)
    return pd.DataFrame(rows)


def compute_lca(
    quantities_by_alt_df: pd.DataFrame,
    factors: Dict[str, float],
    transport_enabled: bool = False,
    transport_distances_km: Dict[str, float] | None = None,
) -> pd.DataFrame:
    """Compute material-based LCA (GWP, Energy) with optional transport."""
    tdist = transport_distances_km or {}

    agg_gwp = float(factors.get("aggregate_gwp_per_kg", 0.0))
    agg_mj = float(factors.get("aggregate_energy_per_kg", 0.0))
    binder_gwp = float(factors.get("binder_gwp_per_kg", 0.0))
    binder_mj = float(factors.get("binder_energy_per_kg", 0.0))
    fiber_gwp = float(factors.get("fiber_gwp_per_kg", 0.0))
    fiber_mj = float(factors.get("fiber_energy_per_kg", 0.0))

    t_gwp = float(factors.get("transport_gwp_per_tkm", 0.0))
    t_mj = float(factors.get("transport_energy_per_tkm", 0.0))

    rows: List[Dict[str, float]] = []
    for _, row in quantities_by_alt_df.iterrows():
        agg_kg = float(row["aggregate_kg"])
        binder_kg = float(row["binder_kg"])
        fiber_kg = float(row["fiber_kg"])

        material_gwp = agg_kg * agg_gwp + binder_kg * binder_gwp + fiber_kg * fiber_gwp
        material_energy = agg_kg * agg_mj + binder_kg * binder_mj + fiber_kg * fiber_mj

        transport_gwp = 0.0
        transport_energy = 0.0
        if transport_enabled:
            agg_tkm = (agg_kg / 1000.0) * float(tdist.get("aggregate_distance_km", 0.0))
            binder_tkm = (binder_kg / 1000.0) * float(tdist.get("binder_distance_km", 0.0))
            fiber_tkm = (fiber_kg / 1000.0) * float(tdist.get("fiber_distance_km", 0.0))
            total_tkm = agg_tkm + binder_tkm + fiber_tkm
            transport_gwp = total_tkm * t_gwp
            transport_energy = total_tkm * t_mj

        rows.append(
            {
                "Alternative": row["Alternative"],
                "Aggregate_kg": agg_kg,
                "Binder_kg": binder_kg,
                "Fiber_kg": fiber_kg,
                "GWP_kgCO2e": material_gwp + transport_gwp,
                "Energy_MJ": material_energy + transport_energy,
                "Transport_GWP_kgCO2e": transport_gwp,
                "Transport_Energy_MJ": transport_energy,
            }
        )

    return pd.DataFrame(rows)
