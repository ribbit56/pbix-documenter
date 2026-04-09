# CLAUDE.md — PBIX Documentation Generator

## Project Overview

A Python CLI tool that ingests a `.pbix` file and produces polished, human-readable documentation for a Power BI semantic model. The target audience is data analytics teams who need to understand, maintain, or onboard onto an existing model. The output should read like documentation written by a senior analyst — not a metadata dump.

---

## Goals

- Extract all meaningful metadata from a `.pbix` file without requiring a live Power BI connection
- Use an LLM to generate plain-English descriptions of DAX measures and Power Query steps
- Produce clean, structured documentation in multiple output formats (Markdown, Word/docx, HTML, PDF)
- Flag model quality issues (orphaned measures, missing descriptions, risky patterns)
- Be runnable as a simple CLI with minimal setup friction

---

## Architecture

```
pbix-doc-generator/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── generate_docs.py          # CLI entry point
├── extractor/
│   ├── __init__.py
│   ├── pbix_extractor.py     # Unzips .pbix, coordinates extraction
│   ├── model_parser.py       # Parses DataModelSchema JSON → structured objects
│   ├── powerquery_parser.py  # Parses Mashup M code per table/query
│   └── report_parser.py      # Parses report layout for visual/measure usage (optional)
├── ai/
│   ├── __init__.py
│   ├── describer.py          # Sends DAX/M to LLM, returns plain-English descriptions
│   └── prompts.py            # All LLM prompt templates, kept separate for easy tuning
├── analyzer/
│   ├── __init__.py
│   └── quality_checks.py     # Orphaned measures, missing descriptions, perf patterns
├── renderer/
│   ├── __init__.py
│   ├── markdown_renderer.py
│   ├── docx_renderer.py
│   ├── html_renderer.py
│   └── pdf_renderer.py
├── models/
│   ├── __init__.py
│   └── schema.py             # Dataclasses: SemanticModel, Table, Measure, Column, Relationship, Query
└── output/                   # Generated docs land here by default
```

---

## Core Data Models (`models/schema.py`)

All extractors should populate these dataclasses. Renderers consume them. The AI layer annotates them.

```python
@dataclass
class SemanticModel:
    name: str
    source_file: str
    generated_at: str
    tables: list[Table]
    relationships: list[Relationship]
    roles: list[Role]

@dataclass
class Table:
    name: str
    description: str
    is_hidden: bool
    is_calculated: bool          # Calculated table (DAX expression, not a query)
    source_query: PowerQuery | None
    columns: list[Column]
    measures: list[Measure]
    hierarchies: list[Hierarchy]
    inferred_role: str           # "fact", "dimension", "bridge", "parameter", "calculated"
    row_count: int | None

@dataclass
class Column:
    name: str
    data_type: str
    is_hidden: bool
    is_calculated: bool
    dax_expression: str | None
    format_string: str | None
    description: str             # From model metadata if set; else AI-generated
    source_column: str | None

@dataclass
class Measure:
    name: str
    table: str
    dax: str
    format_string: str | None
    is_hidden: bool
    description: str             # From model metadata if set; else AI-generated
    business_purpose: str        # AI-generated
    dependencies: list[str]      # Other measures/columns referenced
    complexity_tier: str         # "simple" | "intermediate" | "advanced"
    used_in_visuals: list[str]   # Populated from report_parser if available
    display_folder: str | None

@dataclass
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str             # "many_to_one", "one_to_one", "many_to_many"
    cross_filter_direction: str  # "single" | "both"
    is_active: bool

@dataclass
class PowerQuery:
    table_name: str
    m_code: str
    source_type: str             # "sql", "sharepoint", "excel", "web", "folder", etc.
    source_details: str          # Connection string / path / URL (sanitized)
    step_descriptions: list[str] # AI-generated plain-English per Applied Step
    output_columns: list[str]
    complexity_rating: str       # "simple" | "moderate" | "complex"
```

---

## Extraction Strategy

### Unpacking the .pbix

A `.pbix` is a ZIP archive. Extract it to a temp directory:

```python
import zipfile, tempfile, os

with tempfile.TemporaryDirectory() as tmp:
    with zipfile.ZipFile(pbix_path, 'r') as z:
        z.extractall(tmp)
    # Key paths inside:
    # DataModelSchema  → full model JSON (tables, measures, columns, relationships)
    # Mashup/Package/Formulas/Section1.m  → all Power Query M code
    # Report/Layout   → JSON describing report pages and visuals
```

**Preferred alternative:** Use `pbi-tools` to extract to a clean folder structure before parsing. This handles encoding quirks and gives more predictable JSON. Fall back to raw ZIP extraction if pbi-tools is unavailable.

### Model Parsing

`DataModelSchema` is the primary source. It's a large JSON blob. Key paths:

- `model.tables[]` — tables with columns, measures, hierarchies
- `model.relationships[]` — all relationships
- `model.roles[]` — row-level security roles

### Power Query Parsing

The M code lives in `Mashup`. Each table's query is a named section. Parse section names to map queries back to tables. Extract individual step names from `let ... in` blocks to pair with AI-generated descriptions.

### Report Parsing (Optional)

