"""
partial_repair.py — Targeted Follow-Up Turn Repair Engine
==========================================================
When validation detects that only the follow-up turns (indices 2-5) are
broken (instruction echoes, empty content, placeholder text), this script
generates a focused re-prompt for Gemini and patches the results back
into the existing JSON — preserving the valid Turn 1 Q&A.

Two modes:
  1. --build-prompt <json_path>  → Outputs a repair prompt to stdout
  2. --patch <json_path> <gemini_response_path> → Patches follow-ups into JSON

Usage:
    python partial_repair.py --build-prompt Output/json/Task.json > repair_prompt.txt
    python partial_repair.py --patch Output/json/Task.json Output/followup_response.txt
"""
import sys
import json
import re
import os


def log(msg):
    """Print to stderr to keep stdout clean."""
    print(msg, file=sys.stderr)


def extract_code_context(task):
    """Extract key code context from the main assistant answer for the repair prompt."""
    convs = task.get("conversations", [])
    if len(convs) < 2:
        return "", [], [], ""

    # Turn 1 user question
    turn1_content = convs[0].get("content", "")
    # Truncate to first 500 chars for context
    turn1_summary = turn1_content[:500]
    if len(turn1_content) > 500:
        turn1_summary += "..."

    # Main assistant answer
    main_content = convs[1].get("content", "")
    
    # Try to parse as JSON to extract structure
    req_ids = []
    class_names = []
    arch_summary = ""
    
    try:
        parsed = json.loads(main_content)
        if isinstance(parsed, dict):
            # Extract requirement IDs
            reqs = parsed.get("formal_requirements", [])
            if isinstance(reqs, list):
                for r in reqs:
                    if isinstance(r, dict):
                        rid = r.get("req_id", "")
                        desc = r.get("description", "")
                        if rid:
                            req_ids.append(f"{rid}: {desc[:80]}")

            # Extract class/function names from code
            code = parsed.get("executable_code", "")
            if code:
                # Find class definitions
                class_names = re.findall(r'class\s+(\w+)', code)
                # Find function definitions  
                func_names = re.findall(r'def\s+(\w+)', code)
                class_names = list(set(class_names + func_names))[:15]  # Cap at 15

            # Architecture summary (first 300 chars)
            arch = parsed.get("architecture_block", "")
            if arch:
                arch_summary = arch[:300]
                if len(arch) > 300:
                    arch_summary += "..."
    except (json.JSONDecodeError, TypeError):
        # Content is not JSON — try parsing as raw text
        class_names = re.findall(r'class\s+(\w+)', main_content)[:10]

    return turn1_summary, req_ids, class_names, arch_summary


def build_repair_prompt(json_path):
    """Build a focused prompt asking Gemini to generate only follow-up turns."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        log("ERROR: Invalid JSON structure")
        return ""

    task = data[0]
    turn1_summary, req_ids, class_names, arch_summary = extract_code_context(task)

    reqs_text = "\n".join(f"  - {r}" for r in req_ids) if req_ids else "  (requirements not extracted)"
    classes_text = ", ".join(class_names[:10]) if class_names else "(classes not extracted)"
    arch_text = arch_summary if arch_summary else "(architecture not extracted)"

    prompt = f"""TARGETED FOLLOW-UP GENERATION TASK

You previously generated an excellent coding task. The main answer (code, architecture, requirements) was validated and passed quality checks. However, the follow-up conversation turns were NOT generated correctly — they contained template instructions instead of actual technical content.

Your job: Generate ONLY the 4 follow-up conversation turns (2 user questions + 2 assistant answers) based on the code context below.

--- CONTEXT: THE USER'S ORIGINAL QUESTION ---
{turn1_summary}

--- CONTEXT: YOUR CODE ANSWER (key sections) ---
Formal Requirements:
{reqs_text}

Architecture Summary:
{arch_text}

Key Classes/Functions: {classes_text}

--- YOUR TASK: GENERATE EXACTLY 4 TURNS ---

Format your output using these exact block delimiters:

!!!!!TURN-3-USER!!!!!
[No Thinking] <Your 2-3 sentence technical inquiry here. MUST reference a specific class, variable, or algorithm from the code above. Minimum 100 characters of dense technical depth. Do NOT echo instructions — write actual technical questions.>

!!!!!TURN-4-ASSISTANT!!!!!
<Your detailed technical response here. 500+ characters. Address the specific question with engineering substance. Reference concrete implementation details from the code.>

!!!!!TURN-5-USER!!!!!
[No Thinking] <Another 2-3 sentence technical inquiry pushing the architecture further. MUST reference a different class or algorithm than Turn 3. Minimum 100 characters.>

!!!!!TURN-6-ASSISTANT!!!!!
<Your final detailed technical response. 500+ characters. Provide concrete engineering analysis with specific code-level details.>

