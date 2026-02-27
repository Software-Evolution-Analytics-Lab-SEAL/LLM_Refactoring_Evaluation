# An Empirical Study on the Code Refactoring Capability of Large Language Models


## Prerequisites
We tested on Python 3.10 with a CUDA-enabled GPU for faster inference.

### Models
We used the following LLMs from HuggingFace to perform refactoring generation:
- StarCoder2-15B-Instruct (https://huggingface.co/bigcode/starcoder2-15b-instruct-v0.1)
- Llama-3-8B-Instruct (https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct)

We also use the GPT-4o API from OpenAI (https://platform.openai.com/docs/models/gpt-4o)


## RQ1
To generate refactorings, run the following code:
```
cd RQ1

python3 inference.py -start_line 1 -device cuda:0 -output_file Starcoder2-Results/full_dataset0_processed.jsonl
```

Now to extract the number of code smells, run: `get_code_smells.sh`

### Data Leakage Analysis
To replicate the data leakage analysis on the five Apache projects contained in StarCoder2's training data, use the same RQ1 analysis pipeline on the projects listed in `data_leakage_subset.txt`.

## RQ2
Run `python3 rq2.py`

This script collects the significant reductions in code smells by either developers or the LLM

## RQ3
Run `rminer_llms.sh 1 2` where 1 is the path to the jsonl file with LLM-generated refactorings and 2 is the path to RMiner3.0. Rminer3.0 can be found here: https://github.com/tsantalis/RefactoringMiner.

Then run `python3 save_refactoring_types.py` and `python3 save_refactoring_types_dev.py`.

Finally, run `python3 rq3.py`

### Refactoring Types
The analysis covers all 102 refactoring types detectable by RMiner3.0. See `RQ3/rminer3_refactoring_types.txt` for the complete list of refactoring types.

## RQ4
Run `python3 inference_prompt_engineering.py python3 inference.py -start_line 1 -device {device} -output_file {output_file} -mode {chain_of_thought} or {one_shot}`
