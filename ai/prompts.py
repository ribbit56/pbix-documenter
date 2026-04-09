"""
All LLM prompt templates. Edit here to tune AI output without touching logic.
"""

MEASURE_DESCRIPTION_PROMPT = """\
You are a senior Power BI developer documenting a semantic model for a data analytics team.

## Model Context
Model name: {model_name}
Tables: {table_names}
All measures in model: {all_measure_names}

## Measure to Document
Table: {table_name}
Measure name: {measure_name}
DAX expression:
```
{dax}
```
Format string: {format_string}
Display folder: {display_folder}
Complexity: {complexity_tier}

## Instructions
Write two things:

1. **Description** (1–2 sentences): Explain what this measure calculates in plain English. \
Be specific about the calculation logic. Mention filters, time intelligence, or conditions if present.

2. **Business Purpose** (1 sentence): Explain why this measure exists and how a business user would use it.

Reply in this exact JSON format (no markdown fences):
{{"description": "...", "business_purpose": "..."}}
"""

POWERQUERY_STEP_PROMPT = """\
You are documenting Power Query M code for a data analytics team.

## Table
Table name: {table_name}
Source type: {source_type}

## Full M Code
```
{m_code}
```

## Steps to Document
{step_names}

## Instructions
For each step listed above, write one plain-English sentence explaining what it does. \
Focus on the business action (e.g., "Removes rows where the Status column is blank" not \
"Filters the table using Table.SelectRows").

Reply in this exact JSON format (no markdown fences), with one entry per step in order:
{{"steps": ["step 1 description", "step 2 description", ...]}}
"""

TABLE_ROLE_PROMPT = """\
You are a senior data modeller reviewing a Power BI semantic model.

## Model Context
Model name: {model_name}
All tables: {all_table_names}

## Table to Classify
Table name: {table_name}
Columns: {column_names}
Number of measures: {measure_count}
Has Power Query source: {has_source_query}
Is calculated table: {is_calculated}

## Instructions
Classify this table's role in the model. Choose one of:
- fact: Contains transactional or event-level data (sales, orders, logs)
- dimension: Contains descriptive attributes used for filtering/grouping (customers, products, dates)
- bridge: Resolves a many-to-many relationship between two other tables
- parameter: A disconnected table used for What-If parameters or slicer values
- calculated: A DAX-calculated table (not from a query)
- unknown: Cannot be determined

Reply in this exact JSON format (no markdown fences):
{{"role": "fact|dimension|bridge|parameter|calculated|unknown", "reasoning": "one sentence"}}
"""
