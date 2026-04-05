import json
import subprocess
import os

# 1. Create a "Word Salad" JSON task
test_task = [
    {
        "training_data_id": "TD-TEST",
        "prompt_version": "v1.0",
        "model_used_generation": "gemini-pro",
        "knowledge_source_date": "2024-03-30",
        "document": "Test PDF",
        "task_type": "coding_task",
        "affected_role": "Engineer",
        "date_of_generation": "2024-03-30",
        "key_words": ["test"],
        "summary": "Testing padding detection",
        "difficulty": "95",
        "evaluation_criteria": ["Criteria 1"],
        "conversations": [
            {
                "role": "user",
                "content": "[Thinking] Real problem statement here."
            },
            {
                "role": "assistant",
                "reasoning": "<think>1. Analysis... conceptual visualization visualized difficulty derivation derived difficulty criteria complexity visual visualization visualization visualized. derived difficulty criteria difficulty difficulty derivation derived difficulty criteria visualization visualize virtualized. derived complexity derivation difficulty derivation difficulty criteria visualization visualize visualizations visualize visualizing visualizations visualize visualize visualized.</think>",
                "content": json.dumps({
                    "formal_requirements": [{"req_id": "REQ-1", "description": "D1", "pass_criteria": "P1"}],
                    "architecture_block": "Diagram",
                    "executable_code": "// Copyright by 4QDR.AI\nvoid test() {}",
                    "documentation": "Doc",
                    "usage_examples": "Usage",
                    "testbench_and_mocks": "Testbench",
                    "test_criteria": ["T1", "T2", "T3", "T4", "T5"]
                })
            },
            {
                "role": "user",
                "content": "[No Thinking] conceptual visualization visualized difficulty derivation derived difficulty criteria complexity visual visualization visualization visualized. derived difficulty criteria difficulty difficulty derivation derived difficulty criteria visualization visualize virtualized."
            },
            {
                "role": "assistant",
                "reasoning": "<think></think>",
                "content": "Answer"
            },
            {
                "role": "user",
                "content": "[No Thinking] Real follow up question here about the memory safety of the ring buffer and how it handles concurrency."
            },
            {
                "role": "assistant",
                "reasoning": "<think></think>",
                "content": "Answer 2"
            }
        ]
    }
]

test_file = "tmp_word_salad_test.json"
with open(test_file, 'w') as f:
    json.dump(test_task, f, indent=2)

# 2. Run validator
print("\n🔍 Running Validator on Word Salad Task...")
cmd = f'python .agent/scripts/validate_task.py {test_file}'
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

try:
    report = json.loads(result.stdout)
    status = report.get("overall_status")
    violations = report.get("metrics", {}).get("richness_and_complexity", {}).get("violations", [])
    
    print(f"Status: {status}")
    print("Violations detected:")
    for v in violations:
        print(f"  - {v}")
    
    if "keyword-salad" in str(violations) or "cluster of padding" in str(violations):
        print("\n✅ SUCCESS: Validator correctly identified the word salad padding!")
    else:
        print("\n❌ FAILURE: Validator missed the word salad padding.")
except Exception as e:
    print(f"Error parsing validator output: {e}")
    print(result.stdout)

# Cleanup
if os.path.exists(test_file):
    os.remove(test_file)
