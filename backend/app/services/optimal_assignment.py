from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

import numpy as np
from scipy.optimize import linear_sum_assignment

RowT = TypeVar("RowT")
ColT = TypeVar("ColT")


@dataclass
class Assignment(Generic[RowT, ColT]):
    row: RowT
    col: ColT
    score: float


def solve_optimal_assignment(
    rows: list[RowT],
    cols: list[ColT],
    score_fn: Callable[[RowT, ColT], float],
    *,
    min_score: float,
) -> list[Assignment[RowT, ColT]]:
    """Globally-optimal one-to-one assignment maximizing total score (Hungarian
    algorithm via scipy.optimize.linear_sum_assignment) - replaces the "sort all pairs
    by score, greedily claim" pattern used throughout word_import_service.py. That
    greedy approach is a good approximation but not provably optimal: a row can lock in
    a locally-attractive match that blocks a globally better solution (e.g. row A's best
    match is X at 0.9, but X is also row B's ONLY plausible match at 0.95, while A's
    second-best Y scores 0.85 - greedy gives A=X (0.9), stranding B; the optimal
    assignment gives B=X, A=Y for a higher total of 1.80).

    `min_score` is applied as a post-filter, not baked into the matrix:
    linear_sum_assignment on a rectangular cost matrix ALWAYS returns exactly
    min(len(rows), len(cols)) pairs, no matter how bad they are - it has no built-in
    concept of "leave this row unmatched". Every returned pair is checked against
    min_score here and dropped if it doesn't clear it, so a small side is never forced
    into a nonsensical pairing just to fully saturate the larger side. A dropped pair
    does NOT free its row/column for a second attempt in this call - this is a single-
    shot optimal matching, not iterative rematching, mirroring today's greedy behavior
    where a below-threshold row also just stays unmatched with no retry.

    Builds a dense O(rows*cols) score matrix - fine at hocX's scale (rosters/event
    lists of tens to low hundreds); revisit only if profiling says otherwise for an
    unusually large tenant."""
    if not rows or not cols:
        return []
    score_matrix = np.array([[score_fn(row, col) for col in cols] for row in rows], dtype=float)
    row_indices, col_indices = linear_sum_assignment(-score_matrix)
    results: list[Assignment[RowT, ColT]] = []
    for row_index, col_index in zip(row_indices, col_indices):
        score = float(score_matrix[row_index, col_index])
        if score >= min_score:
            results.append(Assignment(row=rows[row_index], col=cols[col_index], score=score))
    return results
