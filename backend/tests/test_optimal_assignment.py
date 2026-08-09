from app.services.optimal_assignment import solve_optimal_assignment


def test_finds_the_globally_optimal_assignment_not_the_greedy_one():
    # Row 0's best match is col "X" (0.9), but col "X" is ALSO row 1's only plausible
    # match (0.95) - a greedy "sort all pairs, claim best first" pass would give
    # row 0 -> X (0.9) since that's the single highest score overall, stranding row 1
    # with nothing (its only other option, "Y", scores 0.0 for it). The optimal
    # assignment instead gives row 1 -> X (0.95) and row 0 -> Y (0.85), for a strictly
    # higher total (1.80 vs 0.9).
    scores = {(0, "X"): 0.9, (0, "Y"): 0.85, (1, "X"): 0.95, (1, "Y"): 0.0}
    result = solve_optimal_assignment([0, 1], ["X", "Y"], lambda r, c: scores[(r, c)], min_score=0.0)
    total = sum(a.score for a in result)
    assert total > 1.79
    by_row = {a.row: a.col for a in result}
    assert by_row[1] == "X"
    assert by_row[0] == "Y"


def test_min_score_drops_a_pair_instead_of_forcing_it():
    # Only one row, one column, scoring below min_score - linear_sum_assignment would
    # otherwise unconditionally pair them (it always assigns min(rows,cols) pairs).
    result = solve_optimal_assignment([0], ["A"], lambda r, c: 0.1, min_score=0.5)
    assert result == []


def test_empty_rows_or_cols_returns_empty():
    assert solve_optimal_assignment([], ["A"], lambda r, c: 1.0, min_score=0.0) == []
    assert solve_optimal_assignment([0], [], lambda r, c: 1.0, min_score=0.0) == []


def test_more_rows_than_cols_leaves_excess_rows_unassigned():
    result = solve_optimal_assignment([0, 1, 2], ["A"], lambda r, c: 1.0, min_score=0.0)
    assert len(result) == 1
