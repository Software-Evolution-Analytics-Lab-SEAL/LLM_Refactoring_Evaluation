#!/bin/bash

# Run the extraction commands
echo "Running extraction commands..."
python3 extract_project_code.py Starcoder2-Results/full_dataset0_processed.jsonl after_refactoring developer_refactoring
python3 extract_project_code.py Starcoder2-Results/full_dataset0_processed.jsonl before_refactoring before_refactoring
python3 extract_project_code.py Starcoder2-Results/full_dataset0_processed.jsonl generated_response llm_refactoring

# Run the Designite analysis for each directory
echo "Running Designite analysis..."
bash run_designite.sh ./before_refactoring
bash run_designite.sh ./developer_refactoring
bash run_designite.sh ./llm_refactoring

# Run the code smell counting script
echo "Counting smell types..."
python3 count_smell_types.py

echo "All tasks completed."
