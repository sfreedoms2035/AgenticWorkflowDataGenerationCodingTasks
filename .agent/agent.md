# Agent Configuration

## Environment
- **OS:** Windows 11
- **Python:** Conda (base)
- **Browser Automation:** Playwright (persistent profile in `.playwright_profile/`)

## Project Paths
- **Project Root:** `C:\Users\User\VS_Projects\Helpers\Antigravity\AgenticWorkflowBrowser`
- **Input PDFs:** `Input/` (relative to project root)
- **Output JSON:** `Output/json/`
- **Output Thinking:** `Output/thinking/`
- **QA & Eval:** `Eval/`
- **Scripts:** `.agent/scripts/`
- **Prompts:** `.agent/prompts/`

## Core Pipeline Entry Point
```
python pipeline.py                    # Process all PDFs
python pipeline.py --pdf "file.pdf"   # Process one PDF
python pipeline.py --resume           # Resume from checkpoint
python pipeline.py --validate-only    # Validate existing outputs
python pipeline.py --pdf "file.pdf" --turn 3 --task 2  # Start from specific point
python pipeline.py --no-dashboard     # Skip dashboard generation
```

## Scripts (`.agent/scripts/`)
| Script | Purpose |
|--------|---------|
| `validate_task.py` | Full quality gate validation (JSON, structure, richness, CoT, immersion, test count, copyright) |
| `auto_repair.py` | Unified local repair engine (merged content, markdown→JSON, turn padding, think tags) |
| `json_aggregator.py` | Post-processing: normalize training_data_id fields |
| `generate_dashboard.py` | Generate HTML dashboard with pipeline stats |

## Playwright Automation (`run_gemini_playwright_v2.py`)
| Feature | Detail |
|---------|--------|
| Model Selection | Always selects Gemini Pro automatically |
| Manual Steps | Zero — escalating timeouts with smart fallbacks |
| JSON Validation | Validates JSON before writing, attempts surgical repair if invalid |
| Exit Codes | 0 = valid JSON saved, 1 = failure |
| Logging | All output to stderr, stdout reserved for machine-readable data |

## Retry Logic
- **Max 3 Gemini attempts** per task
- Between each attempt, the pipeline decides:
  - **Locally fixable** (JSON structure, missing tags, turn padding) → `auto_repair.py`
  - **Needs regeneration** (volume, CoT, immersion) → Gemini re-prompt with targeted repair prompt
- Dashboard generates once per completed PDF (every 8 tasks)

## PDF Classification
PDFs are auto-classified as **Technical** or **Regulatory** based on keyword scoring:
- Keywords: `iso`, `regulation`, `compliance`, `standard`, `directive`, `sae`, `vda`, `unece`, etc.
- Score ≥ 2 → **REGULATORY** (uses regulatory variation schema)
- Score < 2 → **TECHNICAL** (uses technical variation schema)

## Quality Gates (validate_task.py)
| Gate | Threshold |
|------|-----------|
| CoT length | ≥ 9,000 chars |
| Answer length | ≥ 10,000 chars |
| Code volume | ≥ 400 lines |
| Conversation turns | Exactly 6 |
| CoT sub-elements | All 31 present |
| Self-containment | No banned vocabulary |
| Structured answer | 6 mandatory JSON keys |
| Test criteria | ≥ 5 items |
| Formal requirements | ≥ 5 items |
| Copyright header | `// Copyright by 4QDR.AI` |

## Current Status
- **VDA_5783**: Turn 1 complete (2/16 tasks), resuming from Turn 2
- **Remaining PDFs**: 10 PDFs pending in Input/

## Common Failure Modes & Fixes
| Problem | Cause | Fix |
|---------|-------|-----|
| Google Activity page redirect | Fresh session / cookies | Auto-handled by Playwright script |
| Truncated JSON | Token limit hit | Auto-continue loop (max 3 continuations) |
| Content merged into reasoning | Gemini formatting quirk | `auto_repair.py` splits at `</think>` |
| Markdown instead of JSON answer | Gemini ignores format directive | `auto_repair.py` converts markdown→JSON |
| stdout parse error in repair | `print()` mixed with JSON output | Fixed: all prints to stderr |

## File Naming Convention
```
{DocShort}_Turn{N}_Task{K}.json      # Output JSON
{DocShort}_Turn{N}_Task{K}.txt       # Thinking trace
{DocShort}_Turn{N}_Task{K}_Prompt.txt # Generation prompt
{DocShort}_Turn{N}_Task{K}_QA.json   # QA validation report
```
