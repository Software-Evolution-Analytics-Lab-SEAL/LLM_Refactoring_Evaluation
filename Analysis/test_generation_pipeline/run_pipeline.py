#!/usr/bin/env python3
"""
run_pipeline.py - Orchestrates the full test generation pipeline across all tiers.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# pipeline.py lives in the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import (
    TestExtractionPipeline,
    DoubleCheckExtraction,
    EvoSuiteTestGenerator,
    RandoopTestGenerator,
    LLMTestGenerator,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser(
        description="Full Test Generation Pipeline (no early stopping)"
    )
    ap.add_argument("--dataset", required=True, help="Path to dataset.jsonl")
    ap.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N commits (for quick testing)"
    )
    ap.add_argument(
        "--output-dir", default="pipeline_results",
        help="Root output directory"
    )
    ap.add_argument(
        "--repos-dir", default="pipeline_results/repos",
        help="Directory for bare-cloned repos (cached)"
    )
    ap.add_argument(
        "--tier", type=int, choices=[1, 2, 3, 4], default=None,
        help="Run only a specific tier (default: all)"
    )
    ap.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose (DEBUG) logging"
    )
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("="  * 70)
    logger.info("TEST GENERATION PIPELINE")
    logger.info("="  * 70)
    logger.info("Dataset : %s", args.dataset)
    if args.limit:
        logger.info("Limit   : %d", args.limit)
    logger.info("Output  : %s", args.output_dir)
    logger.info("=" * 70)

    # Track results from each tier
    tier_results = {}

    # ------------------------------------------------------------------
    # TIER 1 – extract existing tests from dataset
    # ------------------------------------------------------------------
    if args.tier in (None, 1):
        t1_dir = f"{args.output_dir}/tier1_extracted"
        extractor = TestExtractionPipeline(output_dir=t1_dir,
                                           repos_dir=args.repos_dir)
        tier1 = extractor.process_dataset(args.dataset, limit=args.limit)
        tier_results["tier1"] = tier1

        if args.tier in (None, 2):
            t2_dir = f"{args.output_dir}/tier2_doublecheck"
            checker = DoubleCheckExtraction(output_dir=t2_dir)
            tier2 = checker.check_commits(tier1["commits_without_tests"], extractor)
            tier_results["tier2"] = tier2

    # ------------------------------------------------------------------
    # TIER 3 – Automated test generation (EvoSuite + Randoop fallback)
    # ------------------------------------------------------------------
    if args.tier in (None, 3):
        cwt_file = Path(f"{args.output_dir}/tier1_extracted/commits_without_tests.json")
        if cwt_file.exists() and args.tier is None:
            commits_needing = json.loads(cwt_file.read_text())
            logger.info("Using cached commits from tier 1: %d", len(commits_needing))
        else:
            commits_needing = []
            with open(args.dataset) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    commits_needing.append(entry)
            if args.limit:
                commits_needing = commits_needing[:args.limit]

        if commits_needing:
            t3a_dir = f"{args.output_dir}/tier3_evosuite"
            evosuite = EvoSuiteTestGenerator(output_dir=t3a_dir)
            tier3a = evosuite.process_commits(commits_needing)
            tier_results["tier3a"] = tier3a

            failed_commits = []
            for result in tier3a.get("results", []):
                if result.get("tests_generated", 0) == 0:
                    for c in commits_needing:
                        if (c["project"] == result["project"] and 
                            c["commit_sha"] == result["commit_sha"]):
                            failed_commits.append(c)
                            break

            if failed_commits:
                logger.info("EvoSuite failed on %d commits, trying Randoop...",
                           len(failed_commits))
                t3b_dir = f"{args.output_dir}/tier3b_randoop"
                randoop = RandoopTestGenerator(output_dir=t3b_dir)
                tier3b = randoop.process_commits(failed_commits)
                tier_results["tier3b"] = tier3b

    # ------------------------------------------------------------------
    # TIER 4 – LLM (placeholder)
    # ------------------------------------------------------------------
    if args.tier in (None, 4):
        logger.info("Tier 4 (LLM) not yet implemented")

    # final comprehensive report
    _report(tier_results, args.output_dir)


# ------------------------------------------------------------------
def _report(tier_results: dict, output_dir: str):
    """Generate comprehensive report of all tiers."""
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 70)

    total_tests = 0

    if "tier1" in tier_results:
        t1_tests = tier_results["tier1"]["stats"]["test_methods_extracted"]
        total_tests += t1_tests
        logger.info("  Tier 1 (Extracted)  : %6d tests", t1_tests)

    if "tier2" in tier_results:
        t2_tests = tier_results["tier2"]["stats"]["methods_recovered"]
        total_tests += t2_tests
        logger.info("  Tier 2 (Double-check): %5d tests", t2_tests)

    if "tier3a" in tier_results:
        t3a_tests = tier_results["tier3a"]["stats"]["tests_generated"]
        total_tests += t3a_tests
        logger.info("  Tier 3a (EvoSuite)  : %6d tests", t3a_tests)

    if "tier3b" in tier_results:
        t3b_tests = tier_results["tier3b"]["stats"]["tests_generated"]
        total_tests += t3b_tests
        logger.info("  Tier 3b (Randoop)   : %6d tests", t3b_tests)

    logger.info("  TOTAL               : %6d tests", total_tests)
    logger.info("=" * 70)

    # Save summary
    summary = {
        "total_tests": total_tests,
        "tier_summaries": {
            name: {
                "stats": tier_results[name].get("stats", {}),
                "results_count": len(tier_results[name].get("results", []))
            }
            for name in tier_results
        }
    }
    summary_path = Path(output_dir) / "final_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    logger.info("\nSummary saved to: %s", summary_path)


if __name__ == "__main__":
    main()
