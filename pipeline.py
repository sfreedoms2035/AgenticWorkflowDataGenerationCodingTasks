"""
pipeline.py — Master Orchestrator for AD/ADAS Coding Task Generation
=====================================================================
Single entry point that automates the entire PDF → 16 tasks pipeline:
  1. Scans Input/ for PDFs
  2. Classifies each PDF as Technical or Regulatory
  3. For each PDF, runs 8 turns × 2 tasks = 16 tasks
  4. Each task: generate prompt → Playwright → validate → auto-repair → retry
  5. Max 3 Gemini attempts per task; local repair between each attempt
  6. Dashboard generated after every completed PDF (8 tasks)
  7. Tracks progress in Output/progress.json for resume support

Usage:
    python pipeline.py                              # Process all PDFs
    python pipeline.py --pdf "specific.pdf"          # Process one PDF
    python pipeline.py --resume                      # Resume from last checkpoint
    python pipeline.py --pdf "file.pdf" --turn 3     # Start from Turn 3
    python pipeline.py --validate-only               # Just validate existing outputs
    python pipeline.py --no-dashboard                # Skip dashboard generation
"""
import os
import sys
import json
import glob
import subprocess
import argparse
import time
import statistics
import webbrowser
from datetime import datetime


# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "Input")
OUTPUT_JSON_DIR = os.path.join(BASE_DIR, "Output", "json")
OUTPUT_THINK_DIR = os.path.join(BASE_DIR, "Output", "thinking")
EVAL_DIR = os.path.join(BASE_DIR, "Eval")
PROMPTS_DIR = os.path.join(BASE_DIR, ".agent", "prompts")
SCRIPTS_DIR = os.path.join(BASE_DIR, ".agent", "scripts")
PROGRESS_FILE = os.path.join(BASE_DIR, "Output", "progress.json")
STATISTICS_FILE = os.path.join(BASE_DIR, "Output", "statistics.json")
DASHBOARD_OUTPUT = os.path.join(BASE_DIR, "Output", "dashboard.html")

PLAYWRIGHT_SCRIPT = os.path.join(BASE_DIR, "run_gemini_playwright_v2.py")
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_task.py")
AUTO_REPAIR_SCRIPT = os.path.join(SCRIPTS_DIR, "auto_repair.py")
PARTIAL_REPAIR_SCRIPT = os.path.join(SCRIPTS_DIR, "partial_repair.py")
DASHBOARD_SCRIPT = os.path.join(SCRIPTS_DIR, "generate_dashboard.py")

MAX_GEMINI_ATTEMPTS = 3  # Max Gemini re-prompts per task


# ── Variation Schema ─────────────────────────────────────────────────────────
# Each turn produces 2 tasks. Schema: (language, difficulty, meta_strategy, role)
VARIATION_TECHNICAL = {
    1: [("C++",    95, "Reverse Engineering",       "Senior Software Architect"),
        ("Rust",   90, "Practical Implementation",  "Senior Software Architect")],
    2: [("Python", 88, "Improve Existing",          "Senior System Engineer"),
        ("C++",    98, "Benchmark & Optimize",      "Senior System Engineer")],
    3: [("Rust",   94, "Critique & Harden",         "Senior Safety Manager"),
        ("Python", 85, "Theory to Code",            "Senior Safety Manager")],
    4: [("C++",    96, "Reverse Engineering",        "Senior Validation Engineer"),
        ("C++",    94, "Benchmark & Optimize",      "Senior Validation Engineer")],
    5: [("Python", 86, "Practical Implementation",  "Senior Integration Engineer"),
        ("Rust",   91, "Threat Modeling",            "Senior Integration Engineer")],
    6: [("C++",    90, "Stress Testing",             "Senior Project Manager"),
        ("Rust",   89, "Improve Existing",           "Senior Project Manager")],
    7: [("C++",    84, "Practical Implementation",  "Senior DevOps Engineer"),
        ("Python", 93, "Theory to Code",            "Senior DevOps Engineer")],
    8: [("Python", 82, "Reverse Engineering",        "Senior Requirements Engineering Manager"),
        ("C++",    99, "Critique & Harden",          "Senior Requirements Engineering Manager")],
}

