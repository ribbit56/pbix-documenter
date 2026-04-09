"""
Parses Power Query M code into PowerQuery dataclasses.
`build_power_query` builds a single PowerQuery object from a table name + M expression.
The old `parse(mashup_path, tables)` entry point is kept for reference but no longer used.
"""
from __future__ import annotations

import re
from pathlib import Path

from models.schema import PowerQuery, Table

# Connection string patterns to sanitize
_SANITIZE_PATTERNS = [
    (re.compile(r'(Password\s*=\s*")[^"]*"', re.IGNORECASE), r'\1***"'),
    (re.compile(r'(pwd\s*=\s*)[^;,"]+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(AccountKey\s*=\s*)[^;,"]+', re.IGNORECASE), r'\1***'),
]

# Source type detection patterns
_SOURCE_TYPE_PATTERNS = [
    (re.compile(r'\bSql\.Database\b', re.IGNORECASE), "sql"),
    (re.compile(r'\bAmazonRedshift\.Database\b', re.IGNORECASE), "redshift"),
    (re.compile(r'\bSnowflake\.Databases\b', re.IGNORECASE), "snowflake"),
    (re.compile(r'\bSharePoint\.Files\b|\bSharePoint\.Tables\b', re.IGNORECASE), "sharepoint"),
    (re.compile(r'\bExcel\.Workbook\b', re.IGNORECASE), "excel"),
    (re.compile(r'\bCsv\.Document\b|\bFile\.Contents\b', re.IGNORECASE), "file"),
    (re.compile(r'\bWeb\.Contents\b|\bWeb\.Page\b', re.IGNORECASE), "web"),
    (re.compile(r'\bOData\.Feed\b', re.IGNORECASE), "odata"),
    (re.compile(r'\bAzure\.DataLake\b|\bAdlsGen2\.Contents\b', re.IGNORECASE), "azure_datalake"),
    (re.compile(r'\bAzure\.BlobStorage\b|\bAzureStorage\b', re.IGNORECASE), "azure_blob"),
    (re.compile(r'\bSalesforce\b', re.IGNORECASE), "salesforce"),
    (re.compile(r'\b#"[^"]+"\s*=\s*\{', re.IGNORECASE), "parameter"),  # parameter tables
    (re.compile(r'\bTable\.FromRows\b', re.IGNORECASE), "placeholder"),  # empty/measure-container tables
]


def parse(mashup_path: Path, tables: list[Table]) -> list[Table]:
    """
    Parse M code and attach PowerQuery objects to matching tables.
    Returns the tables list (mutated in-place).
    """
    if not mashup_path or not mashup_path.exists():
        return tables

    m_code = mashup_path.read_text(encoding="utf-8-sig", errors="replace")
    queries = _split_sections(m_code)

    table_map = {t.name.lower(): t for t in tables}

    for query_name, query_code in queries.items():
        target = table_map.get(query_name.lower())
        if target is None:
            continue

        source_type, source_details = _detect_source(query_code)
        step_names = _extract_step_names(query_code)
        output_cols = _extract_output_columns(query_code)
        complexity = _rate_complexity(query_code, step_names)

        target.source_query = PowerQuery(
            table_name=query_name,
            m_code=query_code,
            source_type=source_type,
            source_details=_sanitize(source_details),
            step_descriptions=[],  # filled by AI layer
            output_columns=output_cols,
            complexity_rating=complexity,
        )

    return tables


def _split_sections(m_code: str) -> dict[str, str]:
    """
    Split Section1.m into individual named queries.
    Format:
        section Section1;
        shared QueryName = let ... in ...;
    """
    queries: dict[str, str] = {}

    # Remove section declaration
    m_code = re.sub(r"^\s*section\s+\w+\s*;", "", m_code, flags=re.MULTILINE).strip()

    # Split on 'shared <Name> =' boundaries
    # The pattern: optional attributes, then 'shared Name ='
    pattern = re.compile(
        r"(?:^|\n)\s*(?:\[[^\]]*\]\s*)*shared\s+(\"[^\"]+\"|[\w.]+)\s*=",
        re.MULTILINE,
    )

    matches = list(pattern.finditer(m_code))
    for i, match in enumerate(matches):
        name_raw = match.group(1).strip('"')
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(m_code)
        body = m_code[start:end].strip().rstrip(";").strip()
        queries[name_raw] = body

    return queries


