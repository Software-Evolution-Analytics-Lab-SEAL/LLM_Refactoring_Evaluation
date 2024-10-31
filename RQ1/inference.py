import torch
import json
import os
import time
from transformers import AutoTokenizer, AutoModelForCausalLM
import argparse

def main():
    parser = argparse.ArgumentParser(description='Run Starcoder refactoring.')
    parser.add_argument('--device', type=str, required=True, help='Device to use, e.g., "cuda:0"')
    parser.add_argument('--start_line', type=int, required=True, help='Line number to start processing from')
    parser.add_argument('--output_file', type=str, required=True, help='Path to the output file')

    args = parser.parse_args()

    model_id = "bigcode/starcoder2-15b"
    device = args.device
    start_line = args.start_line
    output_file_path = args.output_file

    DEFAULT_SYSTEM_PROMPT = """You are a powerful model specialized in refactoring Java code. Code refactoring is
    the process of improving the internal structure, readability, and maintainability of a software codebase without 
    altering its external behavior or functionality. You must output a refactored version of the code."""

    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
    B_SYS, E_SYS = "<<SYS>>\n", "\n<</SYS>>\n\n"

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id).to(device)

    output_dir = os.path.dirname(output_file_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open("sampled_dataset.jsonl", "r") as test_file, open(output_file_path, "a") as results_file:
        lines = test_file.readlines()
        for i in range(start_line, len(lines)):
            data = json.loads(lines[i])
            project = data.get('project', '')
            commit_sha = data.get('commit_sha', '')
            files = data.get('files', [])

            for file_info in files:
                file_name = file_info.get('file_name', '')
                before_code = file_info.get('before_refactoring', '')

                # Construct the prompt with the before code
                pre_prompt = f"""# unrefactored code:
{before_code}
        
# refactored version of the same code:
        """

                prompt = f"{B_SYS}{SYSTEM_PROMPT}{E_SYS}{pre_prompt}"
                print(f"Prompt for file {file_name} in commit {commit_sha}:\n{prompt}\n")

                tokens = tokenizer.encode(prompt, return_tensors="pt").to(device)

                torch.cuda.empty_cache()

                start_time = time.time()
                print("Generating output")
                outputs = model.generate(tokens, max_new_tokens=600, pad_token_id=tokenizer.eos_token_id, eos_token_id=tokenizer.eos_token_id)
                end_time = time.time()
                generation_time = end_time - start_time
                print(f"Generation time: {generation_time} seconds")

                for j in range(len(outputs)):
                    new_tokens = outputs[j][tokens.shape[-1]:]  # Generated tokens
                    response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

                    # Ensure the response does not include the prompt or repetition
                    response = response.replace(pre_prompt.strip(), "").strip()

                    results = {
                        "project": project,
                        "commit_sha": commit_sha,
                        "file_name": file_name,
                        "input": before_code,
                        "generated_response": response,
                        "generation_time": generation_time
                    }
                    results_file.write(json.dumps(results) + "\n")
                    print(f"Result for file {file_name} saved.")

if __name__ == "__main__":
    main()
