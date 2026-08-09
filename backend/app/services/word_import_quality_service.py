from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import WordImportSuggestionOutcome


class WordImportQualityService:
    """Read-only aggregation over WordImportSuggestionOutcome (see
    WordImportService.commit's `_log_outcome`) - kept separate from WordImportService
    itself since this is a distinct read/reporting responsibility, not part of the
    parse/match/commit pipeline."""

    def accept_rate_stats(
        self, db: Session, *, tenant_id: int, template_id: int | None = None
    ) -> list[dict]:
        """One row per (signal_type, score_bucket) with sample_count/accept_rate,
        tenant-scoped. template_id=None aggregates across all of the tenant's
        templates; score_bucket is a 0.1-wide floor bucket of suggested_score (0.0,
        0.1, ..., 0.9) - the same bucketing word_import_thresholds.adaptive_threshold
        uses to learn per-tenant score thresholds from this same data."""
        bucket_expr = func.floor(WordImportSuggestionOutcome.suggested_score * 10) / 10.0
        filters = [WordImportSuggestionOutcome.tenant_id == tenant_id]
        if template_id is not None:
            filters.append(WordImportSuggestionOutcome.template_id == template_id)
        rows = db.execute(
            select(
                WordImportSuggestionOutcome.signal_type,
                bucket_expr.label("score_bucket"),
                func.count().label("sample_count"),
                func.avg(case((WordImportSuggestionOutcome.was_accepted, 1.0), else_=0.0)).label("accept_rate"),
            )
            .where(*filters)
            .group_by(WordImportSuggestionOutcome.signal_type, "score_bucket")
            .order_by(WordImportSuggestionOutcome.signal_type, "score_bucket")
        ).all()
        return [
            {
                "signal_type": row.signal_type,
                "score_bucket": float(row.score_bucket),
                "sample_count": row.sample_count,
                "accept_rate": float(row.accept_rate),
            }
            for row in rows
        ]
