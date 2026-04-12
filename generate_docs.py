#!/usr/bin/env python3
"""
PBIX Semantic Model Documenter
Generates polished documentation from a Power BI .pbix file.

Usage:
  python generate_docs.py [OPTIONS] PBIX_FILE
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


@click.command()
@click.argument("pbix_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output-dir", "-o", default="./output", show_default=True,
              help="Directory where output files will be written.")
@click.option("--format", "-f", "fmt", default="all", show_default=True,
              help="Output format(s): docx, html, pdf, all")
@click.option("--skip-ai", is_flag=True, default=False,
              help="Skip LLM descriptions (faster, metadata-only output).")
@click.option("--skip-report", is_flag=True, default=False,
              help="Skip report layer parsing (no visual usage data).")
@click.option("--skip-quality", is_flag=True, default=False,
              help="Skip quality check analysis.")
@click.option("--model-name", default=None,
              help="Override the model name in output.")
def main(
    pbix_file: str,
    output_dir: str,
    fmt: str,
    skip_ai: bool,
    skip_report: bool,
    skip_quality: bool,
    model_name: str | None,
) -> None:
    """Generate documentation for a Power BI .pbix semantic model."""

    pbix_path = Path(pbix_file).resolve()
    out_dir = Path(output_dir).resolve()
    formats = _parse_formats(fmt)

    console.print(Panel(
        Text.assemble(
            ("PBIX Semantic Model Documenter\n", "bold cyan"),
            (f"Input:  {pbix_path}\n", ""),
            (f"Output: {out_dir}\n", ""),
            (f"Format: {', '.join(formats)}", ""),
        ),
        expand=False,
    ))

    # ── Step 1: Extract ───────────────────────────────────────────────────────
    console.print("\n[bold]Step 1/5:[/bold] Loading .pbix with pbixray...")
    from extractor import pbix_extractor
    try:
        data = pbix_extractor.extract(pbix_path)
    except Exception as e:
        console.print(f"[bold red]Extraction failed:[/bold red] {e}")
        sys.exit(1)

    console.print(f"  [ok] Loaded [cyan]{len(data.tables)}[/cyan] table(s)")

    # ── Step 2: Parse model ───────────────────────────────────────────────────
    console.print("\n[bold]Step 2/5:[/bold] Parsing semantic model...")
    from extractor import model_parser
    try:
        model = model_parser.parse(data)
    except Exception as e:
        console.print(f"[bold red]Model parsing failed:[/bold red] {e}")
        sys.exit(1)

    model.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if model_name:
        model.name = model_name

    n_measures = sum(len(t.measures) for t in model.tables)
    console.print(
        f"  [ok] {len(model.tables)} tables, {n_measures} measures, "
        f"{len(model.relationships)} relationships"
    )

    # ── Step 3: Report layer ──────────────────────────────────────────────────
    if not skip_report and data.report_layout_bytes:
        console.print("\n[bold]Step 3/5:[/bold] Parsing report layout for visual usage...")
        from extractor import report_parser
        report_parser.parse(data.report_layout_bytes, model)
        used_count = sum(1 for t in model.tables for m in t.measures if m.used_in_visuals)
        console.print(f"  [ok] {used_count} measure(s) found in visuals")
    else:
        console.print("\n[bold]Step 3/5:[/bold] Skipping report layer.")

    # ── Step 4: AI annotations ────────────────────────────────────────────────
    if not skip_ai:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            console.print(
                "\n[yellow]Warning:[/yellow] ANTHROPIC_API_KEY not set. "
                "Skipping AI descriptions.\nSet the environment variable and re-run, "
                "or use --skip-ai to suppress this warning."
            )
        else:
            console.print("\n[bold]Step 4/5:[/bold] Generating AI descriptions...")
            from ai import describer
            try:
                describer.annotate_model(model)
                console.print("  [ok] AI annotations complete")
            except Exception as e:
                console.print(f"  [yellow]AI step failed (continuing without):[/yellow] {e}")
    else:
        console.print("\n[bold]Step 4/5:[/bold] Skipping AI descriptions (--skip-ai).")

    # ── Step 5: Quality checks ────────────────────────────────────────────────
    findings = []
    if not skip_quality:
        console.print("\n[bold]Step 5/5:[/bold] Running quality checks...")
        from analyzer import quality_checks
        findings = quality_checks.run_all(model)
        warnings = sum(1 for f in findings if f.severity == "warning")
        infos = sum(1 for f in findings if f.severity == "info")
        console.print(f"  [ok] {warnings} warning(s), {infos} info item(s)")
    else:
        console.print("\n[bold]Step 5/5:[/bold] Skipping quality checks (--skip-quality).")

    # ── Render outputs ────────────────────────────────────────────────────────
    console.print("\n[bold]Rendering output...[/bold]")
    generated: list[Path] = []

    if "docx" in formats:
        try:
            from renderer import docx_renderer
            path = docx_renderer.render(model, findings, out_dir)
            generated.append(path)
            console.print(f"  [ok] Word      -> [cyan]{path}[/cyan]")
        except ImportError:
            console.print("  [yellow]Word skipped[/yellow]: python-docx not installed")

    if "html" in formats:
        from renderer import html_renderer
        path = html_renderer.render(model, findings, out_dir)
        generated.append(path)
        console.print(f"  [ok] HTML      -> [cyan]{path}[/cyan]")

    if "pdf" in formats:
        try:
            from renderer import pdf_renderer
            path = pdf_renderer.render(model, findings, out_dir)
            generated.append(path)
            console.print(f"  [ok] PDF       -> [cyan]{path}[/cyan]")
        except (RuntimeError, OSError, ImportError, Exception) as e:
            short = str(e).split("\n")[0][:120]
            console.print(f"  [yellow]PDF skipped[/yellow]: {short}")
            console.print("  [dim]  (WeasyPrint requires GTK/Pango on Windows — see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)[/dim]")

    console.print(Panel(
        Text.assemble(
            ("Done! ", "bold green"),
            (f"{len(generated)} file(s) written to {out_dir}", ""),
        ),
        expand=False,
    ))


def _parse_formats(fmt: str) -> list[str]:
    all_formats = ["docx", "html", "pdf"]
    fmt = fmt.strip().lower()
    if fmt == "all":
        return all_formats
    parts = [f.strip() for f in fmt.replace(",", " ").split()]
    valid = [f for f in parts if f in all_formats]
    if not valid:
        raise click.BadParameter(
            f"Unknown format(s): {fmt}. Choose from: docx, html, pdf, all"
        )
    return valid


if __name__ == "__main__":
    main()
