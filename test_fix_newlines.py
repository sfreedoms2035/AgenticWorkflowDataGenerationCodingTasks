import re
import json_repair

def escape_physical_newlines_in_strings(json_str):
    in_string = False
    escape_next = False
    result = []
    
    for char in json_str:
        if escape_next:
            result.append(char)
            escape_next = False
            continue
            
        if char == '\\':
            result.append(char)
            escape_next = True
            continue
            
        if char == '"':
            in_string = not in_string
            result.append(char)
            continue
            
        if char == '\n':
            if in_string:
                result.append('\\n')
            else:
                result.append(char)
        elif char == '\r':
            if in_string:
                pass
            else:
                result.append(char)
        else:
            result.append(char)
            
    return "".join(result)

bad_json = """[
  {
    "role": "assistant",
    "reasoning": "<think>
1. Initial Query
The user wants something.
Deliverables: a thing
Constraints: none
</think>",
    "content": "Here is the code."
  }
]"""

print("Original:")
print(bad_json)

fixed = escape_physical_newlines_in_strings(bad_json)
print("\nFixed:")
print(fixed)

parsed = json_repair.loads(fixed)
print("\nParsed (after fix):")
print(parsed)

parsed_bad = json_repair.loads(bad_json)
print("\nParsed (without fix):")
print(parsed_bad)
