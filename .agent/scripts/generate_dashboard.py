"""
generate_dashboard.py — Enhanced Pipeline Progress Dashboard
=============================================================
Generates a self-contained HTML dashboard with:
  - Overall progress & pass rate
  - Statistical distributions (timing, CoT size, answer size, code lines)
  - Failure category breakdown
  - Repair statistics (local vs Gemini)
  - Per-task detail table
  - Dark mode glassmorphism design

Usage:
    python generate_dashboard.py
"""
import os
import json
import glob
import re
import statistics as stats_lib

# Paths relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
JSON_DIR = os.path.join(PROJECT_ROOT, "Output", "json")
THINK_DIR = os.path.join(PROJECT_ROOT, "Output", "thinking")
EVAL_DIR = os.path.join(PROJECT_ROOT, "Eval")
PROGRESS_FILE = os.path.join(PROJECT_ROOT, "Output", "progress.json")
STATISTICS_FILE = os.path.join(PROJECT_ROOT, "Output", "statistics.json")
DASHBOARD_FILE = os.path.join(PROJECT_ROOT, "Output", "dashboard.html")


def safe_stat(arr, fn_name):
    """Safely compute a statistic on an array."""
    if not arr:
        return 0
    if fn_name == "min":
        return min(arr)
    if fn_name == "max":
        return max(arr)
    if fn_name == "mean":
        return round(stats_lib.mean(arr), 1)
    if fn_name == "stddev":
        return round(stats_lib.stdev(arr), 1) if len(arr) > 1 else 0
    return 0


