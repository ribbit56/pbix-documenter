"""
PBIX Semantic Model Documenter — Streamlit UI
Run with: py -m streamlit run app.py
Or double-click launch.bat
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path regardless of launch location
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PBIX Documenter",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Session state ─────────────────────────────────────────────────────────────
def _init_state() -> None:
    defaults = {
        "api_key": "",
        "skip_ai": False,
        "skip_report": False,
        "skip_quality": False,
        "output_formats": ["markdown", "docx", "html"],
        "pipeline_done": False,
        "pipeline_error": None,
        "pbix_path": None,
        "tmp_dir": None,
        "findings": [],
        "generated_files": {},
        "markdown_text": "",
        "model": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _cleanup() -> None:
    tmp = st.session_state.get("tmp_dir")
    if tmp and os.path.exists(tmp):
        shutil.rmtree(tmp, ignore_errors=True)


def _reset() -> None:
    _cleanup()
    st.session_state.clear()
    st.rerun()


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _render_sidebar() -> None:
    with st.sidebar:
        st.title("📊 PBIX Documenter")
        st.info(
            "**100% local** — your .pbix file is never uploaded "
            "to the internet. Everything runs on this machine.",
            icon="🔒",
        )
        st.divider()

        st.subheader("AI Descriptions")
        st.session_state["api_key"] = st.text_input(
            "Anthropic API Key",
            value=st.session_state["api_key"],
            type="password",
            help="Required for AI-generated descriptions. Stored in session memory only — never saved to disk.",
            placeholder="sk-ant-...",
        )
        st.session_state["skip_ai"] = st.checkbox(
            "Skip AI descriptions",
            value=st.session_state["skip_ai"],
            help="Faster run — produces metadata-only output with no plain-English descriptions.",
        )

        st.divider()
        st.subheader("Options")
        st.session_state["skip_report"] = st.checkbox(
            "Skip report layer parsing",
            value=st.session_state["skip_report"],
            help="Skip identifying which measures appear in visuals.",
        )
        st.session_state["skip_quality"] = st.checkbox(
            "Skip quality checks",
            value=st.session_state["skip_quality"],
        )
        st.session_state["output_formats"] = st.multiselect(
            "Output formats",
            options=["markdown", "docx", "html"],
            default=st.session_state["output_formats"],
        )

        if st.session_state["pipeline_done"]:
            st.divider()
            if st.button("🔄 Start Over", use_container_width=True):
                _reset()


# ── Pipeline ──────────────────────────────────────────────────────────────────
def _run_pipeline(pbix_path: Path, tmp_dir: Path) -> None:
    skip_ai = st.session_state["skip_ai"]
    skip_report = st.session_state["skip_report"]
    skip_quality = st.session_state["skip_quality"]
    formats = st.session_state["output_formats"]
    api_key = st.session_state["api_key"]

    with st.status("Generating documentation...", expanded=True) as status:

        # Step 1 — Extract
        st.write("**Step 1/5** — Loading .pbix file...")
        try:
            from extractor import pbix_extractor
            data = pbix_extractor.extract(pbix_path)
            st.write(f"Loaded {len(data.tables)} table(s)")
        except Exception as e:
            status.update(label=f"Extraction failed: {e}", state="error")
            st.session_state["pipeline_error"] = str(e)
            return

        # Step 2 — Parse
        st.write("**Step 2/5** — Parsing semantic model...")
        try:
            from extractor import model_parser
            model = model_parser.parse(data)
            model.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            n_measures = sum(len(t.measures) for t in model.tables)
            st.write(
                f"{len(model.tables)} tables, {n_measures} measures, "
                f"{len(model.relationships)} relationships"
            )
        except Exception as e:
            status.update(label=f"Model parsing failed: {e}", state="error")
            st.session_state["pipeline_error"] = str(e)
            return

        # Step 3 — Report layer
        if not skip_report and data.report_layout_bytes:
            st.write("**Step 3/5** — Parsing report layout...")
            try:
                from extractor import report_parser
                report_parser.parse(data.report_layout_bytes, model)
                used = sum(1 for t in model.tables for m in t.measures if m.used_in_visuals)
                st.write(f"{used} measure(s) found in visuals")
            except Exception as e:
                st.warning(f"Report parsing failed (continuing): {e}")
        else:
            st.write("**Step 3/5** — Skipping report layer.")

        # Step 4 — AI
        if not skip_ai:
            if not api_key:
                st.warning("No API key provided — skipping AI descriptions.")
            else:
                st.write("**Step 4/5** — Generating AI descriptions...")
                try:
                    _run_ai(model, api_key)
                    st.write("AI annotations complete")
                except Exception as e:
                    st.warning(f"AI step failed (continuing without): {e}")
        else:
            st.write("**Step 4/5** — Skipping AI descriptions.")

        # Step 5 — Quality checks
        findings = []
        if not skip_quality:
            st.write("**Step 5/5** — Running quality checks...")
            from analyzer import quality_checks
            findings = quality_checks.run_all(model)
            warnings = sum(1 for f in findings if f.severity == "warning")
            infos = sum(1 for f in findings if f.severity == "info")
            st.write(f"{warnings} warning(s), {infos} info item(s)")
        else:
            st.write("**Step 5/5** — Skipping quality checks.")

        # Render
        st.write("**Rendering output files...**")
        out_dir = tmp_dir / "output"
        generated_files: dict[str, Path] = {}

        if "markdown" in formats:
            from renderer import markdown_renderer
            path = markdown_renderer.render(model, findings, out_dir)
            generated_files["markdown"] = path

        if "docx" in formats:
            try:
                from renderer import docx_renderer
                path = docx_renderer.render(model, findings, out_dir)
                generated_files["docx"] = path
            except ImportError:
                st.warning("Word output skipped — python-docx not installed.")
            except Exception as e:
                st.warning(f"Word output skipped: {e}")

        if "html" in formats:
            try:
                from renderer import html_renderer
                path = html_renderer.render(model, findings, out_dir)
                generated_files["html"] = path
            except Exception as e:
                st.warning(f"HTML output skipped: {e}")

        status.update(label="Documentation generated!", state="complete", expanded=False)

    # Store results in session state
    st.session_state["findings"] = findings
    st.session_state["generated_files"] = generated_files
    st.session_state["markdown_text"] = (
        generated_files["markdown"].read_text(encoding="utf-8")
        if "markdown" in generated_files
        else ""
    )
    st.session_state["model"] = model
    st.session_state["pipeline_done"] = True
    st.session_state["pipeline_error"] = None


def _run_ai(model, api_key: str) -> None:
    """Run AI annotations with a Streamlit progress bar instead of rich.Progress."""
    from ai import describer

    os.environ["ANTHROPIC_API_KEY"] = api_key
    try:
        ctx = describer._model_context(model)

        tables_needing_role = [t for t in model.tables if t.inferred_role == "unknown"]
        all_measures = [(t, m) for t in model.tables for m in t.measures]
        tables_with_pq = [t for t in model.tables if t.source_query is not None]

        total = len(tables_needing_role) + len(all_measures) + len(tables_with_pq)
        if total == 0:
            return

        bar = st.progress(0, text="Starting AI annotations...")
        done = 0

        for table in tables_needing_role:
            bar.progress(done / total, text=f"Table role: {table.name}")
            result = describer.describe_table_role(table, ctx)
            table.inferred_role = result.get("role", "unknown")
            done += 1

        for table, measure in all_measures:
            bar.progress(done / total, text=f"Measure: {measure.name}")
            if not (measure.description and measure.business_purpose):
                desc, purpose = describer.describe_measure(measure, ctx)
                if not measure.description:
                    measure.description = desc
                measure.business_purpose = purpose
            done += 1

        for table in tables_with_pq:
            pq = table.source_query
            bar.progress(done / total, text=f"Power Query: {table.name}")
            if pq and not pq.step_descriptions:
                pq.step_descriptions = describer.describe_powerquery_steps(pq, table.name)
            done += 1

        bar.progress(1.0, text="AI annotations complete")
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ── Results ───────────────────────────────────────────────────────────────────
def _render_results() -> None:
    generated_files: dict[str, Path] = st.session_state["generated_files"]
    findings = st.session_state["findings"]
    markdown_text = st.session_state["markdown_text"]
    model = st.session_state.get("model")

    tab_diagram, tab_preview, tab_quality, tab_downloads = st.tabs(
        ["🔀 Model Diagram", "📄 Preview", "🔍 Quality Findings", "⬇️ Downloads"]
    )

    with tab_diagram:
        if model is None:
            st.info("No model available.")
        else:
            from renderer import diagram_renderer
            import json
            mermaid_src = diagram_renderer.build_mermaid(model)
            mermaid_json = json.dumps(mermaid_src)
            html_src = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: transparent; font-family: sans-serif; }}
  #toolbar {{
    display: flex; gap: 6px; padding: 8px 10px;
    background: rgba(255,255,255,0.06);
    border-bottom: 1px solid rgba(255,255,255,0.1);
  }}
  #toolbar button {{
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.2);
    color: #ddd; border-radius: 6px;
    padding: 5px 12px; font-size: 13px; cursor: pointer;
    transition: background 0.15s;
  }}
  #toolbar button:hover {{ background: rgba(255,255,255,0.22); color: #fff; }}
  #toolbar .sep {{ flex: 1; }}
  #toolbar .hint {{
    color: rgba(255,255,255,0.35); font-size: 12px;
    align-self: center; padding-right: 4px;
  }}
  #container {{
    width: 100%; height: calc(100vh - 52px);
    overflow: hidden; position: relative;
  }}
  #container svg {{
    width: 100%; height: 100%;
  }}
</style>
</head>
<body>
<div id="toolbar">
  <button onclick="pz && pz.zoomIn()" title="Zoom in">＋</button>
  <button onclick="pz && pz.zoomOut()" title="Zoom out">－</button>
  <button onclick="pz && (pz.fit(), pz.center())" title="Fit to window">⊡ Fit</button>
  <button onclick="pz && (pz.resetZoom(), pz.resetPan())" title="Reset view">↺ Reset</button>
  <span class="sep"></span>
  <span class="hint">Scroll to zoom &nbsp;·&nbsp; Drag to pan</span>
</div>
<div id="container">
  <pre class="mermaid" style="display:none" id="mermaid-src"></pre>
</div>
<script>
(async () => {{
  const src = {mermaid_json};
  document.getElementById("mermaid-src").textContent = src;

  mermaid.initialize({{ startOnLoad: false, theme: "default", er: {{ useMaxWidth: false }} }});

  const {{ svg }} = await mermaid.render("diagram", src);
  const container = document.getElementById("container");
  container.innerHTML = svg;

  const svgEl = container.querySelector("svg");
  svgEl.removeAttribute("width");
  svgEl.removeAttribute("height");
  svgEl.style.width  = "100%";
  svgEl.style.height = "100%";

  // Lighten relationship lines and markers for dark backgrounds
  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = `
    .er.relationshipLine {{ stroke: #a0b4cc !important; stroke-width: 1.5px !important; }}
    marker path, marker line {{ stroke: #a0b4cc !important; fill: #a0b4cc !important; }}
    .er.relationshipLabelBox {{ fill: #2a2a3a !important; stroke: #a0b4cc !important; }}
    .er.relationshipLabel {{ fill: #c8d8e8 !important; }}
  `;
  svgEl.prepend(style);

  window.pz = svgPanZoom(svgEl, {{
    zoomEnabled:    true,
    panEnabled:     true,
    controlIconsEnabled: false,
    fit:            true,
    center:         true,
    minZoom:        0.05,
    maxZoom:        20,
    zoomScaleSensitivity: 0.3,
  }});

  window.addEventListener("resize", () => {{ pz.fit(); pz.center(); }});
}})();
</script>
</body>
</html>"""
            st.components.v1.html(html_src, height=680, scrolling=False)

            with st.expander("Show Mermaid source (copy into any Mermaid viewer)"):
                st.code(mermaid_src, language="text")

    with tab_preview:
        if markdown_text:
            st.markdown(markdown_text)
        else:
            st.info("Markdown output was not selected — no preview available.")

    with tab_quality:
        if not findings:
            st.success("No quality issues found.")
        else:
            warnings = [f for f in findings if f.severity == "warning"]
            infos = [f for f in findings if f.severity == "info"]

            if warnings:
                st.subheader(f"Warnings ({len(warnings)})")
                st.dataframe(
                    pd.DataFrame([
                        {"Object": f.object_name, "Category": f.category, "Detail": f.detail}
                        for f in warnings
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )

            if infos:
                with st.expander(f"Info items ({len(infos)})", expanded=False):
                    st.dataframe(
                        pd.DataFrame([
                            {"Object": f.object_name, "Category": f.category, "Detail": f.detail}
                            for f in infos
                        ]),
                        use_container_width=True,
                        hide_index=True,
                    )

    with tab_downloads:
        if not generated_files:
            st.warning("No output files were generated.")
        else:
            st.write("Click a button to download the generated documentation:")
            st.write("")

            cols = st.columns(len(generated_files))
            labels = {
                "markdown": ("📝 Markdown (.md)", "text/markdown"),
                "docx": ("📘 Word (.docx)", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                "html": ("🌐 HTML (.html)", "text/html"),
            }
            for col, (fmt, path) in zip(cols, generated_files.items()):
                label, mime = labels[fmt]
                with col:
                    st.download_button(
                        label=label,
                        data=path.read_bytes(),
                        file_name=path.name,
                        mime=mime,
                        use_container_width=True,
                    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    _init_state()
    _render_sidebar()

    st.title("PBIX Semantic Model Documenter")
    st.caption(
        "Generate polished documentation from any Power BI .pbix file. "
        "Runs entirely on your local machine."
    )

    # Error banner
    if st.session_state["pipeline_error"]:
        st.error(f"**Error:** {st.session_state['pipeline_error']}")

    # Results view
    if st.session_state["pipeline_done"]:
        _render_results()
        return

    # Landing view
    st.divider()
    uploaded = st.file_uploader(
        "Upload your .pbix file",
        type=["pbix"],
        help="The file is written to a temporary folder on this machine and never sent anywhere.",
    )

    # Write the uploaded file to disk once
    if uploaded and st.session_state["pbix_path"] is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="pbixdoc_"))
        tmp_pbix = tmp_dir / uploaded.name
        tmp_pbix.write_bytes(uploaded.read())
        st.session_state["tmp_dir"] = tmp_dir
        st.session_state["pbix_path"] = tmp_pbix

    pbix_path: Path | None = st.session_state["pbix_path"]
    has_formats = bool(st.session_state["output_formats"])

    if pbix_path:
        st.success(f"Ready: **{pbix_path.name}**")

    if not has_formats:
        st.warning("Select at least one output format in the sidebar.")

    btn = st.button(
        "Generate Documentation",
        type="primary",
        disabled=not (pbix_path and has_formats),
        use_container_width=False,
    )

    if btn:
        _run_pipeline(pbix_path, st.session_state["tmp_dir"])
        st.rerun()


if __name__ == "__main__":
    main()
