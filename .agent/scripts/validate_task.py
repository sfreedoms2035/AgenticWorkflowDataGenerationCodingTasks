"""
validate_task.py — Comprehensive Quality Gate Validator
=======================================================
Validates a single-task JSON file against ALL quality gates defined in the
DataQualityChecker and CodingTaskGenerator skills.

Exit codes: 0 = PASS, 1 = FAIL
Output: JSON quality report to stdout

Usage:
    python validate_task.py <filepath>
    python validate_task.py <filepath> --save-report <report_path>
    python validate_task.py <filepath> --quiet
"""
import sys
import json
import re
import os


# ── Quality Gate Thresholds ──────────────────────────────────────────────────
COT_MIN_CHARS = 9_000
COT_REGEN_THRESHOLD = 9_000
ANSWER_MIN_CHARS = 10_000
CODE_MIN_LINES = 300
CODE_REGEN_THRESHOLD = 300
REQUIRED_TURNS = 6
MIN_TEST_CRITERIA = 5
MIN_FORMAL_REQUIREMENTS = 5
COPYRIGHT_HEADER = "Copyright by 4QDR.AI"

REQUIRED_TOP_FIELDS = [
    "training_data_id", "prompt_version", "model_used_generation",
    "knowledge_source_date", "document", "task_type", "affected_role",
    "date_of_generation", "key_words", "summary", "difficulty",
    "evaluation_criteria", "conversations"
]

STRUCTURED_ANSWER_KEYS = [
    "formal_requirements", "architecture_block", "executable_code",
    "documentation", "usage_examples", "testbench_and_mocks", "test_criteria"
]

COT_SUB_ELEMENTS = [
    "1.1", "1.2",
    "2.1", "2.2", "2.3", "2.4", "2.5",
    "3.1", "3.2", "3.3", "3.4", "3.5", "3.6",
    "4.1", "4.2", "4.3",
    "5.1", "5.2", "5.3", "5.4", "5.5",
    "6.1", "6.2", "6.3",
    "7.1", "7.2", "7.3",
    "8.1", "8.2", "8.3", "8.4"
]

BANNED_VOCABULARY = [
    "the user requests",
    "the document says", "source material", "as mentioned in the pdf",
    "based on the provided", "the text states", "generate a task"
]


