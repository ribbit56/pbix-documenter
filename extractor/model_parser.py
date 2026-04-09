"""
Builds a SemanticModel from the DataFrames returned by pbix_extractor.
"""
from __future__ import annotations

import re

import pandas as pd

from extractor.pbix_extractor import PbixData
from models.schema import (
    Column,
    Hierarchy,
    Measure,
    Relationship,
    Role,
    SemanticModel,
    Table,
)

# pbixray cardinality strings → our canonical form
_CARDINALITY_MAP = {
    "M:1": "many_to_one",
    "1:1": "one_to_one",
    "M:M": "many_to_many",
    "1:M": "one_to_many",
}

_CROSS_FILTER_MAP = {
    "Single": "single",
    "Both": "both",
    "OneDirection": "single",
    "BothDirections": "both",
}


def parse(data: PbixData) -> SemanticModel:
    # Skip internal auto-generated tables
    skip_prefixes = ("LocalDateTable_", "DateTableTemplate_")
    visible_tables = [t for t in data.tables if not any(t.startswith(p) for p in skip_prefixes)]

    # p.tables only includes tables with data rows; add any tables that only
    # appear as measure containers (e.g. "Key Measures" with no columns).
    if not data.measures.empty and "TableName" in data.measures.columns:
        seen = set(visible_tables)
        for tname in data.measures["TableName"].unique():
            if tname not in seen and not any(tname.startswith(p) for p in skip_prefixes):
                visible_tables.append(tname)

    tables = _build_tables(data, visible_tables)
    relationships = _build_relationships(data.relationships)
    roles = _build_roles(data.rls)

    return SemanticModel(
        name=data.pbix_path.stem,
        source_file=data.pbix_path.name,
        generated_at="",   # filled by caller
        tables=tables,
        relationships=relationships,
        roles=roles,
    )


def _build_tables(data: PbixData, table_names: list[str]) -> list[Table]:
    tables = []

    # Index DataFrames for fast lookup
    schema_by_table: dict[str, list] = {}
    if not data.schema.empty:
        for _, row in data.schema.iterrows():
            schema_by_table.setdefault(row["TableName"], []).append(row)

    measures_by_table: dict[str, list] = {}
    if not data.measures.empty:
        for _, row in data.measures.iterrows():
            measures_by_table.setdefault(row["TableName"], []).append(row)

    pq_by_table: dict[str, str] = {}
    if not data.power_query.empty:
        for _, row in data.power_query.iterrows():
            pq_by_table[row["TableName"]] = row["Expression"]

    calc_table_names: set[str] = set()
    if not data.dax_tables.empty and "TableName" in data.dax_tables.columns:
        calc_table_names = set(data.dax_tables["TableName"].tolist())

    calc_cols_by_table: dict[str, list] = {}
    if not data.dax_columns.empty and "TableName" in data.dax_columns.columns:
        for _, row in data.dax_columns.iterrows():
            calc_cols_by_table.setdefault(row["TableName"], []).append(row)

    for name in table_names:
        is_calculated = name in calc_table_names
        columns = _build_columns(
            schema_by_table.get(name, []),
            calc_cols_by_table.get(name, []),
        )
        measures = _build_measures(measures_by_table.get(name, []), name)
        source_query = None

        if name in pq_by_table:
            from extractor.powerquery_parser import build_power_query
            source_query = build_power_query(name, pq_by_table[name])

        tables.append(Table(
            name=name,
            description="",
            is_hidden=False,
            is_calculated=is_calculated,
            source_query=source_query,
            columns=columns,
            measures=measures,
            hierarchies=[],
            inferred_role=_infer_role(name, is_calculated, measures),
            row_count=None,
        ))

    return tables


def _build_columns(schema_rows: list, calc_col_rows: list) -> list[Column]:
    cols = []

    # Regular columns from schema
    for row in schema_rows:
        name = row["ColumnName"]
        if name.startswith("RowNumber"):
            continue
        data_type = _pandas_type_to_readable(str(row.get("PandasDataType", "")))
        cols.append(Column(
            name=name,
            data_type=data_type,
            is_hidden=False,
            is_calculated=False,
            dax_expression=None,
            format_string=None,
            description="",
            source_column=name,
        ))

    # Calculated columns
    existing_names = {c.name for c in cols}
    for row in calc_col_rows:
        name = row.get("ColumnName") or row.get("Name", "")
        if not name or name in existing_names:
            continue
        expr = row.get("Expression", "")
        if isinstance(expr, list):
            expr = "\n".join(expr)
        cols.append(Column(
            name=name,
            data_type="calculated",
            is_hidden=False,
            is_calculated=True,
            dax_expression=str(expr) if expr else None,
            format_string=None,
            description="",
            source_column=None,
        ))

    return cols


