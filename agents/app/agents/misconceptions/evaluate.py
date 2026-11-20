"""Repeatable evaluation on synthetic questions only; never reads the chat database.

From agents/: uv run python -m app.agents.misconceptions.evaluate [--offline] [--baseline]
The baseline flag explicitly enables a cloud call using synthetic data.
"""
import argparse
import json
from itertools import combinations
from time import perf_counter

from app.shared.tracing import agent_trace
from .pipeline import cluster, record_metrics

QUESTIONS = [
    {"id": 1, "text": "I think mitosis makes four cells with half the chromosomes. Is that correct?"},
    {"id": 2, "text": "Meiosis makes two identical body cells, right?"},
    {"id": 3, "text": "Plants only do photosynthesis and never cellular respiration, right?"},
    {"id": 4, "text": "Do plants stop needing cellular respiration because they photosynthesize?"},
    {"id": 5, "text": "For fractions, is 1/2 plus 1/3 equal to 2/5?"},
    {"id": 6, "text": "When adding fractions I add the denominators together. Is that right?"},
]
EXPECTED = [{1, 2}, {3, 4}, {5, 6}]


def pair_scores(groups: list[dict]) -> dict:
    expected = {pair for group in EXPECTED for pair in combinations(sorted(group), 2)}
    predicted = {pair for group in groups for pair in combinations(sorted(set(group["question_ids"])), 2)}
    correct = len(expected & predicted)
    precision = correct / len(predicted) if predicted else 0.0
    recall = correct / len(expected)
    return {"pair_precision": round(precision, 3), "pair_recall": round(recall, 3),
            "pair_f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Check the fixture/scorer without model calls.")
    parser.add_argument("--baseline", action="store_true", help="Also send synthetic questions to the configured Haiku baseline.")
    args = parser.parse_args()
    if args.offline and args.baseline:
        parser.error("Choose offline or a live baseline comparison, not both.")
    results = []
    for role in (["local", "baseline"] if args.baseline else ["local"]):
        started = perf_counter()
        groups = cluster(QUESTIONS, offline=args.offline, role=role)
        metrics = {"evaluation": "synthetic-misconceptions-v1", "role": role, "offline": args.offline,
                   "latency_seconds": round(perf_counter() - started, 3), **pair_scores(groups),
                   "provider_cost_usd": 0 if role == "local" else None}
        with agent_trace("misconceptions"):
            record_metrics(metrics)
        results.append({**metrics, "clusters": groups})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
