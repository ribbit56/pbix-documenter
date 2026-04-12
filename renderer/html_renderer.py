"""
Renders a SemanticModel to a single self-contained HTML file.
Collapsible sections, left nav panel, Prism.js syntax highlighting.
"""
from __future__ import annotations

import html
from pathlib import Path

_CARD = {
    "many_to_one":  "many:1",
    "one_to_many":  "1:many",
    "one_to_one":   "1:1",
    "many_to_many": "many:many",
}

from analyzer.quality_checks import QualityFinding
from models.schema import Measure, Relationship, SemanticModel, Table

_PRISM_CSS = "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css"
_PRISM_JS = "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"
_PRISM_SQL = "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-sql.min.js"
_MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"


def render(model: SemanticModel, findings: list[QualityFinding], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = model.name.replace(" ", "_").replace("/", "-")
    out_path = output_dir / f"{safe_name}.html"
    out_path.write_text(_build(model, findings), encoding="utf-8")
    return out_path


def build_html_string(model: SemanticModel, findings: list[QualityFinding]) -> str:
    """Return the HTML as a string (used by pdf_renderer)."""
    return _build(model, findings)


def _build(model: SemanticModel, findings: list[QualityFinding]) -> str:
    from renderer.diagram_renderer import build_mermaid
    nav_links = _build_nav(model)
    content = _build_content(model, findings, build_mermaid(model))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h(model.name)} — Semantic Model Documentation</title>
  <link rel="stylesheet" href="{_PRISM_CSS}">
  <style>
{_CSS}
  </style>
</head>
<body>
  <nav id="sidebar">
    <div id="sidebar-title">{h(model.name)}</div>
    {nav_links}
  </nav>
  <main id="content">
    {content}
  </main>
  <script src="{_MERMAID_JS}"></script>
  <script>mermaid.initialize({{ startOnLoad: true, theme: "default", er: {{ diagramPadding: 20 }} }});</script>
  <script src="{_PRISM_JS}"></script>
  <script src="{_PRISM_SQL}"></script>
