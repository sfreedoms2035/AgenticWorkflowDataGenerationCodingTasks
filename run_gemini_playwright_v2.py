"""
run_gemini_playwright_v2.py — Gemini Web Automation for Task Generation
========================================================================
Injects a mega-prompt (PDF text + task instructions) into Gemini via Playwright
and extracts the JSON task output + thinking trace.

Optimized for speed:
  - Zero manual intervention steps
  - Aggressive timeouts with smart fallbacks
  - Always selects Gemini Pro model
  - Validates JSON before writing

Usage:
    python run_gemini_playwright_v2.py <pdf_path> <prompt_path>

Exit codes:
    0 = Success (valid JSON extracted and saved)
    1 = Failure (extraction failed, JSON invalid, or Gemini error)
"""
import os
import sys
import json
import subprocess
import time
import re
from playwright.sync_api import sync_playwright

# Global timer
_WORKFLOW_START_TIME = time.time()


def log(msg):
    """Timestamped logging to stderr."""
    elapsed = time.time() - _WORKFLOW_START_TIME
    print(f"  [{elapsed:6.1f}s] {msg}", file=sys.stderr)


def clean_repetitive_text(text):
    """Remove verbatim repetitive paragraphs and line-level EOF loops (common in Gemini)."""
    if not text: return text
    
    # 1. Line-level deduplication for common "End of response" triggers
    lines = text.split('\n')
    cleaned_lines = []
    last_line = None
    rep_count = 0
    for l in lines:
        l_strip = l.strip()
        if l_strip == last_line and l_strip in ["[RAW-SRC] EOF", "EOF", "[RAW-SRC]"]:
            rep_count += 1
            if rep_count > 1: continue
        else:
            rep_count = 0
        last_line = l_strip
        cleaned_lines.append(l)
    text = '\n'.join(cleaned_lines)

    # 2. Paragraph-level deduplication
    paragraphs = text.split('\n\n')
    seen = set()
    cleaned = []
    for p in paragraphs:
        p_strip = p.strip()
        if not p_strip: continue
        # Hash long paragraphs to detect loops; use first 200 chars as a fuzzy signature
        p_sig = re.sub(r'\s+', '', p_strip[:200].lower())
        if p_sig in seen and len(p_strip) > 150:
            log(f"  [De-Loop] Skipping repetitive paragraph ({len(p_strip)} chars)")
            continue
        seen.add(p_sig)
        cleaned.append(p)
    return '\n\n'.join(cleaned)


def extract_semantic_blocks(text):
    """
    Extract semantic blocks using strict delimiter matching.
    Looks for blocks bounded by: !!!!!BLOCKNAME!!!!!
    Now more tolerant to spaces and optional colons inside the delimiters.
    Returns: dict mapping block name to its body.
    """
    blocks = {}
    if not text:
        return blocks
        
    pattern = r'[\\!]{3,}\s*([A-Z0-9\-_]+)\s*:?\s*[\\!]{3,}\s*(.*?)(?=[\\!]{3,}\s*[A-Z0-9\-_]+\s*:?\s*[\\!]{3,}|\s*$)'
    matches = re.finditer(pattern, text, re.DOTALL)
    
    for match in matches:
        block_name = match.group(1).strip()
        # Clean specific trailing artifacts (like extra backslashes before quotes)
        block_content = re.sub(r'\\+$', '', match.group(2).strip())
        blocks[block_name] = block_content
        log(f"Extracted block: {block_name} ({len(block_content)} chars)")
    return blocks


def clean_semantic_block(content):
    """Remove markdown code boxes and [RAW-SRC] prefixes from any block content."""
    if not content: return ""
    
    # 1. Strip backslashes from common escaped characters
    content = re.sub(r'\\([_*"\'\-`~])', r'\1', content)
    
    # 2. Remove markdown code block wrappers
    content = re.sub(r'^```[a-z]*\s*', '', content, flags=re.MULTILINE | re.IGNORECASE)
    content = re.sub(r'```\s*$', '', content, flags=re.MULTILINE)
    
    # 3. Strip [RAW-SRC] prefix from each line if present
    content = re.sub(r'^\[RAW-SRC\]\s?', '', content, flags=re.MULTILINE)
    
    return content.strip()


def clean_repetitive_text(text):
    """Remove verbatim repetitive paragraphs (common in Gemini loops)."""
    if not text: return text
    
    # Ensure delimiters form their own boundaries so we don't accidentally delete follow-up turns
    text = re.sub(r'([\\!]{3,})', r'\n\n\1', text)
    
    # Split by double newline to identify paragraphs
    paragraphs = text.split('\n\n')
    seen = set()
    cleaned = []
    for p in paragraphs:
        p_strip = p.strip()
        if not p_strip: continue
        # Hash long paragraphs to detect loops; use first 200 chars as a fuzzy signature
        p_sig = re.sub(r'\s+', '', p_strip[:200].lower())
        if p_sig in seen and len(p_strip) > 150:
            log(f"  [De-Loop] Skipping repetitive paragraph ({len(p_strip)} chars)")
            continue
        seen.add(p_sig)
        cleaned.append(p_strip)
    return '\n\n'.join(cleaned)


# ── Canvas Detection ─────────────────────────────────────────────────────────
CANVAS_DOM_SELECTORS = [
    'user-facing-canvas',
    'immersive-canvas-panel',
    'div.canvas-container',
    'code-block-canvas',
    '[data-test-id*="canvas"]',
    'div[class*="immersive"]',
]

CANVAS_TEXT_SIGNALS = [
    'canvas', 'immersive', 'open in canvas', 'in canvas öffnen',
]