def _extract_step_names(m_code: str) -> list[str]:
    """Extract step names from a let...in block."""
    let_match = re.search(r"\blet\b(.*?)\bin\b", m_code, re.DOTALL | re.IGNORECASE)
    if not let_match:
        return []

    body = let_match.group(1)
    # Each step: Name = expression,
    steps = re.findall(
        r"^\s*(\"[^\"]+\"|[\w ]+?)\s*=",
        body,
        re.MULTILINE,
    )
    return [s.strip().strip('"') for s in steps if s.strip()]


def _detect_source(m_code: str) -> tuple[str, str]:
    for pattern, source_type in _SOURCE_TYPE_PATTERNS:
        if pattern.search(m_code):
            details = _extract_source_details(m_code, source_type)
            return source_type, details
    return "unknown", ""


def _extract_source_details(m_code: str, source_type: str) -> str:
    """Best-effort extraction of server/path from M code."""
    if source_type in ("placeholder", "parameter"):
        return ""

    # SQL: Sql.Database("server", "database")
    sql_match = re.search(r'Sql\.Database\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"', m_code, re.IGNORECASE)
    if sql_match:
        return f"{sql_match.group(1)}/{sql_match.group(2)}"

    # SharePoint: SharePoint.Files("url")
    sp_match = re.search(r'SharePoint\.\w+\s*\(\s*"([^"]+)"', m_code, re.IGNORECASE)
    if sp_match:
        return sp_match.group(1)

    # Excel/File: from path string
    path_match = re.search(r'(?:File\.Contents|Excel\.Workbook)\s*\(\s*"([^"]+)"', m_code, re.IGNORECASE)
    if path_match:
        return path_match.group(1)

    # Generic: first quoted string
    first_string = re.search(r'"([^"]{4,})"', m_code)
    if first_string:
        return first_string.group(1)

    return ""


def _sanitize(text: str) -> str:
    for pattern, replacement in _SANITIZE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _extract_output_columns(m_code: str) -> list[str]:
    """Attempt to find column names from Table.SelectColumns or rename steps."""
    cols = []
    for m in re.finditer(r'Table\.RenameColumns\([^,]+,\s*\{(.*?)\}\)', m_code, re.DOTALL):
        for pair in re.finditer(r'"\s*([^"]+)\s*"\s*,\s*"\s*([^"]+)\s*"', m.group(1)):
            cols.append(pair.group(2))
    if not cols:
        for m in re.finditer(r'Table\.SelectColumns\([^,]+,\s*\{(.*?)\}\)', m_code, re.DOTALL):
            for col in re.finditer(r'"([^"]+)"', m.group(1)):
                cols.append(col.group(1))
    return cols


def _rate_complexity(m_code: str, steps: list[str]) -> str:
    n_steps = len(steps)
    complex_fns = ["Table.NestedJoin", "Table.Group", "Table.Pivot", "Table.Unpivot",
                   "Table.Combine", "Table.AddColumn", "List.Generate", "Table.Buffer"]
    has_complex = any(fn.lower() in m_code.lower() for fn in complex_fns)

    if n_steps >= 10 or has_complex:
        return "complex"
    if n_steps >= 5:
        return "moderate"
    return "simple"


def build_power_query(table_name: str, m_code: str) -> PowerQuery:
    """Build a PowerQuery object from a table name and its M expression string."""
    source_type, source_details = _detect_source(m_code)
    step_names = _extract_step_names(m_code)
    output_cols = _extract_output_columns(m_code)
    complexity = _rate_complexity(m_code, step_names)
    return PowerQuery(
        table_name=table_name,
        m_code=m_code,
        source_type=source_type,
        source_details=_sanitize(source_details),
        step_descriptions=[],  # filled by AI layer
        output_columns=output_cols,
        complexity_rating=complexity,
    )
