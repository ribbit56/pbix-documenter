"""
Sends DAX and M code to Claude and returns plain-English descriptions.
Uses the Anthropic Python SDK. ANTHROPIC_API_KEY must be set in the environment.
"""
from __future__ import annotations

import json

import anthropic
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from ai.prompts import MEASURE_DESCRIPTION_PROMPT, POWERQUERY_STEP_PROMPT, TABLE_ROLE_PROMPT
from models.schema import Measure, PowerQuery, SemanticModel, Table

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 512


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def _call(prompt: str) -> str:
    client = _client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _parse_json(text: str, fallback: dict) -> dict:
    """Parse JSON from LLM response, stripping accidental markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _model_context(model: SemanticModel) -> dict:
    return {
        "model_name": model.name,
        "table_names": ", ".join(t.name for t in model.tables),
        "all_measure_names": ", ".join(
            m.name for t in model.tables for m in t.measures
        ),
        "all_table_names": ", ".join(t.name for t in model.tables),
    }


def annotate_model(model: SemanticModel) -> SemanticModel:
    """
    Run all AI annotations on the model:
    - Table roles (for tables with inferred_role == 'unknown')
    - Measure descriptions and business purposes
    - Power Query step descriptions
    Returns the model mutated in-place.
    """
    ctx = _model_context(model)

    all_measures = [
        (table, measure)
        for table in model.tables
        for measure in table.measures
    ]
    tables_needing_role = [t for t in model.tables if t.inferred_role == "unknown"]
    tables_with_pq = [t for t in model.tables if t.source_query is not None]

    total = len(all_measures) + len(tables_needing_role) + len(tables_with_pq)
    if total == 0:
        return model

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:
        task = progress.add_task("Generating AI descriptions...", total=total)

        # Table roles
        for table in tables_needing_role:
            role_data = describe_table_role(table, ctx)
            table.inferred_role = role_data.get("role", "unknown")
            progress.advance(task)

        # Measures
        for table, measure in all_measures:
            if measure.description and measure.business_purpose:
                progress.advance(task)
                continue
            desc, purpose = describe_measure(measure, ctx)
            if not measure.description:
                measure.description = desc
            measure.business_purpose = purpose
            progress.advance(task)

        # Power Query steps
        for table in tables_with_pq:
            pq = table.source_query
            if pq and not pq.step_descriptions:
                pq.step_descriptions = describe_powerquery_steps(pq, table.name)
            progress.advance(task)

    return model


def describe_measure(measure: Measure, ctx: dict) -> tuple[str, str]:
    """Returns (plain_english_description, inferred_business_purpose)."""
    prompt = MEASURE_DESCRIPTION_PROMPT.format(
        model_name=ctx["model_name"],
        table_names=ctx["table_names"],
        all_measure_names=ctx["all_measure_names"],
        table_name=measure.table,
        measure_name=measure.name,
        dax=measure.dax,
        format_string=measure.format_string or "none",
        display_folder=measure.display_folder or "none",
        complexity_tier=measure.complexity_tier,
    )
    result = _parse_json(
        _call(prompt),
        {"description": measure.name, "business_purpose": ""},
    )
    return result.get("description", ""), result.get("business_purpose", "")


def describe_powerquery_steps(pq: PowerQuery, table_name: str) -> list[str]:
    """Returns one plain-English sentence per Applied Step."""
    from extractor.powerquery_parser import _extract_step_names
    step_names = _extract_step_names(pq.m_code)
    if not step_names:
        return []

    prompt = POWERQUERY_STEP_PROMPT.format(
        table_name=table_name,
        source_type=pq.source_type,
        m_code=pq.m_code[:3000],  # truncate very long M code
        step_names="\n".join(f"- {s}" for s in step_names),
    )
    result = _parse_json(_call(prompt), {"steps": []})
    steps = result.get("steps", [])

    # Pad or truncate to match actual step count
    while len(steps) < len(step_names):
        steps.append("")
    return steps[: len(step_names)]


def describe_table_role(table: Table, ctx: dict) -> dict:
    """Returns {role, reasoning}."""
    col_names = ", ".join(c.name for c in table.columns[:20])
    prompt = TABLE_ROLE_PROMPT.format(
        model_name=ctx["model_name"],
        all_table_names=ctx["all_table_names"],
        table_name=table.name,
        column_names=col_names or "none",
        measure_count=len(table.measures),
        has_source_query=table.source_query is not None,
        is_calculated=table.is_calculated,
    )
    return _parse_json(_call(prompt), {"role": "unknown", "reasoning": ""})
