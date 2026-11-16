"""Paired analysis by question: per-question condition scores, paired differences, question-level bootstrap CIs.
Pure and seeded (random.Random(seed)), so the printed intervals are reproducible.
"""

from __future__ import annotations

import random

B_DEFAULT = 10000


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def question_scores(run_scores: dict[tuple[str, str], list[float]]) -> dict[str, dict[str, float]]:
    """{(qid, condition): [score per finished pass]} -> {qid: {condition: mean over passes}}."""
    out: dict[str, dict[str, float]] = {}
    for (qid, cond), xs in sorted(run_scores.items()):
        if xs:
            out.setdefault(qid, {})[cond] = mean(xs)
    return out


def paired(qs: dict[str, dict[str, float]], a: str, b: str, qids: list[str] | None = None) -> list[float]:
    """a - b for every question (optionally only qids) that has both, in qid order."""
    keys = sorted(qs) if qids is None else sorted(q for q in qids if q in qs)
    return [qs[q][a] - qs[q][b] for q in keys if a in qs[q] and b in qs[q]]


def bootstrap_ci(diffs: list[float], b: int = B_DEFAULT, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile CI of the mean difference, resampling questions with replacement."""
    if not diffs:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(b))
    lo = means[int((1 - level) / 2 * b)]
    hi = means[min(b - 1, int((1 + level) / 2 * b) - 1)]
    return lo, hi


def break_even(build_cost: float, per_correct_map: float, per_correct_other: float, acc_map: float) -> float | None:
    """Questions asked after which the map's cost per correct answer, its build amortized over them, drops to the
    other condition's: (build + n * cost_map) / (n * acc_map) = per_correct_other gives
    n = build / (acc_map * (per_correct_other - per_correct_map)). None when the map's answers are not cheaper
    per correct answer, or it answers nothing right (never pays)."""
    gap = per_correct_other - per_correct_map
    if gap <= 0 or acc_map <= 0:
        return None
    return build_cost / (acc_map * gap)
