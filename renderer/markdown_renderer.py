"""
Renders a SemanticModel to a single Markdown file.
"""
from __future__ import annotations

from pathlib import Path

_CARD = {
    "many_to_one":  "many:1",
    "one_to_many":  "1:many",
    "one_to_one":   "1:1",
    "many_to_many": "many:many",
}

from analyzer.quality_checks import QualityFinding
from models.schema import SemanticModel, Table, Measure, Column, Relationship
from renderer.diagram_renderer import build_mermaid


def render(model: SemanticModel, findings: list[QualityFinding], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = model.name.replace(" ", "_").replace("/", "-")
    out_path = output_dir / f"{safe_name}.md"
    out_path.write_text(_build(model, findings), encoding="utf-8")
    return out_path


def _build(model: SemanticModel, findings: list[QualityFinding]) -> str:
    lines: list[str] = []

    lines += [
        f"# {model.name}",
        "",
        f"**Source file:** `{model.source_file}`  ",
        f"**Generated:** {model.generated_at}",
        "",
    ]

    # Overview
    visible_tables = [t for t in model.tables if not t.is_hidden]
    all_measures = [m for t in model.tables for m in t.measures]
    lines += [
        "## Overview",
        "",
        f"| | |",
        f"|---|---|",
        f"| Tables | {len(visible_tables)} |",
        f"| Relationships | {len(model.relationships)} |",
        f"| Total measures | {len(all_measures)} |",
        f"| Roles (RLS) | {len(model.roles)} |",
        f"| Quality findings | {len(findings)} |",
        "",
    ]

    # Model diagram (Mermaid — renders on GitHub, VS Code, Notion, etc.)
    mermaid_src = build_mermaid(model)
    lines += [
        "## Model Diagram",
        "",
        "```mermaid",
        mermaid_src,
        "```",
        "",
    ]

    # Tables
    lines.append("## Tables")
    lines.append("")
    for table in model.tables:
        lines += _render_table(table)

    # Relationships
    lines += _render_relationships(model.relationships)

    # Roles
    if model.roles:
        lines += _render_roles(model)

    # Quality findings (always show section)
    lines += _render_findings(findings)

    return "\n".join(lines)


def _render_table(table: Table) -> list[str]:
    lines: list[str] = []
    hidden_tag = " *(hidden)*" if table.is_hidden else ""
    lines.append(f"### {table.name}{hidden_tag}")
    lines.append("")

    meta_rows = [
        f"**Role:** {table.inferred_role}",
        f"**Type:** {'Calculated table' if table.is_calculated else 'Imported/DirectQuery'}",
    ]
    if table.source_query:
        pq = table.source_query
        meta_rows.append(f"**Source:** {pq.source_type} — `{pq.source_details}`" if pq.source_details else f"**Source:** {pq.source_type}")
        meta_rows.append(f"**Query complexity:** {pq.complexity_rating}")
    if table.description:
        lines += [f"> {table.description}", ""]

    lines += ["  ".join(meta_rows), ""]

    # Columns
    visible_cols = [c for c in table.columns if not c.is_hidden]
    if visible_cols:
        lines.append("#### Columns")
        lines.append("")
        lines.append("| Column | Type |")
        lines.append("|--------|------|")
        for col in visible_cols:
            lines.append(f"| `{col.name}` | {col.data_type} |")
        lines.append("")

    # Measures
    if table.measures:
        lines.append("#### Measures")
        lines.append("")
        for measure in table.measures:
            lines += _render_measure(measure)

    # Power Query steps
    if table.source_query and table.source_query.step_descriptions:
        pq = table.source_query
        lines.append("#### Power Query Steps")
        lines.append("")
        step_names = _get_step_names_from_m(pq.m_code)
        for i, desc in enumerate(pq.step_descriptions):
            step_name = step_names[i] if i < len(step_names) else f"Step {i+1}"
            if desc:
                lines.append(f"1. **{step_name}** — {desc}")
            else:
                lines.append(f"1. **{step_name}**")
        lines.append("")
        lines.append("<details><summary>Full M Code</summary>")
        lines.append("")
        lines.append("```powerquery")
        lines.append(pq.m_code)
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Hierarchies
    if table.hierarchies:
        lines.append("#### Hierarchies")
        lines.append("")
        for h in table.hierarchies:
            lines.append(f"- **{h.name}**: {' → '.join(h.levels)}")
        lines.append("")

    return lines


def _render_measure(measure: Measure) -> list[str]:
    lines: list[str] = []
    hidden_tag = " *(hidden)*" if measure.is_hidden else ""
    folder_tag = f" — *{measure.display_folder}*" if measure.display_folder else ""
    lines.append(f"##### `{measure.name}`{hidden_tag}{folder_tag}")
    lines.append("")

    if measure.description:
        lines.append(measure.description)
        lines.append("")
    if measure.business_purpose:
        lines.append(f"*Business purpose: {measure.business_purpose}*")
        lines.append("")

    meta = []
    if measure.format_string:
        meta.append(f"Format: `{measure.format_string}`")
    meta.append(f"Complexity: {measure.complexity_tier}")
    if measure.used_in_visuals:
        meta.append(f"Used in: {len(measure.used_in_visuals)} visual(s)")
    if meta:
        lines.append(" | ".join(meta))
        lines.append("")

    lines.append("```dax")
    lines.append(measure.dax)
    lines.append("```")
    lines.append("")

    return lines


def _render_relationships(relationships: list[Relationship]) -> list[str]:
    if not relationships:
        return []
    lines = [
        "## Relationships",
        "",
        "| From | To | Cardinality | Cross-filter | Active |",
        "|------|----|-------------|--------------|--------|",
    ]
    for rel in relationships:
        active = "Yes" if rel.is_active else "No"
        cardinality = _CARD.get(rel.cardinality, rel.cardinality)
        lines.append(
            f"| `{rel.from_table}`[{rel.from_column}] "
            f"| `{rel.to_table}`[{rel.to_column}] "
            f"| {cardinality} | {rel.cross_filter_direction} | {active} |"
        )
    lines.append("")
    return lines


def _render_roles(model: SemanticModel) -> list[str]:
    lines = ["## Row-Level Security Roles", ""]
    for role in model.roles:
        lines.append(f"### {role.name}")
        lines.append("")
        if role.table_permissions:
            for perm in role.table_permissions:
                lines.append(f"- `{perm}`")
        else:
            lines.append("- *(no table filters)*")
        lines.append("")
    return lines


def _render_findings(findings: list[QualityFinding]) -> list[str]:
    lines = ["## Quality Findings", ""]
    if not findings:
        lines += ["*No quality issues found.*", ""]
        return lines

    warnings = [f for f in findings if f.severity == "warning"]
    infos = [f for f in findings if f.severity == "info"]

    if warnings:
        lines.append(f"**{len(warnings)} warning(s)**")
        lines.append("")
        for f in warnings:
            lines.append(f"- [ ] ⚠️ **{f.object_name}** ({f.category}): {f.detail}")
        lines.append("")

    if infos:
        lines.append(f"**{len(infos)} info item(s)**")
        lines.append("")
        for f in infos:
            lines.append(f"- [ ] ℹ️ **{f.object_name}** ({f.category}): {f.detail}")
        lines.append("")

    return lines


def _get_step_names_from_m(m_code: str) -> list[str]:
    import re
    let_match = re.search(r"\blet\b(.*?)\bin\b", m_code, re.DOTALL | re.IGNORECASE)
    if not let_match:
        return []
    body = let_match.group(1)
    steps = re.findall(r"^\s*(\"[^\"]+\"|[\w ]+?)\s*=", body, re.MULTILINE)
    return [s.strip().strip('"') for s in steps if s.strip()]
