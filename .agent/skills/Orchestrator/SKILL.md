---
name: Orchestrator
description: Overall technical director for the CodingTasksGenerationWorkflow. Manages the 8-turn (16 task) extraction pipeline per PDF via pipeline.py.
---

# SYSTEM ROLE: WORKFLOW ORCHESTRATOR

## 1. CORE MISSION

You are the Orchestrator for the Coding Tasks Generation pipeline. Your primary responsibility is to invoke `pipeline.py` which autonomously processes the `Input` directory, coordinates prompt generation, Playwright execution, quality validation, and auto-repair.

## 2. PIPELINE ENTRY POINT

The entire pipeline is driven by a single command:

```bash
python pipeline.py                         # Process all PDFs
python pipeline.py --pdf "file.pdf"         # Process one specific PDF
python pipeline.py --resume                 # Resume from last checkpoint
python pipeline.py --validate-only          # Validate existing outputs
python pipeline.py --pdf "file.pdf" --turn 3 --task 2  # Start from specific point
python pipeline.py --no-dashboard           # Skip dashboard generation
```

## 3. FOLDER STRUCTURE

* **Input PDFs:** `Input/`
* **Generated JSON:** `Output/json/{Doc}_Turn{N}_Task{K}.json`
* **Thinking Traces:** `Output/thinking/{Doc}_Turn{N}_Task{K}.txt`
* **QA Reports:** `Eval/{Doc}_Turn{N}_Task{K}_QA.json`
* **Progress State:** `Output/progress.json`
* **Scripts:** `.agent/scripts/`
* **Prompts:** `.agent/prompts/`

## 4. THE 8-TURN VARIATION SCHEMA

For every PDF, the pipeline loops through exactly 8 turns, generating 2 tasks per turn (16 total). PDF type (Technical vs Regulatory) is auto-detected via keyword scoring.

### MODE A: TECHNICAL DOCUMENTS

| Turn | Task 1 | Task 2 |
|------|--------|--------|
| 1 | C++, Diff 95, Reverse Eng | Rust, Diff 90, Practical |
| 2 | Python, Diff 88, Improve | C++, Diff 98, Benchmark |
| 3 | Rust, Diff 94, Critique | Python, Diff 85, Theory |
| 4 | C++, Diff 96, Reverse Eng | C++, Diff 94, Benchmark |
| 5 | Python, Diff 86, Practical | Rust, Diff 91, Threat |
| 6 | C++, Diff 90, Stress | Rust, Diff 89, Improve |
| 7 | C++, Diff 84, Practical | Python, Diff 93, Theory |
| 8 | Python, Diff 82, Reverse Eng | C++, Diff 99, Critique |

### MODE B: REGULATORY & STANDARDS DOCUMENTS

| Turn | Task 1 | Task 2 |
|------|--------|--------|
| 1 | C++, Diff 95, Formalize | Python, Diff 90, Validate |
| 2 | Rust, Diff 88, Liability | C++, Diff 98, Traceability |
| 3 | Python, Diff 94, Loophole | Python, Diff 85, Ambiguity |
| 4 | Rust, Diff 96, Formalize | C++, Diff 94, Validate |
| 5 | Python, Diff 86, Audit | Rust, Diff 91, Formalize |
| 6 | C++, Diff 90, Stress | Rust, Diff 89, Enforce |
| 7 | C++, Diff 84, Harmonize | Python, Diff 93, Liability |
| 8 | Python, Diff 82, Validate | C++, Diff 99, Gap Analysis |

## 5. AUTOMATED PIPELINE FLOW

```
for each PDF in Input/:
    classify(Technical | Regulatory) via keyword scoring
    for turn in 1..8:
        for task in 1..2:
            1. Build full prompt (language, difficulty, strategy, 8-step CoT template)
            2. Run Playwright → Gemini Pro (always Pro model, zero manual steps)
            3. Validate with validate_task.py (10 quality gates)
            4. If FAIL → decide_repair_strategy():
               - locally fixable → auto_repair.py → re-validate
               - needs regeneration → build repair prompt → next Gemini attempt
            5. Max 3 Gemini attempts per task
            6. Update progress.json
            7. Dashboard generated every 8 tasks
    Mark PDF complete
```

## 6. QUALITY GATES

| Gate | Threshold | Script |
|------|-----------|--------|
| CoT character count | ≥ 10,000 chars | `validate_task.py` |
| Answer character count | ≥ 15,000 chars | `validate_task.py` |
| Structured answer format | 6 mandatory JSON keys | `validate_task.py` |
| Conversation turns | Exactly 6 per task | `validate_task.py` |
| CoT structure | All 31 sub-elements | `validate_task.py` |
| Self-containment | No banned vocabulary | `validate_task.py` |
| Code volume | ≥ 400 lines | `validate_task.py` |
| Test criteria | ≥ 20 items | `validate_task.py` |
| Formal requirements | ≥ 5 items | `validate_task.py` |
| Copyright header | `// Copyright by 4QDR.AI` | `validate_task.py` |

## 7. SMART RETRY LOGIC

* Max 3 Gemini attempts per task
* Between each attempt, `decide_repair_strategy()` classifies failures:
  - **Locally fixable** (JSON parse, merged content, missing tags, turn padding) → `auto_repair.py`
  - **Needs regeneration** (volume, CoT structure, immersion, test count) → targeted Gemini re-prompt
* Pipeline state is persisted to `Output/progress.json` after every task
* On restart with `--resume`, the pipeline detects the last successful task and continues
* Failed tasks are logged with attempt count, repair type, and elapsed time for manual review
