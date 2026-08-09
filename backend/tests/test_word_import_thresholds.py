from app.models import WordImportSuggestionOutcome
from app.services.word_import_thresholds import adaptive_threshold
from tests.factories import make_template, make_tenant


def _seed_outcomes(db, *, tenant_id, template_id, signal_type, score, accepted_count, rejected_count):
    rows = [
        WordImportSuggestionOutcome(tenant_id=tenant_id, template_id=template_id, signal_type=signal_type, suggested_score=score, was_accepted=True)
        for _ in range(accepted_count)
    ] + [
        WordImportSuggestionOutcome(tenant_id=tenant_id, template_id=template_id, signal_type=signal_type, suggested_score=score, was_accepted=False)
        for _ in range(rejected_count)
    ]
    db.add_all(rows)
    db.flush()


def test_returns_default_below_minimum_sample_size(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    _seed_outcomes(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", score=0.5, accepted_count=5, rejected_count=0)

    result = adaptive_threshold(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", default=0.8)
    assert result == 0.8


def test_learns_a_lower_threshold_when_history_supports_it(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    # 10 accepted, 0 rejected at score 0.5-0.59 - well above _MIN_SAMPLE_SIZE (20) once
    # combined with the 0.9 bucket below, and this bucket's own rate is a clean 100%.
    _seed_outcomes(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", score=0.55, accepted_count=10, rejected_count=0)
    _seed_outcomes(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", score=0.95, accepted_count=15, rejected_count=0)

    result = adaptive_threshold(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", default=0.8)
    assert result == 0.5


def test_falls_back_to_default_when_no_bucket_clears_the_floor(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    # 25 samples, but every bucket has a poor (well under 0.8) acceptance rate.
    _seed_outcomes(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", score=0.55, accepted_count=5, rejected_count=20)

    result = adaptive_threshold(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", default=0.8)
    assert result == 0.8


def test_different_signal_types_and_templates_are_isolated(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    other_template = make_template(db, tenant.id, name="Other Template")
    _seed_outcomes(db, tenant_id=tenant.id, template_id=template.id, signal_type="event_match", score=0.55, accepted_count=25, rejected_count=0)

    # Same tenant, different template - must not see the other template's history.
    assert adaptive_threshold(db, tenant_id=tenant.id, template_id=other_template.id, signal_type="event_match", default=0.8) == 0.8
    # Same template, different signal_type - must not see event_match's history either.
    assert adaptive_threshold(db, tenant_id=tenant.id, template_id=template.id, signal_type="participant_match", default=0.6) == 0.6
