# An Empirical Study on the Code Refactoring Capability of Large Language Models

## Setup
### Prerequisites
- Python3

## RQ1
To generate refactorings, run the following code:
```
cd RQ1

python3 inference.py -start_line 1 -device cuda:0 -output_file Starcoder2-Results/full_dataset0_processed.jsonl
```

Now to extract the number of code smells, run: `get_code_smells.sh`

## RQ2
Run `python3 rq2.py`

This script collects the significant reductions in code smells by either developers or the LLM

## RQ3
Run `rminer_llms.sh 1 2` where 1 is the path to the jsonl file with LLM-generated refactorings and 2 is the path to RMiner3.0. Rminer3.0 can be found here: https://github.com/tsantalis/RefactoringMiner.

Then run `python3 save_refactoring_types.py` and `python3 save_refactoring_types_dev.py`.

Finally, run `python3 rq3.py`

## RQ4
