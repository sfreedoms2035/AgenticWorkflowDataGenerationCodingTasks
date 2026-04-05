"""Fix pdfs_completed in progress.json — only truly complete PDFs should be listed."""
import json

with open('Output/progress.json', 'r', encoding='utf-8') as f:
    p = json.load(f)

# Only keep truly completed PDFs (16/16 tasks passed)
p['pdfs_completed'] = ['taxonomy-based threat modeling.pdf']

with open('Output/progress.json', 'w', encoding='utf-8') as f:
    json.dump(p, f, indent=2)

print('Fixed pdfs_completed to:', p['pdfs_completed'])
print(f"Task results count: {len(p['task_results'])}")

for pdf_prefix in ['taxonomy', 'Study', 'VDA']:
    tasks = {k: v for k, v in p['task_results'].items() if k.startswith(pdf_prefix)}
    passed = sum(1 for v in tasks.values() if v['status'] == 'PASS')
    failed = sum(1 for v in tasks.values() if v['status'] == 'FAIL')
    print(f"  {pdf_prefix}: {passed} PASS, {failed} FAIL, {passed+failed} total")
