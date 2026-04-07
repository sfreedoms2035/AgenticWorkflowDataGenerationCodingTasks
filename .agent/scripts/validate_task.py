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
CODE_MIN_LINES = 250
CODE_REGEN_THRESHOLD = 250
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

# Parent step headers that MUST also appear in the CoT
COT_PARENT_HEADERS = ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8."]

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
    "based on the provided", "the text states", "generate a task",
    "generate a multi-turn", "create a coding task", "produce a dataset",
    "cite"
]

# Followup placeholder sentinels that indicate extraction failures
FOLLOWUP_PLACEHOLDERS = [
    "Follow up 1?", "Follow up 2?",
    "Response 1.", "Response 2.",
    "Follow up 1", "Follow up 2",
]

# Instruction-echo sentinels: if these appear in follow-up turn content,
# the model echoed the prompt template instead of generating real content
INSTRUCTION_ECHO_PATTERNS = [
    # Old parenthesized format (kept for legacy/repair prompts)
    "(Write a 2-3 sentence technical inquiry",
    "(Write the first technical response here",
    "(Write another 2-3 sentence",
    "(Write the final technical response here",
    "minimum 100 characters)",
    "Ensure it is highly detailed and contextual.)",
    "Must be highly detailed.)",
    # New angle-bracket format
    "<WRITE YOUR TECHNICAL FOLLOW-UP QUESTION HERE",
    "<WRITE YOUR DETAILED TECHNICAL RESPONSE HERE",
    "<WRITE YOUR SECOND TECHNICAL FOLLOW-UP QUESTION HERE",
    "<WRITE YOUR FINAL TECHNICAL RESPONSE HERE",
    "WRITE YOUR TECHNICAL FOLLOW-UP",
    "NO template text>",
    # Meta-instruction leakage (any format)
    "BANNED VOCABULARY (CRITICAL)",
    "Never say \"based on established practice\"",
    "Never include placeholders like",
    "Every Work Product from VDA/ISO must be treated",
    "(Write the immersive 3-paragraph problem statement here",
]

# JSON key artifact patterns: fragments from LLM treating output as JSON key-value
JSON_KEY_ARTIFACT_PATTERN = r'(?:^|\s)\\?"\s*:\s*\\?"'

# Keywords often used for "Word Salad" padding to inflate character counts
PADDING_KEYWORDS = [
    "visualization", "visualized", "visualize", "visualizations", "visualizing",
    "derivation", "derived", "deriving", "derivations",
    "complexity", "complexities",
    "difficulty", "difficulties",
    "criteria", "criterion",
    "conceptual", "conceptually",
    "initialization", "initialized",
    "virtualized", "virtualization",
]