`Report/Layout` is JSON. Walk `sections[].visualContainers[].config` to find which measures appear in which visuals. Use this to populate `Measure.used_in_visuals` and identify orphaned measures.

---

## AI Layer (`ai/`)

### describer.py

Use the Anthropic Python SDK. All calls should be async-capable for batching.

```python
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

def describe_measure(measure: Measure, model_context: str) -> tuple[str, str]:
    """Returns (plain_english_description, inferred_business_purpose)"""
    ...

def describe_powerquery_steps(m_code: str, table_name: str) -> list[str]:
    """Returns one plain-English sentence per Applied Step"""
    ...
```

### prompts.py

Keep all prompt templates here. This makes it easy to tune without touching logic code.

- `MEASURE_DESCRIPTION_PROMPT` — include measure name, DAX, format string, table context, and names of other measures/columns in the model for grounding
- `POWERQUERY_STEP_PROMPT` — include table name, full M code, step name being described
- `TABLE_ROLE_PROMPT` — infer whether a table is a fact, dimension, bridge, etc.

**Important:** Always pass schema context (table names, column names, other measure names) to the LLM when describing measures. A measure named `[Gross Margin %]` in a model with `[Revenue]` and `[COGS]` measures should produce a much better description than one described in isolation.

---

## Quality Checks (`analyzer/quality_checks.py`)

Run after extraction, before rendering. Return structured findings:

```python
@dataclass
class QualityFinding:
    severity: str        # "warning" | "info"
    category: str        # "orphaned_measure", "missing_description", "perf_pattern", etc.
    object_name: str
    detail: str
```

Checks to implement:

| Check | Severity |
|---|---|
| Measure defined but not used in any visual | warning |
| Model object has no description set | info |
| Bidirectional relationship present | warning |
| FILTER() used on a large table instead of CALCULATETABLE | warning |
| Measure references a hidden/nonexistent column | warning |
| Calculated column that could be a measure | info |
| Table with no relationships | info |
| DAX with no CALCULATE wrapping a time intelligence function | warning |

---

## Output Formats

All renderers receive a `SemanticModel` object plus a list of `QualityFinding` objects.

### Markdown (`markdown_renderer.py`)
- Single `.md` file
- Use heading hierarchy: `#` model, `##` sections, `###` tables/measures
- Fenced code blocks with language hints for DAX (` ```dax `) and M (` ```powerquery `)
- Relationship table as a Markdown table
- Quality findings as a checklist at the end

### Word (`docx_renderer.py`)
- Use `python-docx`
- Apply heading styles so the document gets a proper navigation pane
- Include a table of contents (auto-generated via Word field)
- Syntax-highlight DAX/M using a monospace style with a light gray background
- Relationship inventory as a proper Word table

### HTML (`html_renderer.py`)
- Single self-contained file (inline CSS, no external dependencies)
- Collapsible sections for each table (so the doc doesn't overwhelm on first open)
- Syntax highlighting via embedded Prism.js (CDN or inlined)
- Left-side navigation panel with jump links

### PDF (`pdf_renderer.py`)
- Render from the HTML output using `weasyprint`
- Keeps styling consistent without maintaining a separate template

---

## CLI Interface (`generate_docs.py`)

```
Usage: generate_docs.py [OPTIONS] PBIX_FILE

Options:
  --output-dir PATH       Where to write output files [default: ./output]
  --format TEXT           Output format(s): markdown, docx, html, pdf, all [default: all]
  --skip-ai               Skip LLM descriptions (faster, metadata-only output)
  --skip-report           Skip report layer parsing (no visual usage data)
  --skip-quality          Skip quality check analysis
  --model-name TEXT       Override model name in output
  --help                  Show this message and exit.
```

---

## Environment & Dependencies

```
# requirements.txt
anthropic
python-docx
weasyprint
click
rich              # progress bars and console output
pyyaml            # config file support if needed
```

Set `ANTHROPIC_API_KEY` in environment before running.

Optional: install `pbi-tools` on PATH for cleaner extraction (Windows only; on other platforms fall back to raw ZIP).

---

## Development Priorities

Build in this order to get something working end-to-end quickly:

1. **Raw extraction** — unzip `.pbix`, locate key files, confirm you can read them
2. **Model parser** — populate `SemanticModel` from `DataModelSchema` (no AI yet)
3. **Markdown renderer** — get a metadata-only doc out the door
4. **AI describer** — add LLM descriptions for measures, verify quality
5. **Power Query parser** — extract and describe M code
6. **Quality checks** — flag issues
7. **Additional renderers** — docx, HTML, PDF
8. **Report parser** — visual usage mapping (most complex, lowest priority)

---

## Key Constraints & Notes

- The `.pbix` format is not officially documented by Microsoft. Extraction behavior may vary across `.pbix` versions. Always handle missing keys gracefully.
- `DataModelSchema` can be very large for complex models. Parse incrementally where possible.
- LLM calls can be slow for models with many measures. Batch where possible and show a progress bar.
- Never log or store connection strings or credentials found in Power Query source steps. Sanitize before including in output.
- pbi-tools only runs on Windows. The raw ZIP fallback must work cross-platform.
