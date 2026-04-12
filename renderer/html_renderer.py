"""
Renders a SemanticModel to a single self-contained HTML file.
Collapsible sections, left nav panel, Prism.js syntax highlighting,
sidebar search, complexity-coloured measure cards, print CSS.
"""
from __future__ import annotations

import html
from collections import defaultdict
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
_PRISM_JS  = "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"
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
    content   = _build_content(model, findings, build_mermaid(model))

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
    <div id="search-wrap">
      <input id="search" type="search" placeholder="Search tables…" autocomplete="off">
    </div>
    <div id="nav-links">
    {nav_links}
    </div>
  </nav>
  <main id="content">
    {content}
  </main>
  <script src="{_MERMAID_JS}"></script>
  <script>mermaid.initialize({{ startOnLoad: true, theme: "default", er: {{ diagramPadding: 20 }} }});</script>
  <script src="{_PRISM_JS}"></script>
  <script src="{_PRISM_SQL}"></script>
  <script>
  (function() {{
    var input = document.getElementById("search");
    if (!input) return;
    input.addEventListener("input", function() {{
      var q = input.value.trim().toLowerCase();
      var links = document.querySelectorAll("#nav-links a.nav-sub");
      var sections = document.querySelectorAll("details.table-section");
      links.forEach(function(a) {{
        var match = !q || a.textContent.toLowerCase().includes(q);
        a.parentElement.style.display = match ? "" : "none";
      }});
      sections.forEach(function(sec) {{
        var name = sec.querySelector("summary").textContent.toLowerCase();
        sec.style.display = (!q || name.includes(q)) ? "" : "none";
      }});
    }});
  }})();
  </script>
</body>
</html>"""


def _build_nav(model: SemanticModel) -> str:
    items = [
        '<a href="#overview">Overview</a>',
    ]
    has_sources = any(t.source_query for t in model.tables if not t.is_hidden)
    if has_sources:
        items.append('<a href="#data-sources">Data Sources</a>')
    items.append('<a href="#model-diagram">Model Diagram</a>')
    items.append('<a href="#tables">Tables</a>')
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
      <strong>Source:</strong> <code>{h(model.source_file)}</code> &nbsp;·&nbsp;
      <strong>Generated:</strong> {h(model.generated_at)}
    </p>""")

    # Overview
    visible_tables = [t for t in model.tables if not t.is_hidden]
    all_measures   = [m for t in model.tables for m in t.measures]
    report_row = (
        '<tr><th>Report analysed</th><td>Yes — visual usage data available</td></tr>'
        if model.report_parsed else
        '<tr><th>Report analysed</th><td><em>No — run without Skip Report for visual usage data</em></td></tr>'
    )
    parts.append(f"""
    <section id="overview">
      <h2>Overview</h2>
      <table class="summary-table">
        <tr><th>Tables</th><td>{len(visible_tables)}</td></tr>
        <tr><th>Relationships</th><td>{len(model.relationships)}</td></tr>
        <tr><th>Total measures</th><td>{len(all_measures)}</td></tr>
        <tr><th>Roles (RLS)</th><td>{len(model.roles)}</td></tr>
        <tr><th>Quality findings</th><td>{len(findings)}</td></tr>
        {report_row}
      </table>
    </section>""")

    # Data Sources
    source_tables = [t for t in model.tables if t.source_query and not t.is_hidden]
    if source_tables:
        parts.append(_render_data_sources(source_tables))

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
        parts.append(_render_table(table, model.report_parsed))
    parts.append("</section>")

    # Relationships
    parts.append(_render_relationships(model.relationships))

    # Roles
    if model.roles:
        parts.append('<section id="roles"><h2>Row-Level Security Roles</h2>')
        for role in model.roles:
            perms = "".join(
                f"<li><code>{h(p)}</code></li>" for p in role.table_permissions
            ) or "<li><em>No table filters defined</em></li>"
            parts.append(f"<h3>{h(role.name)}</h3><ul>{perms}</ul>")
        parts.append("</section>")

    # Findings
    parts.append(_render_findings(findings))

    return "\n".join(parts)


def _render_data_sources(source_tables: list[Table]) -> str:
    rows = ""
    for t in source_tables:
        pq = t.source_query
        conn = f"<code>{h(pq.source_details)}</code>" if pq.source_details else "<em>—</em>"
        rows += (
            f"<tr>"
            f"<td>{h(t.name)}</td>"
            f"<td><span class='badge source-badge'>{h(pq.source_type)}</span></td>"
            f"<td>{conn}</td>"
            f"<td>{h(pq.complexity_rating)}</td>"
            f"</tr>"
        )
    return f"""
    <section id="data-sources">
      <h2>Data Sources</h2>
      <table class="data-table">
        <thead><tr><th>Table</th><th>Source Type</th><th>Connection</th><th>Query Complexity</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>"""


