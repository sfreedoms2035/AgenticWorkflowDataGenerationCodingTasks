"""
json_aggregator.py — Post-Processing ID Normalizer
====================================================
Scans all generated task JSON files and normalizes the training_data_id
field to follow the standard naming convention.

Usage:
    python json_aggregator.py
"""
import os
import json
import glob
from datetime import datetime
import re

# Paths relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
JSON_DIR = os.path.join(PROJECT_ROOT, "Output", "json")

# Document short code mapping
DOCS_MAP = {
    "ISO-PAS-8800": "PAS8800",
    "ISO-SAE-21434": "SAE21434",
    "ISO-21448": "SOTIF21448",
    "ISO-26262": "FUSI26262",
    "VDA_5783": "VDA5783",
    "VDA5783": "VDA5783",
}


def get_std_code(doc_name):
    """Map a document name to its standard code."""
    for key, code in DOCS_MAP.items():
        if key.lower() in doc_name.lower():
            return code
    return "UNK"


def process_and_aggregate():
    files = glob.glob(os.path.join(JSON_DIR, "*_Turn*_Task*.json"))
    date_str = datetime.now().strftime("%Y%m%d")

    for filepath in files:
        basename = os.path.basename(filepath)
        match = re.match(r'(.+)_Turn(\d+)_Task(\d+)\.json', basename)
        if not match:
            continue

        doc_name = match.group(1)
        turn_str = match.group(2)
        task_str = match.group(3)
        std_code = get_std_code(doc_name)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list) and len(data) > 0:
                task = data[0]
                expected_id = f"TD-COD-{std_code}-T{turn_str}t{task_str}-{date_str}-v1.0"

                if task.get("training_data_id") != expected_id:
                    task["training_data_id"] = expected_id
                    task["model_used_generation"] = "gemini-3.1-pro"
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                    print(f"  Updated: {basename} → {expected_id}")

        except Exception as e:
            print(f"  Error: {basename}: {e}")

    print("Aggregation complete.")


if __name__ == "__main__":
    process_and_aggregate()