</body>
</html>"""


def _build_nav(model: SemanticModel) -> str:
    items = [
        '<a href="#overview">Overview</a>',
        '<a href="#model-diagram">Model Diagram</a>',
        '<a href="#tables">Tables</a>',
    ]
    for table in model.tables:
        tid = _tid(table.name)
        items.append(f'<a href="#{tid}" class="nav-sub">{h(table.name)}</a>')
    items.append('<a href="#relationships">Relationships</a>')
    if model.roles:
        items.append('<a href="#roles">Roles</a>')
    items.append('<a href="#quality">Quality Findings</a>')
    return "\n    ".join(f"<div>{item}</div>" for item in items)


def _build_content(model: SemanticModel, findings: list[QualityFinding], mermaid_src: str = "") -> str:
    parts: list[str] = []

    # Title
    parts.append(f"""
    <h1>{h(model.name)}</h1>
    <p class="meta">
      <strong>Source:</strong> <code>{h(model.source_file)}</code><br>
      <strong>Generated:</strong> {h(model.generated_at)}
    </p>""")

    # Overview
    visible_tables = [t for t in model.tables if not t.is_hidden]
    all_measures = [m for t in model.tables for m in t.measures]
    parts.append(f"""
    <section id="overview">
      <h2>Overview</h2>
      <table class="summary-table">
        <tr><th>Tables</th><td>{len(visible_tables)}</td></tr>
        <tr><th>Relationships</th><td>{len(model.relationships)}</td></tr>
        <tr><th>Total measures</th><td>{len(all_measures)}</td></tr>
        <tr><th>Roles (RLS)</th><td>{len(model.roles)}</td></tr>
        <tr><th>Quality findings</th><td>{len(findings)}</td></tr>
      </table>
    </section>""")

    # Model Diagram
    if mermaid_src:
        parts.append(f"""
    <section id="model-diagram">
      <h2>Model Diagram</h2>
      <div class="mermaid">
{mermaid_src}
      </div>
    </section>""")

    # Tables
    parts.append('<section id="tables"><h2>Tables</h2>')
    for table in model.tables:
        parts.append(_render_table(table))
    parts.append("</section>")

    # Relationships
    parts.append(_render_relationships(model.relationships))

    # Roles
    if model.roles:
        parts.append('<section id="roles"><h2>Row-Level Security Roles</h2>')
        for role in model.roles:
            perms = "".join(f"<li><code>{h(p)}</code></li>" for p in role.table_permissions) or "<li><em>No table filters</em></li>"
            parts.append(f"<h3>{h(role.name)}</h3><ul>{perms}</ul>")
        parts.append("</section>")

    # Findings
    parts.append(_render_findings(findings))

    return "\n".join(parts)


def _render_table(table: Table) -> str:
    tid = _tid(table.name)
    hidden_badge = '<span class="badge hidden-badge">hidden</span>' if table.is_hidden else ""
    role_badge = f'<span class="badge role-badge">{h(table.inferred_role)}</span>'

    meta_parts = [
        f"<strong>Type:</strong> {'Calculated table' if table.is_calculated else 'Imported/DirectQuery'}",
    ]
    if table.source_query:
        pq = table.source_query
        src = f"{h(pq.source_type)}"
        if pq.source_details:
            src += f" — <code>{h(pq.source_details)}</code>"
        meta_parts.append(f"<strong>Source:</strong> {src}")
        meta_parts.append(f"<strong>Query complexity:</strong> {h(pq.complexity_rating)}")

    desc_html = f'<p class="description">{h(table.description)}</p>' if table.description else ""
    meta_html = " &nbsp;|&nbsp; ".join(meta_parts)

    # Columns
    visible_cols = [c for c in table.columns if not c.is_hidden]
    cols_html = ""
    if visible_cols:
        rows = "".join(
            f"<tr><td><code>{h(c.name)}</code></td><td>{h(c.data_type)}</td></tr>"
            for c in visible_cols
        )
        cols_html = f"""
      <h4>Columns</h4>
      <table class="data-table">
        <thead><tr><th>Column</th><th>Type</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>"""

    # Measures
    measures_html = ""
    if table.measures:
        measures_html = "<h4>Measures</h4>" + "".join(_render_measure(m) for m in table.measures)

    # PQ steps
    pq_html = ""
    if table.source_query and table.source_query.step_descriptions:
        pq = table.source_query
        from extractor.powerquery_parser import _extract_step_names
        step_names = _extract_step_names(pq.m_code)
        steps_li = ""
        for i, desc in enumerate(pq.step_descriptions):
            name = step_names[i] if i < len(step_names) else f"Step {i+1}"
            steps_li += f"<li><strong>{h(name)}</strong> — {h(desc)}</li>" if desc else f"<li><strong>{h(name)}</strong></li>"

        code_escaped = h(pq.m_code)
        pq_html = f"""
      <h4>Power Query Steps</h4>
      <ol>{steps_li}</ol>
      <details>
        <summary>Full M Code</summary>
        <pre><code class="language-sql">{code_escaped}</code></pre>
      </details>"""

    # Hierarchies
    hier_html = ""
    if table.hierarchies:
        items = "".join(f"<li><strong>{h(hr.name)}</strong>: {h(' → '.join(hr.levels))}</li>" for hr in table.hierarchies)
        hier_html = f"<h4>Hierarchies</h4><ul>{items}</ul>"

    return f"""
  <details id="{tid}" class="table-section">
    <summary>
      {role_badge} {h(table.name)} {hidden_badge}
    </summary>
    <div class="table-body">
      {desc_html}
      <p class="meta">{meta_html}</p>
      {cols_html}
      {measures_html}
      {pq_html}
      {hier_html}
    </div>
  </details>"""


def _render_measure(measure: Measure) -> str:
    hidden_badge = '<span class="badge hidden-badge">hidden</span>' if measure.is_hidden else ""
    folder = f'<span class="badge folder-badge">{h(measure.display_folder)}</span>' if measure.display_folder else ""
    desc_html = f"<p>{h(measure.description)}</p>" if measure.description else ""
    purpose_html = f'<p><em>Business purpose: {h(measure.business_purpose)}</em></p>' if measure.business_purpose else ""

    meta_parts = [f"Complexity: {h(measure.complexity_tier)}"]
    if measure.format_string:
        meta_parts.append(f"Format: <code>{h(measure.format_string)}</code>")
    if measure.used_in_visuals:
        meta_parts.append(f"Used in {len(measure.used_in_visuals)} visual(s)")

    dax_escaped = h(measure.dax)
    return f"""
    <div class="measure">
      <h5><code>{h(measure.name)}</code> {hidden_badge} {folder}</h5>
      {desc_html}
      {purpose_html}
      <p class="meta">{" &nbsp;|&nbsp; ".join(meta_parts)}</p>
      <pre><code class="language-sql">{dax_escaped}</code></pre>
    </div>"""


def _render_relationships(relationships: list[Relationship]) -> str:
    if not relationships:
        return ""
    rows = "".join(
        f"<tr>"
        f"<td><code>{h(r.from_table)}[{h(r.from_column)}]</code></td>"
        f"<td><code>{h(r.to_table)}[{h(r.to_column)}]</code></td>"
        f"<td>{h(_CARD.get(r.cardinality, r.cardinality))}</td>"
        f"<td>{h(r.cross_filter_direction)}</td>"
        f"<td>{'Yes' if r.is_active else 'No'}</td>"
        f"</tr>"
        for r in relationships
    )
    return f"""
  <section id="relationships">
    <h2>Relationships</h2>
    <table class="data-table">
      <thead><tr><th>From</th><th>To</th><th>Cardinality</th><th>Cross-filter</th><th>Active</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>"""


def _render_findings(findings: list[QualityFinding]) -> str:
    if not findings:
        return '<section id="quality"><h2>Quality Findings</h2><p>No issues found.</p></section>'

    warnings = [f for f in findings if f.severity == "warning"]
    infos = [f for f in findings if f.severity == "info"]

    parts = ['<section id="quality"><h2>Quality Findings</h2>']
    for section_findings, label, icon in [(warnings, "Warnings", "⚠️"), (infos, "Info", "ℹ️")]:
        if not section_findings:
            continue
        items = "".join(
            f'<li><strong>{icon} {h(f.object_name)}</strong> <span class="badge">{h(f.category)}</span> — {h(f.detail)}</li>'
            for f in section_findings
        )
        parts.append(f"<h3>{label} ({len(section_findings)})</h3><ul class='findings-list'>{items}</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _tid(name: str) -> str:
    """URL-safe ID from table name."""
    return "table-" + name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")


def h(text) -> str:
    """HTML-escape a value."""
    return html.escape(str(text or ""))


_CSS = """
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      margin: 0;
      display: flex;
      min-height: 100vh;
      color: #1a1a1a;
    }
    #sidebar {
      width: 240px;
      min-width: 240px;
      background: #f8f9fa;
      border-right: 1px solid #dee2e6;
      padding: 16px 0;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }
    #sidebar-title {
      font-weight: 700;
      font-size: 13px;
      padding: 0 16px 12px;
      color: #495057;
      border-bottom: 1px solid #dee2e6;
      margin-bottom: 8px;
      word-break: break-word;
    }
    #sidebar div { }
    #sidebar a {
      display: block;
      padding: 4px 16px;
      color: #0d6efd;
      text-decoration: none;
      font-size: 13px;
    }
    #sidebar a.nav-sub { padding-left: 28px; color: #495057; font-size: 12px; }
    #sidebar a:hover { background: #e9ecef; }
    #content {
      flex: 1;
      padding: 32px 40px;
      max-width: 1100px;
    }
    h1 { font-size: 28px; margin-bottom: 4px; }
    h2 { font-size: 20px; margin-top: 36px; border-bottom: 2px solid #dee2e6; padding-bottom: 6px; }
    h3 { font-size: 17px; margin-top: 24px; }
    h4 { font-size: 15px; margin-top: 18px; color: #343a40; }
    h5 { font-size: 14px; margin-top: 12px; margin-bottom: 4px; }
    p.meta { font-size: 12px; color: #6c757d; }
    p.description { font-style: italic; color: #495057; }
    .badge {
      display: inline-block;
      padding: 1px 7px;
      border-radius: 12px;
      font-size: 11px;
      background: #e9ecef;
      color: #495057;
      margin-left: 4px;
    }
    .hidden-badge { background: #f8d7da; color: #721c24; }
    .role-badge { background: #d1ecf1; color: #0c5460; }
    .folder-badge { background: #fff3cd; color: #856404; }
    details.table-section {
      border: 1px solid #dee2e6;
      border-radius: 6px;
      margin-bottom: 12px;
    }
    details.table-section > summary {
      padding: 10px 16px;
      cursor: pointer;
      font-size: 15px;
      font-weight: 600;
      background: #f8f9fa;
      border-radius: 6px;
      list-style: none;
    }
    details.table-section > summary::-webkit-details-marker { display: none; }
    details.table-section > summary::before { content: "▶ "; font-size: 10px; color: #6c757d; }
    details[open].table-section > summary::before { content: "▼ "; }
    .table-body { padding: 16px 20px; }
    .measure {
      border-left: 3px solid #dee2e6;
      padding: 8px 12px;
      margin-bottom: 16px;
      background: #fafafa;
    }
    table.summary-table { border-collapse: collapse; }
    table.summary-table th, table.summary-table td { padding: 4px 16px 4px 0; text-align: left; }
    table.summary-table th { color: #6c757d; font-weight: normal; }
    table.data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    table.data-table th, table.data-table td {
      border: 1px solid #dee2e6;
      padding: 6px 10px;
      text-align: left;
      vertical-align: top;
    }
    table.data-table th { background: #f8f9fa; font-weight: 600; }
    pre {
      background: #f8f9fa;
      border: 1px solid #dee2e6;
      border-radius: 4px;
      padding: 10px 14px;
      overflow-x: auto;
      font-size: 12px;
    }
    code { font-family: "Cascadia Code", "Consolas", monospace; font-size: 12px; }
    details > summary { cursor: pointer; }
    ul.findings-list li { margin-bottom: 6px; }
"""
