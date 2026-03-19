from __future__ import annotations

from io import BytesIO
from typing import Dict

import pandas as pd


def _write_df(writer: pd.ExcelWriter, name: str, df: pd.DataFrame) -> None:
    safe_name = name[:31]
    df.to_excel(writer, sheet_name=safe_name, index=False)


def build_excel_workbook_bytes(
    inputs_df: pd.DataFrame,
    layers_df: pd.DataFrame,
    quantities_df: pd.DataFrame,
    lca_df: pd.DataFrame,
    lcca_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    extra_sheets: Dict[str, pd.DataFrame] | None = None,
) -> bytes:
    """Create workbook bytes with fixed core sheets and optional extras."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        _write_df(writer, "Inputs", inputs_df)
        _write_df(writer, "Layers", layers_df)
        _write_df(writer, "Quantities", quantities_df)
        _write_df(writer, "LCA", lca_df)
        _write_df(writer, "LCCA", lcca_df)
        _write_df(writer, "Summary", summary_df)

        if extra_sheets:
            for name, df in extra_sheets.items():
                _write_df(writer, name, df)

    output.seek(0)
    return output.getvalue()