def validate_task(filepath):
    """Run all quality gates and return structured report."""
    report = {
        "report_id": "QA-AUTO",
        "evaluated_file": os.path.basename(filepath),
        "overall_status": "PASS",
        "locally_fixable": [],       # Issues auto_repair.py can fix
        "needs_regeneration": [],    # Issues requiring full Gemini re-prompt
        "needs_partial_repair": [],  # Issues fixable by re-prompting only follow-up turns
        "metrics": {
            "json_structure": {"status": "PASS", "violations": []},
            "conversation_completeness": {"status": "PASS", "violations": []},
            "richness_and_complexity": {"status": "PASS", "violations": []},
            "structured_answer_format": {"status": "PASS", "violations": []},
            "cot_structure": {"status": "PASS", "violations": []},
            "self_containment": {"status": "PASS", "violations": []},
            "followup_quality": {"status": "PASS", "violations": []},
            "thinking_quality": {"status": "PASS", "violations": []},
        }
    }

    def fail(category, message, fixable_locally=False, partial_repair=False):
        report["overall_status"] = "FAIL"
        report["metrics"][category]["status"] = "FAIL"
        report["metrics"][category]["violations"].append(message)
        if fixable_locally:
            report["locally_fixable"].append({"category": category, "issue": message})
        elif partial_repair:
            report["needs_partial_repair"].append({"category": category, "issue": message})
        else:
            report["needs_regeneration"].append({"category": category, "issue": message})

    def check_keyword_padding(text, turn_label):
        """Check for excessive density of padding keywords (word-salad)."""
        if not text:
            return
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return
        
        # 1. Check density of padding keywords
        padding_count = sum(1 for w in words if w in PADDING_KEYWORDS)
        density = padding_count / len(words)
        if density > 0.15:  # Absolute density threshold
            fail("richness_and_complexity",
                 f"{turn_label} contains keyword-salad padding "
                 f"({padding_count}/{len(words)} padding words, {density:.1%})",
                 fixable_locally=False)
            return

        # 2. Check for "dense clusters" (3+ keywords in a window of 5)
        for i in range(len(words) - 4):
            window = words[i:i+5]
            win_padding = sum(1 for w in window if w in PADDING_KEYWORDS)
            if win_padding >= 4:
                fail("richness_and_complexity",
                     f"{turn_label} contains a dense cluster of padding keywords "
                     f"(e.g., '{' '.join(window)}')",
                     fixable_locally=False)
                return

    def check_internal_repetition(text, turn_label):
        """Check for verbatim repeated paragraphs or large blocks (looping)."""
        if not text or len(text) < 1000:
            return
        paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 100]
        if not paragraphs:
            return
            
        seen_sigs = {}
        for i, p in enumerate(paragraphs):
            # Signature: first 150 chars normalized
            sig = re.sub(r'\s+', '', p[:150].lower())
            if sig in seen_sigs:
                fail("richness_and_complexity",
                     f"{turn_label} contains a verbatim repetition loop. "
                     f"Paragraph {i} matches paragraph {seen_sigs[sig]}.",
                     fixable_locally=False)
                return
            seen_sigs[sig] = i

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
            fail("json_structure", f"Missing required field: '{field}'", fixable_locally=True)

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
            # Followup assistant turns (3 and 5) with empty content need full regeneration
            if conv.get("role") == "assistant" and i in [3, 5]:
                fail("conversation_completeness",
                     f"Turn {i}: empty assistant content (last followup response is blank) — requires regeneration",
                     fixable_locally=False)
            elif conv.get("role") == "assistant" and i > 1:
                fail("conversation_completeness",
                     f"Turn {i}: empty content",
                     fixable_locally=True)
            else:
                fail("conversation_completeness",
                     f"Turn {i}: empty content",
                     fixable_locally=False)

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

    # ── Gate 3a: Empty or Placeholder Thinking Check ──────────────────────
    # Detect [NO_THINKING_SECTION] placeholder or a completely empty reasoning field.
    # Both indicate the LLM failed to produce a real CoT monologue.
    EMPTY_THINKING_SENTINELS = [
        "[NO_THINKING_SECTION]",
        "[no_thinking_section]",
        "<think></think>",   # Empty self-closed tags
    ]
    reasoning_stripped = reasoning.strip()
    if not reasoning_stripped:
        fail("richness_and_complexity",
             "Main assistant turn (index 1): reasoning field is completely empty — requires regeneration",
             fixable_locally=False)
    else:
        for sentinel in EMPTY_THINKING_SENTINELS:
            if reasoning_stripped == sentinel or reasoning_stripped.startswith("[NO_THINKING_SECTION]"):
                fail("richness_and_complexity",
                     f"Main assistant turn (index 1): reasoning contains placeholder '{sentinel}' instead of real CoT — requires regeneration",
                     fixable_locally=False)
                break

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
    # Collapse multiple horizontal spaces to single spaces to allow matching against Gemini's double-spaced lists
    think_normalized = re.sub(r'[ \t]+', ' ', think_normalized)

    # ── Gate 5a: Check parent step headers (1. through 8.) ───────────────
    missing_parents = []
    for parent in COT_PARENT_HEADERS:
        # Match e.g. "1." or "**1.**" or "### 1." at start of line
        pattern = rf'(?:^|[\n\r])[\s#\-\*]*{re.escape(parent)}[\s]'
        if not re.search(pattern, think_normalized):
            missing_parents.append(parent)

    if missing_parents:
        fail("cot_structure",
             f"Missing CoT parent headers: {', '.join(missing_parents)}",
             fixable_locally=False)

    # ── Gate 5b: Check sub-elements (1.1 through 8.4) ────────────────────
    missing_elements = []
    for elem in COT_SUB_ELEMENTS:
        # Flexible pattern to match headers like: "1.1.", "**1.1.**", "### 1.1", "- 1.1:"
        pattern = rf'(?:^|[\n\r])[\s#\-\*]*{re.escape(elem)}[\.\s:\)]'
        if not re.search(pattern, think_normalized):
            missing_elements.append(elem)

    if missing_elements:
        # User Optimization: If the CoT is very long (>15k), allow up to 5 missing sub-elements as fixable
        is_fixable = (cot_len > 15_000 and len(missing_elements) <= 5)
        
        if len(missing_elements) <= 5:
            fail("cot_structure",
                 f"Missing CoT sub-elements: {', '.join(missing_elements)}",
                 fixable_locally=is_fixable)
        else:
            fail("cot_structure",
                 f"Missing {len(missing_elements)} CoT sub-elements: "
                 f"{', '.join(missing_elements[:5])}...",
                 fixable_locally=False)

    # ── Gate 5c: Duplicate <think> tag detection ─────────────────────────
    # Detect patterns like <think>\n<think> or <think>\n\<think\>
    dup_think = re.search(r'<think>\s*(?:\\?<think\\?>|<think>)', reasoning)
    if dup_think:
        fail("cot_structure",
             "Duplicate <think> tag detected inside reasoning",
             fixable_locally=True)

    # ── Gate 6: Self-Containment (Immersion) ─────────────────────────────
    full_text = (reasoning + " " + content).lower()
    for banned in BANNED_VOCABULARY:
        if banned.lower() in full_text:
            fail("self_containment",
                 f"Banned vocabulary detected: '{banned}'",
                 fixable_locally=True)

    # ── Gate 7: Followup Placeholder Detection ───────────────────────────
    # Detect when extraction produced fallback placeholder text
    for idx in [2, 3, 4, 5]:  # Follow-up turns
        if idx < len(convs):
            conv_content = convs[idx].get("content", "").strip()
            for placeholder in FOLLOWUP_PLACEHOLDERS:
                if conv_content == placeholder:
                    fail("conversation_completeness",
                         f"Turn {idx}: contains extraction placeholder '{placeholder}'",
                         fixable_locally=False)

    # ── Gate 8: Follow-up Specificity (User turns 2, 4) ──────────────────
    for idx in [2, 4]:  # User follow-up turns
        if idx < len(convs) and convs[idx].get("role") == "user":
            fu_content = convs[idx].get("content", "")
            if len(fu_content) < 100:
                fail("conversation_completeness",
                     f"Turn {idx}: follow-up user prompt too short ({len(fu_content)} chars, min 100)",
                     fixable_locally=False)

    # ── Gate 9: [Thinking]/[No Thinking] Prefix Check ────────────────────
    # Turn 0 (user) must start with [Thinking]
    if len(convs) > 0 and convs[0].get("role") == "user":
        t0_content = convs[0].get("content", "")
        if not t0_content.startswith("[Thinking]"):
            fail("conversation_completeness",
                 "Turn 0: user prompt must start with '[Thinking]'",
                 fixable_locally=True)
    # Turns 2, 4 (user) must start with [No Thinking]
    for idx in [2, 4]:
        if idx < len(convs) and convs[idx].get("role") == "user":
            tu_content = convs[idx].get("content", "")
            if not tu_content.startswith("[No Thinking]"):
                fail("conversation_completeness",
                     f"Turn {idx}: user prompt must start with '[No Thinking]'",
                     fixable_locally=True)

    # ── Gate 10: Anti-Repetition for formal_requirements ──────────────────
    try:
        parsed_for_rep = json.loads(content)
        if isinstance(parsed_for_rep, dict):
            reqs = parsed_for_rep.get("formal_requirements", [])
            if isinstance(reqs, list) and len(reqs) > 1:
                descriptions = [r.get("description", "") for r in reqs if isinstance(r, dict)]
                if len(descriptions) != len(set(descriptions)):
                    fail("structured_answer_format",
                         "Duplicate descriptions in formal_requirements",
                         fixable_locally=False)
    except (json.JSONDecodeError, TypeError):
        pass  # Already caught in Gate 4

    # ── Gate 11: Keyword-Salad Padding and Internal Repetition ────────────
    # Check main reasoning and follow-up user turns
    check_keyword_padding(reasoning, "Reasoning (CoT)")
    check_internal_repetition(reasoning, "Reasoning (CoT)")
    
    for i, conv in enumerate(convs):
        if conv.get("role") == "user":
            check_keyword_padding(conv.get("content", ""), f"Turn {i} (user)")

    # ── Gate 12: [No Thinking] Tag Duplication ────────────────────────────
    # Detect doubled [No Thinking] prefix with JSON key artifacts between them
    for idx in [2, 4]:  # User follow-up turns
        if idx < len(convs) and convs[idx].get("role") == "user":
            fu_content = convs[idx].get("content", "")
            # Pattern: [No Thinking] ... [No Thinking] (doubled prefix)
            nt_count = fu_content.count("[No Thinking]")
            if nt_count > 1:
                fail("followup_quality",
                     f"Turn {idx}: duplicated [No Thinking] prefix ({nt_count} occurrences)",
                     fixable_locally=True)

    # ── Gate 13: Instruction Echo Detection (Follow-Up Turns) ─────────────
    # Detect when model echoed the prompt template instead of generating real content
    for idx in [2, 3, 4, 5]:  # All follow-up turns
        if idx < len(convs):
            fu_content = convs[idx].get("content", "")
            for echo_pattern in INSTRUCTION_ECHO_PATTERNS:
                if echo_pattern in fu_content:
                    fail("followup_quality",
                         f"Turn {idx}: instruction echo detected — model echoed prompt template "
                         f"instead of generating content (matched: '{echo_pattern[:50]}...')",
                         partial_repair=True)
                    break  # One match per turn is enough

    # ── Gate 14: JSON Key Artifact Detection ──────────────────────────────
    # Detect \":\" or ",\r\n  \"" fragments in content that indicate LLM treated output as JSON key-value
    for idx in [0, 2, 3, 4, 5]:  # Skip index 1 (main assistant JSON)
        if idx >= len(convs):
            continue
        conv_content = convs[idx].get("content", "")
        # Only flag if the fragment appears at suspicious positions (start of content, or around [No Thinking])
        if re.search(r'\\?"\s*:\s*\\?"\[', conv_content):
            fail("followup_quality",
                 f"Turn {idx}: JSON key artifact detected in content (LLM output formatting corruption)",
                 fixable_locally=True)
        # Also check for the specific pattern: content starts with \": \"
        if conv_content.strip().startswith('\\"') or conv_content.strip().startswith('": "'):
            fail("followup_quality",
                 f"Turn {idx}: content starts with JSON key artifact",
                 fixable_locally=True)

    # ── Gate 15: [No Thinking] Tag Leaking into Assistant Content ─────────
    # [No Thinking] is a USER-ONLY prefix. If it appears in assistant turns, it's a generation error.
    for idx in [1, 3, 5]:  # Assistant turns (0-indexed: Turn 2, Turn 4, Turn 6)
        if idx < len(convs) and convs[idx].get("role") == "assistant":
            asst_content = convs[idx].get("content", "")
            if isinstance(asst_content, str) and asst_content.strip().startswith("[No Thinking]"):
                fail("followup_quality",
                     f"Turn {idx}: assistant content starts with '[No Thinking]' — this tag is for USER turns only",
                     partial_repair=True)

    # ── Gate 16: COT Meta-Generation Detection ────────────────────────────
    # Detect if the COT/reasoning describes task generation instead of problem solving
    META_COT_PATTERNS = [
        "the request is to generate",
        "i need to generate",
        "i will structure the user turn",
        "i need to create a task",
        "the meta-strategy is",
        "the document classification is",
        "the variation schema",
        "i will generate",
        "creating a coding task",
        "to generate a multi-turn",
        "produce a dataset",
        "generate exactly 1 distinct",
    ]
    reasoning_lower = reasoning.lower()
    meta_cot_hits = []
    for pat in META_COT_PATTERNS:
        if pat in reasoning_lower:
            meta_cot_hits.append(pat)
    if len(meta_cot_hits) >= 2:  # Allow 1 borderline match, flag on 2+
        fail("thinking_quality",
             f"COT describes task generation instead of problem solving. "
             f"Meta-generation phrases found: {meta_cot_hits[:5]}",
             fixable_locally=False)

    # ── Gate 17: Raw Thinking File Integrity ──────────────────────────────
    # Check the auxiliary thinking.txt file for extraction failures or emptiness
    # Derive thinking path: Output/json/XXX.json -> Output/thinking/XXX.txt
    try:
        json_dir = os.path.dirname(os.path.abspath(filepath))
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        # Navigate from .../Output/json/ to .../Output/thinking/
        output_dir = os.path.dirname(json_dir)
        thinking_dir = os.path.join(output_dir, "thinking")
        thinking_path = os.path.join(thinking_dir, f"{base_name}.txt")

        if os.path.exists(thinking_path):
            with open(thinking_path, 'r', encoding='utf-8', errors='replace') as tf:
                raw_think = tf.read().strip()
                
            fail_markers = ["[NO_THINKING_SECTION]", "[EXTRACTION_FAILED]", "[EXTRACTION_ERROR]"]
            for marker in fail_markers:
                if marker in raw_think:
                    fail("thinking_quality", 
                         f"Internal thinking monologue extraction failed: {marker}", 
                         fixable_locally=False)
                    break
            
            # Check for effective length (excluding markers)
            if not raw_think or len(raw_think) < 100:
                 fail("thinking_quality", 
                      f"Internal thinking monologue is critically undersized ({len(raw_think)} chars)", 
                      fixable_locally=False)
        else:
            # If the thinking file is missing entirely, it's a pipeline failure
            fail("thinking_quality", "Missing auxiliary thinking.txt file", fixable_locally=False)

    except Exception as e:
        # Fallback to avoid breaking validation if filesystem permissions or paths are weird
        pass

    # Add enriched summary stats to report
    code_lines_stat = 0
    test_criteria_stat = 0
    formal_req_stat = 0
    try:
        parsed_stats = json.loads(content)
        if isinstance(parsed_stats, dict):
            code_stat = parsed_stats.get("executable_code", "")
            code_lines_stat = code_stat.count("\\n") + code_stat.count("\n") + 1
            tc = parsed_stats.get("test_criteria", [])
            test_criteria_stat = len(tc) if isinstance(tc, list) else 0
            fr = parsed_stats.get("formal_requirements", [])
            formal_req_stat = len(fr) if isinstance(fr, list) else 0
    except (json.JSONDecodeError, TypeError):
        pass

    report["stats"] = {
        "cot_chars": cot_len,
        "answer_chars": content_len,
        "code_lines": code_lines_stat,
        "test_criteria_count": test_criteria_stat,
        "formal_req_count": formal_req_stat,
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
