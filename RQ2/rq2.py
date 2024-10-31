import pandas as pd
import json
import numpy as np
from scipy.stats import mannwhitneyu
import os

# Function to calculate Cohen's d for effect size
def cohen_d(x, y):
    nx = len(x)
    ny = len(y)
    dof = nx + ny - 2
    pooled_std = np.sqrt(((nx - 1) * np.std(x, ddof=1) ** 2 + (ny - 1) * np.std(y, ddof=1) ** 2) / dof)
    return (np.mean(x) - np.mean(y)) / pooled_std

# Function to calculate Cliff's Delta
def cliffs_delta(x, y):
    nx = len(x)
    ny = len(y)
    greater = 0
    less = 0
    equal = 0
    for i in x:
        for j in y:
            if i > j:
                greater += 1
            elif i < j:
                less += 1
            else:
                equal += 1
    delta = (greater - less) / (nx * ny)
    return delta

# Load the JSON files
with open('llm_refactoring_data.json', 'r') as llm_json_file:
    llm_refactoring_data = json.load(llm_json_file)

with open('dev_refactoring_data.json', 'r') as dev_json_file:
    dev_refactoring_data = json.load(dev_json_file)

# Read the CSV file
csv_file = 'code_smell_type_distribution.csv'
df = pd.read_csv(csv_file)

# Initialize dictionaries to store the refactoring types distributions
llm_refactoring_distribution = {}
developer_refactoring_distribution = {}

# Function to process refactoring data
def process_refactoring_data(refactoring_data, distribution_dict, project_folder_name):
    for entry in refactoring_data:
        project_name = entry['project_name']
        commit_sha = entry['commit_sha']
        files = entry['files']
        refactoring_type_entry = entry['refactoring_type']

        # Extract the file names in the required format
        file_names = [os.path.basename(f).replace('.java', '') for f in files]

        sub_folder = f"{project_name}_smells"
        project_data = df[(df['Sub Folder'] == sub_folder) & (df['Type Name'].isin(file_names))]

        # Debug statements to check why project_data might be empty
        if project_data.empty:
            print(f"Project Data is empty for Project: {project_name}, Sub Folder: {sub_folder}, Files: {file_names}")
        else:
            before_smells = project_data[project_data['Project Folder'] == 'before_refactoring']['Code Smell Count'].sum()
            refactored_smells = project_data[project_data['Project Folder'] == project_folder_name]['Code Smell Count'].sum()

            smell_reduction = before_smells - refactored_smells

            if refactoring_type_entry not in distribution_dict:
                distribution_dict[refactoring_type_entry] = []

            distribution_dict[refactoring_type_entry].append(smell_reduction)

# Process both LLM and developer refactoring data
process_refactoring_data(llm_refactoring_data, llm_refactoring_distribution, 'llm_refactoring')
process_refactoring_data(dev_refactoring_data, developer_refactoring_distribution, 'developer_refactoring')

# Prepare a list to save significant results
significant_results = []

# Perform Mann-Whitney U tests to determine if the difference between LLM and developer refactoring types is significant
print("\nMann-Whitney U Test Results:")
for refactoring_type in set(list(llm_refactoring_distribution.keys()) + list(developer_refactoring_distribution.keys())):
    llm_array = llm_refactoring_distribution.get(refactoring_type, [])
    developer_array = developer_refactoring_distribution.get(refactoring_type, [])
    
    if len(llm_array) > 1 and len(developer_array) > 1:  # Ensure there are enough data points for the test
        u_stat, p_value = mannwhitneyu(llm_array, developer_array, alternative='two-sided')
        if p_value < 0.05:
            better = 'LLM' if np.median(llm_array) > np.median(developer_array) else 'Developer'
            effect_size = cohen_d(llm_array, developer_array)
            delta = cliffs_delta(llm_array, developer_array)
            result = f'Refactoring Type: {refactoring_type}, P-Value: {p_value}, Better: {better}, Effect Size (Cohen\'s d): {effect_size}, Cliff\'s Delta: {delta}'
            significant_results.append(result)
            print(result)
        else:
            print(f'Refactoring Type: {refactoring_type}, Result: No significant difference')
    else:
        print(f'Refactoring Type: {refactoring_type}, Result: Not enough data points for Mann-Whitney U test')

# Save the significant results to a text file
output_file = 'significant_results_refactorings.txt'
with open(output_file, 'w') as f:
    for result in significant_results:
        f.write(result + '\n')

print(f'Significant results saved to {output_file}')