def _build_measures(rows: list, table_name: str) -> list[Measure]:
    measures = []
    for row in rows:
        name = row.get("Name", "")
        dax = row.get("Expression", "") or ""
        if isinstance(dax, list):
            dax = "\n".join(dax)
        dax = str(dax).strip()

        desc = row.get("Description") or ""
        if desc is None or (isinstance(desc, float)):
            desc = ""

        folder = row.get("DisplayFolder")
        if folder is None or (isinstance(folder, float)):
            folder = None

        measures.append(Measure(
            name=str(name),
            table=table_name,
            dax=dax,
            format_string=None,
            is_hidden=False,
            description=str(desc),
            business_purpose="",
            dependencies=_extract_dax_references(dax),
            complexity_tier=_classify_dax_complexity(dax),
            used_in_visuals=[],
            display_folder=str(folder) if folder else None,
        ))
    return measures


def _build_relationships(df: pd.DataFrame) -> list[Relationship]:
    if df.empty:
        return []
    rels = []
    for _, row in df.iterrows():
        from_table = row.get("FromTableName", "") or ""
        from_col = row.get("FromColumnName", "") or ""
        to_table = row.get("ToTableName", "") or ""
        to_col = row.get("ToColumnName", "") or ""

        # Skip rows missing key fields (e.g. orphan date table entries)
        if not from_table or not to_table:
            continue

        cardinality_raw = str(row.get("Cardinality", "M:1"))
        cardinality = _CARDINALITY_MAP.get(cardinality_raw, "many_to_one")

        cross_filter_raw = str(row.get("CrossFilteringBehavior", "Single"))
        cross_filter = _CROSS_FILTER_MAP.get(cross_filter_raw, "single")

        is_active = bool(row.get("IsActive", True))

        rels.append(Relationship(
            from_table=str(from_table),
            from_column=str(from_col),
            to_table=str(to_table),
            to_column=str(to_col),
            cardinality=cardinality,
            cross_filter_direction=cross_filter,
            is_active=is_active,
        ))
    return rels


def _build_roles(df: pd.DataFrame) -> list[Role]:
    if df.empty or df.columns.empty:
        return []
    roles = []
    name_col = next((c for c in df.columns if "name" in c.lower()), None)
    if not name_col:
        return []
    for _, row in df.iterrows():
        roles.append(Role(name=str(row[name_col]), table_permissions=[]))
    return roles


def _infer_role(name: str, is_calculated: bool, measures: list) -> str:
    if is_calculated:
        return "calculated"
    upper = name.upper()
    if upper.startswith("FACT_") or upper.startswith("FCT_"):
        return "fact"
    if upper.startswith("DIM_") or upper.startswith("DIMENSION_"):
        return "dimension"
    if upper.startswith("BRIDGE_") or upper.startswith("BRG_"):
        return "bridge"
    if "PARAM" in upper or "SLICER" in upper:
        return "parameter"
    # Tables with measures but few/no columns are measure tables
    if measures and len(measures) >= 1:
        return "measure table"
    return "unknown"


def _pandas_type_to_readable(pandas_type: str) -> str:
    mapping = {
        "int64": "whole number",
        "Int64": "whole number",
        "float64": "decimal number",
        "object": "text",
        "string": "text",
        "bool": "boolean",
        "datetime64[ns]": "date/time",
        "datetime64": "date/time",
    }
    for k, v in mapping.items():
        if k in pandas_type:
            return v
    return pandas_type or "unknown"


def _extract_dax_references(dax: str) -> list[str]:
    refs = set()
    for m in re.finditer(r"(?:'[^']+'|\w+)\[([^\]]+)\]", dax):
        refs.add(m.group(1))
    return sorted(refs)


def _classify_dax_complexity(dax: str) -> str:
    upper = dax.upper()
    advanced = ["CALCULATE", "CALCULATETABLE", "FILTER", "ALL", "ALLEXCEPT",
                "ALLSELECTED", "USERELATIONSHIP", "CROSSFILTER", "TREATAS",
                "SUMMARIZE", "ADDCOLUMNS", "TOPN", "RANKX", "EARLIER"]
    intermediate = ["IF", "SWITCH", "DIVIDE", "RELATED", "RELATEDTABLE",
                    "COUNTROWS", "DISTINCTCOUNT", "AVERAGEX", "SUMX",
                    "DATEADD", "SAMEPERIODLASTYEAR", "DATESYTD", "TOTALYTD"]
    adv = sum(1 for fn in advanced if fn in upper)
    if adv >= 2:
        return "advanced"
    if adv == 1 or any(fn in upper for fn in intermediate):
        return "intermediate"
    return "simple"
