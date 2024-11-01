
import json
import os
import argparse

def load_original_files(input_file_path):
    original_files = set()
    with open(input_file_path, 'r') as file:
        for line in file:
            try:
                data = json.loads(line)
                project_name = data.get("project", "")
                commit_sha = data.get("commit_sha", "")
                file_name = data.get("file_name", "")
                if project_name and commit_sha and file_name:
                    original_files.add((project_name, commit_sha, file_name))
            except Exception as e:
                print(f"An error occurred while loading original files: {e}")
    return original_files

def process_jsonl(input_file_path, original_file_set, refactoring_key, output_dir):
    with open(input_file_path, 'r') as file:
        for line in file:
            try:
                data = json.loads(line)
                project_name = data.get("project", "default_project_name")
                commit_sha = data.get("commit_sha", "default_commit_sha")
                files = data.get("files", [])

                for file_data in files:
                    file_name = file_data.get("file_name", "default_name.java")
                    file_key = (project_name, commit_sha, file_name)
                    if file_key not in original_file_set:
                        continue  # Skip saving if the file is not in the original dataset

                    after_refactoring = file_data.get(f"{refactoring_key}", "")
                    
                    # Extract directory path from the file name
                    dir_structure = os.path.dirname(file_name)
                    
                    # Use the extracted project name and commit_sha in the directory path
                    after_dir_path = os.path.join(f"{output_dir}", project_name, commit_sha)
                    
                    # Ensure all intermediate directories are created
                    os.makedirs(after_dir_path, exist_ok=True)

                    # Final output file path
                    after_output_file_path = os.path.join(after_dir_path, os.path.basename(file_name))

                    # Write the after_refactoring content
                    with open(after_output_file_path, 'w') as after_file:
                        after_file.write(preprocess_generated_response(after_refactoring))

            except Exception as e:
                print(f"An error occurred: {e}")

def preprocess_generated_response(response_text):
    marker = "sion of the same code:"
    if marker in response_text:
        # Keep only the part after the marker
        return response_text.split(marker)[-1]
    else:
        # If the marker is not found, return the original text
        return response_text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process JSONL files with command line arguments.")
    parser.add_argument("input_file_path", help="Path to the StarCoder2 generated refactorings JSONL file")
    parser.add_argument("refactoring_key", help="Key to retrieve the 'after_refactoring' data")
    parser.add_argument("output_dir", help="Base directory for storing processed files")
    args = parser.parse_args()

    # Load the original file names with project and commit_sha from the JSONL
    original_file_set = load_original_files(args.input_file_path)

    # Process the JSONL with the original file set
    process_jsonl('sampled_dataset.jsonl', original_file_set, args.refactoring_key, args.output_dir)