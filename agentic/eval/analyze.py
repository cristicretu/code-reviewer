"""Analyze agent traces and compute operational metrics.

Parses the agent trace output from run_agent_eval.py and computes:
  - Step efficiency: steps used vs. max allowed
  - Task completion rate: did the agent reach a verdict?
  - Verdict distribution
  - Comment statistics

Usage:
    python -m agentic.eval.analyze --trace outputs/eval/agent_trace.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_trace(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def analyze(trace: dict) -> dict:
    runs = trace.get("runs", [])
    config = trace.get("config", {})
    max_steps = config.get("max_steps", 20)
    n = len(runs)

    if n == 0:
        return {"error": "No runs in trace", "n_examples": 0}

    verdicts: dict[str, int] = {}
    total_comments = 0
    total_time = 0.0
    task_completed = 0

    for run in runs:
        v = run.get("verdict")
        if v:
            verdicts[v] = verdicts.get(v, 0) + 1
            task_completed += 1
        total_comments += run.get("n_comments", 0)
        total_time += run.get("elapsed_seconds", 0)

    return {
        "n_examples": n,
        "max_steps": max_steps,
        "task_completion_rate": round(task_completed / n, 3) if n else 0,
        "n_completed": task_completed,
        "verdict_distribution": verdicts,
        "avg_comments": round(total_comments / n, 2) if n else 0,
        "total_comments": total_comments,
        "avg_time_seconds": round(total_time / n, 1) if n else 0,
        "total_time_seconds": round(total_time, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent trace analysis")
    parser.add_argument("--trace", type=Path, default=Path("outputs/eval/agent_trace.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/eval/agent_analysis.json"))
    args = parser.parse_args()

    if not args.trace.exists():
        print(f"ERROR: Trace file not found at {args.trace}")
        print("Run agentic/eval/run_agent_eval.py first.")
        return 1

    trace = load_trace(args.trace)
    analysis = analyze(trace)

    print(f"{'='*50}")
    print("AGENT OPERATIONAL ANALYSIS")
    print(f"{'='*50}")
    print(f"  Examples evaluated:   {analysis['n_examples']}")
    print(f"  Task completion rate: {analysis['task_completion_rate']:.1%} ({analysis['n_completed']}/{analysis['n_examples']})")
    print(f"  Avg comments per PR:  {analysis['avg_comments']}")
    print(f"  Avg time per PR:      {analysis['avg_time_seconds']}s")
    print(f"  Verdict distribution: {analysis['verdict_distribution']}")
    print(f"  Max agent steps:      {analysis['max_steps']}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"\nSaved to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
