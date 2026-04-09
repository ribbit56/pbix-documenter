"""
Loads a .pbix file using pbixray and returns raw data as a PbixData bundle.
pbixray handles XPress9 decompression natively — no external tools required.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pbixray import PBIXRay


@dataclass
class PbixData:
    """All raw data extracted from a .pbix file."""
    pbix_path: Path
    tables: list[str]                   # All table names
    measures: pd.DataFrame              # TableName, Name, Expression, DisplayFolder, Description
    relationships: pd.DataFrame         # FromTableName, FromColumnName, ToTableName, ToColumnName, IsActive, Cardinality, CrossFilteringBehavior, ...
    schema: pd.DataFrame                # TableName, ColumnName, PandasDataType
    power_query: pd.DataFrame           # TableName, Expression (full M code)
    dax_tables: pd.DataFrame            # TableName, Expression (calculated tables)
    dax_columns: pd.DataFrame           # Calculated columns
    rls: pd.DataFrame                   # Row-level security
    report_layout_bytes: bytes | None   # Raw bytes of Report/Layout for visual parsing


def extract(pbix_path: str | Path) -> PbixData:
    pbix_path = Path(pbix_path).resolve()
    if not pbix_path.exists():
        raise FileNotFoundError(f"File not found: {pbix_path}")

    p = PBIXRay(str(pbix_path))

    # Safely read each DataFrame, returning empty DF on failure
    def safe(attr: str) -> pd.DataFrame:
        try:
            val = getattr(p, attr)
            return val if isinstance(val, pd.DataFrame) else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    tables: list[str] = []
    try:
        tables = list(p.tables) if p.tables is not None else []
    except Exception:
        pass

    # Extract Report/Layout bytes directly from the ZIP for the report parser
    report_layout_bytes = None
    try:
        with zipfile.ZipFile(pbix_path, "r") as z:
            if "Report/Layout" in z.namelist():
                report_layout_bytes = z.read("Report/Layout")
    except Exception:
        pass

    return PbixData(
        pbix_path=pbix_path,
        tables=tables,
        measures=safe("dax_measures"),
        relationships=safe("relationships"),
        schema=safe("schema"),
        power_query=safe("power_query"),
        dax_tables=safe("dax_tables"),
        dax_columns=safe("dax_columns"),
        rls=safe("rls"),
        report_layout_bytes=report_layout_bytes,
    )
