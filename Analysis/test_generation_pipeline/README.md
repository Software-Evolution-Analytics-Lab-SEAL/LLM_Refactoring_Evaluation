# Test Generation Pipeline

A multi-tier test generation pipeline for semantic equivalence testing of code refactorings.

## Overview

| Tier | Strategy | Description |
|------|----------|-------------|
| 1 | Extract existing tests | Parse test files already present in the dataset |
| 2 | Double-check | Broader heuristic search on commits with zero tests |
| 3a | EvoSuite | Automated test generation with EvoSuite |
| 3b | Randoop (fallback) | Random test generation for commits where EvoSuite failed |

## Requirements

- Ubuntu (tested on Ubuntu 20.04+)
- Python 3.8+
- Java 8 JDK (for EvoSuite and Randoop)
- Maven 3.6.3 (for compilation)
- Git (for repo cloning)

## Quick Start

```bash
# 1. Setup tools (downloads JDK, Maven, EvoSuite, Randoop)
bash setup.sh

# 2. Run full pipeline
python3 run_pipeline.py --dataset ../dataset.jsonl

# 3. Run a single tier
python3 run_pipeline.py --dataset ../dataset.jsonl --tier 3

# 4. Enable verbose/debug logging
python3 run_pipeline.py --dataset ../dataset.jsonl --verbose
```

## Output

```
pipeline_results/
├── final_summary.json
├── tier1_extracted/
│   ├── extraction_results.json
│   ├── extracted_tests.json
│   └── commits_without_tests.json
├── tier2_doublecheck/
│   └── doublecheck_results.json
├── tier3_evosuite/
│   └── evosuite_results.json
└── tier3b_randoop/
    └── randoop_results.json
```

## Dataset Format

JSONL with one commit per line:

```json
{
  "project": "camel",
  "commit_sha": "abc123...",
  "files": [
    {
      "file_name": "src/main/java/Foo.java",
      "before_refactoring": "...",
      "after_refactoring": "..."
    }
  ]
}
```

## Files

- `pipeline.py` — Core implementation of all tiers
- `run_pipeline.py` — CLI orchestrator
- `setup.sh` — Tool download and setup script
