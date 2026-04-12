<p align="center">
  <img src="logo/logo-dark.svg" width="160" alt="PBIX Documenter dark logo" />
  &nbsp;&nbsp;&nbsp;
  <img src="logo/logo-light.svg" width="160" alt="PBIX Documenter light logo" />
</p>

# PBIX Semantic Model Documenter

A CLI tool and Streamlit desktop app that automatically generates polished documentation for Power BI semantic models from any `.pbix` file — entirely on your local machine, no cloud upload required.

---

## Features

- **Zero-config extraction** — powered by [pbixray](https://github.com/Hugoberry/pbixray), handles modern XPress9-compressed `.pbix` files natively
- **Multiple output formats** — Markdown, Word (.docx), and HTML from a single run
- **Interactive model diagram** — entity-relationship diagram in the Streamlit app (Graphviz), HTML output (Mermaid.js), and Markdown (Mermaid code block for GitHub / VS Code / Notion)
- **AI-powered descriptions** — optional Anthropic Claude integration writes plain-English descriptions of DAX measures, Power Query steps, and table roles
- **Quality checks** — 8 built-in checks covering orphaned measures, bidirectional relationships, FILTER() on fact tables, missing descriptions, isolated tables, broken references, and more
- **Power Query analysis** — source type detection (SQL, Excel, CSV, SharePoint, Snowflake, etc.), complexity rating, and step-by-step descriptions
- **Report layer parsing** — identifies which measures are actually used in visuals
- **Row-level security** — documents RLS roles and table permissions
- **Desktop-friendly** — Streamlit UI runs locally on `localhost:8501`, file never leaves your machine

---

## Screenshots

### Streamlit App — Model Diagram tab
Tables are colour-coded by role (blue = fact, green = dimension, purple = measure table) with crow's-foot relationship notation.

### Streamlit App — Quality Findings tab
Warnings and info items presented as filterable dataframes.

---

## Quick Start

### Prerequisites

- Python 3.10+
- Windows, macOS, or Linux

### Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** PDF output requires WeasyPrint with GTK/Pango. On Windows this is complex to set up — the tool gracefully skips PDF and shows an install link if GTK is not found.

### Run the Streamlit app (recommended)

**Windows — double-click `launch.bat`**

or from a terminal:

```bash
py -m streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

### Run the CLI

```bash
py generate_docs.py "path/to/report.pbix" --format all --skip-ai
```

---

## CLI Usage

```
Usage: generate_docs.py [OPTIONS] PBIX_PATH

Options:
  --format TEXT        Output format(s): markdown, docx, html, pdf, all
                       [default: all]
  --output-dir PATH    Directory to write output files  [default: ./output]
  --skip-ai            Skip AI-generated descriptions
  --skip-report        Skip report layer parsing (visual usage detection)
  --skip-quality       Skip quality checks
  --help               Show this message and exit.
```

**Examples**

```bash
# Fast run — no AI, no report parsing
py generate_docs.py "Sales Report.pbix" --format markdown --skip-ai --skip-report

# Full run with AI descriptions (requires ANTHROPIC_API_KEY)
py generate_docs.py "Sales Report.pbix" --format all

# Word and HTML only
py generate_docs.py "Sales Report.pbix" --format docx,html --skip-ai
```

---

## Output Formats

All three formats contain the same content sections:

| Section | Markdown | Word | HTML |
|---------|----------|------|------|
| Overview stats | ✅ | ✅ | ✅ |
| Model diagram | Mermaid block | Mermaid source | Mermaid.js (interactive) |
| Tables (columns, measures, PQ, hierarchies) | ✅ | ✅ | ✅ collapsible |
| Relationships table | ✅ | ✅ | ✅ |
| Row-level security roles | ✅ | ✅ | ✅ |
| Quality findings | ✅ checkboxes | ✅ | ✅ |
| Table of contents | — | ✅ Word field | Sidebar nav |
| Syntax highlighting | fenced blocks | Courier New | Prism.js |

---

## AI Descriptions

When an `ANTHROPIC_API_KEY` is provided (or entered in the Streamlit sidebar), the tool calls the Claude API to generate:

- **DAX measure descriptions** — plain-English explanation + business purpose for every measure
- **Power Query step descriptions** — a sentence per Applied Step explaining what the transformation does
- **Table role descriptions** — inferred role for any table the heuristic couldn't classify automatically

Set the key as an environment variable or paste it into the Streamlit sidebar (it is never written to disk).

```bash
set ANTHROPIC_API_KEY=sk-ant-...   # Windows
export ANTHROPIC_API_KEY=sk-ant-... # macOS/Linux
py generate_docs.py "report.pbix" --format all
```

---

## Quality Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Orphaned measures | Warning | Measures not used in any visual (requires report parsing) |
| Bidirectional relationships | Warning | Cross-filter set to "Both" — can cause ambiguous results |
| FILTER() on fact table | Warning | Performance anti-pattern |
| Broken measure references | Warning | Reference to a hidden or nonexistent column/measure |
| Time intelligence without CALCULATE | Warning | Time function used outside a filter context |
| Missing descriptions | Info | Tables, columns, and measures with no description |
| Calculated column as measure | Info | Calculated column uses an aggregation — better as a measure |
| Isolated tables | Info | Tables with no relationships |

---

## Project Structure

```
pbix-documenter/
├── app.py                  # Streamlit UI
├── generate_docs.py        # Click CLI entry point
├── launch.bat              # Windows one-click launcher
├── requirements.txt
│
├── extractor/
│   ├── pbix_extractor.py   # pbixray wrapper → PbixData dataclass
│   ├── model_parser.py     # PbixData → SemanticModel
│   ├── powerquery_parser.py
│   └── report_parser.py    # Visual usage detection
│
├── models/
│   └── schema.py           # Dataclasses: SemanticModel, Table, Measure, …
│
├── ai/
│   ├── describer.py        # Claude API calls
│   └── prompts.py
│
├── analyzer/
│   └── quality_checks.py   # 8 quality check functions
│
└── renderer/
    ├── diagram_renderer.py # Graphviz DOT + Mermaid ER diagram
    ├── markdown_renderer.py
    ├── docx_renderer.py
    ├── html_renderer.py
    └── pdf_renderer.py     # WeasyPrint (requires GTK on Windows)
```

---

## Requirements

```
anthropic
click
pbixray
python-docx
rich
pyyaml
streamlit>=1.40
weasyprint  # optional — PDF only, requires GTK/Pango on Windows
```

---

## License

MIT
