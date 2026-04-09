"""
Generates visual model diagrams:
  - build_dot()     -> Graphviz DOT string  (used by Streamlit st.graphviz_chart)
  - build_mermaid() -> Mermaid erDiagram string (embedded in HTML / Markdown)
"""
from __future__ import annotations

import html as _html_mod
from models.schema import SemanticModel

# ── Colour scheme by role ─────────────────────────────────────────────────────
# (header_bg, header_fg, body_bg)
_ROLE_COLOURS: dict[str, tuple[str, str, str]] = {
    "fact":          ("#1565C0", "#FFFFFF", "#E3F2FD"),  # blue
    "dimension":     ("#2E7D32", "#FFFFFF", "#E8F5E9"),  # green
    "measure table": ("#6A1B9A", "#FFFFFF", "#F3E5F5"),  # purple
    "bridge":        ("#E65100", "#FFFFFF", "#FFF3E0"),  # orange
    "parameter":     ("#455A64", "#FFFFFF", "#ECEFF1"),  # grey-blue
    "calculated":    ("#455A64", "#FFFFFF", "#ECEFF1"),
}
_DEFAULT_COLOUR = ("#455A64", "#FFFFFF", "#ECEFF1")

_MAX_COLS_DOT = 10  # max visible columns per table in Graphviz


# ── Graphviz DOT ──────────────────────────────────────────────────────────────

def build_dot(model: SemanticModel) -> str:
    """Return a Graphviz DOT string for the semantic model."""
    lines = [
        "digraph model {",
        '  graph [rankdir=LR fontname="Helvetica" bgcolor="transparent" '
        "nodesep=0.7 ranksep=1.5]",
        '  node  [fontname="Helvetica" margin=0 shape=none]',
        '  edge  [fontname="Helvetica" fontsize=9 color="#888888" arrowsize=0.85]',
        "",
    ]

    for table in [t for t in model.tables if not t.is_hidden]:
        hdr_bg, hdr_fg, body_bg = _ROLE_COLOURS.get(table.inferred_role, _DEFAULT_COLOUR)
        visible_cols = [c for c in table.columns if not c.is_hidden]
        show_cols = visible_cols[:_MAX_COLS_DOT]
        extra = len(visible_cols) - _MAX_COLS_DOT

        rows: list[str] = []

        # ── Header row ────────────────────────────────────────────────────────
        role_txt = table.inferred_role.replace("measure table", "measures")
        rows.append(
            f'<TR><TD BGCOLOR="{hdr_bg}" ALIGN="LEFT" CELLPADDING="5">'
            f'<FONT COLOR="{hdr_fg}" POINT-SIZE="12"><B>{_he(table.name)}</B></FONT>'
            f'<FONT COLOR="{hdr_fg}" POINT-SIZE="8">  {_he(role_txt)}</FONT>'
            f"</TD></TR>"
        )

        # ── Column rows ───────────────────────────────────────────────────────
        for col in show_cols:
            dtype = _short_type(col.data_type)
            calc = " *" if col.is_calculated else ""
            rows.append(
                f'<TR><TD ALIGN="LEFT" BGCOLOR="{body_bg}" CELLPADDING="2">'
                f'<FONT POINT-SIZE="10">{_he(col.name)}{_he(calc)}</FONT>'
                f'<FONT POINT-SIZE="8" COLOR="#777777">  {_he(dtype)}</FONT>'
                f"</TD></TR>"
            )

        if extra > 0:
            rows.append(
                f'<TR><TD ALIGN="LEFT" BGCOLOR="{body_bg}" CELLPADDING="2">'
                f'<FONT POINT-SIZE="8" COLOR="#999999">  +{extra} more column{"s" if extra != 1 else ""}&#8230;</FONT>'
                f"</TD></TR>"
            )

        # ── Measures summary row ──────────────────────────────────────────────
        if table.measures:
            m_n = len(table.measures)
            noun = "measure" if m_n == 1 else "measures"
            rows.append(
                f'<TR><TD ALIGN="LEFT" BGCOLOR="#F8F0FF" CELLPADDING="2">'
                f'<FONT POINT-SIZE="9" COLOR="#6A1B9A">  &#931; {m_n} {noun}</FONT>'
                f"</TD></TR>"
            )

        row_html = "\n    ".join(rows)
        label = (
            f'<\n  <TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0">\n'
            f"    {row_html}\n"
            f"  </TABLE>\n>"
        )
        lines.append(f"  {_dot_id(table.name)} [label={label}]")

    lines.append("")

    # ── Edges ─────────────────────────────────────────────────────────────────
    for rel in model.relationships:
        if rel.cardinality == "many_to_one":
            arrow = "arrowhead=normal arrowtail=crow dir=both"
        elif rel.cardinality == "one_to_many":
            arrow = "arrowhead=crow arrowtail=normal dir=both"
        elif rel.cardinality == "one_to_one":
            arrow = "arrowhead=tee arrowtail=tee dir=both"
        else:  # many_to_many
            arrow = "arrowhead=crow arrowtail=crow dir=both"

        active_attr = "" if rel.is_active else ' style="dashed"'
        edge_label = f"{rel.from_column}"
        lines.append(
            f"  {_dot_id(rel.from_table)} -> {_dot_id(rel.to_table)} "
            f'[label="{_he(edge_label)}" {arrow}{active_attr}]'
        )

    lines.append("}")
    return "\n".join(lines)


