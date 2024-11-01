#!/bin/bash

# Define the paths
input_jsonl_file="$1"
rminer_home="$2"
output_dir="llm_refactoring_types"
mkdir -p "$output_dir"

# Check if input file and rminer_home are provided
if [ -z "$input_jsonl_file" ]; then
  echo "Please provide the path to the JSONL file."
  exit 1
fi

if [ -z "$rminer_home" ]; then
  echo "Please provide the path to RefactoringMiner home directory."
  exit 1
fi

# Function to extract value from JSON string
extract_json_value() {
  echo "$1" | sed -n "s/.*\"$2\": \"\([^\"]*\)\".*/\1/p"
}

# Read JSONL file line by line
while IFS= read -r line; do
  # Parse the JSON line to extract "input", "generated_response", "project", and "commit_sha"
  input_code=$(extract_json_value "$line" "input")
  generated_response=$(extract_json_value "$line" "generated_response")
  project_name=$(extract_json_value "$line" "project")
  commit_sha=$(extract_json_value "$line" "commit_sha")

  # Create a directory for the project if it doesn't exist
  project_output_dir="${output_dir}/${project_name}_${commit_sha}"
  mkdir -p "$project_output_dir"

  # Create a temporary Git repository to store the files
  repo_dir=$(mktemp -d)
  cd "$repo_dir"
  git init
  git remote add origin https://fake.url/repo.git
  echo -e "$input_code" > code.java
  git add code.java
  git commit -m "Initial commit"
  input_commit=$(git rev-parse HEAD)

  echo -e "$generated_response" > code.java
  git add code.java
  git commit -m "Refactored code"
  generated_commit=$(git rev-parse HEAD)
  cd -

  # Run RefactoringMiner with the correct arguments
  output_json_file="${project_output_dir}/$(basename "$repo_dir")_${commit_sha}.json"
  "${rminer_home}/RefactoringMiner" -bc "$repo_dir" "$input_commit" "$generated_commit" -json "$output_json_file"

  # Check if RefactoringMiner ran successfully
  if [ $? -ne 0 ]; then
    echo "RefactoringMiner failed for commit $input_commit to $generated_commit in $repo_dir."
  else
    echo "Refactoring detected and saved to $output_json_file."
  fi

  # Clean up temporary repository
  rm -rf "$repo_dir"

done < "$input_jsonl_file"

echo "Refactoring detection completed. Results are stored in the $output_dir directory."