CRITICAL RULES:
1. Reference SPECIFIC class names, functions, or variables from the code: {classes_text}
2. NO placeholders, NO prompt echoing, NO meta-commentary
3. Do NOT repeat these instructions — generate ACTUAL content
4. Each user question MUST be at least 100 characters of pure technical depth
5. Each assistant answer MUST be at least 500 characters of engineering substance
6. BANNED: "the document says", "as per the provided text", "source material", "this task"
7. Do NOT output backticks, Canvas, or side panels — raw text only
"""
    return prompt


def patch_followups(json_path, response_text):
    """Parse Gemini's follow-up response and patch it into the existing JSON."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list) or len(data) == 0:
        log("ERROR: Invalid JSON structure")
        return False

    task = data[0]
    convs = task.get("conversations", [])

    if len(convs) < 6:
        log("ERROR: Task has fewer than 6 turns — cannot patch")
        return False

    # Extract blocks from response
    block_pattern = r'[\\!]{3,}([A-Z0-9\-_]+)[\\!]{3,}\s*(.*?)(?=[\\!]{3,}[A-Z0-9\-_]+[\\!]{3,}|\s*$)'
    matches = re.finditer(block_pattern, response_text, re.DOTALL | re.IGNORECASE)
    
    blocks = {}
    for match in matches:
        name = match.group(1).upper()
        content = match.group(2).strip()
        # Clean any trailing delimiters
        content = re.sub(r'[\\!]{3,}.*$', '', content, flags=re.MULTILINE).strip()
        blocks[name] = content
        log(f"  Extracted repair block: {name} ({len(content)} chars)")

    # Fallback: try simpler patterns if no blocks found
    if not blocks:
        log("  Trying simpler extraction patterns...")
        simple_patterns = {
            "TURN-3-USER": r'TURN.?3.?USER[:\s]*(.*?)(?=TURN.?4|$)',
            "TURN-4-ASSISTANT": r'TURN.?4.?ASSISTANT[:\s]*(.*?)(?=TURN.?5|$)',
            "TURN-5-USER": r'TURN.?5.?USER[:\s]*(.*?)(?=TURN.?6|$)',
            "TURN-6-ASSISTANT": r'TURN.?6.?ASSISTANT[:\s]*(.*?)$',
        }
        for key, pattern in simple_patterns.items():
            m = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
            if m:
                blocks[key] = m.group(1).strip()

    if not blocks:
        log("ERROR: Could not extract any follow-up blocks from Gemini response")
        return False

    # Patch the follow-up turns
    patched = False
    
    turn3_content = blocks.get("TURN-3-USER", "")
    if turn3_content and len(turn3_content) > 50:
        # Ensure [No Thinking] prefix
        if not turn3_content.startswith("[No Thinking]"):
            turn3_content = "[No Thinking] " + turn3_content
        convs[2]["content"] = turn3_content
        patched = True
        log(f"  Patched Turn 3 (user): {len(turn3_content)} chars")

    turn4_content = blocks.get("TURN-4-ASSISTANT", "")
    if turn4_content and len(turn4_content) > 50:
        convs[3]["content"] = turn4_content
        convs[3]["reasoning"] = "<think></think>"
        patched = True
        log(f"  Patched Turn 4 (assistant): {len(turn4_content)} chars")

    turn5_content = blocks.get("TURN-5-USER", "")
    if turn5_content and len(turn5_content) > 50:
        if not turn5_content.startswith("[No Thinking]"):
            turn5_content = "[No Thinking] " + turn5_content
        convs[4]["content"] = turn5_content
        patched = True
        log(f"  Patched Turn 5 (user): {len(turn5_content)} chars")

    turn6_content = blocks.get("TURN-6-ASSISTANT", "")
    if turn6_content and len(turn6_content) > 50:
        convs[5]["content"] = turn6_content
        convs[5]["reasoning"] = "<think></think>"
        patched = True
        log(f"  Patched Turn 6 (assistant): {len(turn6_content)} chars")

    if patched:
        task["conversations"] = convs
        data[0] = task
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        log(f"  ✅ Patched follow-up turns in {os.path.basename(json_path)}")
        return True
    else:
        log("  ❌ No follow-up blocks found to patch")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        log("Usage:")
        log("  python partial_repair.py --build-prompt <json_path>")
        log("  python partial_repair.py --patch <json_path> <response_path>")
        sys.exit(1)

    mode = sys.argv[1]
    json_path = sys.argv[2]

    if mode == "--build-prompt":
        prompt = build_repair_prompt(json_path)
        print(prompt)  # stdout for piping
    elif mode == "--patch":
        if len(sys.argv) < 4:
            log("ERROR: --patch requires <json_path> <response_path>")
            sys.exit(1)
        response_path = sys.argv[3]
        with open(response_path, 'r', encoding='utf-8') as f:
            response_text = f.read()
        success = patch_followups(json_path, response_text)
        result = {"status": "PATCHED" if success else "FAILED"}
        print(json.dumps(result, indent=2))
        sys.exit(0 if success else 1)
    else:
        log(f"Unknown mode: {mode}")
        sys.exit(1)
"""
"""
