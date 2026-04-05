"""Batch validate all Study_European-AI-Standards_FINAL JSON files."""
import json, subprocess, os, glob

files = sorted(glob.glob("Output/json/Study_European-AI-Standards_FINAL*.json"))
print(f"Found {len(files)} files\n")
print(f"{'File':<55} {'Status':<6} {'CoT':>6} {'Ans':>7} {'Code':>5} {'Locally':>8} {'Partial':>8} {'Regen':>6}")
print("-" * 105)

failed_files = []

for fp in files:
    r = subprocess.run(["python", ".agent/scripts/validate_task.py", fp],
                       capture_output=True, text=True, encoding="utf-8")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"{os.path.basename(fp):<55} {'ERROR':<6}")
        failed_files.append((fp, "ERROR", []))
        continue
    
    status = d.get("overall_status", "?")
    stats = d.get("stats", {})
    cot = stats.get("cot_chars", "?")
    ans = stats.get("answer_chars", "?")
    code = stats.get("code_lines", "?")
    local = len(d.get("locally_fixable", []))
    partial = len(d.get("needs_partial_repair", []))
    regen = len(d.get("needs_regeneration", []))
    
    print(f"{os.path.basename(fp):<55} {status:<6} {cot:>6} {ans:>7} {code:>5} {local:>8} {partial:>8} {regen:>6}")
    
    if status == "FAIL":
        issues = []
        for x in d.get("locally_fixable", []):
            issues.append(f"  [LOCAL] {x['issue']}")
        for x in d.get("needs_partial_repair", []):
            issues.append(f"  [PARTIAL] {x['issue']}")
        for x in d.get("needs_regeneration", []):
            issues.append(f"  [REGEN] {x['issue']}")
        failed_files.append((fp, status, issues))

print(f"\n{'=' * 105}")
passed = sum(1 for fp in files if fp not in [f[0] for f in failed_files])
print(f"SUMMARY: {passed}/{len(files)} PASS, {len(failed_files)}/{len(files)} FAIL\n")

if failed_files:
    print("FAILED FILES DETAIL:")
    for fp, status, issues in failed_files:
        print(f"\n  {os.path.basename(fp)} ({status}):")
        for iss in issues:
            print(f"    {iss}")
