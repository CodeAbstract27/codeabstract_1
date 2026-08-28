import json
import os
import sys

transcript_full_path = r"C:\Users\HP\.gemini\antigravity-ide\brain\a1cc8017-de0f-4ffe-810c-d5c4a4480bfc\.system_generated\logs\transcript_full.jsonl"
output_csv_path = r"c:\Users\HP\OneDrive\Desktop\Projects\IM\evaluation\datasets\humaneval_tasks.csv"

os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

with open(transcript_full_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("type") == "USER_INPUT":
            content = data.get("content", "")
            if "HumanEval/0" in content:
                # Find where the CSV begins
                idx = content.find("task_id,prompt,canonical_solution,test,entry_point")
                if idx != -1:
                    csv_text = content[idx:]
                    with open(output_csv_path, "w", encoding="utf-8") as out:
                        out.write(csv_text)
                    print(f"Successfully extracted {len(csv_text.splitlines())} lines to {output_csv_path}")
                    break
