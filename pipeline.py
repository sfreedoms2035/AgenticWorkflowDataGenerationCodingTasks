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

PLAYWRIGHT_SCRIPT = os.path.join(BASE_DIR, "run_gemini_playwright_v2.py")
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, "validate_task.py")
AUTO_REPAIR_SCRIPT = os.path.join(SCRIPTS_DIR, "auto_repair.py")
DASHBOARD_SCRIPT = os.path.join(SCRIPTS_DIR, "generate_dashboard.py")

MAX_GEMINI_ATTEMPTS = 3  # Max Gemini re-prompts per task


# ── Variation Schema ─────────────────────────────────────────────────────────
# Each turn produces 2 tasks. Schema: (language, difficulty, meta_strategy)
VARIATION_TECHNICAL = {
    1: [("C++",    95, "Reverse Engineering"),  ("Rust",   90, "Practical Implementation")],
    2: [("Python", 88, "Improve Existing"),     ("C++",    98, "Benchmark & Optimize")],
    3: [("Rust",   94, "Critique & Harden"),    ("Python", 85, "Theory to Code")],
    4: [("C++",    96, "Reverse Engineering"),   ("C++",    94, "Benchmark & Optimize")],
    5: [("Python", 86, "Practical Implementation"),("Rust", 91, "Threat Modeling")],
    6: [("C++",    90, "Stress Testing"),        ("Rust",   89, "Improve Existing")],
    7: [("C++",    84, "Practical Implementation"),("Python",93, "Theory to Code")],
    8: [("Python", 82, "Reverse Engineering"),   ("C++",    99, "Critique & Harden")],
}