def detect_canvas_active(page):
    """Return True if Gemini has activated Canvas/Immersive mode."""
    try:
        # 1. Check for Canvas DOM elements
        for sel in CANVAS_DOM_SELECTORS:
            if page.locator(sel).count() > 0:
                log(f"  [Canvas] Canvas DOM element detected: {sel}")
                return True

        # 2. Check for Canvas text signals in buttons/chips
        result = page.evaluate("""() => {
            const allText = document.body.innerText.toLowerCase();
            const signals = ['open in canvas', 'in canvas öffnen', 'immersive-canvas', 'canvas panel'];
            for (const sig of signals) {
                if (allText.includes(sig)) return sig;
            }
            // Also check for canvas-specific element attributes
            const canvasEls = document.querySelectorAll('[class*="canvas"], [data-test-id*="canvas"]');
            if (canvasEls.length > 0) return 'canvas-element-found';
            return null;
        }""")
        if result:
            log(f"  [Canvas] Canvas signal detected: {result}")
            return True
    except Exception as e:
        log(f"  [Canvas] Detection check failed (non-fatal): {e}")
    return False


def escape_canvas(page):
    """Attempt to close Canvas and return to normal chat. Returns True if successful."""
    log("  [Canvas] Attempting to escape Canvas mode...")
    try:
        # Try clicking X/close buttons on canvas panels
        close_selectors = [
            'button[aria-label*="close"]',
            'button[aria-label*="Close"]',
            'button[aria-label*="Schließen"]',
            'button[data-test-id*="close"]',
            'button[class*="close-button"]',
            'button[class*="dismiss"]',
        ]
        for sel in close_selectors:
            btn = page.locator(sel)
            if btn.count() > 0:
                try:
                    btn.first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    if not detect_canvas_active(page):
                        log("  [Canvas] Canvas closed via close button.")
                        return True
                except Exception:
                    pass

        # Fallback: navigate to a new chat
        log("  [Canvas] Close button failed — navigating to fresh chat...")
        page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        if not detect_canvas_active(page):
            log("  [Canvas] Navigated to fresh chat — Canvas cleared.")
            return True
    except Exception as e:
        log(f"  [Canvas] Escape failed: {e}")
    return False


def heuristic_extract_blocks(text):
    """Fallback extraction using keywords if !!!!! tags are missing or broken."""
    blocks = {}
    
    # Heuristic Mapping for section identification
    mappings = {
        'METADATA': [r'METADATA', r'Task Metadata', r'Task Info'],
        'REQUIREMENTS': [r'REQUIREMENTS', r'Formal Requirements', r'REQ-'],
        'ARCHITECTURE': [r'ARCHITECTURE', r'Architecture Block', r'Design Block'],
        'DATA-STREAM': [r'DATA-STREAM', r'Code Block', r'Executable Code', r'DATA-BLOCK', r'CODE'],
        'DOCUMENTATION': [r'DOCUMENTATION', r'Docs Block', r'Doc Block'],
        'USAGE-EXAMPLES': [r'USAGE', r'Usage Examples', r'Usage Block'],
        'TEST-CRITERIA': [r'TESTBENCH', r'Test-Bench', r'Mock Block', r'Test Criteria'],
    }

    # Attempt to extract turns by narrative markers if blocks are missing
    for i in range(1, 7):
        role = "USER" if i % 2 != 0 else "ASSISTANT"
        p_marker = rf'Turn {i}\s*(?:\({role}\)|- {role}|Prompt|Response)'
        # Look for these specifically in the raw text
        m = re.search(rf'(?:{p_marker}).*?\n(.*?)(?=Turn {i+1}|!!!!!|\s*$)', text, re.DOTALL | re.IGNORECASE)
        if m and m.group(1):
            block_name = f"TURN-{i}-USER" if i % 2 != 0 else f"TURN-{i}-ASSISTANT"
            blocks[block_name] = m.group(1).strip()
            log(f"  [Heuristic] Recovered {block_name}")

    # Section keyword scanner
    chunks = text.split('\n\n')
    current_block = None
    for chunk in chunks:
        found_header = False
        for block_key, patterns in mappings.items():
            for p in patterns:
                if re.search(rf'^[#\s\*]*{p}', chunk, re.IGNORECASE):
                    current_block = block_key
                    found_header = True
                    # Strip the header portion
                    content = re.sub(rf'^[#\s\*]*{p}[#\s\*:]*', '', chunk, flags=re.IGNORECASE).strip()
                    blocks[block_key] = (blocks.get(block_key, "") + "\n" + content).strip()
                    break
            if found_header: break
        
        if not found_header and current_block:
            blocks[current_block] = (blocks.get(current_block, "") + "\n" + chunk).strip()

    return blocks


