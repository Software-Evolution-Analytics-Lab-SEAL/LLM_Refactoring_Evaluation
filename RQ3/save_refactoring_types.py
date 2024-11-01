import os
import json
import csv

def extract_files_from_jsonl(jsonl_file):
    files_dict = {}
    
    with open(jsonl_file, 'r') as f:
        for line in f:
            entry = json.loads(line)
            project = entry['project']
            commit_sha = entry['commit_sha']
            file_name = entry['file_name']
            
            if project not in files_dict:
                files_dict[project] = {}
            
            if commit_sha not in files_dict[project]:
                files_dict[project][commit_sha] = []
            
            files_dict[project][commit_sha].append(file_name)
    
    return files_dict

def extract_refactoring_data(directory, files_dict):
    data = []

    for subdir, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(subdir, file)
                try:
                    with open(file_path, 'r') as f:
                        content = json.load(f)
                        for commit in content.get("commits", []):
                            project_commit = os.path.basename(subdir)
                            project_name, commit_sha = project_commit.rsplit('_', 1)
                            for refactoring in commit.get("refactorings", []):
                                refactoring_type = refactoring.get("type")
                                if refactoring_type:
                                    if project_name in files_dict and commit_sha in files_dict[project_name]:
                                        data.append({
                                            "project_name": project_name,
                                            "commit_sha": commit_sha,
                                            "files": files_dict[project_name][commit_sha],
                                            "refactoring_type": refactoring_type
                                        })
                except (json.JSONDecodeError, KeyError):
                    print(f"Skipping invalid or incomplete JSON file: {file_path}")
                    continue
    
    return data

def save_to_json(data, output_file):
    with open(output_file, 'w') as jsonfile:
        json.dump(data, jsonfile, indent=4)

def main():
    directory = "llm_refactoring_types"
    jsonl_file = "Starcoder2-Results/full_dataset0_processed.jsonl"  # replace with your actual JSONL file name
    output_file = "llm_refactoring_data.json"
    
    files_dict = extract_files_from_jsonl(jsonl_file)
    data = extract_refactoring_data(directory, files_dict)
    save_to_json(data, output_file)
    print(f"Data has been written to {output_file}")

if __name__ == "__main__":
    main()