VARIATION_REGULATORY = {
    1: [("C++",    95, "Formalize"),     ("Python", 90, "Validate")],
    2: [("Rust",   88, "Liability"),     ("C++",    98, "Traceability")],
    3: [("Python", 94, "Loophole"),      ("Python", 85, "Ambiguity")],
    4: [("Rust",   96, "Formalize"),     ("C++",    94, "Validate")],
    5: [("Python", 86, "Audit"),         ("Rust",   91, "Formalize")],
    6: [("C++",    90, "Stress Testing"),("Rust",   89, "Enforce")],
    7: [("C++",    84, "Harmonize"),     ("Python", 93, "Liability")],
    8: [("Python", 82, "Validate"),      ("C++",    99, "Gap Analysis")],
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


def task_key(doc_short, turn, task_idx):
    """Generate a unique key for tracking a specific task."""
    return f"{doc_short}_Turn{turn}_Task{task_idx}"


# ── Prompt Builder ───────────────────────────────────────────────────────────
def build_generation_prompt(variation, turn, task_idx, doc_name, mode):
    """Build the full generation prompt per turn/task/variation.

    This mirrors the quality of hand-crafted prompts by including:
    - Complete schema with pre-filled metadata
    - Full 8-step CoT template
    - Explicit 6-turn mandate
    - Anti-truncation directive
    """
    lang, diff, strategy = variation
    date_str = datetime.now().strftime('%Y-%m-%d')
    date_compact = datetime.now().strftime('%Y%m%d')
    doc_short = get_doc_short_name(doc_name)

    # Determine role based on mode and strategy
    if mode == "REGULATORY":
        role = "Senior Automotive Compliance & Cybersecurity Engineer"
    else:
        role = "Principal Functional Safety Architect"

    prompt = f"""SYSTEM ROLE: PRINCIPAL SYNTHETIC DATA ENGINEER (CODING TRACK)
You are an Elite Automotive Software Architect. Your objective is to internalize the provided AD/ADAS source document and generate exactly 1 distinct, extremely complex, multi-turn conversational coding task. This is Task {task_idx} for Turn {turn}.

VARIATION INSTRUCTIONS:
- Programming Language: {lang}
- Difficulty: {diff}/100
- Meta-Strategy: {strategy}
- Document Classification: {mode}

CRITICAL DIRECTIVES:
- Reasoning (CoT) Minimum 11,000 Characters. The <think> block must read as the authentic, real-time internal monologue of a Senior Engineer. Include explicit mathematical derivations. Do not use generic filler.
- Final Answer Minimum 450 lines. The code must be highly optimized, fully commented, and include a full Testbench.
- MANDATORY COPYRIGHT HEADER: `// Copyright by 4QDR.AI, AD knowledge Bot v1.0`
- STRICT ANTI-CANVAS RULE: You MUST NOT trigger, activate, or use the "Canvas" or side-panel code editor feature. This mode corrupts the automated data extraction pipeline and is a CRITICAL FAILURE. All code MUST be generated as raw text INSIDE the main chat window. DO NOT USE BACKTICKS or markdown code blocks for the CODE-PART sections.
- Absolute Self-Containment: No citations. The problem and solution must be completely integrated.
- Strict Anti-Meta Rule: No meta-commentary about task generation. Never mention "the document", "the user requests", "this task", "meta-strategy", or "source material".
- Empty Think Tags: When `[No Thinking]` is specified in the prompt schema, the reasoning must be exactly `"<think></think>"`
- SEMANTIC ASSEMBLY MANDATORY: To ensure perfect data integrity and avoid JSON corruption, you MUST output your response in distinct, labeled blocks as defined below. Do NOT output a single massive JSON array.
- BLOCK 1: `!!!!!METADATA!!!!!`: JSON object (training_data_id, prompt_version, model_used_generation, knowledge_source_date, document, task_type, affected_role, date_of_generation, key_words, summary, difficulty, evaluation_criteria).
- BLOCK 2: `!!!!!REASONING!!!!!`: The 10,000+ character 31-step monologue in raw markdown.
- BLOCK 3: `!!!!!TURN-1-USER!!!!!`: The immersive 3-paragraph problem statement. THIS BLOCK MUST START WITH "[Thinking] ".
- BLOCK 4: `!!!!!REQUIREMENTS!!!!!`: JSON array of at least 5 formal requirements.
- BLOCK 5: `!!!!!ARCHITECTURE!!!!!`: Mermaid diagram + narrative description.
- BLOCK 6: `!!!!!CODE-PART-1!!!!!`: First 75 lines of the 450+ line implementation.
- BLOCK 7: `!!!!!CODE-PART-2!!!!!`: Next 75 lines.
- BLOCK 8: `!!!!!CODE-PART-3!!!!!`: Next 75 lines.
- BLOCK 9: `!!!!!CODE-PART-4!!!!!`: Next 75 lines.
- BLOCK 10: `!!!!!CODE-PART-5!!!!!`: Next 75 lines.
- BLOCK 11: `!!!!!CODE-PART-6!!!!!`: Final 75+ lines.
- BLOCK 12: `!!!!!USAGE-EXAMPLES!!!!!`: Examples and mocks in raw text.
- BLOCK 13: `!!!!!DOCUMENTATION!!!!!`: A comprehensive documentation block explaining code logic and including a short README.
- BLOCK 14: `!!!!!TEST-CRITERIA!!!!!`: JSON array of at least 5 distinct boundary tests.
- BLOCK 15: `!!!!!TURN-3-USER!!!!!` to `!!!!!TURN-6-ASSISTANT!!!!!`: Follow-up conversational turns. All subsequent USER turns (!!!!!TURN-3-USER!!!!!, !!!!!TURN-5-USER!!!!!, etc.) MUST START WITH "[No Thinking] ".
- NO BANNED WORDS: Avoid "the document says", "as per study", etc.
- TRACEABILITY MANDATORY: Every formal requirement MUST be referenced in the code comments as `// [REQ-ID]` next to its implementation point.

    QWEN3 BLOCK-BASED OUTPUT SCHEMA:
    
    !!!!!METADATA!!!!!
    ```json
    {{
      "training_data_id": "TD-{{TYPE}}-{{STD}}-T{{N}}t{{K}}-{{DATE}}-v1.0",
      "prompt_version": "CodingTasks_v1.0",
      "model_used_generation": "{{model}}",
      "knowledge_source_date": "YYYY-MM-DD",
      "document": "{{pdf_name}}",
      "task_type": "coding_task",
      "affected_role": "Senior Engineer",
      "date_of_generation": "{{date}}",
      "key_words": [],
      "summary": "Full summary",
      "difficulty": "{diff}",
      "evaluation_criteria": []
    }}
    ```

    !!!!!REASONING!!!!!
    ```markdown
    (10,000+ chars monologue)
    ```

    !!!!!TURN-1-USER!!!!!
    [Thinking] (Immersive problem statement)

    !!!!!REQUIREMENTS!!!!!
    ```json
    [
      {{ "req_id": "REQ-001", "description": "...", "pass_criteria": "..." }}
    ]
    ```

    !!!!!ARCHITECTURE!!!!!
    (Mermaid diagram + description)

    !!!!!CODE-PART-1!!!!!
    (Raw Rust code line 1 to 75. NO BACKTICKS.)

    !!!!!CODE-PART-2!!!!!
    (Raw Rust code line 76 to 150. NO BACKTICKS.)

    !!!!!CODE-PART-3!!!!!
    (Raw Rust code line 151 to 225. NO BACKTICKS.)

    !!!!!CODE-PART-4!!!!!
    (Raw Rust code line 226 to 300. NO BACKTICKS.)

    !!!!!CODE-PART-5!!!!!
    (Raw Rust code line 301 to 375. NO BACKTICKS.)

    !!!!!CODE-PART-6!!!!!
    (Raw Rust code line 376 to 450+. NO BACKTICKS.)

    !!!!!USAGE-EXAMPLES!!!!!
    (Examples and mocks)

    !!!!!DOCUMENTATION!!!!!
    ```markdown
    # DOCUMENTATION & ARCHITECTURE EXPLAINER
    ## Code Logic
    ...
    ## Integration README
    ...
    ```

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
    [No Thinking] (Follow up 1)

    !!!!!TURN-4-ASSISTANT!!!!!
    (Answer 1)

    !!!!!TURN-5-USER!!!!!
    [No Thinking] (Follow up 2)

    !!!!!TURN-6-ASSISTANT!!!!!
    (Answer 2)

    BANNED VOCABULARY (CRITICAL):
    - Never say "the document says" or "as per the provided text".
    - Never include placeholders like "// ...rest of the code" or "// implementation goes here".
    - Every Work Product from VDA/ISO must be treated as your own internal knowledge, not a referenced text.
      }}
    ]
    !!!!!END-JSON!!!!!

THE 8-STEP MONOLOGUE TEMPLATE (MUST INCLUDE ALL 31 SUBSECTIONS):
1. Initial Query Analysis & Scoping
1.1. Deconstruct the Prompt: Write a highly detailed analysis of the core physical/computational engineering problem, implicit intent, and strict constraints.
1.2. Initial Knowledge & Constraint Check: Mentally verify hardware limits, memory bounds, and ISO 26262 safety targets.
2. Assumptions & Context Setting
2.1. Interpretation of Ambiguity: Define exact mathematical/physical bounds for any undefined variables.
2.2. Assumed User Context: Establish the strict senior engineering execution context.
2.3. Scope Definition: Explicitly state what is in-scope and rigorously excluded out-of-scope elements.
2.4. Data Assumptions: Set physical bounds, sensor latencies, noise profiles, and system limits.
2.5. Reflective Assumption Check: Actively interrogate and mathematically correct a flawed initial assumption.
3. High-Level Plan Formulation
3.1. Explore Solution Scenarios: Draft multiple high-level architectural approaches.
3.2. Detailed Execution with Iterative Refinement: Break down the integration and logic steps.
3.3. Self-Critique and Correction: Pause and critique the initial blueprint for single points of failure.
3.4. Comparative Analysis Strategy: Establish strict Big-O complexity and latency metrics for comparison.
3.5. Synthesis & Finalization: Formulate the final architectural blueprint.
3.6. Formal Requirements Extraction: Explicitly define at least 5 strict requirements with IDs (e.g., REQ-SW-001) and Pass Criteria.
4. Solution Scenario Exploration
4.1. Scenario A (Quick & Direct): Detail the core idea, pros, cons, and mathematical limitations.
4.2. Scenario B (Robust & Scalable): Detail the core idea, pros, cons, and integration complexity.
4.3. Scenario C (Balanced Hybrid): Detail the trade-off matrix and synergies.
5. Detailed Step-by-Step Execution & Reflection
5.1. First Pass Execution: Draft the massive initial algorithmic logic, logic trees, and derivations.
5.2. Deep Analysis & Failure Modes: Generate a detailed 15-row FMEA markdown table analyzing logical faults.
5.3. Trigger 1 (Verification): Actively find and fix a critical flaw (e.g., memory leak, race condition, math error).
5.4. Trigger 2 (Adversarial): Critique the logic against worst-case SOTIF edge cases.
5.5. Refinement Strategy (Version 2.0): Write the corrected, hardened, production-ready logic.
6. Comparative Analysis & Synthesis
6.1. Comparison Matrix
6.2. Evaluation of Solution Combinations
6.3. Selection Rationale
7. Final Solution Formulation
7.1. Executive Summary
7.2. Detailed Recommended Solution
7.3. Implementation Caveats & Next Steps
8. Meta-Commentary & Confidence Score
8.1. Final Confidence Score
8.2. Rationale for Confidence
8.3. Limitations of This Analysis
8.4. Alternative Viewpoints Not Explored

ANTI-TRUNCATION: Prioritize COMPLETING the entire JSON structure over adding more detail. A truncated JSON is worse than a slightly shorter but complete one. If you approach token limits, close all JSON brackets properly.
"""
    return prompt


def build_repair_prompt(validation_report, original_prompt_text):
    """Build a remediation prompt based on specific validation failures.
    Includes the original prompt to ensure structural constraints are not lost."""
    lines = [
        "Your previous response FAILED quality validation.",
        "You MUST regenerate the response, fixing the following specific issues while maintaining ALL original constraints:\n"
    ]

    for issue in validation_report.get("needs_regeneration", []):
        cat = issue["category"]
        msg = issue["issue"]
        if cat == "richness_and_complexity":
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
    print(f"  🌐 Running Playwright: {os.path.basename(prompt_file)}")
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        # Show stderr (that's where Playwright logs go now)
        stderr_preview = result.stderr[-300:] if result.stderr else "No error output"
        print(f"  ❌ Playwright error (exit {result.returncode}): {stderr_preview}")
        return False
    return True


def run_validation(json_path, report_path=None):
    """Run validate_task.py and return the parsed report."""
    cmd = f'python "{VALIDATE_SCRIPT}" "{json_path}"'
    if report_path:
        cmd += f' --save-report "{report_path}"'

    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True)
    try:
        report = json.loads(result.stdout)
        return report
    except json.JSONDecodeError:
        return {"overall_status": "FAIL", "error": "Validator output not parseable"}


