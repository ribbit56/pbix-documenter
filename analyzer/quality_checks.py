"""
Runs quality checks on the semantic model and returns structured findings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from models.schema import SemanticModel, Table, Measure, Column, Relationship


@dataclass
class QualityFinding:
    severity: str        # "warning" | "info"
    category: str        # e.g. "orphaned_measure", "missing_description"
    object_name: str
    detail: str


def run_all(model: SemanticModel) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    findings.extend(_check_orphaned_measures(model))
    findings.extend(_check_bidirectional_relationships(model))
    findings.extend(_check_filter_on_large_table(model))
    findings.extend(_check_broken_measure_references(model))
    findings.extend(_check_calculated_columns_as_measures(model))
    findings.extend(_check_isolated_tables(model))
    findings.extend(_check_time_intelligence_without_calculate(model))
    return findings


def _check_orphaned_measures(model: SemanticModel) -> list[QualityFinding]:
    """Measures defined but not used in any visual (only checked when report was parsed)."""
    if not model.report_parsed:
        return []
    findings = []
    for table in model.tables:
        for measure in table.measures:
            if not measure.used_in_visuals and not measure.is_hidden:
                findings.append(QualityFinding(
                    severity="warning",
                    category="orphaned_measure",
                    object_name=f"{table.name}[{measure.name}]",
                    detail=(
                        "This measure is not used in any visual. "
                        "Consider hiding or removing it if it's no longer needed."
                    ),
                ))
    return findings




def _check_bidirectional_relationships(model: SemanticModel) -> list[QualityFinding]:
    findings = []
    for rel in model.relationships:
        if rel.cross_filter_direction == "both":
            findings.append(QualityFinding(
                severity="warning",
                category="bidirectional_relationship",
                object_name=f"{rel.from_table}[{rel.from_column}] → {rel.to_table}[{rel.to_column}]",
                detail=(
                    "Bidirectional cross-filtering can cause ambiguous filter paths "
                    "and unexpected results. Use only when necessary."
                ),
            ))
    return findings


def _check_filter_on_large_table(model: SemanticModel) -> list[QualityFinding]:
    """FILTER() applied directly to a fact table — should use CALCULATETABLE instead."""
    findings = []
    fact_tables = {t.name for t in model.tables if t.inferred_role == "fact"}
    if not fact_tables:
        return findings

    pattern = re.compile(r"\bFILTER\s*\(\s*(" + "|".join(re.escape(n) for n in fact_tables) + r")\b", re.IGNORECASE)

    for table in model.tables:
        for measure in table.measures:
            if pattern.search(measure.dax):
                findings.append(QualityFinding(
                    severity="warning",
                    category="perf_pattern",
                    object_name=f"{table.name}[{measure.name}]",
                    detail=(
                        "FILTER() is applied directly to a fact table. "
                        "Use CALCULATETABLE() or push predicates into CALCULATE() for better performance."
                    ),
                ))
    return findings


def _check_broken_measure_references(model: SemanticModel) -> list[QualityFinding]:
    """Measure references a hidden or nonexistent column."""
    findings = []
    all_columns: set[str] = set()
    hidden_columns: set[str] = set()

    for table in model.tables:
        for col in table.columns:
            all_columns.add(col.name.lower())
            if col.is_hidden:
                hidden_columns.add(col.name.lower())

    all_measures: set[str] = {
        m.name.lower()
        for t in model.tables
        for m in t.measures
    }

    for table in model.tables:
        for measure in table.measures:
            for dep in measure.dependencies:
                dep_lower = dep.lower()
                if dep_lower in hidden_columns:
                    findings.append(QualityFinding(
                        severity="warning",
                        category="hidden_column_reference",
                        object_name=f"{table.name}[{measure.name}]",
                        detail=f"References hidden column [{dep}]. This may cause unexpected results.",
                    ))
                elif dep_lower not in all_columns and dep_lower not in all_measures:
                    findings.append(QualityFinding(
                        severity="warning",
                        category="broken_reference",
                        object_name=f"{table.name}[{measure.name}]",
                        detail=f"References [{dep}] which does not exist in the model.",
                    ))
    return findings


def _check_calculated_columns_as_measures(model: SemanticModel) -> list[QualityFinding]:
    """Calculated columns that aggregate data — better as measures."""
    findings = []
    agg_pattern = re.compile(r"\b(SUM|AVERAGE|COUNT|MAX|MIN|SUMX|AVERAGEX|COUNTROWS)\s*\(", re.IGNORECASE)
    for table in model.tables:
        for col in table.columns:
            if col.is_calculated and col.dax_expression and agg_pattern.search(col.dax_expression):
                findings.append(QualityFinding(
                    severity="info",
                    category="calc_column_as_measure",
                    object_name=f"{table.name}[{col.name}]",
                    detail=(
                        "This calculated column uses an aggregation function. "
                        "Consider converting it to a measure for better performance and flexibility."
                    ),
                ))
    return findings


def _check_isolated_tables(model: SemanticModel) -> list[QualityFinding]:
    """Tables with no relationships to other tables."""
    findings = []
    related_tables: set[str] = set()
    for rel in model.relationships:
        related_tables.add(rel.from_table)
        related_tables.add(rel.to_table)

    for table in model.tables:
        if table.is_hidden:
            continue
        if table.name not in related_tables:
            findings.append(QualityFinding(
                severity="info",
                category="isolated_table",
                object_name=table.name,
                detail=(
                    "This table has no relationships to other tables. "
                    "If it is used in the model, ensure it is connected correctly."
                ),
            ))
    return findings


def _check_time_intelligence_without_calculate(model: SemanticModel) -> list[QualityFinding]:
    """Time intelligence functions called without a CALCULATE wrapper."""
    findings = []
    time_intel_fns = [
        "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
        "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTYEAR", "NEXTQUARTER",
        "NEXTMONTH", "NEXTDAY", "DATESYTD", "DATESMTD", "DATESQTD",
        "PARALLELPERIOD", "DATESBETWEEN", "DATESINPERIOD",
    ]
    ti_pattern = re.compile(
        r"\b(" + "|".join(time_intel_fns) + r")\s*\(",
        re.IGNORECASE,
    )
    calc_pattern = re.compile(r"\bCALCULATE\s*\(", re.IGNORECASE)

    for table in model.tables:
        for measure in table.measures:
            if ti_pattern.search(measure.dax) and not calc_pattern.search(measure.dax):
                findings.append(QualityFinding(
                    severity="warning",
                    category="time_intelligence_no_calculate",
                    object_name=f"{table.name}[{measure.name}]",
                    detail=(
                        "A time intelligence function is used without a CALCULATE() wrapper. "
                        "This may not evaluate in the expected filter context."
                    ),
                ))
    return findings