def _render_table(table: Table, report_parsed: bool) -> str:
    tid = _tid(table.name)
    hidden_badge = '<span class="badge hidden-badge">hidden</span>' if table.is_hidden else ""
    role_badge   = f'<span class="badge role-badge role-{h(table.inferred_role.replace(" ", "-"))}">{h(table.inferred_role)}</span>'

    meta_parts = [
        f"<strong>Type:</strong> {'Calculated table' if table.is_calculated else 'Imported / DirectQuery'}",
    ]
    if table.source_query:
        pq = table.source_query
        src = h(pq.source_type)
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
        has_format = any(c.format_string for c in visible_cols)
        has_source = any(c.source_column for c in visible_cols)
        calc_cols  = [c for c in visible_cols if c.is_calculated and c.dax_expression]

        header_cells = "<th>Column</th><th>Type</th>"
        if has_format:
            header_cells += "<th>Format</th>"
        if has_source:
            header_cells += "<th>Source Column</th>"

        col_rows = ""
        for c in visible_cols:
            calc_badge = '<span class="badge calc-badge">calc</span>' if c.is_calculated else ""
            row = f"<td><code>{h(c.name)}</code>{calc_badge}</td><td>{h(c.data_type)}</td>"
            if has_format:
                row += f"<td><code>{h(c.format_string or '')}</code></td>" if c.format_string else "<td></td>"
            if has_source:
                row += f"<td><code>{h(c.source_column or '')}</code></td>" if c.source_column else "<td></td>"
            col_rows += f"<tr>{row}</tr>"

        calc_exprs_html = ""
        if calc_cols:
            items = ""
            for c in calc_cols:
                items += f"""
            <div class="calc-col-expr">
              <strong><code>{h(c.name)}</code></strong>
              <pre><code class="language-sql">{h(c.dax_expression)}</code></pre>
            </div>"""
            calc_exprs_html = f"""
          <details class="calc-exprs">
            <summary>Calculated column expressions ({len(calc_cols)})</summary>
            {items}
          </details>"""

        cols_html = f"""
      <h4>Columns</h4>
      <table class="data-table">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{col_rows}</tbody>
      </table>
      {calc_exprs_html}"""

    # Measures — grouped by display folder
    measures_html = ""
    if table.measures:
        folders: dict[str, list[Measure]] = defaultdict(list)
        for m in table.measures:
            folders[m.display_folder or ""].append(m)

        folder_order = [""] + sorted(k for k in folders if k)
        rendered_measures = ""
        for folder_key in folder_order:
            if folder_key not in folders:
                continue
            if folder_key:
                rendered_measures += f'<h5 class="folder-heading">📁 {h(folder_key)}</h5>'
            for m in folders[folder_key]:
                rendered_measures += _render_measure(m, report_parsed)

        measures_html = f"<h4>Measures</h4>{rendered_measures}"

    # Power Query steps
    pq_html = ""
    if table.source_query and table.source_query.step_descriptions:
        pq = table.source_query
        from extractor.powerquery_parser import _extract_step_names
        step_names = _extract_step_names(pq.m_code)
        steps_li = ""
        for i, desc in enumerate(pq.step_descriptions):
            name = step_names[i] if i < len(step_names) else f"Step {i+1}"
            steps_li += (
                f"<li><strong>{h(name)}</strong> — {h(desc)}</li>" if desc
                else f"<li><strong>{h(name)}</strong></li>"
            )
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
        items = "".join(
            f"<li><strong>{h(hr.name)}</strong>: {h(' → '.join(hr.levels))}</li>"
            for hr in table.hierarchies
        )
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