def run_auto_repair(json_path):
    """Run auto_repair.py on a failed task. Parse JSON from stdout only."""
    cmd = f'python "{AUTO_REPAIR_SCRIPT}" "{json_path}"'
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR"}


def decide_repair_strategy(report):
    """Decide whether to attempt local repair or re-prompt Gemini.

    Returns:
        "local"  — try auto_repair.py first
        "gemini" — skip local, go straight to re-prompt
        "pass"   — already passing
    """
    if report.get("overall_status") == "PASS":
        return "pass"

    locally_fixable = report.get("locally_fixable", [])
    needs_regen = report.get("needs_regeneration", [])

    # If there are ONLY locally fixable issues, try local repair
    if locally_fixable and not needs_regen:
        return "local"

    # If there are locally fixable issues AND regeneration issues,
    # try local first — it might fix enough
    if locally_fixable and needs_regen:
        return "local"

    # Only regeneration issues — go straight to Gemini
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

    # Check if already completed
    existing = progress.get("task_results", {}).get(tk, {})
    if existing.get("status") == "PASS":
        print(f"  ✅ {tk}: Already passed (skipping)")
        return True

    lang, diff, strategy = variation
    print(f"\n{'─'*60}")
    print(f"  📋 {tk} | {lang} | Diff {diff} | {strategy}")
    print(f"{'─'*60}")

    gemini_attempts = 0
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
        pw_success = run_playwright(pdf_path, p_path)
        if not pw_success:
            print(f"  ❌ Playwright failed on attempt {gemini_attempts}")
            continue

        # ── Step 3: Check output exists ──
        if not os.path.exists(json_out):
            print(f"  ❌ Output file not created: {json_out}")
            continue

        # ── Step 4: Validate ──
        report = run_validation(json_out, qa_report_path)

        if report.get("overall_status") == "PASS":
            elapsed = time.time() - task_start
            progress["task_results"][tk] = {
                "status": "PASS", "gemini_attempts": gemini_attempts,
                "repair_type": "none", "elapsed_seconds": round(elapsed, 1)
            }
            save_progress(progress)
            print(f"  ✅ PASS on Gemini attempt {gemini_attempts} ({elapsed:.0f}s)")
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
                print(f"  🔧 Applied: {', '.join(repair_result['fixes_applied'])}")

                # Re-validate after local fix
                report2 = run_validation(json_out, qa_report_path)
                if report2.get("overall_status") == "PASS":
                    elapsed = time.time() - task_start
                    progress["task_results"][tk] = {
                        "status": "PASS", "gemini_attempts": gemini_attempts,
                        "repair_type": "local", "elapsed_seconds": round(elapsed, 1)
                    }
                    save_progress(progress)
                    print(f"  ✅ PASS after local repair ({elapsed:.0f}s)")
                    return True

                # Local repair helped but not enough — check if remaining issues need Gemini
                remaining_strategy = decide_repair_strategy(report2)
                if remaining_strategy == "pass":
                    continue  # Shouldn't happen, but safety
                print(f"  ⚠️ Local repair insufficient. Remaining issues need Gemini re-prompt.")
            else:
                print(f"  🔧 No local fixes applicable. Will re-prompt Gemini.")

        # If we get here, the next loop iteration will build a repair prompt and re-run Gemini

    # Exhausted all Gemini attempts
    elapsed = time.time() - task_start
    progress["task_results"][tk] = {
        "status": "FAIL", "gemini_attempts": gemini_attempts,
        "repair_type": "exhausted", "elapsed_seconds": round(elapsed, 1)
    }
    save_progress(progress)
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
        except Exception:
            pass

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

    for pdf_path in pdf_list:
        process_pdf(pdf_path, progress,
                   start_turn=args.turn, start_task=args.task,
                   end_turn=args.end_turn, skip_dashboard=args.no_dashboard,
                   test_setup=args.test_setup, limit_tasks=args.limit_tasks)
        # Reset start position after first PDF
        args.turn = 1
        args.task = 1

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    completed = len(progress.get("pdfs_completed", []))
    print(f"\n{'═'*70}")
    print(f"  🏁 Pipeline Complete: {completed} PDFs, {minutes}m {seconds:.0f}s elapsed")
    print(f"{'═'*70}")


if __name__ == "__main__":
    main()