def validate_task(filepath):
    """Run all quality gates and return structured report."""
    report = {
        "report_id": "QA-AUTO",
        "evaluated_file": os.path.basename(filepath),
        "overall_status": "PASS",
        "locally_fixable": [],       # Issues auto_repair.py can fix
        "needs_regeneration": [],    # Issues requiring Gemini re-prompt
        "metrics": {
            "json_structure": {"status": "PASS", "violations": []},
            "conversation_completeness": {"status": "PASS", "violations": []},
            "richness_and_complexity": {"status": "PASS", "violations": []},
            "structured_answer_format": {"status": "PASS", "violations": []},
            "cot_structure": {"status": "PASS", "violations": []},
            "self_containment": {"status": "PASS", "violations": []},
        }
    }

    def fail(category, message, fixable_locally=False):
        report["overall_status"] = "FAIL"
        report["metrics"][category]["status"] = "FAIL"
        report["metrics"][category]["violations"].append(message)
        if fixable_locally:
            report["locally_fixable"].append({"category": category, "issue": message})
        else:
            report["needs_regeneration"].append({"category": category, "issue": message})

    # ── Gate 0: JSON Parsing ─────────────────────────────────────────────
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        fail("json_structure", f"JSON parse error: {e}", fixable_locally=True)
        return report
    except FileNotFoundError:
        fail("json_structure", f"File not found: {filepath}")
        return report

    if not isinstance(data, list) or len(data) == 0:
        fail("json_structure", "Expected non-empty JSON array")
        return report

    task = data[0]
    if not isinstance(task, dict):
        fail("json_structure", "First element is not a JSON object")
        return report

    # ── Gate 1: Top-Level Fields ─────────────────────────────────────────
    for field in REQUIRED_TOP_FIELDS:
        if field not in task:
            fail("json_structure", f"Missing required field: '{field}'")

    # ── Gate 2: Conversation Structure ───────────────────────────────────
    convs = task.get("conversations", [])
    if not isinstance(convs, list):
        fail("conversation_completeness", "conversations is not an array")
        return report

    if len(convs) != REQUIRED_TURNS:
        fail("conversation_completeness",
             f"Expected {REQUIRED_TURNS} turns, got {len(convs)}",
             fixable_locally=(len(convs) < REQUIRED_TURNS))

    # Check role alternation: user, assistant, user, assistant, user, assistant
    expected_roles = ["user", "assistant", "user", "assistant", "user", "assistant"]
    for i, (conv, expected_role) in enumerate(zip(convs, expected_roles)):
        if not isinstance(conv, dict):
            fail("conversation_completeness", f"Turn {i}: expected a JSON object but got a different type")
            continue
        actual_role = conv.get("role", "")
        if actual_role != expected_role:
            fail("conversation_completeness",
                 f"Turn {i}: expected role '{expected_role}', got '{actual_role}'")

    # Check non-empty content for all turns
    for i, conv in enumerate(convs):
        if not isinstance(conv, dict):
            continue
        content = conv.get("content", "")
        if not content or not content.strip():
            fail("conversation_completeness",
                 f"Turn {i}: empty content",
                 fixable_locally=(conv.get("role") == "assistant" and i > 1))

    # Check <think></think> format for No-Thinking assistant turns (indices 3, 5)
    for i in [3, 5]:
        if i < len(convs):
            conv = convs[i]
            if isinstance(conv, dict) and conv.get("role") == "assistant":
                reasoning = conv.get("reasoning", "")
                if reasoning != "<think></think>":
                    if not reasoning or reasoning.strip() == "":
                        fail("conversation_completeness",
                             f"Turn {i}: missing <think></think> tags (got empty reasoning)",
                             fixable_locally=True)

    if len(convs) < 2:
        return report  # Can't check further without main assistant turn

    # ── Gate 3: Main Assistant Turn (index 1) — Richness ─────────────────
    main_assistant = convs[1]
    reasoning = main_assistant.get("reasoning", "")
    content = main_assistant.get("content", "")

    # Check for merged content-in-reasoning anomaly
    if len(content.strip()) < 100 and "</think>" in reasoning:
        parts = reasoning.split("</think>", 1)
        if len(parts) == 2 and len(parts[1].strip()) > 100:
            fail("richness_and_complexity",
                 f"Content merged into reasoning ({len(parts[1])} chars after </think>)",
                 fixable_locally=True)
            # For length checks below, use the actual content length
            content = parts[1].strip()

    cot_len = len(reasoning)
    content_len = len(content)

    if cot_len < COT_MIN_CHARS:
        # User requested: regen below 9000
        needs_regen = (cot_len < COT_REGEN_THRESHOLD)
        fail("richness_and_complexity",
             f"CoT too short: {cot_len} chars (min {COT_MIN_CHARS})",
             fixable_locally=not needs_regen)

    if content_len < ANSWER_MIN_CHARS:
        fail("richness_and_complexity",
             f"Answer too short: {content_len} chars (min {ANSWER_MIN_CHARS})")

    # Check for forbidden placeholder patterns
    if re.search(r'\.{4,}', content):
        fail("richness_and_complexity",
             "Found forbidden placeholder (4+ dots) in content")

    # ── Gate 4: Structured Answer Format ─────────────────────────────────
    try:
        parsed_answer = json.loads(content)
        if isinstance(parsed_answer, dict):
            for key in STRUCTURED_ANSWER_KEYS:
                if key not in parsed_answer:
                    fail("structured_answer_format",
                         f"Missing structured answer key: '{key}'",
                         fixable_locally=True)

            # Check executable_code has enough lines
            code = parsed_answer.get("executable_code", "")
            code_lines = code.count("\\n") + code.count("\n") + 1
            if code_lines < CODE_MIN_LINES:
                # User requested: regen below 300
                needs_regen = (code_lines < CODE_REGEN_THRESHOLD)
                fail("richness_and_complexity",
                     f"Code too short: ~{code_lines} lines (min {CODE_MIN_LINES})",
                     fixable_locally=not needs_regen)

            # ── Gate 4a: Copyright Header ────────────────────────────────
            if COPYRIGHT_HEADER not in code:
                fail("structured_answer_format",
                     f"Missing copyright header: '{COPYRIGHT_HEADER}'",
                     fixable_locally=True)

            # ── Gate 4b: Test Criteria Count ─────────────────────────────
            test_criteria = parsed_answer.get("test_criteria", [])
            if isinstance(test_criteria, list) and len(test_criteria) < MIN_TEST_CRITERIA:
                fail("structured_answer_format",
                     f"Too few test_criteria: {len(test_criteria)} (min {MIN_TEST_CRITERIA})")

            # ── Gate 4c: Formal Requirements Count ───────────────────────
            formal_reqs = parsed_answer.get("formal_requirements", [])
            if isinstance(formal_reqs, list) and len(formal_reqs) < MIN_FORMAL_REQUIREMENTS:
                fail("structured_answer_format",
                     f"Too few formal_requirements: {len(formal_reqs)} (min {MIN_FORMAL_REQUIREMENTS})")
        else:
            fail("structured_answer_format",
                 "Content is valid JSON but not an object (expected dict with 6 keys)",
                 fixable_locally=True)
    except (json.JSONDecodeError, TypeError):
        # Content is not JSON — might be raw markdown
        fail("structured_answer_format",
             "Content is not a valid JSON object (may be raw markdown)",
             fixable_locally=True)

    # ── Gate 5: CoT 8-Step Structure ─────────────────────────────────────
    # Extract think block content
    think_match = re.search(r'<think>(.*?)</think>', reasoning, re.DOTALL)
    think_content = think_match.group(1) if think_match else reasoning

    # Normalize: convert escaped \\n sequences to actual newlines for regex matching
    think_normalized = think_content.replace("\\n", "\n").replace("\\\\n", "\n")

    missing_elements = []
    for elem in COT_SUB_ELEMENTS:
        # Flexible pattern to match headers like: "1.1.", "**1.1.**", "### 1.1", "- 1.1:"
        pattern = rf'(?:^|[\n\r])[\s#\-\*]*{re.escape(elem)}[\.\s:\)]'
        if not re.search(pattern, think_normalized):
            missing_elements.append(elem)

    if missing_elements:
        if len(missing_elements) <= 5:
            fail("cot_structure",
                 f"Missing CoT sub-elements: {', '.join(missing_elements)}")
        else:
            fail("cot_structure",
                 f"Missing {len(missing_elements)} CoT sub-elements: "
                 f"{', '.join(missing_elements[:5])}...")

    # ── Gate 6: Self-Containment (Immersion) ─────────────────────────────
    full_text = (reasoning + " " + content).lower()
    for banned in BANNED_VOCABULARY:
        if banned.lower() in full_text:
            fail("self_containment",
                 f"Banned vocabulary detected: '{banned}'")

    # Add summary stats to report
    report["stats"] = {
        "cot_chars": cot_len,
        "answer_chars": content_len,
        "turns": len(convs),
    }

    return report


def main():
    quiet = "--quiet" in sys.argv

    if len(sys.argv) < 2:
        if not quiet:
            print(json.dumps({"overall_status": "FAIL", "error": "No filepath provided"}))
        sys.exit(1)

    filepath = sys.argv[1]
    report = validate_task(filepath)

    # Optionally save report to file
    if "--save-report" in sys.argv:
        idx = sys.argv.index("--save-report")
        if idx + 1 < len(sys.argv):
            report_path = sys.argv[idx + 1]
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    sys.exit(0 if report["overall_status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