def generate_dashboard():
    os.makedirs(os.path.dirname(DASHBOARD_FILE), exist_ok=True)

    # Count files
    json_files = glob.glob(os.path.join(JSON_DIR, "*.json"))
    thinking_files = glob.glob(os.path.join(THINK_DIR, "*.txt"))
    qa_files = glob.glob(os.path.join(EVAL_DIR, "*_QA.json"))

    # Load progress
    progress = {}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progress = json.load(f)

    # Load statistics
    statistics = {}
    if os.path.exists(STATISTICS_FILE):
        with open(STATISTICS_FILE, 'r', encoding='utf-8') as f:
            statistics = json.load(f)

    # Collect task data
    task_results = progress.get("task_results", {})
    pass_count = sum(1 for d in task_results.values() if d.get("status") == "PASS")
    fail_count = sum(1 for d in task_results.values() if d.get("status") != "PASS")
    total = pass_count + fail_count

    # Metric arrays for charts
    elapsed_arr = [d.get("elapsed_seconds", 0) for d in task_results.values() if d.get("elapsed_seconds")]
    cot_arr = [d.get("cot_chars", 0) for d in task_results.values() if d.get("cot_chars")]
    ans_arr = [d.get("answer_chars", 0) for d in task_results.values() if d.get("answer_chars")]
    code_arr = [d.get("code_lines", 0) for d in task_results.values() if d.get("code_lines")]
    attempts_arr = [d.get("gemini_attempts", 1) for d in task_results.values()]

    # Repair breakdown
    repair_none = sum(1 for d in task_results.values() if d.get("repair_type") == "none")
    repair_local = sum(1 for d in task_results.values() if d.get("repair_type") == "local")
    repair_gemini = sum(1 for d in task_results.values() if d.get("repair_type") in ("gemini", "local+gemini"))
    repair_exhausted = sum(1 for d in task_results.values() if d.get("repair_type") == "exhausted")

    # Attempt distribution
    attempt_1 = sum(1 for d in task_results.values() if d.get("gemini_attempts", 1) == 1 and d.get("status") == "PASS")
    attempt_2 = sum(1 for d in task_results.values() if d.get("gemini_attempts", 1) == 2 and d.get("status") == "PASS")
    attempt_3 = sum(1 for d in task_results.values() if d.get("gemini_attempts", 1) == 3 and d.get("status") == "PASS")

    # Group by PDF
    pdf_stats = {}
    for jf in json_files:
        name = os.path.basename(jf)
        match = re.match(r'(.+)_Turn\d+_Task\d+\.json', name)
        if match:
            doc = match.group(1)
            pdf_stats[doc] = pdf_stats.get(doc, 0) + 1

    pdfs_completed = len(progress.get("pdfs_completed", []))
    total_pdfs = max(len(set(pdf_stats.keys())), 1)

    # Build stat bar helper (inline SVG bar chart)
    def stat_bar(label, val, max_val, color):
        pct = min(100, int(val / max(max_val, 1) * 100))
        return f"""<div class="stat-bar-row">
            <span class="stat-label">{label}</span>
            <div class="stat-bar-bg"><div class="stat-bar-fill" style="width:{pct}%;background:{color};"></div></div>
            <span class="stat-value">{val:,.0f}</span>
        </div>"""

    # Build stats section
    def stats_card(title, arr, unit=""):
        if not arr:
            return f'<div class="stat-card"><h3>{title}</h3><p class="no-data">No data</p></div>'
        mn = safe_stat(arr, "min")
        mx = safe_stat(arr, "max")
        mean = safe_stat(arr, "mean")
        sd = safe_stat(arr, "stddev")
        return f"""<div class="stat-card">
            <h3>{title}</h3>
            <div class="stat-grid">
                <div class="stat-item"><span class="stat-num">{mn:,.0f}</span><span class="stat-lbl">Min</span></div>
                <div class="stat-item"><span class="stat-num">{mx:,.0f}</span><span class="stat-lbl">Max</span></div>
                <div class="stat-item"><span class="stat-num">{mean:,.0f}</span><span class="stat-lbl">Mean</span></div>
                <div class="stat-item"><span class="stat-num">{sd:,.0f}</span><span class="stat-lbl">Std Dev</span></div>
            </div>
            {stat_bar("Min", mn, mx, "#03dac6")}
            {stat_bar("Mean", mean, mx, "#bb86fc")}
            {stat_bar("Max", mx, mx, "#cf6679")}
        </div>"""

    stats_html = stats_card("Task Duration (seconds)", elapsed_arr)
    stats_html += stats_card("CoT Size (chars)", cot_arr)
    stats_html += stats_card("Answer Size (chars)", ans_arr)
    stats_html += stats_card("Code Lines", code_arr)

    # Per-task table rows
    task_rows = ""
    for tk in sorted(task_results.keys()):
        d = task_results[tk]
        status = d.get("status", "?")
        icon = "✅" if status == "PASS" else "❌"
        cot = f'{d.get("cot_chars", 0):,}'
        ans = f'{d.get("answer_chars", 0):,}'
        code = f'{d.get("code_lines", 0)}'
        elapsed = f'{d.get("elapsed_seconds", 0):.0f}s'
        attempts = d.get("gemini_attempts", 1)
        repair = d.get("repair_type", "none")
        repairs_applied = d.get("repairs_applied", [])
        repairs_str = ", ".join(repairs_applied) if repairs_applied else "—"

        row_class = "pass-row" if status == "PASS" else "fail-row"
        task_rows += f"""<tr class="{row_class}">
            <td>{icon} {tk}</td>
            <td>{cot}</td><td>{ans}</td><td>{code}</td>
            <td>{elapsed}</td><td>{attempts}</td>
            <td><span class="repair-badge repair-{repair}">{repair}</span></td>
            <td class="repairs-col">{repairs_str}</td>
        </tr>"""

    # PDF progress rows
    pdf_rows = ""
    for doc, count in sorted(pdf_stats.items()):
        pct = min(100, int(count / 16 * 100))
        color = "#03dac6" if pct == 100 else "#bb86fc"
        pdf_rows += f"""<div class="pdf-row">
            <span class="pdf-name">{doc}</span>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width:{pct}%;background:{color};"></div>
            </div>
            <span class="pdf-count">{count}/16</span>
        </div>"""

    # Pass rate for donut
    pass_rate = round(pass_count / max(total, 1) * 100, 1)
    first_attempt_rate = round(attempt_1 / max(total, 1) * 100, 1)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AD/ADAS Pipeline Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 40%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 2rem;
        }}
        .header {{
            text-align: center;
            margin-bottom: 2rem;
            padding: 2rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }}
        .header h1 {{
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(90deg, #bb86fc, #03dac6, #cf6679);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }}
        .header .subtitle {{ color: #666; font-size: 0.85rem; }}
        .header .timestamp {{ color: #555; font-size: 0.75rem; margin-top: 0.3rem; }}

        /* ─── Metric Cards ─── */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1rem;
            margin-bottom: 2.5rem;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.03);
            backdrop-filter: blur(16px);
            border-radius: 16px;
            padding: 1.5rem;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.06);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .metric-card:hover {{ transform: translateY(-4px); box-shadow: 0 12px 32px rgba(0,0,0,0.4); }}
        .metric-value {{
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(90deg, #bb86fc, #03dac6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .metric-value.success {{ background: linear-gradient(90deg, #03dac6, #00e676); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .metric-value.danger {{ background: linear-gradient(90deg, #cf6679, #ff5252); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .metric-label {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.3rem; }}

        /* ─── Section Headers ─── */
        .section-title {{
            font-size: 1.3rem;
            font-weight: 600;
            margin: 2rem 0 1rem;
            color: #bb86fc;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .section-title::after {{ content: ''; flex: 1; height: 1px; background: rgba(187,134,252,0.2); }}

        /* ─── Statistics Cards ─── */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.2rem;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.03);
            border-radius: 14px;
            padding: 1.5rem;
            border: 1px solid rgba(255,255,255,0.06);
        }}
        .stat-card h3 {{ font-size: 0.9rem; color: #bb86fc; margin-bottom: 1rem; font-weight: 500; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; margin-bottom: 1rem; }}
        .stat-item {{ text-align: center; }}
        .stat-num {{ display: block; font-size: 1.3rem; font-weight: 600; color: #e0e0e0; }}
        .stat-lbl {{ font-size: 0.65rem; color: #777; text-transform: uppercase; }}
        .stat-bar-row {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.4rem; }}
        .stat-label {{ font-size: 0.7rem; color: #999; width: 35px; text-align: right; }}
        .stat-bar-bg {{ flex: 1; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }}
        .stat-bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.6s ease; }}
        .stat-value {{ font-size: 0.7rem; color: #aaa; width: 60px; }}
        .no-data {{ color: #555; font-style: italic; font-size: 0.85rem; }}

        /* ─── Repair Breakdown ─── */
        .repair-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .repair-card {{
            background: rgba(255,255,255,0.03);
            border-radius: 12px;
            padding: 1.2rem;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.06);
        }}
        .repair-card .num {{ font-size: 1.8rem; font-weight: 700; }}
        .repair-card .label {{ font-size: 0.7rem; color: #888; text-transform: uppercase; margin-top: 0.3rem; }}

        /* ─── PDF Progress ─── */
        .pdf-row {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.8rem 1rem;
            background: rgba(255,255,255,0.02);
            border-radius: 8px;
            margin-bottom: 0.5rem;
        }}
        .pdf-name {{ flex: 0 0 280px; font-size: 0.8rem; color: #ccc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .progress-bar-bg {{ flex: 1; height: 8px; background: rgba(255,255,255,0.06); border-radius: 4px; overflow: hidden; }}
        .progress-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
        .pdf-count {{ flex: 0 0 50px; text-align: right; font-size: 0.8rem; color: #aaa; }}

        /* ─── Task Table ─── */
        .task-table-wrapper {{
            overflow-x: auto;
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 2rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.78rem;
        }}
        th {{
            background: rgba(187,134,252,0.1);
            color: #bb86fc;
            padding: 0.8rem;
            text-align: left;
            font-weight: 500;
            text-transform: uppercase;
            font-size: 0.7rem;
            letter-spacing: 0.04em;
            position: sticky;
            top: 0;
        }}
        td {{ padding: 0.65rem 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.03); }}
        .pass-row td {{ color: #ccc; }}
        .fail-row td {{ color: #cf6679; }}
        .repair-badge {{
            display: inline-block;
            padding: 0.15rem 0.5rem;
            border-radius: 6px;
            font-size: 0.65rem;
            font-weight: 500;
        }}
        .repair-none {{ background: rgba(3,218,198,0.15); color: #03dac6; }}
        .repair-local {{ background: rgba(187,134,252,0.15); color: #bb86fc; }}
        .repair-gemini {{ background: rgba(255,152,0,0.15); color: #ffab40; }}
        .repair-exhausted {{ background: rgba(207,102,121,0.15); color: #cf6679; }}
        .repair-local\\+gemini {{ background: rgba(255,152,0,0.15); color: #ffab40; }}
        .repairs-col {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.7rem; color: #777; }}

        /* ─── Footer ─── */
        .footer {{ text-align: center; margin-top: 3rem; color: #444; font-size: 0.7rem; padding-top: 1.5rem; border-top: 1px solid rgba(255,255,255,0.04); }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 AD/ADAS Coding Tasks Pipeline</h1>
        <p class="subtitle">Automated generation via Gemini + Playwright · Quality-gated with auto-repair</p>
        <p class="timestamp">Last updated: {progress.get("updated_at", "—")}</p>
    </div>

    <!-- ─── Top Metrics ─── -->
    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-value">{total}</div>
            <div class="metric-label">Total Tasks</div>
        </div>
        <div class="metric-card">
            <div class="metric-value success">{pass_count}</div>
            <div class="metric-label">QA Passed</div>
        </div>
        <div class="metric-card">
            <div class="metric-value danger">{fail_count}</div>
            <div class="metric-label">QA Failed</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{pass_rate}%</div>
            <div class="metric-label">Pass Rate</div>
        </div>
        <div class="metric-card">
            <div class="metric-value success">{first_attempt_rate}%</div>
            <div class="metric-label">1st Attempt</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{pdfs_completed}/{total_pdfs}</div>
            <div class="metric-label">PDFs Done</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{len(thinking_files)}</div>
            <div class="metric-label">Think Traces</div>
        </div>
    </div>

    <!-- ─── Statistical Distributions ─── -->
    <h2 class="section-title">📊 Statistical Distributions</h2>
    <div class="stats-grid">
        {stats_html}
    </div>

    <!-- ─── Repair Breakdown ─── -->
    <h2 class="section-title">🔧 Repair Analysis</h2>
    <div class="repair-grid">
        <div class="repair-card">
            <div class="num" style="color:#03dac6;">{repair_none}</div>
            <div class="label">No Repair Needed</div>
        </div>
        <div class="repair-card">
            <div class="num" style="color:#bb86fc;">{repair_local}</div>
            <div class="label">Local Repair</div>
        </div>
        <div class="repair-card">
            <div class="num" style="color:#ffab40;">{repair_gemini}</div>
            <div class="label">Gemini Retry</div>
        </div>
        <div class="repair-card">
            <div class="num" style="color:#cf6679;">{repair_exhausted}</div>
            <div class="label">Exhausted (Failed)</div>
        </div>
    </div>

    <!-- ─── Attempt Distribution ─── -->
    <h2 class="section-title">🎯 Attempt Distribution</h2>
    <div class="repair-grid">
        <div class="repair-card">
            <div class="num" style="color:#03dac6;">{attempt_1}</div>
            <div class="label">Pass on 1st</div>
        </div>
        <div class="repair-card">
            <div class="num" style="color:#bb86fc;">{attempt_2}</div>
            <div class="label">Pass on 2nd</div>
        </div>
        <div class="repair-card">
            <div class="num" style="color:#ffab40;">{attempt_3}</div>
            <div class="label">Pass on 3rd</div>
        </div>
    </div>

    <!-- ─── Per-Document Progress ─── -->
    <h2 class="section-title">📄 Per-Document Progress</h2>
    {pdf_rows if pdf_rows else '<p class="no-data">No tasks generated yet.</p>'}

    <!-- ─── Per-Task Detail ─── -->
    <h2 class="section-title">📋 Per-Task Detail</h2>
    <div class="task-table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Task</th>
                    <th>CoT</th><th>Answer</th><th>Code</th>
                    <th>Time</th><th>Attempts</th>
                    <th>Repair</th><th>Fixes Applied</th>
                </tr>
            </thead>
            <tbody>
                {task_rows if task_rows else '<tr><td colspan="8" class="no-data">No task data yet.</td></tr>'}
            </tbody>
        </table>
    </div>

    <div class="footer">
        <p>Pipeline Dashboard · Generated by generate_dashboard.py · © 4QDR.AI</p>
    </div>
</body>
</html>
"""
    with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Dashboard updated: {DASHBOARD_FILE}")


if __name__ == "__main__":
    generate_dashboard()
