"""
Run the golden eval set against the live orchestrator graph and print a
scorecard. Operational tool, not a pytest suite — it needs the real
dockerized stack up (Postgres/pgvector, MinIO, Redis) and makes real LLM
calls for every answer and every judge, so it costs money and takes minutes
to run. See eval/README.md and the top-level README's "Evaluation" section.

Usage:
    python -m app.evals.run
    make eval
"""
import asyncio
import logging
import sys

from app.evals.runner import run_eval
from app.evals.schemas import ScoreCard

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# Below this, treat it as a regression to investigate, not noise — tuned
# against the real baseline recorded in the README once Phase 3 first ran
# live (see that section for the actual numbers and why these thresholds
# were picked).
MIN_CORRECTNESS_RATE = 0.70
MIN_FAITHFULNESS_RATE = 0.85


def _print_scorecard(card: ScoreCard) -> None:
    print("\n" + "=" * 78)
    print(f"CogniFetch eval — {card.n_cases} cases")
    print("=" * 78)
    print(f"Retrieval:    mean precision={card.mean_precision:.2f}  mean recall={card.mean_recall:.2f}")
    print(f"Correctness:  {card.correctness_rate:.0%}")
    print(f"Faithfulness: {card.faithfulness_rate:.0%}")
    print(f"Citations:    {card.citation_accuracy_rate:.0%}  (over cases that cited anything)")
    print("-" * 78)
    print(f"{'case':<16} {'route':<24} {'P/R':<9} {'correct':<9} {'faithful':<9} {'cite'}")
    print("-" * 78)
    for r in card.case_results:
        cite = "-" if r.citation_accuracy is None else r.citation_accuracy.score
        pr = f"{r.retrieval.precision:.1f}/{r.retrieval.recall:.1f}"
        print(
            f"{r.case_id:<16} {str(r.handled_by):<24} {pr:<9} "
            f"{r.correctness.score:<9} {r.faithfulness.score:<9} {cite}"
        )
    print("-" * 78)
    print("By route:")
    for route, stats in card.by_route.items():
        print(
            f"  {route:<24} n={stats.n:<3} "
            f"correctness={stats.correctness_rate:.0%}  faithfulness={stats.faithfulness_rate:.0%}"
        )
    print("=" * 78 + "\n")


async def main() -> int:
    card = await run_eval()
    _print_scorecard(card)

    failed = card.correctness_rate < MIN_CORRECTNESS_RATE or card.faithfulness_rate < MIN_FAITHFULNESS_RATE
    if failed:
        print(
            f"FAIL: below gate (correctness>={MIN_CORRECTNESS_RATE:.0%}, "
            f"faithfulness>={MIN_FAITHFULNESS_RATE:.0%})"
        )
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