def _render_measure(measure: Measure, report_parsed: bool) -> str:
    hidden_badge = '<span class="badge hidden-badge">hidden</span>' if measure.is_hidden else ""
    folder_badge = (
        f'<span class="badge folder-badge">{h(measure.display_folder)}</span>'
        if measure.display_folder else ""
    )
    complexity_class = {
        "simple":       "measure-simple",
        "intermediate": "measure-intermediate",
        "advanced":     "measure-advanced",
    }.get(measure.complexity_tier, "")

    desc_html    = f"<p>{h(measure.description)}</p>" if measure.description else ""
    purpose_html = (
        f'<p class="business-purpose"><em>Business purpose: {h(measure.business_purpose)}</em></p>'
        if measure.business_purpose else ""
    )

    meta_parts = [f"Complexity: <span class='badge complexity-badge complexity-{h(measure.complexity_tier)}'>{h(measure.complexity_tier)}</span>"]
    if measure.format_string:
        meta_parts.append(f"Format: <code>{h(measure.format_string)}</code>")

    # Visual usage
    if report_parsed:
        if measure.used_in_visuals:
            vis_items = "".join(f"<li>{h(v)}</li>" for v in measure.used_in_visuals)
            meta_parts.append(
                f'<details class="inline-details"><summary>Used in {len(measure.used_in_visuals)} visual(s)</summary>'
                f'<ul class="detail-list">{vis_items}</ul></details>'
            )
        else:
            meta_parts.append('<span class="badge orphan-badge">not used in any visual</span>')
    else:
        meta_parts.append("<em>Visual usage: report not analysed</em>")

    # Dependencies
    deps_html = ""
    if measure.dependencies:
        dep_items = "".join(f"<li><code>{h(d)}</code></li>" for d in measure.dependencies)
        deps_html = (
            f'<details class="inline-details"><summary>Dependencies ({len(measure.dependencies)})</summary>'
            f'<ul class="detail-list">{dep_items}</ul></details>'
        )

    dax_escaped = h(measure.dax)
    return f"""
    <div class="measure {complexity_class}">
      <h5><code>{h(measure.name)}</code> {hidden_badge} {folder_badge}</h5>
      {desc_html}
      {purpose_html}
      <p class="meta">{" &nbsp;|&nbsp; ".join(meta_parts)}</p>
      {deps_html}
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
    infos    = [f for f in findings if f.severity == "info"]

    parts = ['<section id="quality"><h2>Quality Findings</h2>']
    for section_findings, label, icon in [(warnings, "Warnings", "⚠️"), (infos, "Info", "ℹ️")]:
        if not section_findings:
            continue
        items = "".join(
            f'<li><strong>{icon} {h(f.object_name)}</strong> '
            f'<span class="badge">{h(f.category)}</span> — {h(f.detail)}</li>'
            for f in section_findings
        )
        parts.append(f"<h3>{label} ({len(section_findings)})</h3><ul class='findings-list'>{items}</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _tid(name: str) -> str:
    return "table-" + name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")


def h(text) -> str:
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
      background: #fff;
    }

    /* ── Sidebar ── */
    #sidebar {
      width: 240px;
      min-width: 240px;
      background: #f8f9fa;
      border-right: 1px solid #dee2e6;
      padding: 0;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }
    #sidebar-title {
      font-weight: 700;
      font-size: 13px;
      padding: 14px 16px 10px;
      color: #343a40;
      border-bottom: 1px solid #dee2e6;
      word-break: break-word;
    }
    #search-wrap {
      padding: 8px 12px;
      border-bottom: 1px solid #dee2e6;
    }
    #search {
      width: 100%;
      padding: 5px 8px;
      border: 1px solid #ced4da;
      border-radius: 4px;
      font-size: 12px;
      outline: none;
    }
    #search:focus { border-color: #86b7fe; box-shadow: 0 0 0 2px rgba(13,110,253,.15); }
    #nav-links { padding: 6px 0; flex: 1; }
    #sidebar a {
      display: block;
      padding: 4px 16px;
      color: #0d6efd;
      text-decoration: none;
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    #sidebar a.nav-sub { padding-left: 28px; color: #495057; font-size: 12px; }
    #sidebar a:hover { background: #e9ecef; }

    /* ── Content ── */
    #content {
      flex: 1;
      padding: 32px 48px;
      max-width: 1400px;
      min-width: 0;
    }
    h1 { font-size: 28px; margin: 0 0 4px; }
    h2 { font-size: 20px; margin-top: 40px; border-bottom: 2px solid #dee2e6; padding-bottom: 6px; }
    h3 { font-size: 17px; margin-top: 24px; }
    h4 { font-size: 15px; margin-top: 20px; color: #343a40; }
    h5 { font-size: 14px; margin: 10px 0 4px; }
    p.meta { font-size: 12px; color: #6c757d; margin: 4px 0; }
    p.description { font-style: italic; color: #495057; margin: 6px 0; }
    p.business-purpose { font-size: 13px; color: #495057; margin: 4px 0; }

    /* ── Badges ── */
    .badge {
      display: inline-block;
      padding: 1px 7px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 500;
      background: #e9ecef;
      color: #495057;
      margin-left: 4px;
      vertical-align: middle;
    }
    .hidden-badge  { background: #f8d7da; color: #842029; }
    .orphan-badge  { background: #fff3cd; color: #664d03; }
    .calc-badge    { background: #e0cffc; color: #432874; }
    .folder-badge  { background: #fff3cd; color: #856404; }
    .source-badge  { background: #d1ecf1; color: #0c5460; }
    .role-badge    { background: #d1ecf1; color: #0c5460; }
    .role-fact     { background: #cfe2ff; color: #084298; }
    .role-dimension { background: #d1e7dd; color: #0a3622; }
    .role-measure-table { background: #e2d9f3; color: #3d1a78; }
    .role-bridge   { background: #fde8d8; color: #6a2c0e; }
    .complexity-badge { }
    .complexity-simple       { background: #d1e7dd; color: #0a3622; }
    .complexity-intermediate { background: #fff3cd; color: #664d03; }
    .complexity-advanced     { background: #f8d7da; color: #842029; }

    /* ── Table sections (collapsible) ── */
    details.table-section {
      border: 1px solid #dee2e6;
      border-radius: 6px;
      margin-bottom: 10px;
    }
    details.table-section > summary {
      padding: 10px 16px;
      cursor: pointer;
      font-size: 15px;
      font-weight: 600;
      background: #f8f9fa;
      border-radius: 6px;
      list-style: none;
      user-select: none;
    }
    details.table-section > summary::-webkit-details-marker { display: none; }
    details.table-section > summary::before { content: "▶ "; font-size: 10px; color: #6c757d; }
    details[open].table-section > summary::before { content: "▼ "; }
    details[open].table-section > summary { border-radius: 6px 6px 0 0; }
    .table-body { padding: 16px 20px; }

    /* ── Folder heading inside measures ── */
    .folder-heading {
      font-size: 13px;
      font-weight: 600;
      color: #6c757d;
      margin: 16px 0 6px;
      padding-bottom: 3px;
      border-bottom: 1px dashed #dee2e6;
    }

    /* ── Measure cards ── */
    .measure {
      border-left: 4px solid #dee2e6;
      padding: 10px 14px;
      margin-bottom: 14px;
      background: #fafafa;
      border-radius: 0 4px 4px 0;
    }
    .measure-simple       { border-left-color: #198754; }
    .measure-intermediate { border-left-color: #fd7e14; }
    .measure-advanced     { border-left-color: #dc3545; }

    /* ── Inline collapsible details (dependencies, visual usage) ── */
    details.inline-details {
      display: inline;
    }
    details.inline-details > summary {
      display: inline;
      cursor: pointer;
      color: #0d6efd;
      font-size: 12px;
    }
    details.inline-details > summary::-webkit-details-marker { display: none; }
    ul.detail-list {
      margin: 4px 0 4px 16px;
      padding: 6px 10px;
      background: #f1f3f5;
      border-radius: 4px;
      font-size: 12px;
    }
    ul.detail-list li { margin: 2px 0; }

    /* ── Calculated column expressions ── */
    details.calc-exprs > summary {
      cursor: pointer;
      font-size: 12px;
      color: #6c757d;
      margin-top: 6px;
    }
    .calc-col-expr { margin: 8px 0; }

    /* ── Tables ── */
    table.summary-table { border-collapse: collapse; margin-top: 8px; }
    table.summary-table th,
    table.summary-table td { padding: 4px 16px 4px 0; text-align: left; }
    table.summary-table th { color: #6c757d; font-weight: normal; min-width: 160px; }
    table.data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-top: 6px;
    }
    table.data-table th,
    table.data-table td {
      border: 1px solid #dee2e6;
      padding: 6px 10px;
      text-align: left;
      vertical-align: top;
    }
    table.data-table th { background: #f8f9fa; font-weight: 600; }

    /* ── Code ── */
    pre {
      background: #f8f9fa;
      border: 1px solid #dee2e6;
      border-radius: 4px;
      padding: 10px 14px;
      overflow-x: auto;
      font-size: 12px;
      margin: 6px 0;
    }
    code { font-family: "Cascadia Code", "Consolas", monospace; font-size: 12px; }

    /* ── Quality findings ── */
    ul.findings-list { padding-left: 20px; }
    ul.findings-list li { margin-bottom: 6px; }

    /* ── General details ── */
    details > summary { cursor: pointer; }

    /* ── Print ── */
    @media print {
      #sidebar { display: none; }
      #content { padding: 16px; max-width: 100%; }
      details.table-section,
      details.table-section > summary,
      details[open].table-section { display: block !important; }
      details.table-section > summary::before { content: ""; }
      .measure { break-inside: avoid; }
      a { color: inherit; text-decoration: none; }
    }
"""
