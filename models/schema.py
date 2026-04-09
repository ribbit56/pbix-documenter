from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PowerQuery:
    table_name: str
    m_code: str
    source_type: str             # "sql", "sharepoint", "excel", "web", "folder", etc.
    source_details: str          # Connection string / path / URL (sanitized)
    step_descriptions: list[str] # AI-generated plain-English per Applied Step
    output_columns: list[str]
    complexity_rating: str       # "simple" | "moderate" | "complex"


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
class Hierarchy:
    name: str
    levels: list[str]


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
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str             # "many_to_one", "one_to_one", "many_to_many"
    cross_filter_direction: str  # "single" | "both"
    is_active: bool


@dataclass
class Role:
    name: str
    table_permissions: list[str]


@dataclass
class SemanticModel:
    name: str
    source_file: str
    generated_at: str
    tables: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    report_parsed: bool = False  # True once report_parser has run
