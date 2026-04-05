---
description: Automatically orchestrates the generation of 16 coding tasks per PDF using Playwright and Gemini Web App.
---

# CodingTasksGenerationWorkflow

This workflow generates 16 expert-level AD/ADAS coding tasks per PDF by automating the Gemini web interface via `pipeline.py`.

// turbo-all

## EXECUTION STEPS (MANDATORY — Follow in Order)

### Step 1: Load Context
Read the agent configuration to understand paths and current state:
```bash
cat .agent/agent.md
```

### Step 2: Check Current State
Check what PDFs exist and what progress has been made:
```bash
dir Input\*.pdf
type Output\progress.json
```
If `progress.json` doesn't exist, this is a fresh start. If it exists, read it to determine the next PDF / turn / task to process.

### Step 3: Validate Existing Outputs (if any)
Run validation on all existing outputs to understand current quality state:
```bash
python pipeline.py --validate-only
```
Review the output. Note which tasks PASS and which FAIL.

### Step 4a: Fresh Start — Process All PDFs
If no progress exists or all PDFs need processing:
```bash
python pipeline.py
```

### Step 4b: Resume After Interruption
If progress.json shows partial completion, resume from the exact point:
```bash
python pipeline.py --resume
```
Or specify the exact position if known:
```bash
python pipeline.py --pdf "FILENAME.pdf" --turn N --task K
```
**How to determine resume point:** Read `progress.json`, find the last task with `"status": "PASS"`, and start from the next task in the sequence. Each PDF has 8 turns × 2 tasks = 16 tasks. Turn N, Task K means the Kth task (1 or 2) within Turn N (1-8).

### Step 4c: Process a Specific PDF
```bash
python pipeline.py --pdf "VDA_5783_Positionspapier_ISO_SAE_21434_EN (1).pdf"
```

### Step 5: Post-Pipeline Validation
After the pipeline finishes (or after manual intervention), re-validate all outputs:
```bash
python pipeline.py --validate-only
```

### Step 6: Normalize Training Data IDs
Once all tasks for a PDF pass validation, normalize the IDs:
```bash
python .agent/scripts/json_aggregator.py
```

### Step 7: Generate Final Dashboard
```bash
python .agent/scripts/generate_dashboard.py
```
Open `Eval/dashboard.html` to review results.

---

## WHAT THE PIPELINE DOES AUTOMATICALLY

`pipeline.py` handles all of these internally — you do NOT need to call individual scripts:

1. **Classifies** each PDF as Technical or Regulatory (keyword scoring)
2. **Builds** a full prompt per turn/task/variation (language, difficulty, meta-strategy, complete 8-step CoT template)
3. **Runs** `run_gemini_playwright_v2.py` (always selects Gemini Pro, zero manual steps)
4. **Validates** output via `validate_task.py` (10 quality gates)
5. **Decides** repair strategy: local fix (`auto_repair.py`) vs Gemini re-prompt
6. **Retries** up to 3 Gemini attempts per task
7. **Saves** progress after every task for resume support
8. **Generates** dashboard every 8 completed tasks

---

## RECOVERY FROM COMMON FAILURES

### Pipeline Crashed Mid-Task
```bash
python pipeline.py --resume
```
Progress is saved after every task. The pipeline will skip all passed tasks and continue.

### A Task Keeps Failing After 3 Attempts
The task is logged as FAIL in `progress.json`. To retry it manually:
1. Read the QA report: `type Eval\{Doc}_Turn{N}_Task{K}_QA.json`
2. Review the violations
3. If it's a local fix, run: `python .agent/scripts/auto_repair.py Output\json\{Doc}_Turn{N}_Task{K}.json`
4. Re-validate: `python .agent/scripts/validate_task.py Output\json\{Doc}_Turn{N}_Task{K}.json`
5. If it needs regeneration, re-run the specific task: `python pipeline.py --pdf "file.pdf" --turn N --task K`

### Playwright Browser Issues
If the browser hangs or can't find the chat input:
1. Close all Chrome/Chromium windows
2. Optionally clear the profile: `rmdir /s .playwright_profile`
3. Re-run: `python pipeline.py --resume`

### Google Activity Page / Login Required
The Playwright script auto-handles activity page redirects. If login is needed, you have 120 seconds to log in manually before the script times out.

---

## QUALITY GATES

| Gate | Threshold |
| --- | --- |
| CoT length | ≥ 9,000 chars |
| Answer length | ≥ 10,000 chars |
| Structured answer | 6 mandatory JSON keys |
| Conversation turns | Exactly 6 per task |
| CoT structure | All 31 sub-elements |
| Self-containment | No banned vocabulary |
| Code volume | ≥ 300 lines |
| Test criteria | ≥ 5 items |
| Formal requirements | ≥ 5 items |
| Copyright header | `// Copyright by 4QDR.AI` |

## REPAIR STRATEGY

- **Local fixes** (auto_repair.py): JSON parsing, merged content, markdown→JSON, missing think tags, turn padding
- **Gemini re-prompt**: volume failures (CoT/answer too short), missing CoT elements, immersion breaks, insufficient tests
- **Max 3 Gemini attempts** per task — local repair is always attempted first between attempts

## AGENT GUIDELINES

- **Always use the scripts.** Never manually edit JSON output files unless `auto_repair.py` cannot fix the issue.
- **Always resume, never restart.** Use `--resume` or explicit `--turn/--task` flags. Never delete `progress.json`.
- **Optimize freely.** The agent can modify workflow files, scripts, and skills to improve quality, speed, or reliability. But the core execution path (Steps 1-7) must remain intact.
- **Log what you change.** If you modify a script or skill, note it in the conversation so the user is aware.
