import torch
import json
import os
import sys
import time
from transformers import AutoTokenizer, AutoModelForCausalLM
from datasets import load_dataset
import argparse

def main():
    parser = argparse.ArgumentParser(description='Run Starcoder refactoring.')
    parser.add_argument('--device', type=str, required=True, help='Device to use, e.g., "cuda:0"')
    parser.add_argument('--start_line', type=int, required=True, help='Line number to start processing from')
    parser.add_argument('--output_file', type=str, required=True, help='Path to the output file')
    parser.add_argument('--mode', type=str, required=True, choices=['chain_of_thought', 'one_shot'], 
                        help='Mode of prompt generation: chain of thought or one-shot')

    args = parser.parse_args()

    model_id = "bigcode/starcoder2-15b"
    device = args.device
    start_line = args.start_line
    output_file_path = args.output_file
    mode = args.mode

    DEFAULT_SYSTEM_PROMPT = """You are a powerful model specialized in refactoring Java code. Code refactoring is
    the process of improving the internal structure, readability, and maintainability of a software codebase without 
    altering its external behavior or functionality."""

    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
    B_SYS, E_SYS = "<<SYS>>\n", "\n<</SYS>>\n\n"

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id).to(device)

    output_dir = os.path.dirname(output_file_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open("test_java.jsonl", "r") as test_file, open(output_file_path, "a") as results_file:
        lines = test_file.readlines()
        for i in range(start_line, len(lines)):
            data = json.loads(lines[i])
            before_code = data['before_refactoring']

            if mode == 'chain_of_thought':
                pre_prompt = f"""# Suggested refactoring types:
{data.get('suggested_refactorings', 'List of refactoring types developers performed on this commit with definitions')}

# unrefactored code snippet (java):
{before_code}

# refactored version of the same code snippet:
"""
            else:
                pre_prompt = f"""# unrefactored code snippet (java):
{before_code}

# refactored version of the same code snippet:
"""

            prompt = f"{B_SYS}{SYSTEM_PROMPT}{E_SYS}{pre_prompt}"
            print(prompt)

            tokens = tokenizer.encode(prompt, return_tensors="pt").to(device)

            torch.cuda.empty_cache()

            start_time = time.time()
            print("Generating output")
            outputs = model.generate(tokens, max_new_tokens=600, pad_token_id=tokenizer.eos_token_id, eos_token_id=tokenizer.eos_token_id)
            end_time = time.time()
            generation_time = end_time - start_time
            print(f"Generation time: {generation_time}")

            for j in range(len(outputs)):
                new_tokens = outputs[j][tokens.shape[-1]:]  # Generated tokens
                response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

                # Ensure the response does not include the prompt or repetition
                response = response.replace(prompt.strip(), "").strip()

                results = {
                    "project": data['project'],
                    "commit_sha": data['commit_sha'],
                    "file_name": data['file_name'],
                    "input": before_code,
                    "generated_response": response,
                    "generation_time": generation_time
                }
                results_file.write(json.dumps(results) + "\n")

if __name__ == "__main__":
    main()
