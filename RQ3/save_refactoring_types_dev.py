import os
import json
import csv

def extract_developer_refactorings(jsonl_file):
    data = []
    
    with open(jsonl_file, 'r') as f:
        for line in f:
            entry = json.loads(line)
            project_name = entry['project']
            commit_sha = entry['commit_sha']
            refactoring_types = entry['refactoring_types']
            files = entry['files']

            # Extract refactoring types and associated file names
            for refactoring_type, count in refactoring_types.items():
                data.append({
                    "project_name": project_name,
                    "commit_sha": commit_sha,
                    "files": [file['file_name'] for file in files],
                    "refactoring_type": refactoring_type,
                    "count": count
                })
    
    return data

def save_to_json(data, output_file):
    with open(output_file, 'w') as jsonfile:
        json.dump(data, jsonfile, indent=4)

def main():
    jsonl_file = "sampled_dataset.jsonl" 
    output_file = "dev_refactoring_data.json"
    
    data = extract_developer_refactorings(jsonl_file)
    save_to_json(data, output_file)
    print(f"Data has been written to {output_file}")

if __name__ == "__main__":
    main()
