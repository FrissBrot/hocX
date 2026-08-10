from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WordImportSuggestionOutcome

# Cold-start guard: below this many logged decisions for this (tenant, template,
# signal_type), trust the global default entirely - too few samples for a per-tenant
# threshold to be statistically meaningful, and an early wrong guess could otherwise
# self-reinforce (a badly-set threshold suppresses correct suggestions, which produces
# more "changed"/rejected outcomes, which further skews the learned threshold).
_MIN_SAMPLE_SIZE = 20
# Per-bucket minimum too, so a single lucky/unlucky sample never decides a whole decile.
_MIN_BUCKET_SAMPLE_SIZE = 5
_ACCEPT_RATE_FLOOR = 0.8


def adaptive_threshold(db: Session, *, tenant_id: int, template_id: int, signal_type: str, default: float) -> float:
    """Learns a per-tenant+template score threshold for `signal_type` from real commit
    history (WordImportSuggestionOutcome, see WordImportService.commit's `_log_outcome`)
    instead of trusting one hardcoded module-wide default for every tenant alike - some
    tenants have many similarly-named participants/events and need a stricter bar,
    others would benefit from a looser one.

    Buckets `suggested_score` into 0.1-wide bands and returns the lower edge of the
    LOWEST-scoring band whose empirical acceptance rate still clears _ACCEPT_RATE_FLOOR
    - the lowest score this tenant's own history says is still safe to auto-trust. Falls
    back to `default` when there isn't enough history yet (cold start) or when no band
    clears the floor - never invents a threshold from a thin or noisy sample."""
    rows = db.execute(
        select(WordImportSuggestionOutcome.suggested_score, WordImportSuggestionOutcome.was_accepted).where(
            WordImportSuggestionOutcome.tenant_id == tenant_id,
            WordImportSuggestionOutcome.template_id == template_id,
            WordImportSuggestionOutcome.signal_type == signal_type,
            # Excludes WordImportService.commit()'s 0.0 sentinel (logged whenever the
            # client couldn't report the real originally-suggested score - e.g. the
            # actual top suggestion fell outside the capped candidate list it was shown,
            # see _log_outcome). Those rows are frequent and, being explicit accepts of
            # an unknown-but-not-actually-near-zero score, can reach a high acceptance
            # rate purely from that pollution - left in, bucket 0 could "learn" a 0.0
            # threshold and disable this signal's matching gate entirely. A genuine
            # fuzzy-matched candidate score is never exactly 0.0 in practice.
            WordImportSuggestionOutcome.suggested_score > 0,
        )
    ).all()
    if len(rows) < _MIN_SAMPLE_SIZE:
        return default

    buckets: dict[int, list[bool]] = defaultdict(list)
    for score, accepted in rows:
        buckets[min(int(score * 10), 9)].append(accepted)

    candidate_thresholds: list[float] = []
    for bucket_index in sorted(buckets):
        accepted_list = buckets[bucket_index]
        if len(accepted_list) < _MIN_BUCKET_SAMPLE_SIZE:
            continue
        rate = sum(accepted_list) / len(accepted_list)
        if rate >= _ACCEPT_RATE_FLOOR:
            candidate_thresholds.append(bucket_index / 10.0)
    return min(candidate_thresholds) if candidate_thresholds else default