# ── Mermaid ER ────────────────────────────────────────────────────────────────

_MERMAID_CARDINALITY = {
    "many_to_one":  ("}|", "||"),
    "one_to_many":  ("||", "|{"),
    "one_to_one":   ("||", "||"),
    "many_to_many": ("}|", "|{"),
}

_TYPE_MAP = {
    "whole number":    "int",
    "decimal number":  "float",
    "float64":         "float",
    "text":            "string",
    "date/time":       "datetime",
    "date":            "date",
    "true/false":      "bool",
    "binary":          "binary",
    "duration":        "duration",
}


def build_mermaid(model: SemanticModel) -> str:
    """Return a Mermaid erDiagram string for the semantic model."""
    # Collect columns that participate in at least one relationship
    rel_cols: set[tuple[str, str]] = set()
    for rel in model.relationships:
        rel_cols.add((rel.from_table, rel.from_column))
        rel_cols.add((rel.to_table, rel.to_column))

    lines = ["erDiagram"]

    for table in model.tables:
        if table.is_hidden:
            continue

        tid = _mermaid_id(table.name)

        # Key (relationship) columns first, then up to 5 others
        key_cols   = [c for c in table.columns if (table.name, c.name) in rel_cols and not c.is_hidden]
        other_cols = [c for c in table.columns if (table.name, c.name) not in rel_cols and not c.is_hidden]
        slots      = max(0, 6 - len(key_cols))
        show_cols  = key_cols + other_cols[:slots]

        if show_cols:
            lines.append(f"    {tid} {{")
            for col in show_cols:
                dtype = _TYPE_MAP.get(col.data_type.lower(), col.data_type.replace(" ", "_")[:12])
                lines.append(f"        {dtype} {_mermaid_field(col.name)}")
            lines.append("    }")
        else:
            # Entity with no visible columns (e.g. pure measure table) — omit body
            lines.append(f"    {tid}")

    lines.append("")

    for rel in model.relationships:
        left_c, right_c = _MERMAID_CARDINALITY.get(rel.cardinality, ("}|", "||"))
        link = "--" if rel.is_active else ".."
        label = rel.from_column.replace('"', "")
        lines.append(
            f"    {_mermaid_id(rel.from_table)} {left_c}{link}{right_c} "
            f'{_mermaid_id(rel.to_table)} : "{label}"'
        )

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _he(text: str) -> str:
    """HTML-escape for Graphviz HTML labels."""
    return _html_mod.escape(str(text))


def _dot_id(name: str) -> str:
    """Quoted Graphviz node identifier."""
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mermaid_id(name: str) -> str:
    """Safe Mermaid entity name (alphanumeric + underscore only)."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _mermaid_field(name: str) -> str:
    """Safe Mermaid field name."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _short_type(data_type: str) -> str:
    return _TYPE_MAP.get(data_type.lower(), data_type)
