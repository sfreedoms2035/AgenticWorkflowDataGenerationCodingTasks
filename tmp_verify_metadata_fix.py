import json
import subprocess
import os

# 1. Create a task with MISSING metadata
# Filename needs to follow the pattern for context extraction
test_file = "TestDoc_Turn1_Task5.json"

test_task = [
    {
        # COMPLETELY MISSING METADATA FIELDS (except conversations)
        "conversations": [
            {
                "role": "user",
                "content": "[Thinking] Problem statement"
            },
            {
                "role": "assistant",
                "reasoning": "<think>1. Analysis</think>",
                "content": "Answer"
            }
        ]
    }
]

with open(test_file, 'w') as f:
    json.dump(test_task, f, indent=2)

print(f"🔍 Created test file {test_file} with missing metadata.")

# 2. Run Repair
print("🔧 Running auto_repair.py...")
cmd = f'python .agent/scripts/auto_repair.py {test_file}'
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

# 3. Check Result
try:
    repair_report = json.loads(result.stdout)
    print(f"Repair Status: {repair_report.get('status')}")
    print(f"Fixes Applied: {repair_report.get('fixes_applied')}")
    
    with open(test_file, 'r') as f:
        repaired_data = json.load(f)
        task = repaired_data[0]
        
        missing_still = [k for k in ["training_data_id", "document", "affected_role"] if k not in task]
        if not missing_still:
            print("\n✅ SUCCESS: Metadata was synthesized correctly!")
            print(f"   training_data_id: {task.get('training_data_id')}")
            print(f"   document: {task.get('document')}")
        else:
            print(f"\n❌ FAILURE: Missing keys still: {missing_still}")
            
except Exception as e:
    print(f"Error: {e}")
    print(result.stdout)

# Cleanup
if os.path.exists(test_file):
    os.remove(test_file)
