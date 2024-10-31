## Setup
### Prerequisites
- Python3
- Pip

### Install Dependencies
```
pip install -r  requirements.txt
```

## Usage
To collect the dataset, run:
`collect_refactorings.sh`

## RQ1
To generate refactorings and collect code smells, run the following code:
```
cd RQ1

python3 inference.py
```

Now to extract the number of code smells, run: `extract_code_smells.sh`


### Note
Depending on the size of the test.jsonl file, inference.py could take several days to weeks, and the dataset will take up a lot of space. We include our code smell metrics in the RQ1 folder under code_smells.

## RQ2
The script we use for fine-tuning is given in RQ2: `fine_tuning.ipynb`

Adjust the output directory to where the model checkpoints will be saved.

## RQ3
To generate refactorings with the fine-tuned model, first, adjust the fine-tuned model path at the beginning of `inference_finetuned.py`, then run.

## RQ4
