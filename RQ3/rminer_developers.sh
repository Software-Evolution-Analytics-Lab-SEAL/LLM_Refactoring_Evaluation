#!/bin/bash

# Define the paths
input_jsonl_file="sampled_dataset.jsonl"
rminer_home="$1"
output_dir="refactoring_types"
mkdir -p "$output_dir"

# Check if rminer_home is provided
if [ -z "$rminer_home" ]; then
  echo "Please provide the path to RefactoringMiner home directory as the first argument."
  exit 1
fi

# Function to extract value from JSON string using awk
extract_json_value() {
  echo "$1" | awk -v key="$2" '{
    n = match($0, "\""key"\": \""); 
    if (n > 0) {
      val = substr($0, n + length(key) + 4);
      m = match(val, "\"");
      print substr(val, 1, m - 1);
    }
  }'
}

# Function to extract multiline values (e.g., before_refactoring, after_refactoring)
extract_multiline_value() {
  echo "$1" | sed -n "/\"$2\": \"/,/\]/p" | sed -e "s/\"$2\": \"//" -e 's/\",$//'
}

# Function to extract the array of file objects as a string
extract_files_array() {
  echo "$1" | sed -n 's/.*"files": \[\(.*\)\].*/\1/p' | sed 's/}, {/}},{/g'
}

# Read JSONL file line by line
while IFS= read -r line; do
  # Parse the JSON line to extract "project" and "commit_sha"
  project_name=$(extract_json_value "$line" "project")
  commit_sha=$(extract_json_value "$line" "commit_sha")

  echo "Processing project: $project_name, commit: $commit_sha"

  # Create a directory for the project if it doesn't exist
  project_output_dir="${output_dir}/${project_name}_${commit_sha}"
  mkdir -p "$project_output_dir"

  # Extract and process each file in the files array
  files_array=$(extract_files_array "$line")
  IFS='},' read -ra files <<< "$files_array"
  for file in "${files[@]}"; do
    file="{${file}}"
    file_name=$(extract_json_value "$file" "file_name")
    before_refactoring=$(extract_multiline_value "$file" "before_refactoring")
    after_refactoring=$(extract_multiline_value "$file" "after_refactoring")

    echo "Processing file: $file_name"
    echo "Before refactoring: $before_refactoring"
    echo "After refactoring: $after_refactoring"

    # Check if the before and after refactoring code were correctly extracted
    if [ -z "$before_refactoring" ] || [ -z "$after_refactoring" ]; then
      echo "Error: Unable to extract refactoring code for $file_name"
      continue
    fi

    # Create a temporary Git repository to store the files
    repo_dir=$(mktemp -d)
    cd "$repo_dir"
    git init
    git remote add origin https://fake.url/repo.git
    echo -e "$before_refactoring" > "$(basename "$file_name")"
    git add "$(basename "$file_name")"
    git commit -m "Initial commit"
    input_commit=$(git rev-parse HEAD)

    echo -e "$after_refactoring" > "$(basename "$file_name")"
    git add "$(basename "$file_name")"
    git commit -m "Refactored code"
    generated_commit=$(git rev-parse HEAD)
    cd -

    # Run RefactoringMiner with the correct arguments
    output_json_file="${project_output_dir}/$(basename "$repo_dir")_${commit_sha}_$(basename "$file_name" .java).json"
    "${rminer_home}/RefactoringMiner" -bc "$repo_dir" "$input_commit" "$generated_commit" -json "$output_json_file"

    # Check if RefactoringMiner ran successfully
    if [ $? -ne 0 ]; then
      echo "RefactoringMiner failed for commit $input_commit to $generated_commit in $repo_dir."
    else
      echo "Refactoring detected and saved to $output_json_file."
    fi

    # Clean up temporary repository
    rm -rf "$repo_dir"
  done
done < "$input_jsonl_file"

echo "Refactoring detection completed. Results are stored in the $output_dir directory."
