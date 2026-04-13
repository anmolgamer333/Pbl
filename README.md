# Integrated LCA-LCCA Pavement Web App (PBL)

Local Streamlit web app for deterministic agency-cost LCCA and materials-based LCA of four asphalt pavement alternatives for **1 lane-km**.

## Scope
- Functional unit: 1 lane-km
- Default lane width: 3.5 m (area = 3500 m2)
- Length: fixed at 1000 m
- Analysis period: default 20 years (editable)
- Design traffic: default 40 MSA (reporting input)
- Effective subgrade CBR: default 8% (reporting input)
- Alternatives:
  - A1 Porous + Fiber
  - A2 Porous - Fiber
  - A3 Dense + Fiber
  - A4 Dense - Fiber

## Important Design Note
Layer thicknesses in the app are prefilled as an **initial trial** for iterative design updates.
The app does **not** claim they are final IRC values.

## Features
- Editable trial pavement layers table (BC, DBM, WMM, GSB, Subgrade)
- Mix inputs by alternative (binder %, cellulose fiber %)
- LCCA (agency costs only):
  - Initial construction
  - Optional transport cost in initial construction (`Rs/ton-km` with material distances)
  - Maintenance/rehab events
  - Salvage at year 20 (entered as positive value, internally treated as negative cost)
  - Deterministic NPV at 3%, 4%, 6%
- LCA (materials-based):
  - GWP (kg CO2-eq)
  - Energy (MJ)
  - User-supplied factors only (no invented factors)
  - Optional transport impacts (per ton-km and distances)
- On-screen tables and matplotlib bar charts
- Exports:
  - Excel workbook
  - CSV summary

## File Structure
- `app.py` - Streamlit UI and orchestration
- `model.py` - pure calculation functions (area, quantities, LCA, LCCA, NPV)
- `export_excel.py` - Excel workbook generation with required sheets
- `tests/test_model.py` - minimal unit tests for NPV
- `requirements.txt` - Python dependencies

## Installation
```bash
pip install -r requirements.txt
```

## Run App
```bash
streamlit run app.py
```

## Run Tests
```bash
pytest -q
```
If `pytest` command is not in PATH, run:
```bash
python -m pytest -q
```

## Calculation Logic

### 1) Quantities (per lane-km)
- Area = lane_width * 1000
- For each layer:
  - Volume = area * thickness
  - Mass = volume * density
- Asphalt layers are split by alternative-specific mix percentages:
  - binder_kg = asphalt_mix_kg * binder%
  - fiber_kg = asphalt_mix_kg * fiber%
  - aggregate_kg = asphalt_mix_kg - binder_kg - fiber_kg
- Non-asphalt layers can be included as aggregate-like mass using the checkbox.

### 2) LCCA
- Initial construction cost per alternative:
  - aggregate_kg * aggregate_rate
  - binder_kg * binder_rate
  - fiber_kg * fiber_rate
  - + optional laying_rate_per_m2 * area
- Event schedule:
  - Year 0 initial construction
  - User maintenance/rehab events
  - Salvage at year 20 (negative cost)
- NPV:
  - NPV = sum(cost_t / (1+r)^t)
  - rates: 3%, 4%, 6%

### 3) LCA
- Materials impacts from user-entered factors:
  - GWP = sum(mass_kg * factor_kgCO2e_per_kg)
  - Energy = sum(mass_kg * factor_MJ_per_kg)
- Optional transport impacts:
  - ton-km = mass_ton * distance_km
  - Added using user transport factors for GWP and energy

## Excel Export Sheets
Workbook includes:
- `Inputs` - geometry and design reporting inputs
- `Layers` - editable trial section used in run
- `Quantities` - per-alternative aggregate/binder/fiber masses
- `LCA` - GWP, Energy, and transport contributions
- `LCCA` - NPV sensitivity table
- `Summary` - merged LCA + LCCA headline outputs

Also included as extra transparency sheets:
- `LCCA_Events`
- `Layer_Quantities`
- `Maintenance`

## Assumptions
- LCCA is agency-cost only.
- Inputs for emission factors and unit costs are placeholders entered by the user.
- No default market costs or literature emission factors are hardcoded.
- Subgrade thickness is treated as 0 by default for quantity calculations (reporting layer).
- The trial layer set is editable and intended for iterative design, not final design declaration.

## Initial Trial Layer Prefill (Editable)
- BC: 40 mm
- DBM: 140 mm
- WMM: 250 mm
- GSB: 200 mm
- Subgrade: 0 mm (represents infinite/undefined thickness in this computational context)

## Suggested Workflow
1. Edit geometry/reporting inputs.
2. Update trial section and densities.
3. Set binder/fiber percentages for A1-A4.
4. Enter unit costs, maintenance schedule, and salvage values.
5. Enter LCA factors (required) and optional transport data.
6. Click **Run LCA + LCCA**.
7. Export Excel and CSV outputs.