def validate_and_save_json(llm_response, out_json_path, thinking_text=None):
    """Assemble the granular semantic blocks into a valid 6-turn conversational JSON."""
    try:
        import json_repair
        
        # 0. Clean repetition loops first
        llm_response = clean_repetitive_text(llm_response)
        
        # 1. Primary Regex Extraction
        blocks = extract_semantic_blocks(llm_response)
        
        # 2. Heuristic Fallback if primary extraction failed
        if not blocks or len(blocks) < 5:
            log("⚠️ Insufficient semantic blocks found. Invoking heuristic recovery...")
            h_blocks = heuristic_extract_blocks(llm_response)
            for k, v in h_blocks.items():
                if k not in blocks or len(blocks[k]) < 50:
                    blocks[k] = v
        
        if not blocks:
            log("❌ FATAL: No semantic blocks recovered even with heuristics.")
            return False

        # 1. Extraction: Metadata
        metadata_raw = clean_semantic_block(blocks.get("METADATA", "{}"))
        try:
            # metadata_raw might have underscores escaped as \_
            metadata = json_repair.loads(metadata_raw)
        except:
            metadata = {}
        
        # Ensure metadata is a dict (fix for AttributeErrors)
        if not isinstance(metadata, dict):
            metadata = {}

        # 2. Extraction: Reasoning
        # Use REASONING block first, then fallback to passed thinking_text
        reasoning_main = clean_semantic_block(blocks.get("REASONING", thinking_text or "(Missing thinking monologue)"))
        # Strip both normal and escaped think tags to prevent doubling
        reasoning_main = re.sub(r'\\?</?think\\?>', '', reasoning_main, flags=re.IGNORECASE).strip()

        # 3. Extraction: Assistant Content (Monolithic or Granular)
        # Try Monolithic first
        assistant_json_raw = clean_semantic_block(blocks.get("TURN-2-ASSISTANT-DATA", "{}"))
        try:
            mono_obj = json_repair.loads(assistant_json_raw)
        except:
            mono_obj = {}

        # Try Granular
        reqs_raw = clean_semantic_block(blocks.get("REQUIREMENTS", "[]"))
        try:
            reqs = json_repair.loads(reqs_raw)
        except:
            reqs = []
            
        test_crit_raw = clean_semantic_block(blocks.get("TEST-CRITERIA", "[]"))
        try:
            test_crit = json_repair.loads(test_crit_raw)
        except:
            test_crit = []

        # Handle fragmented code parts (Supports both DATA-STREAM-PART and legacy CODE-PART)
        all_code_parts = []
        code_keys = sorted([k for k in blocks.keys() if k.startswith("DATA-STREAM-PART-") or k.startswith("CODE-PART-")], 
                           key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
        for k in code_keys:
            all_code_parts.append(clean_semantic_block(blocks[k]))
        
        # Fallback if no parts but a "CODE" block or found inside monolithic JSON
        if not all_code_parts:
            if "CODE" in blocks:
                all_code_parts.append(clean_semantic_block(blocks["CODE"]))
            elif mono_obj.get("executable_code"):
                code = mono_obj.get("executable_code")
                all_code_parts.append("\n".join(code) if isinstance(code, list) else code)
        
        full_code = "\n\n".join(all_code_parts)

        # Merge results into final object
        assistant_content_obj = {
            "formal_requirements": reqs if reqs else mono_obj.get("formal_requirements", []),
            "architecture_block": clean_semantic_block(blocks.get("ARCHITECTURE", mono_obj.get("architecture_block", ""))),
            "executable_code": full_code,
            "documentation": clean_semantic_block(blocks.get("DOCUMENTATION", mono_obj.get("documentation", ""))),
            "usage_examples": clean_semantic_block(blocks.get("USAGE-EXAMPLES", mono_obj.get("usage_examples", ""))),
            "testbench_and_mocks": "Included in Code/Examples", 
            "test_criteria": test_crit if test_crit else mono_obj.get("test_criteria", [])
        }
        
        # 4. Clean Other Turns (also strip escaped think tags from content)
        def _strip_escaped_think(text):
            """Remove normal and escaped think tags from content."""
            text = re.sub(r'\\?</?think\\?>', '', text, flags=re.IGNORECASE).strip()
            return text
        
        turn1 = clean_semantic_block(blocks.get("TURN-1-USER", "Problem statement missing."))
        turn3 = clean_semantic_block(blocks.get("TURN-3-USER", "How does this handle edge cases?"))
        turn4 = _strip_escaped_think(clean_semantic_block(blocks.get("TURN-4-ASSISTANT", "Logic verified.")))
        turn5 = clean_semantic_block(blocks.get("TURN-5-USER", "Follow up 2?"))
        turn6 = _strip_escaped_think(clean_semantic_block(blocks.get("TURN-6-ASSISTANT", "Response 2.")))
        
        # Build 6-Turn Conversations Array
        conversations = [
            {"role": "user", "content": turn1},
            {
                "role": "assistant", 
                "reasoning": f"<think>\n{reasoning_main}\n</think>",
                "content": json.dumps(assistant_content_obj, indent=2, ensure_ascii=False)
            },
            {"role": "user", "content": turn3},
            {
                "role": "assistant",
                "reasoning": "<think></think>",
                "content": turn4
            },
            {"role": "user", "content": turn5},
            {
                "role": "assistant",
                "reasoning": "<think></think>",
                "content": turn6
            }
        ]

        final_task = metadata.copy()
        final_task["conversations"] = conversations
        if "task_type" not in final_task: final_task["task_type"] = "coding_task"
        
        data = [final_task]
        with open(out_json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        log(f"✅ Assembly Success! Saved to {os.path.basename(out_json_path)}")
        return True

    except Exception as e:
        log(f"❌ Assembling failed: {e}")
        import traceback
        log(traceback.format_exc())
        return False



def run_gemini(pdf_path, prompt_file):
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_text = f.read()

    basename = os.path.basename(prompt_file)
    core_name = basename.replace("_Prompt.txt", "").replace("_RepairPrompt.txt", "")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_json = os.path.join(script_dir, "Output", "json", f"{core_name}.json")
    out_txt = os.path.join(script_dir, "Output", "thinking", f"{core_name}.txt")

    abs_pdf_path = os.path.abspath(pdf_path)

    # --- CACHED PDF EXTRACTION ---
    cache_path = abs_pdf_path.replace(".pdf", ".txt")
    if os.path.exists(cache_path):
        log(f"Using cached text: {os.path.basename(cache_path)}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            extracted_text = f.read()
    else:
        log(f"Extracting PDF via LiteParse: {os.path.basename(abs_pdf_path)}")
        cmd = f'npx.cmd --yes @llamaindex/liteparse parse "{abs_pdf_path}" --format json -q'
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')
            if proc.returncode != 0:
                log(f"LiteParse Error: {proc.stderr}")
                return False

            pdf_data = json.loads(proc.stdout)
            extracted_text = ""
            for page in pdf_data.get('pages', []):
                extracted_text += page.get('text', '') + "\n\n"
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(extracted_text)
            log(f"Extracted {len(extracted_text)} chars, cached to .txt")
        except Exception as e:
            log(f"PDF extraction failed: {e}")
            return False

    # --- BUILD MEGA-PROMPT ---
    code_block_directive = """
---
CRITICAL OUTPUT FORMAT DIRECTIVE:
You MUST output your response using granular blocks delimited by !!!!!BLOCK-NAME!!!!! tags (e.g., !!!!!METADATA!!!!!, !!!!!REASONING!!!!!, !!!!!TURN-2-ASSISTANT-DATA!!!!!, !!!!!CODE-PART-1!!!!!).
You MAY use markdown fenced code blocks (e.g. ```json```, ```cpp```, ```python```, ```rust```) INSIDE the !!!!!BLOCK-NAME!!!!! delimiters for readability.
CRITICAL RULE: ALL code, text, and paragraphs inside every block MUST use explicit literal escaped newlines (\\n) and escaped double quotes (\\") to conform to the strict JSON specification. DO NOT use raw physical newlines inside the blocks.
IMPORTANT: Prioritize COMPLETING the entire block structure over adding more detail. A truncated response is worse than a slightly shorter but complete one.
CRITICAL AVOIDANCE: DO NOT use "Canvas" mode, "Gems", or any interactive coding interface. Output your answer purely as plain text strictly inside the standard chat window. DO NOT trigger side-by-side or interactive execution environments.
"""

    mega_prompt = f"""
# SOURCE DOCUMENT FOR ANALYSIS:
{extracted_text}

---
# INSTRUCTIONS:
{prompt_text}
{code_block_directive}
"""
    log(f"Mega-prompt assembled: {len(mega_prompt)} chars")

    # --- PLAYWRIGHT AUTOMATION ---
    log("Starting Playwright...")
    success = False

    with sync_playwright() as p:
        user_data_dir = os.path.join(os.getcwd(), ".playwright_profile")
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            permissions=["clipboard-read", "clipboard-write"]
        )

        page = browser.new_page()
        page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")

        # --- AUTO-DISMISS: Activity/Consent Pages ---
        def ensure_on_gemini():
            """Navigate to the Gemini chat page (/app), handling any redirects or wrong pages.
            Returns True when confirmed on the active chat page (has rich-textarea).
            """
            for attempt in range(5):
                page.wait_for_timeout(1500)
                current_url = page.url

                # Close non-Gemini tabs
                for tab in browser.pages:
                    if tab != page and ("myactivity" in tab.url or "consent" in tab.url or "accounts.google" in tab.url):
                        tab.close()

                # Dismiss any open context menus first (Escape key)
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                except Exception:
                    pass

                # Check if we are on the CHAT page specifically (not /search, /history, etc.)
                is_chat_page = (
                    "gemini.google.com" in current_url and
                    "/search" not in current_url and
                    "/history" not in current_url and
                    "myactivity" not in current_url and
                    "consent" not in current_url
                )

                if is_chat_page:
                    # Double-check: if rich-textarea is present, we are definitely on chat
                    try:
                        if page.locator('rich-textarea').count() > 0:
                            return True
                    except Exception:
                        pass
                    # Page looks like /app but no textarea yet — wait a bit more
                    page.wait_for_timeout(1000)
                    try:
                        if page.locator('rich-textarea').count() > 0:
                            return True
                    except Exception:
                        pass

                log(f"Not on Gemini chat (url={current_url[:70]}) — navigating to /app")
                page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

            return False

        ensure_on_gemini()

        # --- FORCE NEW CHAT TO PREVENT STATE BLEED ---
        log("Forcing 'New Chat' to guarantee clean state...")
        try:
            # Check if we're on an existing chat (URL contains /app/ followed by a chat ID)
            current_url = page.url
            import re as _re
            is_existing_chat = bool(_re.search(r'/app/[a-f0-9]{8,}', current_url))
            
            if is_existing_chat:
                log(f"  ⚠️ Landed on existing chat: {current_url[:80]}")
                
                # Try clicking 'New Chat' / 'Neuer Chat' — it's an <a> link, not a <button>
                new_chat_selectors = [
                    'a[data-test-id="new-chat-button"]',
                    'a:has-text("Neuer Chat")',
                    'a:has-text("New chat")',
                    'a[href="/app"]',
                    'button:has-text("Neuer Chat")',
                    'button:has-text("New chat")',
                ]
                clicked = False
                for sel in new_chat_selectors:
                    btn = page.locator(sel)
                    if btn.count() > 0:
                        try:
                            btn.first.click(timeout=3000)
                            page.wait_for_timeout(2000)
                            log(f"  ✅ Clicked 'New Chat' via: {sel}")
                            clicked = True
                            break
                        except Exception:
                            continue
                
                # Verify we actually moved to a clean /app — if not, force navigate
                new_url = page.url
                if _re.search(r'/app/[a-f0-9]{8,}', new_url):
                    log(f"  ⚠️ Still on old chat after click. Force-navigating to /app...")
                    page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    log(f"  ✅ Navigated to clean /app")
            else:
                log(f"  ✅ Already on clean chat: {current_url[:80]}")
        except Exception as e:
            log(f"  ⚠️ New Chat logic error: {e}. Force-navigating...")
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

        # Wait for chat input — with escalating timeouts
        chat_ready = False
        for timeout in [10000, 10000, 15000]:
            try:
                page.wait_for_selector('rich-textarea', timeout=timeout)
                chat_ready = True
                break
            except Exception:
                log(f"Chat input not found (timeout {timeout}ms), retrying...")
                ensure_on_gemini()

        if not chat_ready:
            log("FATAL: Chat input never appeared. Gemini may require manual login.")
            log("Waiting 120s for manual intervention...")
            try:
                page.wait_for_selector('rich-textarea', timeout=120000)
                chat_ready = True
            except Exception:
                log("FATAL: Gave up waiting for chat input.")
                browser.close()
                return False


        # --- ALWAYS SELECT PRO MODEL + READ ACTUAL MODEL NAME ---
        log("Selecting Gemini Pro model...")
        selected_model_name = "Gemini-3.1-pro"  # default fallback
        try:
            # Click the model dropdown
            dropdown_selectors = [
                'button[aria-label*="Model"]',
                'button[aria-label*="Modell"]',
                'button[data-test-id*="model"]',
                'button.model-selector',
                'button[class*="model"]',
            ]
            dropdown_clicked = False
            for sel in dropdown_selectors:
                dropdown = page.locator(sel)
                if dropdown.count() > 0:
                    dropdown.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    dropdown_clicked = True
                    log(f"  Dropdown opened via: {sel}")
                    break

            if dropdown_clicked:
                # Select Pro option — try multiple patterns
                pro_patterns = [
                    ('text="3.1 Pro"',      "Gemini-3.1-pro"),
                    ('span:has-text("3.1 Pro")', "Gemini-3.1-pro"),
                    ('div:has-text("3.1 Pro")',  "Gemini-3.1-pro"),
                    ('text="2.5 Pro"',      "Gemini-2.5-pro"),
                    ('span:has-text("2.5 Pro")', "Gemini-2.5-pro"),
                    ('div:has-text("2.5 Pro")',  "Gemini-2.5-pro"),
                    ('text="Pro"',          "Gemini-pro"),
                    ('span:has-text("Pro")', "Gemini-pro"),
                    ('div[role="option"]:has-text("Pro")', "Gemini-pro"),
                    ('li:has-text("Pro")',   "Gemini-pro"),
                    ('div:has-text("Pro")',  "Gemini-pro"),
                ]
                selected = False
                for ps, model_label in pro_patterns:
                    try:
                        opt = page.locator(ps).last
                        if opt.is_visible(timeout=1000):
                            # Try to capture the actual text before clicking
                            try:
                                opt_text = opt.inner_text(timeout=500).strip()
                                if opt_text:
                                    # Normalize: "Gemini 3.1 Pro" → "Gemini-3.1-pro"
                                    selected_model_name = re.sub(r'\s+', '-', opt_text.lower())
                                    selected_model_name = re.sub(r'[^a-z0-9\.\-]', '', selected_model_name)
                                    selected_model_name = "Gemini-" + selected_model_name.lstrip("gemini-") if not selected_model_name.startswith("gemini") else selected_model_name
                                    # Capitalize first letter
                                    selected_model_name = selected_model_name[0].upper() + selected_model_name[1:]
                                    log(f"  Captured model text: '{opt_text}' → normalized: '{selected_model_name}'")
                                else:
                                    selected_model_name = model_label
                            except Exception:
                                selected_model_name = model_label
                            opt.click(timeout=2000)
                            log(f"  ✅ Selected model via: {ps} → '{selected_model_name}'")
                            selected = True
                            break
                    except Exception:
                        continue

                if not selected:
                    # Try to read existing selected model from button label
                    try:
                        btn_text = page.locator(dropdown_selectors[0]).first.inner_text(timeout=500).strip()
                        if btn_text:
                            selected_model_name = re.sub(r'\s+', '-', btn_text.lower())
                            selected_model_name = selected_model_name[0].upper() + selected_model_name[1:]
                            log(f"  Read current model from button: '{selected_model_name}'")
                    except Exception:
                        pass
                    page.keyboard.press("Escape")
                    log(f"  Pro option not found in dropdown — current: '{selected_model_name}'")
            else:
                # Try to read model from label without opening dropdown
                try:
                    for sel in dropdown_selectors:
                        btn = page.locator(sel)
                        if btn.count() > 0:
                            btn_text = btn.first.inner_text(timeout=500).strip()
                            if btn_text and len(btn_text) > 2:
                                selected_model_name = re.sub(r'\s+', '-', btn_text.lower())
                                selected_model_name = selected_model_name[0].upper() + selected_model_name[1:]
                                log(f"  Read current model from button (no dropdown): '{selected_model_name}'")
                                break
                except Exception:
                    pass
                log(f"  No model dropdown found — using: '{selected_model_name}'")
        except Exception as e:
            log(f"  Model selection skipped (non-fatal): {e}")

        # Write selected model name to sidecar file so pipeline can read it
        try:
            model_sidecar = prompt_file + ".model"
            with open(model_sidecar, 'w', encoding='utf-8') as _mf:
                _mf.write(selected_model_name)
            log(f"  Model name written to sidecar: {selected_model_name}")
        except Exception as e:
            log(f"  Could not write model sidecar (non-fatal): {e}")

        page.wait_for_timeout(500)  # Brief settle

        # --- FORCE DISABLE CANVAS UI CHIPS ---
        log("Checking for Canvas suggestion chips to disable...")
        try:
            page.evaluate("""() => {
                const canvasChips = document.querySelectorAll('button, div, span, mat-chip');
                for (const el of canvasChips) {
                    if (el.innerText && el.innerText.toLowerCase().includes('canvas')) {
                        // Find any close icons/buttons inside or adjacent to the canvas chip
                        const closeBtn = el.querySelector('button, [aria-label*="close"], [aria-label*="Schließen"], [data-test-id*="close"], mat-icon, [class*="close"]');
                        if (closeBtn) {
                            closeBtn.click();
                        } else if (el.nextElementSibling && el.nextElementSibling.innerText.includes('×')) {
                            el.nextElementSibling.click();
                        } else if (el.parentElement) {
                            const parentClose = el.parentElement.querySelector('button[aria-label*="close"], button[aria-label*="Schließen"]');
                            if (parentClose) parentClose.click();
                        }
                    }
                }
            }""")
            page.wait_for_timeout(500)
        except Exception as e:
            log(f"Canvas disable check skipped: {e}")




        # --- INJECT MEGA-PROMPT ---
        log("Injecting mega-prompt...")
        try:
            # 1. Primary injection: Use Playwright's evaluate to safely pass the string and trigger React
            log("  Injecting Mega-Prompt via JS...")
            page.evaluate("""(text) => {
                const box = document.querySelector('rich-textarea p') || document.querySelector('rich-textarea div[contenteditable="true"]');
                if (box) {
                    box.innerHTML = '';  // Clear existing content
                    box.innerText = text;
                    box.dispatchEvent(new Event('input', {bubbles: true}));
                }
            }""", mega_prompt)
            page.wait_for_timeout(1000)
            
            # 2. Focus the box and type a space to natively wake up the React/Lit event listeners (fallback if dispatchEvent wasn't enough)
            prompt_box = page.locator('rich-textarea, div[contenteditable="true"], textarea').first
            prompt_box.click(timeout=5000)
            page.keyboard.press("Space")
            page.wait_for_timeout(300)
            page.keyboard.press("Backspace")
            page.wait_for_timeout(500)
            
            # 3. Send the prompt via Send button click
            prompt_sent = False
            send_btn = page.locator('button[aria-label*="Send message"], button[aria-label*="Nachricht senden"], button.send-button, [data-test-id="send-button"]')
            if send_btn.count() > 0 and send_btn.first.is_visible() and send_btn.first.is_enabled():
                try:
                    send_btn.first.click(timeout=3000)
                    log("  Clicked Send button explicitly.")
                    prompt_sent = True
                except Exception:
                    pass
            
            # 4. Fallback: If Send button click didn't work, try Enter
            if not prompt_sent:
                page.keyboard.press("Enter")
                log("  Pressed Enter to send prompt (Send button fallback).")
            
            # 5. Wait and verify the prompt was actually sent (textarea should clear)
            page.wait_for_timeout(2000)
            
            # Check if generation has started (stop button visible = prompt was sent)
            generation_started = False
            for ssel in ['button[aria-label*="Stop generating"]', 'button[aria-label*="Generierung stoppen"]']:
                try:
                    stop_btn = page.locator(ssel)
                    if stop_btn.count() > 0 and stop_btn.first.is_visible():
                        generation_started = True
                        break
                except Exception:
                    pass
            
            if not generation_started:
                # Double-check: is the textarea still full? If so, try sending again
                textarea_content = page.evaluate("""() => {
                    const box = document.querySelector('rich-textarea p') || document.querySelector('rich-textarea div[contenteditable="true"]');
                    return box ? box.innerText.trim().length : 0;
                }""")
                if textarea_content > 100:
                    log(f"  ⚠️ Textarea still has {textarea_content} chars — prompt may not have sent. Retrying Send button...")
                    if send_btn.count() > 0 and send_btn.first.is_visible():
                        send_btn.first.click(timeout=2000)
                    else:
                        page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                else:
                    log("  ✅ Textarea cleared — prompt was sent successfully.")
                
        except Exception as e:
            log(f"Primary injection failed: {e}. Trying fallback native clear+fill...")
            try:
                prompt_box = page.locator('rich-textarea, div[contenteditable="true"], textarea').first
                prompt_box.click(timeout=5000)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.wait_for_timeout(300)
                # Instead of insert_text which can be slow and buggy for 40k chars, use evaluate again
                page.evaluate("(text) => navigator.clipboard.writeText(text)", mega_prompt)
                prompt_box.click()
                page.keyboard.press("Control+V")
                page.wait_for_timeout(1000)
                page.keyboard.press("Enter")
            except Exception as e2:
                log(f"FATAL: Failed to inject prompt: {e2}")
                browser.close()
                return False

        # --- WAIT FOR GENERATION TO FINISH ---
        canvas_detected_during_gen = False

        def wait_for_completion():
            """Wait for Gemini to finish generating with Canvas detection and loop detection.
            Returns: 'DONE', 'CANVAS', 'TIMEOUT', 'WORD_SALAD'
            """
            nonlocal canvas_detected_during_gen
            log("Waiting for generation to complete (with Canvas+loop detection)...")
            finished_selectors = [
                'button[aria-label*="Good response"]',
                'button[aria-label*="Gute Antwort"]',
                'button[aria-label*="Copy answer"]',
                'button[aria-label*="Antwort kopieren"]'
            ]
            stop_selectors = [
                'button[aria-label*="Stop generating"]',
                'button[aria-label*="Generierung stoppen"]',
                'button:has(svg.stop-icon)',
                'button:has(mat-icon:has-text("stop"))'
            ]

            # Polling loop
            max_wait = 750  # 12.5 minutes (raised from 420s)
            start_wait = time.time()
            rep_check_interval = 5
            canvas_check_counter = 0

            while time.time() - start_wait < max_wait:
                # 0. Canvas check every ~30s (every 6 poll cycles)
                canvas_check_counter += 1
                if canvas_check_counter % 6 == 0:
                    if detect_canvas_active(page):
                        log("  ⚠️ CANVAS DETECTED during generation — stopping and flagging for retry.")
                        # Try to stop generation first
                        for ssel in stop_selectors:
                            stop_btn = page.locator(ssel)
                            if stop_btn.count() > 0:
                                try:
                                    stop_btn.first.click()
                                    page.wait_for_timeout(500)
                                except Exception:
                                    pass
                                break
                        canvas_detected_during_gen = True
                        return 'CANVAS'

                # 1. Check for UI completion signal
                try:
                    is_generating = False
                    for ssel in stop_selectors:
                        stop_btn = page.locator(ssel)
                        if stop_btn.count() > 0 and stop_btn.first.is_visible():
                            is_generating = True
                            break
                    
                    if not is_generating:
                        for sel in finished_selectors:
                            loc = page.locator(sel)
                            if loc.count() > 0 and loc.last.is_visible():
                                # Double-check it didn't just flicker
                                page.wait_for_timeout(2000)
                                is_gen_now = False
                                for ssel in stop_selectors:
                                    sbtn = page.locator(ssel)
                                    if sbtn.count() > 0 and sbtn.first.is_visible():
                                        is_gen_now = True
                                        break
                                if not is_gen_now:
                                    log("  ✅ Generation complete (UI signal detected)")
                                    return 'DONE'
                except Exception:
                    pass

                # 2. Check for infinite loops / word salad in DOM
                try:
                    current_text = page.evaluate("""() => {
                        const msgs = document.querySelectorAll('message-content');
                        if (msgs.length === 0) return "";
                        return msgs[msgs.length-1].innerText;
                    }""")

                    if current_text:
                        words = [w.lower() for w in re.split(r'\s+', current_text) if len(w) > 2]
                        if len(words) > 100:
                            recent_words = words[-100:]
                            unique_ratio = len(set(recent_words)) / 100

                            if unique_ratio < 0.28:
                                log(f"  ⚠️ WORD SALAD DETECTED (Diversity: {unique_ratio:.2f}). Force-stopping.")
                                for ssel in stop_selectors:
                                    stop_btn = page.locator(ssel)
                                    if stop_btn.count() > 0 and stop_btn.first.is_visible():
                                        stop_btn.first.click()
                                        log("  ✅ Clicked 'Stop generating' button.")
                                        break
                                page.wait_for_timeout(1000)
                                return 'WORD_SALAD'

                        # Exact-line repetition check
                        latest_lines = current_text.split('\n')[-20:]
                        if len(latest_lines) >= 15:
                            from collections import Counter
                            counts = Counter([l.strip() for l in latest_lines if l.strip()])
                            most_common, freq = counts.most_common(1)[0] if counts else ("", 0)
                            if freq >= 12 and (most_common in ["[RAW-SRC] EOF", "EOF"] or len(most_common) > 10):
                                log(f"  ⚠️ LOOP DETECTED on line: '{most_common}' ({freq}/20). Force-stopping.")
                                return 'WORD_SALAD'
                except Exception:
                    pass

                page.wait_for_timeout(rep_check_interval * 1000)

            log("  ⚠️ Generation timed out after 750s. Returning TIMEOUT status.")
            return 'TIMEOUT'

        gen_status = wait_for_completion()
        log(f"  Generation status: {gen_status}")

        # --- CANVAS DETECTED: escape and signal for infrastructure retry ---
        if gen_status == 'CANVAS':
            log("  [Canvas] Escaping Canvas mode and flagging infrastructure retry...")
            escape_canvas(page)
            browser.close()
            return 'CANVAS'

        # --- TIMEOUT: signal for infrastructure retry ---
        if gen_status == 'TIMEOUT':
            log("  [Timeout] Generation timed out — flagging infrastructure retry...")
            # Try to stop generation
            for ssel in [
                'button[aria-label*="Stop generating"]',
                'button[aria-label*="Generierung stoppen"]',
            ]:
                try:
                    btn = page.locator(ssel)
                    if btn.count() > 0:
                        btn.first.click()
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    pass
            browser.close()
            return 'TIMEOUT'

        # --- POST-GENERATION: Double-check Canvas hasn't activated at end ---
        page.wait_for_timeout(1000)
        if detect_canvas_active(page):
            log("  [Canvas] Canvas detected AFTER generation — escaping before extraction...")
            escape_canvas(page)
            # Wait for normal chat to settle
            page.wait_for_timeout(2000)
            if detect_canvas_active(page):
                log("  [Canvas] Canvas persists — flagging infrastructure retry.")
                browser.close()
                return 'CANVAS'

        # ── PHASE A: Extract Gemini's Internal Thinking ──
        log("Phase A: Extracting Gemini thinking...")
        gemini_thinking = ""

        try:
            think_btn_selectors = [
                'button.thoughts-header-button',
                '.thoughts-header-button',
                'button:has-text("Gedankengang anzeigen")',
                'button:has-text("Show thinking")',
                'button:has-text("Show thoughts")',
                'button:has-text("Thought for")',
                'button:has-text("Gedankengang")',
                'button:has-text("Hat ")',
                'button:has-text("nachgedacht")',
                '[role="button"]:has-text("Thought for")',
                '[role="button"]:has-text("Hat ")',
                '[role="button"]:has-text("nachgedacht")',
                'div[class*="thoughts-header"]'
            ]

            think_btn = None
            for sel in think_btn_selectors:
                btn = page.locator(sel)
                if btn.count() > 0:
                    # MUST pick the LAST button on the page (the latest message)
                    think_btn = btn.last
                    break

            if think_btn:
                think_btn.click()
                page.wait_for_timeout(1500)

                gemini_thinking = page.evaluate("""() => {
                    const selectors = [
                        '.thought-container', '.thoughts-container', '.thoughts-body',
                        '.thinking-content', 'thinking-content',
                        '[class*="thought-content"]', '[class*="thoughts-text"]',
                    ];
                    for (const sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) {
                            const el = els[els.length - 1]; // Pick the LAST one
                            if (el && el.innerText && el.innerText.trim().length > 10) {
                                return el.innerText.trim();
                            }
                        }
                    }
                    // Walk from button
                    let btns = Array.from(document.querySelectorAll('button, [role="button"]')).filter(el => {
                        const text = el.innerText || '';
                        return text.includes('Thought for') || text.includes('Hat ') || text.includes('nachgedacht') || text.includes('Gedankengang') || text.includes('Show thinking');
                    });
                    const btn = btns.length > 0 ? btns[btns.length - 1] : null;
                    if (btn) {
                        const parent = btn.closest('[class*="thought"]') || btn.parentElement;
                        if (parent) {
                            const btnText = btn.innerText || '';
                            let parentText = parent.innerText || '';
                            parentText = parentText.replace(btnText, '').trim();
                            if (parentText.length > 10) return parentText;
                        }
                        let sibling = btn.nextElementSibling;
                        while (sibling) {
                            if (sibling.innerText && sibling.innerText.trim().length > 10) {
                                return sibling.innerText.trim();
                            }
                            sibling = sibling.nextElementSibling;
                        }
                    }
                    return '';
                }""")

                if gemini_thinking:
                    # Clean up button labels
                    for label in ["Gedankengang anzeigen", "Gedankengang verbergen",
                                  "Show thinking", "Hide thinking", "Show thoughts", "Hide thoughts",
                                  "expand_more", "expand_less"]:
                        gemini_thinking = gemini_thinking.replace(label, "").strip()
                    gemini_thinking = re.sub(r'Thought for \d+ seconds?', '', gemini_thinking).strip()
                    gemini_thinking = re.sub(r'Hat \d+ Sekunden? nachgedacht', '', gemini_thinking).strip()
                    log(f"Thinking extracted: {len(gemini_thinking)} chars")
                else:
                    # Fallback: diff method
                    expanded_full = page.locator('message-content').last.inner_text() if page.locator('message-content').count() > 0 else ""
                    think_btn.click()
                    page.wait_for_timeout(800)
                    collapsed_text = page.locator('message-content').last.inner_text() if page.locator('message-content').count() > 0 else ""
                    if len(expanded_full) > len(collapsed_text) + 50:
                        gemini_thinking = expanded_full[:len(expanded_full) - len(collapsed_text)].strip()
                        log(f"Thinking extracted via diff: {len(gemini_thinking)} chars")
                    else:
                        gemini_thinking = "[EXTRACTION_FAILED]"
            else:
                    if gemini_thinking == "[NO_THINKING_SECTION]":
                        try:
                            with open(os.path.join("Output", "dump_nothinking.html"), "w", encoding="utf-8") as f:
                                f.write(page.content())
                            log("  [Dump] Saved page DOM to Output/dump_nothinking.html for inspection.")
                        except Exception:
                            pass

        except Exception as e:
            gemini_thinking = f"[EXTRACTION_ERROR] {str(e)}"
            log(f"Thinking extraction error: {e}")

        # ── PHASE B: Extract Main Response ──
        log("Phase B: Extracting main response...")

        # Collapse thinking if expanded
        try:
            for sel in ['button.thoughts-header-button', 'button:has-text("Hide")', 'button:has-text("verbergen")']:
                btn = page.locator(sel)
                if btn.count() > 0:
                    is_expanded = page.evaluate("""(selector) => {
                        const btn = document.querySelector(selector);
                        if (!btn) return false;
                        return btn.getAttribute('aria-expanded') === 'true' ||
                               btn.innerText.includes('verbergen') || btn.innerText.includes('Hide');
                    }""", sel)
                    if is_expanded:
                        btn.first.click()
                        page.wait_for_timeout(400)
                    break
        except Exception:
            pass

        full_text = ""
        try:
            # 1. Clear clipboard
            page.evaluate("navigator.clipboard.writeText('')")
            
            # 2. Try the general "Copy answer" button
            copy_selectors = [
                 'button[aria-label*="Copy answer"]',
                 'button[aria-label*="Antwort kopieren"]',
                 'button[mattooltip*="Copy answer"]',
                 'button[mattooltip*="Antwort kopieren"]',
                 'button[mattooltip*="content_copy"]',
                 'button[aria-label*="Copy text"]',
                 'button:has(mat-icon:has-text("content_copy"))'
            ]
            copy_clicked = False
            for copy_sel in copy_selectors:
                copy_btn = page.locator(copy_sel)
                if copy_btn.count() > 0:
                    # Some buttons are hidden until hovered
                    try:
                        copy_btn.last.hover(timeout=1000)
                    except Exception:
                        pass
                    copy_btn.last.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    copy_clicked = True
                    log(f"Clicked copy button: {copy_sel}")
                    break
            
            if copy_clicked:
                full_text = page.evaluate("navigator.clipboard.readText()")
                if full_text and len(full_text) > 100:
                    log(f"Clipboard extraction successful ({len(full_text)} chars)")
                else:
                    log("Clipboard extraction yielded empty/short text. Trying select-all.")
                    full_text = ""
            
            # 3. If still empty, try select-all copy inside Canvas or main text
            if not full_text:
                log("Attempting Select-All (Ctrl+A / Ctrl+C) copy...")
                canvas = page.locator('user-facing-canvas, .gemini-canvas, div[class*="canvas"]')
                if canvas.count() > 0:
                    canvas.last.click(timeout=2000)
                else:
                    msg = page.locator('message-content')
                    if msg.count() > 0:
                        msg.last.click(timeout=2000)
                
                page.keyboard.press("Control+A")
                page.wait_for_timeout(200)
                page.keyboard.press("Control+C")
                page.wait_for_timeout(500)
                
                full_text = page.evaluate("navigator.clipboard.readText()")
                if full_text and len(full_text) > 100:
                    log(f"Select-All extraction successful ({len(full_text)} chars)")
                    
                    # Unselect text safely
                    try:
                        page.mouse.click(0, 0)
                    except Exception:
                        pass
                else:
                    full_text = ""
                    
        except Exception as err:
            log(f"Clipboard extraction failed: {err}")
            full_text = ""

        # Fallback to DOM extraction if clipboard failed
        if not full_text:
            try:
                log("Falling back to DOM extraction...")
                full_text = page.evaluate("""() => {
                    let text = "";
                    let msgNodes = document.querySelectorAll('message-content');
                    if (msgNodes.length > 0) {
                        text += msgNodes[msgNodes.length - 1].innerText + "\\n";
                    }
                    let canvasNodes = document.querySelectorAll('user-facing-canvas, .gemini-canvas, div[class*="canvas"]');
                    canvasNodes.forEach(c => {
                        if (c.innerText) text += c.innerText + "\\n";
                    });
                    return text || document.body.innerText;
                }""")
            except Exception as err:
                log(f"DOM extraction failed: {err}")
                full_text = ""
        
        log(f"Final response length: {len(full_text)} chars")

        # --- SAVE FILES ---
        os.makedirs(os.path.dirname(out_json), exist_ok=True)
        os.makedirs(os.path.dirname(out_txt), exist_ok=True)

        with open(out_txt, 'w', encoding='utf-8') as f:
            f.write(gemini_thinking)

        # In the new semantic strategy, we pass the entire response (full_text) 
        # to the validator which will extract the blocks and assemble the 6-turn JSON.
        success = validate_and_save_json(full_text, out_json, gemini_thinking)

        if success:
            log(f"✅ Assembly Success: {os.path.basename(out_json)}")
        else:
            log(f"⚠️ Assembly FAILED — raw text saved for manual inspection")
            with open(out_json.replace(".json", "_raw_fail.txt"), 'w', encoding='utf-8') as f:
                f.write(full_text)

        browser.close()

    return 'OK' if success else False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python run_gemini_playwright_v2.py <pdf_path> <prompt_path>", file=sys.stderr)
        sys.exit(1)

    result = run_gemini(sys.argv[1], sys.argv[2])

    elapsed = time.time() - _WORKFLOW_START_TIME
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    log(f"TOTAL TIME: {minutes}m {seconds:.1f}s")

    # Exit codes: 0=success, 1=failure, 2=canvas, 3=timeout
    if result == 'OK':
        sys.exit(0)
    elif result == 'CANVAS':
        log("EXIT: Canvas mode detected — pipeline should infrastructure-retry")
        sys.exit(2)
    elif result == 'TIMEOUT':
        log("EXIT: Generation timed out — pipeline should infrastructure-retry")
        sys.exit(3)
    else:
        sys.exit(1)
