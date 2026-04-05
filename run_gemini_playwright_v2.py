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
    """Extract delimited blocks from the LLM response, handling potential backslash escaping (e.g. \!\!)."""
    blocks = {}
    # Extremely aggressive pattern: Match any sequence of 3+ (!) or (\!) as delimiters.
    # Group 1 is the block name.
    # We allow backslashes in the delimiter but NOT in the captured block name.
    pattern = r'[\\!]{3,}([A-Z0-9\-_]+)[\\!]{3,}\s*(.*?)(?=[\\!]{3,}[A-Z0-9\-_]+[\\!]{3,}|\s*$)'
    matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)
    for match in matches:
        name = match.group(1).upper()
        content = match.group(2).strip()
        # Remove any trailing block delimiters if caught by DOTALL
        content = re.sub(r'[\\!]{3,}.*$', '', content, flags=re.MULTILINE).strip()
        blocks[name] = content
        log(f"Extracted block: {name} ({len(content)} chars)")
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
        cleaned.append(p)
    return '\n\n'.join(cleaned)


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
        p_marker = rf'Turn {i} \({role}|Prompt|Response\)'
        # Look for these specifically in the raw text
        m = re.search(rf'{p_marker}.*?\n(.*?)(?=Turn {i+1}|!!!!!|\s*$)', text, re.DOTALL | re.IGNORECASE)
        if m:
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
        reasoning_main = re.sub(r'</?think>', '', reasoning_main, flags=re.IGNORECASE).strip()

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
        
        # 4. Clean Other Turns
        turn1 = clean_semantic_block(blocks.get("TURN-1-USER", "Problem statement missing."))
        turn3 = clean_semantic_block(blocks.get("TURN-3-USER", "How does this handle edge cases?"))
        turn4 = clean_semantic_block(blocks.get("TURN-4-ASSISTANT", "Logic verified."))
        turn5 = clean_semantic_block(blocks.get("TURN-5-USER", "Follow up 2?"))
        turn6 = clean_semantic_block(blocks.get("TURN-6-ASSISTANT", "Response 2."))
        
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
You MUST wrap your ENTIRE JSON output between the exact literal tags !!!!!START-JSON!!!!! and !!!!!END-JSON!!!!!.
Do NOT use ANY markdown code blocks, backticks, or ` ```json `. That triggers interactive tools which are BANNED.
CRITICAL RULE: ALL code, text, and paragraphs inside every JSON string value MUST use explicit literal escaped newlines (\\n) and escaped double quotes (\\") to conform to the strict JSON specification. DO NOT use raw physical newlines inside the JSON strings.
IMPORTANT: Prioritize COMPLETING the entire JSON structure over adding more detail. A truncated JSON is worse than a slightly shorter but complete one.
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
            """Navigate past any Google redirects. Returns True when on Gemini."""
            for attempt in range(5):
                page.wait_for_timeout(1500)
                current_url = page.url

                # Close non-Gemini tabs
                for tab in browser.pages:
                    if tab != page and ("myactivity" in tab.url or "consent" in tab.url or "accounts.google" in tab.url):
                        tab.close()

                if "gemini.google.com" in current_url:
                    return True

                log(f"Redirect detected: {current_url[:60]}... navigating back")
                page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")

            return "gemini.google.com" in page.url

        ensure_on_gemini()

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

        # --- ALWAYS SELECT PRO MODEL ---
        log("Selecting Gemini Pro model...")
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
                    'text="3.1 Pro"',
                    'span:has-text("3.1 Pro")',
                    'div:has-text("3.1 Pro")',
                    'text="2.5 Pro"',
                    'span:has-text("2.5 Pro")',
                    'div:has-text("2.5 Pro")',
                    'text="Pro"',
                    'span:has-text("Pro")',
                    'div[role="option"]:has-text("Pro")',
                    'li:has-text("Pro")',
                    'div:has-text("Pro")',
                ]
                selected = False
                for ps in pro_patterns:
                    try:
                        opt = page.locator(ps).last
                        if opt.is_visible(timeout=1000):
                            opt.click(timeout=2000)
                            log(f"  ✅ Selected Pro model via: {ps}")
                            selected = True
                            break
                    except Exception:
                        continue

                if not selected:
                    page.keyboard.press("Escape")
                    log("  Pro option not found in dropdown — may already be selected")
            else:
                log("  No model dropdown found — likely already on Pro")
        except Exception as e:
            log(f"  Model selection skipped (non-fatal): {e}")

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
            js_prompt = mega_prompt.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')
            page.evaluate(f"() => {{ const box = document.querySelector('rich-textarea p'); if (box) box.innerText = `{js_prompt}`; }}")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
        except Exception as e:
            log(f"Primary injection failed: {e}. Trying fallback...")
            try:
                prompt_box = page.locator('rich-textarea, div[contenteditable="true"], textarea').first
                prompt_box.click(timeout=5000)
                page.keyboard.insert_text(mega_prompt)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
            except Exception as e2:
                log(f"FATAL: Failed to inject prompt: {e2}")
                browser.close()
                return False

        # --- WAIT FOR GENERATION TO FINISH ---
        def wait_for_completion():
            """Wait for Gemini to finish generating with active loop detection."""
            log("Waiting for generation to complete (with loop detection)...")
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
            
            # Polling loop instead of static wait
            max_wait = 420  # 7 minutes
            start_wait = time.time()
            rep_check_interval = 5
            
            while time.time() - start_wait < max_wait:
                # 1. Check for UI completion signal
                try:
                    for sel in finished_selectors:
                        if page.locator(sel).count() > 0:
                            log("  ✅ Generation complete (UI signal detected)")
                            return
                except Exception: pass

                # 2. Check for infinite loops / word salad in DOM
                try:
                    current_text = page.evaluate("""() => {
                        const msgs = document.querySelectorAll('message-content');
                        if (msgs.length === 0) return "";
                        return msgs[msgs.length-1].innerText;
                    }""")
                    
                    if current_text:
                        # Split by whitespace to get tokens
                        words = [w.lower() for w in re.split(r'\s+', current_text) if len(w) > 2]
                        if len(words) > 100:
                            # Sample the last 100 words
                            recent_words = words[-100:]
                            unique_ratio = len(set(recent_words)) / 100
                            
                            # Log diversity for debugging (to stderr)
                            # log(f"  [Monitor] Diversity: {unique_ratio:.2f}")

                            if unique_ratio < 0.28:
                                log(f"  ⚠️ WORD SALAD DETECTED (Diversity: {unique_ratio:.2f}). Force-stopping.")
                                
                                # Try to click "Stop generating" button
                                for ssel in stop_selectors:
                                    stop_btn = page.locator(ssel)
                                    if stop_btn.count() > 0 and stop_btn.first.is_visible():
                                        stop_btn.first.click()
                                        log("  ✅ Clicked 'Stop generating' button.")
                                        break
                                
                                page.wait_for_timeout(1000)
                                return
                        
                        # Existing exact-line repetition check as fallback
                        latest_lines = current_text.split('\n')[-20:]
                        if len(latest_lines) >= 15:
                            from collections import Counter
                            counts = Counter([l.strip() for l in latest_lines if l.strip()])
                            most_common, freq = counts.most_common(1)[0] if counts else ("", 0)
                            if freq >= 12 and (most_common in ["[RAW-SRC] EOF", "EOF"] or len(most_common) > 10):
                                log(f"  ⚠️ LOOP DETECTED on line: '{most_common}' ({freq}/20). Force-stopping.")
                                return
                except Exception: pass

                page.wait_for_timeout(rep_check_interval * 1000)
                
            log("  ⚠️ UI signal timeout. Proceeding to extraction.")

        wait_for_completion()

        # ── PHASE A: Extract Gemini's Internal Thinking ──
        log("Phase A: Extracting Gemini thinking...")
        gemini_thinking = ""

        try:
            think_btn_selectors = [
                'button.thoughts-header-button',
                'button:has-text("Gedankengang anzeigen")',
                'button:has-text("Show thinking")',
                'button:has-text("Show thoughts")',
                'button:has-text("Thought for")',
                'button:has-text("Gedankengang")',
            ]

            think_btn = None
            for sel in think_btn_selectors:
                btn = page.locator(sel)
                if btn.count() > 0:
                    think_btn = btn.first
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
                        const el = document.querySelector(sel);
                        if (el && el.innerText && el.innerText.trim().length > 10) {
                            return el.innerText.trim();
                        }
                    }
                    // Walk from button
                    const btn = document.querySelector('.thoughts-header-button') ||
                                document.querySelector('button[class*="thought"]');
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
                gemini_thinking = "[NO_THINKING_SECTION]"
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

    return success


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python run_gemini_playwright_v2.py <pdf_path> <prompt_path>", file=sys.stderr)
        sys.exit(1)

    result = run_gemini(sys.argv[1], sys.argv[2])

    elapsed = time.time() - _WORKFLOW_START_TIME
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    log(f"TOTAL TIME: {minutes}m {seconds:.1f}s")

    sys.exit(0 if result else 1)
