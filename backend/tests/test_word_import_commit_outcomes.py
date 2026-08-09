"""First end-to-end tests of WordImportService.commit() (previously only the private
list-grouping helpers were unit-tested, see test_word_import_service.py) - focused on
the C.9 (WordImportSuggestionOutcome logging) and A.4 (rejected_candidates negative
feedback) behavior, since those are the parts that specifically need a real commit()
round-trip against the DB to verify."""
from datetime import date

from sqlalchemy import select

from app.models import WordImportProfile, WordImportSuggestionOutcome
from app.schemas.word_import import WordImportCommit, WordImportEventCommit
from app.services.word_import_quality_service import WordImportQualityService
from app.services.word_import_service import WordImportService
from tests.factories import make_event, make_template, make_tenant


def _template_with_protocol_number(db, tenant):
    template = make_template(db, tenant.id)
    # create_from_template requires a protocol_number it can either be given directly
    # or derive from the template's own pattern - the bare factory leaves this None.
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    return template


def _commit_events(db, *, tenant, template, events):
    service = WordImportService()
    payload = WordImportCommit(template_id=template.id, protocol_date=date(2026, 3, 1), events=events)
    return service.commit(db, tenant_id=tenant.id, user_id=1, payload=payload)


def test_logs_rejected_outcome_when_final_choice_differs_from_suggestion(db):
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    suggested_event = make_event(db, tenant.id, title="Elternabend", event_date=date(2026, 3, 1))
    actually_chosen_event = make_event(db, tenant.id, title="Vorstandssitzung", event_date=date(2026, 3, 2))

    _commit_events(
        db,
        tenant=tenant,
        template=template,
        events=[
            WordImportEventCommit(
                approved=True,
                linked_event_id=actually_chosen_event.id,
                final_title=actually_chosen_event.title,
                final_date=actually_chosen_event.event_date,
                originally_suggested_event_id=suggested_event.id,
                originally_suggested_score=0.82,
            )
        ],
    )

    outcomes = list(db.execute(select(WordImportSuggestionOutcome).where(WordImportSuggestionOutcome.tenant_id == tenant.id)).scalars())
    assert len(outcomes) == 1
    assert outcomes[0].signal_type == "event_match"
    assert outcomes[0].was_accepted is False
    assert outcomes[0].suggested_score == 0.82


def test_logs_accepted_outcome_when_final_choice_matches_suggestion(db):
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    event = make_event(db, tenant.id, title="Elternabend", event_date=date(2026, 3, 1))

    _commit_events(
        db,
        tenant=tenant,
        template=template,
        events=[
            WordImportEventCommit(
                approved=True,
                linked_event_id=event.id,
                final_title=event.title,
                final_date=event.event_date,
                originally_suggested_event_id=event.id,
                originally_suggested_score=0.95,
            )
        ],
    )

    outcomes = list(db.execute(select(WordImportSuggestionOutcome).where(WordImportSuggestionOutcome.tenant_id == tenant.id)).scalars())
    assert len(outcomes) == 1
    assert outcomes[0].was_accepted is True


def test_no_outcome_logged_when_nothing_was_originally_suggested(db):
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    event = make_event(db, tenant.id, title="Neuer Anlass", event_date=date(2026, 3, 1))

    _commit_events(
        db,
        tenant=tenant,
        template=template,
        events=[
            WordImportEventCommit(
                approved=True,
                linked_event_id=event.id,
                final_title=event.title,
                final_date=event.event_date,
                originally_suggested_event_id=None,
                originally_suggested_score=None,
            )
        ],
    )

    outcomes = list(db.execute(select(WordImportSuggestionOutcome).where(WordImportSuggestionOutcome.tenant_id == tenant.id)).scalars())
    assert outcomes == []


def test_rejection_is_recorded_in_profile_for_negative_feedback(db):
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    suggested_event = make_event(db, tenant.id, title="Elternabend", event_date=date(2026, 3, 1))
    actually_chosen_event = make_event(db, tenant.id, title="Vorstandssitzung", event_date=date(2026, 3, 2))

    _commit_events(
        db,
        tenant=tenant,
        template=template,
        events=[
            WordImportEventCommit(
                approved=True,
                linked_event_id=actually_chosen_event.id,
                final_title=actually_chosen_event.title,
                final_date=actually_chosen_event.event_date,
                originally_suggested_event_id=suggested_event.id,
                originally_suggested_score=0.82,
            )
        ],
    )

    profile = db.execute(
        select(WordImportProfile).where(WordImportProfile.tenant_id == tenant.id, WordImportProfile.template_id == template.id)
    ).scalar_one()
    key = f"event:{actually_chosen_event.event_date.isoformat()}|vorstandssitzung"
    rejected_entry = profile.mapping_config_json["rejected_candidates"][key]
    assert suggested_event.id in rejected_entry["rejected"]
    assert rejected_entry["chosen"] == actually_chosen_event.id


def test_quality_service_aggregates_accept_rate_by_bucket(db):
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    db.add_all(
        [
            WordImportSuggestionOutcome(tenant_id=tenant.id, template_id=template.id, signal_type="event_match", suggested_score=0.85, was_accepted=True),
            WordImportSuggestionOutcome(tenant_id=tenant.id, template_id=template.id, signal_type="event_match", suggested_score=0.87, was_accepted=True),
            WordImportSuggestionOutcome(tenant_id=tenant.id, template_id=template.id, signal_type="event_match", suggested_score=0.5, was_accepted=False),
        ]
    )
    db.flush()

    stats = WordImportQualityService().accept_rate_stats(db, tenant_id=tenant.id, template_id=template.id)
    buckets_by_score = {(b["signal_type"], b["score_bucket"]): b for b in stats}
    assert buckets_by_score[("event_match", 0.8)]["sample_count"] == 2
    assert buckets_by_score[("event_match", 0.8)]["accept_rate"] == 1.0
    assert buckets_by_score[("event_match", 0.5)]["accept_rate"] == 0.0
