import os
import csv
from collections import defaultdict

CODE_SMELL_DIRECTORY = "code_smells"
OUTPUT_FILE = "code_smell_type_distribution.csv"

def count_code_smells(directory):
    overall_distribution = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    
    for project_folder in os.listdir(directory):
        project_folder_path = os.path.join(directory, project_folder)
        
        if os.path.isdir(project_folder_path):
            for sub_folder in os.listdir(project_folder_path):
                sub_folder_path = os.path.join(project_folder_path, sub_folder)
                
                if os.path.isdir(sub_folder_path):
                    design_smells_distribution = count_smells_in_file(os.path.join(sub_folder_path, 'designCodeSmells.csv'))
                    implementation_smells_distribution = count_smells_in_file(os.path.join(sub_folder_path, 'implementationCodeSmells.csv'))

                    for (type_name, code_smell), count in design_smells_distribution.items():
                        overall_distribution[project_folder][sub_folder][(type_name, code_smell)] += count
                    for (type_name, code_smell), count in implementation_smells_distribution.items():
                        overall_distribution[project_folder][sub_folder][(type_name, code_smell)] += count

    save_distribution_to_csv(overall_distribution)

def count_smells_in_file(file_path):
    smells_distribution = defaultdict(int)
    try:
        with open(file_path, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                type_name = row['Type Name']
                code_smell = row['Code Smell']
                smells_distribution[(type_name, code_smell)] += 1
    except FileNotFoundError:
        print(f"File not found: {file_path}")
    except KeyError as e:
        print(f"Missing expected column in {file_path}: {e}")
    return smells_distribution

def save_distribution_to_csv(distribution):
    with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Project Folder", "Sub Folder", "Type Name", "Code Smell", "Code Smell Count"])
        
        for project_folder, sub_folders in distribution.items():
            for sub_folder, type_smells in sub_folders.items():
                for (type_name, code_smell), count in type_smells.items():
                    writer.writerow([project_folder, sub_folder, type_name, code_smell, count])

count_code_smells(CODE_SMELL_DIRECTORY)