VARIATION_REGULATORY = {
    1: [("C++",    95, "Formalize",       "Senior Software Architect"),
        ("Python", 90, "Validate",        "Senior Software Architect")],
    2: [("Rust",   88, "Liability",       "Senior System Engineer"),
        ("C++",    98, "Traceability",    "Senior System Engineer")],
    3: [("Python", 94, "Loophole",        "Senior Safety Manager"),
        ("Python", 85, "Ambiguity",       "Senior Safety Manager")],
    4: [("Rust",   96, "Formalize",       "Senior Validation Engineer"),
        ("C++",    94, "Validate",        "Senior Validation Engineer")],
    5: [("Python", 86, "Audit",           "Senior Integration Engineer"),
        ("Rust",   91, "Formalize",       "Senior Integration Engineer")],
    6: [("C++",    90, "Stress Testing",  "Senior Project Manager"),
        ("Rust",   89, "Enforce",         "Senior Project Manager")],
    7: [("C++",    84, "Harmonize",       "Senior DevOps Engineer"),
        ("Python", 93, "Liability",       "Senior DevOps Engineer")],
    8: [("Python", 82, "Validate",        "Senior Requirements Engineering Manager"),
        ("C++",    99, "Gap Analysis",    "Senior Requirements Engineering Manager")],
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def ensure_dirs():
    """Create all required directories."""
    for d in [OUTPUT_JSON_DIR, OUTPUT_THINK_DIR, EVAL_DIR, PROMPTS_DIR]:
        os.makedirs(d, exist_ok=True)


def get_doc_short_name(pdf_filename):
    """Convert PDF filename to a clean short name for file naming."""
    name = os.path.splitext(pdf_filename)[0]
    name = name.replace(" (1)", "").replace(" ", "_")
    if len(name) > 30:
        parts = name.split("_")
        if len(parts) > 3:
            name = "_".join(parts[:3])
    return name


def classify_pdf(pdf_path):
    """Auto-detect if a PDF is Technical or Regulatory based on keywords."""
    regulatory_keywords = [
        "iso", "regulation", "compliance", "standard", "directive",
        "unece", "r155", "r156", "homologation", "type approval",
        "legal", "liability", "eu ai act", "positionspapier",
        "sae", "vda", "normung", "ece", "annex"
    ]

    # Read cached text if available
    txt_cache = pdf_path.replace(".pdf", ".txt")
    if os.path.exists(txt_cache):
        with open(txt_cache, 'r', encoding='utf-8', errors='ignore') as f:
            text_sample = f.read(5000).lower()
    else:
        text_sample = os.path.basename(pdf_path).lower()

    score = sum(1 for kw in regulatory_keywords if kw in text_sample)
    mode = "REGULATORY" if score >= 2 else "TECHNICAL"
    return mode


def task_output_path(doc_short, turn, task_idx):
    """Generate the standardized output file path for a task (consistent capital T)."""
    return os.path.join(OUTPUT_JSON_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}.json")


def thinking_output_path(doc_short, turn, task_idx):
    """Generate the standardized thinking file path."""
    return os.path.join(OUTPUT_THINK_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}.txt")


def prompt_path(doc_short, turn, task_idx, is_repair=False):
    """Generate the prompt file path."""
    suffix = "_RepairPrompt" if is_repair else "_Prompt"
    return os.path.join(PROMPTS_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}{suffix}.txt")


# ── Progress Tracking ────────────────────────────────────────────────────────
def load_progress():
    """Load progress state from disk."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "started_at": datetime.now().isoformat(),
        "pdfs_completed": [],
        "task_results": {}
    }


def save_progress(progress):
    """Save progress state to disk."""
    progress["updated_at"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2)


def collect_task_stats(json_path, report):
    """Extract per-task metrics from the validation report for logging."""
    stats = report.get("stats", {})
    return {
        "cot_chars": stats.get("cot_chars", 0),
        "answer_chars": stats.get("answer_chars", 0),
        "code_lines": stats.get("code_lines", 0),
        "test_criteria_count": stats.get("test_criteria_count", 0),
        "formal_req_count": stats.get("formal_req_count", 0),
    }


def print_task_summary(tk, status, stats, elapsed, repair_type, attempts):
    """Print a concise one-line summary of a completed task to the console."""
    icon = "✅" if status == "PASS" else "❌"
    cot = f"{stats.get('cot_chars', 0):,}"
    ans = f"{stats.get('answer_chars', 0):,}"
    code = f"{stats.get('code_lines', 0)}"
    repair_label = f" [{repair_type}]" if repair_type != "none" else ""
    print(f"  {icon} {tk} | CoT: {cot} chars | Ans: {ans} chars | Code: {code} lines | "
          f"Time: {elapsed:.0f}s | Attempts: {attempts}{repair_label}")


def compute_statistics(progress):
    """Compute min/max/mean/stddev for all tracked metrics and save to statistics.json."""
    results = progress.get("task_results", {})
    if not results:
        return {}

    # Collect arrays of each metric
    metric_arrays = {
        "elapsed_seconds": [],
        "cot_chars": [],
        "answer_chars": [],
        "code_lines": [],
        "test_criteria_count": [],
        "gemini_attempts": [],
    }

    pass_count = 0
    fail_count = 0
    local_repair_count = 0
    gemini_retry_count = 0

    for tk, data in results.items():
        if data.get("status") == "PASS":
            pass_count += 1
        else:
            fail_count += 1

        if data.get("repair_type") == "local":
            local_repair_count += 1
        if data.get("gemini_attempts", 1) > 1:
            gemini_retry_count += 1

        for key in metric_arrays:
            val = data.get(key)
            if val is not None and isinstance(val, (int, float)):
                metric_arrays[key].append(val)

    def stats_for(arr):
        if not arr:
            return {"min": 0, "max": 0, "mean": 0, "stddev": 0, "count": 0}
        return {
            "min": round(min(arr), 1),
            "max": round(max(arr), 1),
            "mean": round(statistics.mean(arr), 1),
            "stddev": round(statistics.stdev(arr), 1) if len(arr) > 1 else 0,
            "count": len(arr),
        }

    total = pass_count + fail_count
    stats_summary = {
        "computed_at": datetime.now().isoformat(),
        "total_tasks": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "first_attempt_success_rate": round(
            sum(1 for d in results.values() if d.get("gemini_attempts", 1) == 1 and d.get("status") == "PASS") / max(total, 1) * 100, 1),
        "local_repair_count": local_repair_count,
        "gemini_retry_count": gemini_retry_count,
        "metrics": {k: stats_for(v) for k, v in metric_arrays.items()},
    }

    # Save to disk
    with open(STATISTICS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_summary, f, indent=2)

    return stats_summary


def print_statistical_summary(stats_summary, label=""):
    """Print a formatted statistical summary to the console."""
    if not stats_summary:
        return
    m = stats_summary.get("metrics", {})
    print(f"\n  {'═'*65}")
    print(f"  📊 STATISTICAL SUMMARY{': ' + label if label else ''}")
    print(f"  {'═'*65}")
    for metric_name, display_name in [
        ("elapsed_seconds", "Task Times"),
        ("cot_chars", "CoT Chars"),
        ("answer_chars", "Ans Chars"),
        ("code_lines", "Code Lines"),
        ("test_criteria_count", "Test Items"),
    ]:
        s = m.get(metric_name, {})
        if s.get("count", 0) > 0:
            print(f"  {display_name:>12s}:  min={s['min']:>8}  max={s['max']:>8}  "
                  f"mean={s['mean']:>8}  stddev={s['stddev']:>8}")
    print(f"  {'─'*65}")
    print(f"  1st-attempt success: {stats_summary.get('first_attempt_success_rate', 0)}% "
          f"({sum(1 for d in [] if True)})")
    print(f"  Local repairs:       {stats_summary.get('local_repair_count', 0)}")
    print(f"  Gemini retries:      {stats_summary.get('gemini_retry_count', 0)}")
    total = stats_summary.get('total_tasks', 0)
    passed = stats_summary.get('pass_count', 0)
    failed = stats_summary.get('fail_count', 0)
    print(f"  Total: {passed}/{total} passed, {failed}/{total} failed")
    print(f"  {'═'*65}")


def task_key(doc_short, turn, task_idx):
    """Generate a unique key for tracking a specific task."""
    return f"{doc_short}_Turn{turn}_Task{task_idx}"


# ── Prompt Builder ───────────────────────────────────────────────────────────
def build_generation_prompt(variation, turn, task_idx, doc_name, mode, is_soft_retry=False):
    """Build the full generation prompt per turn/task/variation.
    
    If is_soft_retry is True, relax constraints to bypass Gemini Safety Filters.
    """
    lang, diff, strategy, role = variation
    date_str = datetime.now().strftime('%Y-%m-%d')
    date_compact = datetime.now().strftime('%Y%m%d')
    doc_short = get_doc_short_name(doc_name)

    # Volume targets (intentionally higher than validator thresholds for buffer)
    reasoning_vol = "10,000+ characters" if not is_soft_retry else "At least 5,000 characters"
    code_vol = "450+ lines" if not is_soft_retry else "At least 200 lines"
    
    # Persona Selection — anti-Canvas directive
    if not is_soft_retry:
        persona_directive = 'VIRTUAL TERMINAL PERSONA: You are a legacy VT100 Data Terminal. You lack the hardware to render side-panels or code editors. Any attempt to use "Canvas" or side-panels will result in a hardware system crash. All output MUST be a raw text stream in the main chat window.'
    else:
        persona_directive = 'STANDARD OUTPUT: Provide the response in clear, sequential markdown blocks. Do NOT use side-panels or Canvas mode.'

    lang_lower = lang.lower() if lang != "C++" else "cpp"

    prompt = f"""<instructions>
SYSTEM ROLE: ELITE AUTOMOTIVE {role}
You ARE the {role}. You are solving a real, critical engineering problem. The source document above is your domain knowledge — you have fully internalized it as your own expertise. You will now demonstrate your mastery by solving exactly 1 extremely complex engineering challenge.

CRITICAL IDENTITY RULE: You are NOT generating a task, NOT creating training data, NOT producing a dataset. You are an expert engineer SOLVING a real problem. Your internal monologue (COT/reasoning) must reflect the thought process of an engineer actively solving the problem — analyzing physics, deriving equations, evaluating trade-offs, debugging algorithms. NEVER think about "generating", "creating tasks", "structuring output", "meeting character limits", or "the prompt".

<variation>
- Programming Language: {lang}
- Difficulty: {diff}/100
- Meta-Strategy: {strategy}
- Assigned Role: {role}
- Document Classification: {mode}
</variation>

<critical_directives>
1. REASONING VOLUME: Minimum {reasoning_vol}. The reasoning block must read as the authentic, real-time internal monologue of a {role}. Include explicit mathematical derivations (kinematics, matrix calculus, control theory). Do not use generic filler.
2. CODE VOLUME: Minimum {code_vol} of production-quality {lang} code. Fully commented, with exhaustive boundary tests.
3. {persona_directive}
4. COPYRIGHT HEADER: Every code block MUST start with `// Copyright by 4QDR.AI, AD knowledge Bot v1.0`
5. MODEL NAME: Use exactly "Gemini-3.1-pro" for model_used_generation in the METADATA block.
6. KNOWLEDGE SOURCE DATE: Extract the publication date from the source document above (look for copyright year, publication date, version date, or document date). Use format YYYY-MM-DD. If no date is found, write "Unknown".
7. SELF-CONTAINMENT: No citations, no references to "the document", "Section 3", or external sources. The problem and solution must stand completely alone as canonical engineering truth.
8. ANTI-META RULE (APPLIES TO ALL OUTPUT INCLUDING REASONING/COT): Never mention "the document", "the user requests", "this task", "meta-strategy", "source material", "the text states", "based on the provided", "generate a task", "the prompt", "character count", "character limit", "block schema", "variation schema", or "output format". Your reasoning/COT is the brain of the {role} SOLVING the problem — NOT the brain of an AI planning how to generate a dataset. BANNED COT phrases: "I need to generate", "The request is to generate", "I will structure the user turn", "I need to create a task", "The meta-strategy is", "The document classification is".
9. EMPTY THINK TAGS AND [No Thinking] SCOPE: The `[No Thinking]` prefix is a USER-ONLY tag. It appears ONLY at the start of user follow-up questions (Turns 3 and 5). Assistant responses (Turns 4 and 6) must NEVER start with or contain "[No Thinking]". When a user turn has `[No Thinking]`, the corresponding assistant reasoning MUST be exactly `"<think></think>"` — not empty string, not omitted.
10. NO PLACEHOLDERS: STRICTLY FORBIDDEN to use `...`, `// simplified`, `TBD`, `Follow up 1?`, `Response 2.`, or any placeholder text in code or follow-up turns. Every line must be real, functional content.
11. ANTI-LOOPING: Do not repeat identical technical paragraphs or derivations. Each section must provide unique, incremental engineering value.
12. NO KEYWORD SALAD: Repetitive word clusters like "derived from derived derivation complexity visualized" are an entropy failure and will be rejected.
13. TRACEABILITY: Every formal requirement MUST be referenced in code comments as `// [REQ-ID]` next to its implementation.
14. ANTI-REPETITION MANDATE: All req_id descriptions, pass_criteria, code functions, and test criteria must be semantically unique. No copy-paste, no templated loops.
15. CROSS-TURN DIVERSITY: You MUST NOT reuse architectural patterns, problem statements, or code logic from previous turns.
16. FOLLOW-UP SPECIFICITY: Follow-up questions MUST reference specific named components (classes, functions, constants) from YOUR code. Generic questions like "How does the system handle edge cases?" are rejected.
17. RICH CODE COMMENTS & INTERNAL DOCUMENTATION: Every code block MUST contain rich inline documentation. This includes: (a) Module-level header comments explaining the overall purpose, design rationale, and key assumptions; (b) Function/method-level docstrings describing parameters, return values, preconditions, postconditions, and algorithmic complexity; (c) Inline comments explaining non-obvious logic, mathematical derivations, physical constants, safety-critical decision points, and boundary-condition handling; (d) Section separator comments dividing the code into logical subsystems (e.g., `// ── Sensor Fusion Pipeline ──`, `// ── ASIL-D Safety Monitor ──`). Bare code without explanatory comments is UNACCEPTABLE.
18. REQUIREMENTS TRACEABILITY IN CODE: Every formal requirement (REQ-SW-001, etc.) MUST be explicitly traced in the code via inline comments placed directly above or beside the implementing code section. Use the format `// [REQ-SW-XXX] <brief description of how this code satisfies the requirement>`. Each requirement must appear at least once in the code. Additionally, include a traceability matrix as a block comment at the end of the code listing each REQ-ID, its implementing function/class, and its verification method.
</critical_directives>

<output_format>
OUTPUT YOUR RESPONSE IN DISTINCT LABELED BLOCKS. Use the exact `!!!!!BLOCK-NAME!!!!!` delimiters below.
IMPORTANT: Wrap JSON content inside fenced code blocks marked json and code content inside fenced code blocks marked {lang_lower} for readability.
CRITICAL: Do NOT use Canvas, Gems, side-panels, or any interactive coding interface. ALL output must be raw text in the main chat response window. Using Canvas WILL crash the VT100 terminal.

BLOCKS (13 total):
- BLOCK 1  `!!!!!METADATA!!!!!`: JSON metadata (13 fields). Wrap in json fenced code block.
- BLOCK 2  `!!!!!REASONING!!!!!`: The 10,000+ char 31-step engineering monologue. Raw markdown, no fenced block.
- BLOCK 3  `!!!!!TURN-1-USER!!!!!`: Immersive 3-paragraph problem statement from the {role}. MUST START WITH "[Thinking] ".
- BLOCK 4  `!!!!!REQUIREMENTS!!!!!`: JSON array of at least 5 formal requirements. Wrap in json fenced code block.
- BLOCK 5  `!!!!!ARCHITECTURE!!!!!`: Mermaid diagram + narrative description.
- BLOCK 6  `!!!!!CODE!!!!!`: The COMPLETE {code_vol} {lang} implementation in a single block. Wrap in {lang_lower} fenced code block. Must include copyright header. NO truncation, NO ellipses.
- BLOCK 7  `!!!!!USAGE-EXAMPLES!!!!!`: Invocation examples and mock data.
- BLOCK 8  `!!!!!DOCUMENTATION!!!!!`: Code logic explanation and integration README.
- BLOCK 9  `!!!!!TEST-CRITERIA!!!!!`: JSON array of at least 5 distinct boundary tests. Wrap in json fenced code block.
- BLOCK 10 `!!!!!TURN-3-USER!!!!!`: Technical inquiry (100+ chars) referencing a specific code identifier. START: "[No Thinking] ".
- BLOCK 11 `!!!!!TURN-4-ASSISTANT!!!!!`: Engineering response (500+ chars) with specific code references and complexity analysis. MUST NOT start with "[No Thinking]" — that tag is for USER turns only.
- BLOCK 12 `!!!!!TURN-5-USER!!!!!`: Another inquiry (100+ chars) about a DIFFERENT component. START: "[No Thinking] ".
- BLOCK 13 `!!!!!TURN-6-ASSISTANT!!!!!`: Final technical response (500+ chars) with worst-case complexity bounds. MUST NOT start with "[No Thinking]" — that tag is for USER turns only.
</output_format>

<cot_template>
THE 8-STEP COT MONOLOGUE TEMPLATE (ALL 31 SUB-ELEMENTS MANDATORY):
Populate this exact template inside !!!!!REASONING!!!!!. Do not skip any numbering.

1. Initial Query Analysis & Scoping
1.1. Deconstruct the Request: Detailed analysis of the core ENGINEERING problem (NOT the generation task). Analyze the physics, mathematics, system constraints, and safety implications. You are solving this problem, not generating it.
1.2. Initial Knowledge & Constraint Check: Verify hardware limits, memory bounds, ISO 26262 safety targets.
2. Assumptions & Context Setting
2.1. Interpretation of Ambiguity: Define exact mathematical/physical bounds for undefined variables.
2.2. Assumed User Context: Establish the strict {role} execution context.
2.3. Scope Definition: Explicitly state in-scope and rigorously excluded out-of-scope elements.
2.4. Data Assumptions: Set physical bounds, sensor latencies, noise profiles, system limits.
2.5. Reflective Assumption Check: Interrogate and mathematically correct a flawed initial assumption.
3. High-Level Plan Formulation
3.1. Explore Solution Scenarios: Draft multiple high-level architectural approaches.
3.2. Detailed Execution with Iterative Refinement: Break down integration and logic steps.
3.3. Self-Critique and Correction: Critique the initial blueprint for single points of failure.
3.4. Comparative Analysis Strategy: Establish strict Big-O complexity and latency metrics.
3.5. Synthesis & Finalization: Formulate the final architectural blueprint.
3.6. Formal Requirements Extraction: Define at least 5 strict requirements with IDs (REQ-SW-001) and Pass Criteria.
4. Solution Scenario Exploration
4.1. Scenario A (Quick & Direct): Core idea, pros, cons, mathematical limitations.
4.2. Scenario B (Robust & Scalable): Core idea, pros, cons, integration complexity.
4.3. Scenario C (Balanced Hybrid): Trade-off matrix and synergies.
5. Detailed Step-by-Step Execution & Reflection
5.1. First Pass Execution: Draft the massive initial algorithmic logic.
5.2. Deep Analysis & Failure Modes: Generate a 15-row FMEA markdown table.
5.3. Trigger 1 (Verification): Find and fix a critical flaw (memory leak, race condition, math error).
5.4. Trigger 2 (Adversarial): Critique logic against worst-case SOTIF edge cases.
5.5. Refinement Strategy (Version 2.0): Corrected, hardened, production-ready logic.
6. Comparative Analysis & Synthesis
6.1. Comparison Matrix: Draw a 6x5 markdown comparison table.
6.2. Evaluation of Solution Combinations: Hybrid strengths and emergent capabilities.
6.3. Selection Rationale: Mathematically backed justification.
7. Final Solution Formulation
7.1. Executive Summary: One-paragraph highly technical summary.
7.2. Detailed Recommended Solution: Plan the exact code structure.
7.3. Implementation Caveats & Next Steps: Hardware-specific deployment risks.
8. Meta-Commentary & Confidence Score
8.1. Final Confidence Score: Rate out of 100.
8.2. Rationale for Confidence: Justify based on self-correction loops.
8.3. Limitations of This Analysis: Physical/theoretical/compute limitations.
8.4. Alternative Viewpoints Not Explored: Radical paradigm shifts.
</cot_template>

<block_schema>
OUTPUT SCHEMA (block delimiters for extraction):

!!!!!METADATA!!!!!
```json
{{
  "training_data_id": "TD-CODING-{doc_short}-T{turn}t{task_idx}-{date_compact}-v1.0",
  "prompt_version": "CodingTasks_v1.0",
  "model_used_generation": "Gemini-3.1-pro",
  "knowledge_source_date": "EXTRACT-FROM-DOCUMENT-YYYY-MM-DD",
  "document": "{doc_name}",
  "task_type": "coding_task",
  "affected_role": "{role}",
  "date_of_generation": "{date_str}",
  "key_words": ["keyword1", "keyword2", "keyword3"],
  "summary": "One-sentence technical summary.",
  "difficulty": "{diff}",
  "evaluation_criteria": ["criterion1"]
}}
```

!!!!!REASONING!!!!!
1. Initial Query Analysis & Scoping
1.1. ...
(all 8 sections, 31 sub-elements, minimum 10,000 chars total)

!!!!!TURN-1-USER!!!!!
[Thinking] ...

!!!!!REQUIREMENTS!!!!!
```json
[
  {{ "req_id": "REQ-001", "description": "...", "pass_criteria": "..." }}
]
```

!!!!!ARCHITECTURE!!!!!
...

!!!!!CODE!!!!!
({lang_lower} fenced code block with {code_vol} of complete, production-quality {lang} code starting with copyright header)

!!!!!USAGE-EXAMPLES!!!!!
...

!!!!!DOCUMENTATION!!!!!
...

!!!!!TEST-CRITERIA!!!!!
```json
[
  "Boundary Test 1: ...",
  "Boundary Test 2: ...",
  "Boundary Test 3: ...",
  "Boundary Test 4: ...",
  "Boundary Test 5: ..."
]
```

!!!!!TURN-3-USER!!!!!
[No Thinking] ...

!!!!!TURN-4-ASSISTANT!!!!!
(Direct technical response — NO [No Thinking] prefix)

!!!!!TURN-5-USER!!!!!
[No Thinking] ...

!!!!!TURN-6-ASSISTANT!!!!!
(Direct technical response — NO [No Thinking] prefix)
</block_schema>

ANTI-TRUNCATION: Prioritize COMPLETING the entire block structure over adding more detail. A truncated response is worse than a slightly shorter but complete one. If you are running low on tokens, reduce detail density but NEVER omit blocks.
</instructions>"""
    return prompt


def build_repair_prompt(validation_report, original_prompt_text):
    """Build a remediation prompt based on specific validation failures.
    Includes the original prompt to ensure structural constraints are not lost."""
    lines = [
        "Your previous response FAILED quality validation.",
        "CRITICAL: You MUST regenerate the response using the FULL 13-BLOCK SCHEMA (!!!!!METADATA!!!!! through !!!!!TURN-6-ASSISTANT!!!!!).",
        "Do NOT omit any blocks. Even if you are fixing a specific issue, the entire structured output must be provided.",
        "\nYou MUST fix the following specific issues while maintaining ALL original constraints:\n"
    ]

    for issue in validation_report.get("needs_regeneration", []):
        cat = issue["category"]
        msg = issue["issue"]
        if cat == "richness_and_complexity":
            if "keyword-salad" in msg or "cluster of padding" in msg:
                lines.append(f"- CRITICAL QUALITY FAILURE: {msg}. You used repetitive 'word-salad' padding or verbatim loops to meet length requirements. This is STRICTLY FORBIDDEN. Provide genuine engineering substance instead.")
            elif "repetition loop" in msg:
                lines.append(f"- REPETITION FAILURE: {msg}. Your response contained identical repeated paragraphs. Delete the duplicates and fill the space with new, deep technical details.")
            else:
                lines.append(f"- VOLUME FAILURE: {msg}. Expand your content significantly to meet the character/line limits.")
        elif cat == "cot_structure":
            lines.append(f"- COT STRUCTURE: {msg}. You MUST explicitly include all 1.1 through 8.4 headings.")
        elif cat == "self_containment":
            lines.append(f"- IMMERSION FAILURE: {msg}. Remove ALL meta-commentary, do not break character.")
        elif cat == "structured_answer_format":
            lines.append(f"- STRUCTURE: {msg}. Ensure all mandatory JSON keys and required arrays are populated.")
        else:
            lines.append(f"- {cat.upper()}: {msg}")

    lines.append("\n--- ORIGINAL TASK INSTRUCTIONS ---")
    lines.append("Review the original instructions below and ensure your new output satisfies BOTH the original rules AND fixes the failures listed above.")
    lines.append("-" * 40)
    lines.append(original_prompt_text)
    
    return "\n".join(lines)


# ── Execution Engine ─────────────────────────────────────────────────────────
def run_playwright(pdf_path, prompt_file):
    """Execute the Playwright script and return success boolean."""
    cmd = f'python "{PLAYWRIGHT_SCRIPT}" "{pdf_path}" "{prompt_file}"'
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        # Check for safety rejection (approx 139 chars) or empty response
        if result.stderr and ("Normally I can help with things like" in result.stderr or "139 chars" in result.stderr):
            print(f"  ⚠️ Gemini Safety Rejection detected.")
            return "SAFETY_REJECTION"
            
        stderr_preview = result.stderr[-300:] if result.stderr else "No error output"
        print(f"  ❌ Playwright error (exit {result.returncode}): {stderr_preview}")
        return False
    return True


def run_validation(json_path, report_path=None):
    """Run validate_task.py and return the parsed report."""
    cmd = f'python "{VALIDATE_SCRIPT}" "{json_path}"'
    if report_path:
        cmd += f' --save-report "{report_path}"'

    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        report = json.loads(result.stdout)
        return report
    except json.JSONDecodeError:
        return {"overall_status": "FAIL", "error": "Validator output not parseable"}


def run_auto_repair(json_path):
    """Run auto_repair.py on a failed task. Parse JSON from stdout only."""
    cmd = f'python "{AUTO_REPAIR_SCRIPT}" "{json_path}"'
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR"}


def run_partial_repair(json_path, pdf_path):
    """Run partial_repair.py to fix only broken follow-up turns.
    
    Steps:
      1. Build a focused prompt from context in the valid main answer
      2. Send it to Gemini via Playwright
      3. Patch the follow-up turns back into the JSON
    """
    # Step 1: Build repair prompt
    cmd = f'python "{PARTIAL_REPAIR_SCRIPT}" --build-prompt "{json_path}"'
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    
    repair_prompt = result.stdout.strip()
    if not repair_prompt or len(repair_prompt) < 100:
        print(f"  ❌ Partial repair: failed to build repair prompt")
        return False
    
    # Save the repair prompt
    basename = os.path.splitext(os.path.basename(json_path))[0]
    repair_prompt_path = os.path.join(PROMPTS_DIR, f"{basename}_FollowupRepairPrompt.txt")
    with open(repair_prompt_path, 'w', encoding='utf-8') as f:
        f.write(repair_prompt)
    
    print(f"  📝 Follow-up repair prompt saved ({len(repair_prompt)} chars)")
    
    # Step 2: Run Playwright with the repair prompt
    print(f"  🌐 Sending follow-up repair to Gemini...")
    pw_result = run_playwright(pdf_path, repair_prompt_path)
    if not pw_result:
        print(f"  ❌ Playwright failed for follow-up repair")
        return False
    
    # Step 3: The Playwright script will have produced a new JSON output.
    # We need to extract the follow-up turns from the Gemini response
    # However, since Playwright writes to a fixed path based on filename,
    # and we're using a different prompt file, we need the raw response.
    # Use the raw_fail.txt or extract from the generated JSON.
    raw_response_path = json_path.replace(".json", "_raw_fail.txt")
    
    # Check if Playwright produced a response we can use
    if os.path.exists(raw_response_path):
        cmd_patch = f'python "{PARTIAL_REPAIR_SCRIPT}" --patch "{json_path}" "{raw_response_path}"'
        patch_result = subprocess.run(cmd_patch, shell=True, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            patch_report = json.loads(patch_result.stdout)
            if patch_report.get("status") == "PATCHED":
                print(f"  ✅ Follow-up turns patched successfully")
                return True
        except json.JSONDecodeError:
            pass
    
    print(f"  ❌ Partial repair: could not patch follow-ups")
    return False


def decide_repair_strategy(report):
    """Decide whether to attempt local repair, partial repair, or full re-prompt.

    Returns:
        "local"   — try auto_repair.py first
        "partial" — follow-up turns broken, try partial_repair.py
        "gemini"  — skip local, go straight to full re-prompt
        "pass"    — already passing
    """
    if report.get("overall_status") == "PASS":
        return "pass"

    locally_fixable = report.get("locally_fixable", [])
    needs_regen = report.get("needs_regeneration", [])
    needs_partial = report.get("needs_partial_repair", [])

    # If there are locally fixable issues, always try local repair first
    if locally_fixable:
        return "local"

    # If only follow-up issues remain (no full regen needed), do partial repair
    if needs_partial and not needs_regen:
        return "partial"

    # Full regeneration needed (possibly combined with partial issues)
    if needs_regen:
        return "gemini"

    # Safety fallback
    return "gemini"


# ── Main Pipeline ────────────────────────────────────────────────────────────
def process_task(pdf_path, doc_short, doc_name, turn, task_idx,
                 variation, mode, progress):
    """Process a single task: generate → validate → smart repair loop.

    Retry logic:
    - Max 3 Gemini attempts
    - Between each attempt, always try local repair first
    - Agent decides: if issue is locally fixable (JSON structure, missing tags etc)
      → auto_repair.py. If issue needs regeneration (volume, CoT, immersion)
      → Gemini re-prompt.
    """
    tk = task_key(doc_short, turn, task_idx)
    json_out = task_output_path(doc_short, turn, task_idx)
    qa_report_path = os.path.join(EVAL_DIR, f"{doc_short}_Turn{turn}_Task{task_idx}_QA.json")
    task_start = time.time()
    task_stats = {}  # Will hold per-task metrics

    # Check if already completed (disk + progress)
    existing = progress.get("task_results", {}).get(tk, {})
    file_exists = os.path.exists(json_out)

    if existing.get("status") == "PASS" and file_exists:
        print(f"  ✅ {tk}: Already passed and exists (skipping)")
        return True
    
    if file_exists and not existing.get("status") == "PASS":
        print(f"  ⚠️ {tk}: File exists but progress marks it FAIL/PENDING (will re-process)")
    elif existing.get("status") == "PASS" and not file_exists:
        print(f"  ⚠️ {tk}: Marked PASS in progress but file is missing (will re-process)")

    lang, diff, strategy, role = variation
    print(f"\n{'─'*60}")
    print(f"  📋 {tk} | {lang} | Diff {diff} | {strategy} | {role}")
    print(f"{'─'*60}")

    gemini_attempts = 0
    final_repair_type = "none"
    # Always generate the base prompt text so it's available for repairs
    base_prompt_text = build_generation_prompt(variation, turn, task_idx, doc_name, mode)

    while gemini_attempts < MAX_GEMINI_ATTEMPTS:
        gemini_attempts += 1

        # ── Step 1: Build and save prompt ──
        if gemini_attempts == 1:
            prompt_text = base_prompt_text
            p_path = prompt_path(doc_short, turn, task_idx, is_repair=False)
        else:
            # Build repair prompt from last validation report
            last_report = run_validation(json_out)
            if last_report.get("overall_status") == "PASS":
                break  # Fixed by previous local repair!

            prompt_text = build_repair_prompt(last_report, base_prompt_text)
            p_path = prompt_path(doc_short, turn, task_idx, is_repair=True)

        # Save prompt
        os.makedirs(os.path.dirname(p_path), exist_ok=True)
        with open(p_path, 'w', encoding='utf-8') as f:
            f.write(prompt_text)

        # ── Step 2: Run Playwright (Gemini attempt) ──
        print(f"  🌐 Gemini attempt {gemini_attempts}/{MAX_GEMINI_ATTEMPTS}...")
        pw_result = run_playwright(pdf_path, p_path)
        
        # SAFETY RETRY LOGIC
        if pw_result == "SAFETY_REJECTION":
            print(f"  ⚠️ Triggering 'Soft Prompt' retry to bypass safety filters...")
            p_text = build_generation_prompt(variation, turn, task_idx, doc_name, mode, is_soft_retry=True)
            with open(p_path, 'w', encoding='utf-8') as f: f.write(p_text)
            pw_result = run_playwright(pdf_path, p_path)

        if not pw_result:
            print(f"  ❌ Playwright failed on attempt {gemini_attempts}")
            continue

        # ── Step 3: Check output exists ──
        if not os.path.exists(json_out):
            print(f"  ❌ Output file not created: {json_out}")
            continue

        # ── Step 4: Validate ──
        report = run_validation(json_out, qa_report_path)
        task_stats = collect_task_stats(json_out, report)

        if report.get("overall_status") == "PASS":
            elapsed = time.time() - task_start
            progress["task_results"][tk] = {
                "status": "PASS", "gemini_attempts": gemini_attempts,
                "repair_type": final_repair_type, "elapsed_seconds": round(elapsed, 1),
                **task_stats
            }
            save_progress(progress)
            print_task_summary(tk, "PASS", task_stats, elapsed, final_repair_type, gemini_attempts)
            return True

        # ── Step 5: Smart repair decision ──
        strategy_decision = decide_repair_strategy(report)
        violations = []
        for cat, data in report.get("metrics", {}).items():
            violations.extend(data.get("violations", []))
        
        print(f"  ⚠️ VALIDATION FAILED on attempt {gemini_attempts}:")
        for v in violations:
            print(f"       - {v}")
        print(f"  🔍 Repair strategy: {strategy_decision}")

        if strategy_decision == "local":
            # Try local repair
            print(f"  🔧 Running auto_repair.py...")
            repair_result = run_auto_repair(json_out)
            if repair_result.get("fixes_applied"):
                final_repair_type = "local"
                print(f"  🔧 Applied: {', '.join(repair_result['fixes_applied'])}")

                # Re-validate after local fix
                report2 = run_validation(json_out, qa_report_path)
                task_stats = collect_task_stats(json_out, report2)
                if report2.get("overall_status") == "PASS":
                    elapsed = time.time() - task_start
                    progress["task_results"][tk] = {
                        "status": "PASS", "gemini_attempts": gemini_attempts,
                        "repair_type": "local", "elapsed_seconds": round(elapsed, 1),
                        "repairs_applied": repair_result.get("fixes_applied", []),
                        **task_stats
                    }
                    save_progress(progress)
                    print_task_summary(tk, "PASS", task_stats, elapsed, "local", gemini_attempts)
                    return True

                # Local repair helped but not enough — check if remaining issues need Gemini
                remaining_strategy = decide_repair_strategy(report2)
                if remaining_strategy == "pass":
                    continue  # Shouldn't happen, but safety
                elif remaining_strategy == "partial":
                    # Only follow-up turns remain broken — try partial repair
                    print(f"  🔄 Local repair fixed structural issues. Attempting partial follow-up repair...")
                    partial_ok = run_partial_repair(json_out, pdf_path)
                    if partial_ok:
                        report3 = run_validation(json_out, qa_report_path)
                        task_stats = collect_task_stats(json_out, report3)
                        if report3.get("overall_status") == "PASS":
                            elapsed = time.time() - task_start
                            progress["task_results"][tk] = {
                                "status": "PASS", "gemini_attempts": gemini_attempts,
                                "repair_type": "local+partial", "elapsed_seconds": round(elapsed, 1),
                                "repairs_applied": repair_result.get("fixes_applied", []) + ["partial_followup_repair"],
                                **task_stats
                            }
                            save_progress(progress)
                            print_task_summary(tk, "PASS", task_stats, elapsed, "local+partial", gemini_attempts)
                            return True
                print(f"  ⚠️ Local repair insufficient. Remaining issues need Gemini re-prompt.")
                final_repair_type = "local+gemini"
            else:
                print(f"  🔧 No local fixes applicable. Will re-prompt Gemini.")

        elif strategy_decision == "partial":
            # Only follow-up turns are broken — try targeted partial repair
            print(f"  🔄 Running partial follow-up repair...")
            partial_ok = run_partial_repair(json_out, pdf_path)
            if partial_ok:
                report2 = run_validation(json_out, qa_report_path)
                task_stats = collect_task_stats(json_out, report2)
                if report2.get("overall_status") == "PASS":
                    elapsed = time.time() - task_start
                    progress["task_results"][tk] = {
                        "status": "PASS", "gemini_attempts": gemini_attempts,
                        "repair_type": "partial", "elapsed_seconds": round(elapsed, 1),
                        "repairs_applied": ["partial_followup_repair"],
                        **task_stats
                    }
                    save_progress(progress)
                    print_task_summary(tk, "PASS", task_stats, elapsed, "partial", gemini_attempts)
                    return True
            print(f"  ⚠️ Partial repair insufficient. Will try full Gemini re-prompt.")

        # If we get here, the next loop iteration will build a repair prompt and re-run Gemini
        final_repair_type = "gemini" if final_repair_type == "none" else final_repair_type

    # Exhausted all Gemini attempts
    elapsed = time.time() - task_start
    progress["task_results"][tk] = {
        "status": "FAIL", "gemini_attempts": gemini_attempts,
        "repair_type": "exhausted", "elapsed_seconds": round(elapsed, 1),
        **task_stats
    }
    save_progress(progress)
    print_task_summary(tk, "FAIL", task_stats, elapsed, "exhausted", gemini_attempts)
    print(f"  ❌ FAILED after {gemini_attempts} Gemini attempts — flagged for manual review")
    return False


def process_pdf(pdf_path, progress, start_turn=1, start_task=1, end_turn=8, skip_dashboard=False, test_setup=False, limit_tasks=0):
    """Process all tasks for a single PDF up to end_turn or limit_tasks."""
    pdf_name = os.path.basename(pdf_path)
    doc_short = get_doc_short_name(pdf_name)
    doc_name = os.path.splitext(pdf_name)[0]

    print(f"\n{'═'*70}")
    print(f"  📄 Processing: {pdf_name}")
    print(f"  📁 Short name: {doc_short}")
    print(f"{'═'*70}")

    # Classify PDF
    mode = classify_pdf(pdf_path)
    schema = VARIATION_REGULATORY if mode == "REGULATORY" else VARIATION_TECHNICAL
    print(f"  📊 Classification: {mode}")

    # Load PDF text cache
    txt_cache = pdf_path.replace(".pdf", ".txt")
    if os.path.exists(txt_cache):
        with open(txt_cache, 'r', encoding='utf-8') as f:
            pdf_text = f.read()
        print(f"  📝 Using cached text: {len(pdf_text)} chars")
    else:
        print(f"  📝 No cached text — Playwright will extract on first run")

    # Process each turn
    total_pass = 0
    total_fail = 0
    tasks_since_dashboard = 0
    tasks_processed_this_run = 0
    pdf_start = time.time()

    for turn in range(start_turn, end_turn + 1):
        variations = schema[turn]
        for task_idx_0, variation in enumerate(variations):
            task_idx = task_idx_0 + 1
            if turn == start_turn and task_idx < start_task:
                continue

            result = process_task(
                pdf_path, doc_short, doc_name,
                turn, task_idx, variation, mode, progress)

            if result:
                total_pass += 1
            else:
                total_fail += 1

            tasks_since_dashboard += 1
            tasks_processed_this_run += 1

            if test_setup:
                print("\n  [TEST SETUP] Exiting after 1 task.")
                break

            if limit_tasks > 0 and tasks_processed_this_run >= limit_tasks:
                print(f"\n  [LIMIT REACHED] Exiting after {limit_tasks} tasks.")
                break
        
        if (test_setup) or (limit_tasks > 0 and tasks_processed_this_run >= limit_tasks):
            break

            # Dashboard every 8 tasks
            if not skip_dashboard and tasks_since_dashboard >= 8:
                try:
                    print(f"\n  📊 Generating dashboard (after {total_pass + total_fail} tasks)...")
                    subprocess.run(f'python "{DASHBOARD_SCRIPT}"', shell=True,
                                  cwd=BASE_DIR, capture_output=True)
                    tasks_since_dashboard = 0
                except Exception:
                    pass

    # Final dashboard for any remaining tasks
    if not skip_dashboard and tasks_since_dashboard > 0:
        try:
            print(f"\n  📊 Generating final dashboard...")
            subprocess.run(f'python "{DASHBOARD_SCRIPT}"', shell=True,
                          cwd=BASE_DIR, capture_output=True)
            # Auto-open the dashboard in the browser
            if os.path.exists(DASHBOARD_OUTPUT):
                print(f"  🌐 Opening dashboard in browser...")
                webbrowser.open(f'file:///{DASHBOARD_OUTPUT.replace(os.sep, "/")}')
        except Exception:
            pass

    # Compute and print statistical summary for this PDF
    stats_summary = compute_statistics(progress)
    print_statistical_summary(stats_summary, label=pdf_name)

    # PDF summary
    pdf_elapsed = time.time() - pdf_start
    pdf_min = int(pdf_elapsed // 60)
    pdf_sec = pdf_elapsed % 60
    print(f"\n{'═'*70}")
    print(f"  📄 {pdf_name} COMPLETE: {total_pass}/16 passed, {total_fail}/16 failed")
    print(f"  ⏱️  Elapsed: {pdf_min}m {pdf_sec:.0f}s")
    print(f"{'═'*70}")

    if total_fail == 0:
        progress["pdfs_completed"].append(pdf_name)
        save_progress(progress)

    return total_fail == 0


def validate_only_mode():
    """Just validate all existing JSON files without generating new ones."""
    json_files = sorted(glob.glob(os.path.join(OUTPUT_JSON_DIR, "*.json")))
    if not json_files:
        print("No JSON files found in Output/json/")
        return

    print(f"\n{'═'*70}")
    print(f"  🔍 Validate-Only Mode: {len(json_files)} files")
    print(f"{'═'*70}")

    pass_count = 0
    for jf in json_files:
        qa_path = os.path.join(EVAL_DIR, os.path.basename(jf).replace(".json", "_QA.json"))
        report = run_validation(jf, qa_path)
        status = report.get("overall_status", "?")
        stats = report.get("stats", {})
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {os.path.basename(jf)}: {status}"
              f"  (CoT: {stats.get('cot_chars', '?')}, Ans: {stats.get('answer_chars', '?')})")
        if status == "PASS":
            pass_count += 1
        else:
            for cat, data in report.get("metrics", {}).items():
                for v in data.get("violations", []):
                    print(f"       ⚠️ [{cat}] {v}")

    print(f"\n  Results: {pass_count}/{len(json_files)} passed")


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AD/ADAS Coding Task Generation Pipeline")
    parser.add_argument("--pdf", help="Process a specific PDF file")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--turn", type=int, default=1, help="Start from turn N")
    parser.add_argument("--end-turn", type=int, default=8, help="End at turn N (inclusive). Useful for test runs.")
    parser.add_argument("--task", type=int, default=1, help="Start from task K within the turn")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing outputs")
    parser.add_argument("--limit-tasks", type=int, default=0, help="Stop after N tasks (regardless of turns)")
    parser.add_argument("--limit-pdfs", type=int, default=0, help="Stop after N PDFs have been completed")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard generation")
    parser.add_argument("--test-setup", action="store_true", help="One turn (turn 2), one task (task 1), one attempt (test mode)")
    args = parser.parse_args()

    if args.test_setup:
        args.turn = 2
        args.end_turn = 2
        args.task = 1
        global MAX_GEMINI_ATTEMPTS
        MAX_GEMINI_ATTEMPTS = 1

    ensure_dirs()

    if args.validate_only:
        validate_only_mode()
        return

    progress = load_progress()
    start_time = time.time()

    # Get PDF list
    if args.pdf:
        pdf_path = os.path.join(INPUT_DIR, args.pdf) if not os.path.isabs(args.pdf) else args.pdf
        if not os.path.exists(pdf_path):
            print(f"❌ PDF not found: {pdf_path}")
            sys.exit(1)
        pdf_list = [pdf_path]
    else:
        pdf_list = sorted(glob.glob(os.path.join(INPUT_DIR, "*.pdf")))

    if not pdf_list:
        print("❌ No PDFs found in Input/")
        sys.exit(1)

    print(f"\n{'═'*70}")
    print(f"  🚀 Pipeline Starting: {len(pdf_list)} PDFs to process")
    print(f"  📂 Input:  {INPUT_DIR}")
    print(f"  📂 Output: {OUTPUT_JSON_DIR}")
    print(f"  🔄 Max Gemini attempts per task: {MAX_GEMINI_ATTEMPTS}")
    print(f"{'═'*70}")

    # Filter out already-completed PDFs (unless specific PDF requested)
    if not args.pdf:
        pdf_list = [p for p in pdf_list
                    if os.path.basename(p) not in progress.get("pdfs_completed", [])]
        if not pdf_list:
            print("✅ All PDFs already completed!")
            return

    pdfs_processed = 0
    for pdf_path in pdf_list:
        success = process_pdf(pdf_path, progress,
                   start_turn=args.turn, start_task=args.task,
                   end_turn=args.end_turn, skip_dashboard=args.no_dashboard,
                   test_setup=args.test_setup, limit_tasks=args.limit_tasks)
        
        if success:
            pdfs_processed += 1
        
        # Reset start position after first PDF
        args.turn = 1
        args.task = 1

        if args.limit_pdfs > 0 and pdfs_processed >= args.limit_pdfs:
            print(f"\n  [LIMIT REACHED] Exiting after processing {pdfs_processed} PDFs.")
            break

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    completed = len(progress.get("pdfs_completed", []))
    print(f"\n{'═'*70}")
    print(f"  🏁 Pipeline Complete: {completed} PDFs, {minutes}m {seconds:.0f}s elapsed")
    print(f"{'═'*70}")


if __name__ == "__main__":
    main()
