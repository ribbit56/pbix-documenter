"""
Renders a SemanticModel to PDF using WeasyPrint (renders from the HTML output).
"""
from __future__ import annotations

from pathlib import Path

from analyzer.quality_checks import QualityFinding
from models.schema import SemanticModel
from renderer.html_renderer import build_html_string


def render(model: SemanticModel, findings: list[QualityFinding], output_dir: Path) -> Path:
    import io
    import sys
    _old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        from weasyprint import HTML
    except Exception as e:
        sys.stderr = _old_stderr
        raise RuntimeError(str(e)) from e
    finally:
        sys.stderr = _old_stderr

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = model.name.replace(" ", "_").replace("/", "-")
    out_path = output_dir / f"{safe_name}.pdf"

    html_string = build_html_string(model, findings)
    HTML(string=html_string).write_pdf(str(out_path))
    return out_path
