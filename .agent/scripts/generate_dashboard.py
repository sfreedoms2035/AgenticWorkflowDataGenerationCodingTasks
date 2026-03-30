"""
generate_dashboard.py — Pipeline Progress Dashboard
=====================================================
Generates a self-contained HTML dashboard with pipeline statistics,
per-PDF progress, and QA pass/fail rates.

Usage:
    python generate_dashboard.py
"""
import os
import json
import glob
import re

# Paths relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
JSON_DIR = os.path.join(PROJECT_ROOT, "Output", "json")
THINK_DIR = os.path.join(PROJECT_ROOT, "Output", "thinking")
EVAL_DIR = os.path.join(PROJECT_ROOT, "Eval")
PROGRESS_FILE = os.path.join(PROJECT_ROOT, "Output", "progress.json")


def generate_dashboard():
    os.makedirs(EVAL_DIR, exist_ok=True)

    # Count files
    json_files = glob.glob(os.path.join(JSON_DIR, "*.json"))
    thinking_files = glob.glob(os.path.join(THINK_DIR, "*.txt"))
    qa_files = glob.glob(os.path.join(EVAL_DIR, "*_QA.json"))

    # Load progress
    progress = {}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progress = json.load(f)

    # Count pass/fail from progress or QA files
    pass_count = 0
    fail_count = 0

    task_results = progress.get("task_results", {})
    if task_results:
        for tk, res in task_results.items():
            if res.get("status") == "PASS":
                pass_count += 1
            else:
                fail_count += 1
    else:
        for qa in qa_files:
            try:
                with open(qa, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if d.get("overall_status") == "PASS":
                    pass_count += 1
                else:
                    fail_count += 1
            except Exception:
                pass

    # Group by PDF
    pdf_stats = {}
    for jf in json_files:
        name = os.path.basename(jf)
        match = re.match(r'(.+)_Turn\d+_Task\d+\.json', name)
        if match:
            doc = match.group(1)
            pdf_stats[doc] = pdf_stats.get(doc, 0) + 1

    pdfs_completed = len(progress.get("pdfs_completed", []))
    total_pdfs = len(set(pdf_stats.keys())) or 1

    # Build per-PDF rows
    pdf_rows = ""
    for doc, count in sorted(pdf_stats.items()):
        pct = min(100, int(count / 16 * 100))
        color = "#03dac6" if pct == 100 else "#bb86fc"
        pdf_rows += f"""
        <div class="pdf-row">
            <span class="pdf-name">{doc}</span>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: {pct}%; background: {color};"></div>
            </div>
            <span class="pdf-count">{count}/16</span>
        </div>"""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Coding Tasks Generation Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', 'Segoe UI', 'Roboto', sans-serif;
            background: linear-gradient(135deg, #0d0d0d 0%, #1a1a2e 50%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 2rem;
        }}
        .header {{
            text-align: center;
            margin-bottom: 2.5rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .header h1 {{
            font-size: 1.8rem;
            background: linear-gradient(90deg, #bb86fc, #03dac6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header p {{ color: #888; margin-top: 0.5rem; font-size: 0.9rem; }}
        .metrics-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1.2rem;
            margin-bottom: 2.5rem;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.04);
            backdrop-filter: blur(12px);
            border-radius: 14px;
            padding: 1.5rem;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.08);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .metric-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }}
        .metric-value {{
            font-size: 2.2rem;
            font-weight: 700;
            margin-bottom: 0.3rem;
            background: linear-gradient(90deg, #bb86fc, #03dac6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .metric-label {{ font-size: 0.85rem; color: #999; text-transform: uppercase; letter-spacing: 0.05em; }}
        .section-title {{
            font-size: 1.2rem;
            margin-bottom: 1rem;
            color: #bb86fc;
        }}
        .pdf-row {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.8rem 1rem;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            margin-bottom: 0.5rem;
        }}
        .pdf-name {{ flex: 0 0 250px; font-size: 0.85rem; color: #ccc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .progress-bar-bg {{ flex: 1; height: 8px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; }}
        .progress-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
        .pdf-count {{ flex: 0 0 50px; text-align: right; font-size: 0.85rem; color: #aaa; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>AD/ADAS Coding Tasks Pipeline</h1>
        <p>Automated generation via Gemini Pro + Playwright</p>
    </div>

    <div class="metrics-container">
        <div class="metric-card">
            <div class="metric-value">{len(json_files)}</div>
            <div class="metric-label">Tasks Generated</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{pass_count}</div>
            <div class="metric-label">QA Passed</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{fail_count}</div>
            <div class="metric-label">QA Failed</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{len(thinking_files)}</div>
            <div class="metric-label">Thinking Traces</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{pdfs_completed}/{total_pdfs}</div>
            <div class="metric-label">PDFs Complete</div>
        </div>
    </div>

    <h2 class="section-title">Per-Document Progress</h2>
    {pdf_rows if pdf_rows else '<p style="color:#666;">No tasks generated yet.</p>'}
</body>
</html>
"""
    dashboard_path = os.path.join(EVAL_DIR, "dashboard.html")
    with open(dashboard_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Dashboard updated: {dashboard_path}")


if __name__ == "__main__":
    generate_dashboard()
