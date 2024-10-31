import pandas as pd
from scipy.stats import mannwhitneyu
import numpy as np

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

# Read the CSV file
csv_file = 'code_smell_type_distribution.csv'
df = pd.read_csv(csv_file)

# Filter data based on 'Project Folder'
before_df = df[df['Project Folder'] == 'before_refactoring']
llm_df = df[df['Project Folder'] == 'llm_refactoring']
developer_df = df[df['Project Folder'] == 'developer_refactoring']

# Initialize a dictionary to store the reduction distributions and arrays for reductions
reduction_distribution = {}
llm_reductions = {}
developer_reductions = {}

# Extract unique type names
type_names = df['Type Name'].unique()

# Process each type name
for type_name in type_names:
    reduction_distribution[type_name] = {}
    
    # Get code smell counts for 'before_smells'
    before_counts = before_df[before_df['Type Name'] == type_name].groupby('Code Smell')['Code Smell Count'].sum()
    
    # Get code smell counts for 'llm_smells'
    llm_counts = llm_df[llm_df['Type Name'] == type_name].groupby('Code Smell')['Code Smell Count'].sum()
    
    # Get code smell counts for 'developer_refactoring_smells'
    developer_counts = developer_df[developer_df['Type Name'] == type_name].groupby('Code Smell')['Code Smell Count'].sum()
    
    # Calculate reductions
    for code_smell in before_counts.index:
        before_count = before_counts.get(code_smell, 0)
        llm_count = llm_counts.get(code_smell, 0)
        developer_count = developer_counts.get(code_smell, 0)
        
        llm_reduction = max(0, before_count - llm_count)
        developer_reduction = max(0, before_count - developer_count)
        
        reduction_distribution[type_name][code_smell] = {
            'before_count': before_count,
            'llm_reduction': llm_reduction,
            'developer_reduction': developer_reduction
        }
        
        if code_smell not in llm_reductions:
            llm_reductions[code_smell] = []
        if code_smell not in developer_reductions:
            developer_reductions[code_smell] = []
        
        llm_reductions[code_smell].append(llm_reduction)
        developer_reductions[code_smell].append(developer_reduction)

# Prepare a list to save significant results
significant_results = []

# Perform Mann-Whitney U tests to determine if the difference between LLM and developer reductions is significant
print("\nMann-Whitney U Test Results:")
for code_smell in llm_reductions.keys():
    llm_array = llm_reductions[code_smell]
    developer_array = developer_reductions[code_smell]
    
    if len(llm_array) > 1 and len(developer_array) > 1:  # Ensure there are enough data points for the test
        u_stat, p_value = mannwhitneyu(llm_array, developer_array, alternative='two-sided')
        if p_value < 0.05:
            if np.median(llm_array) > np.median(developer_array):
                better = 'LLM'
            else:
                better = 'Developer'
            effect_size = cohen_d(llm_array, developer_array)
            delta = cliffs_delta(llm_array, developer_array)
            result = f'Code Smell: {code_smell}, P-Value: {p_value}, Better: {better}, Effect Size (Cohen\'s d): {effect_size}, Cliff\'s Delta: {delta}'
            significant_results.append(result)
            print(result)
        else:
            print(f'Code Smell: {code_smell}, Result: No significant difference')
    else:
        print(f'Code Smell: {code_smell}, Result: Not enough data points for Mann-Whitney U test')

# Save the significant results to a text file
output_file = 'significant_results.txt'
with open(output_file, 'w') as f:
    for result in significant_results:
        f.write(result + '\n')

print(f'Significant results saved to {output_file}')
