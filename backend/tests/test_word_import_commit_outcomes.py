"""First end-to-end tests of WordImportService.commit() (previously only the private
list-grouping helpers were unit-tested, see test_word_import_service.py) - focused on
the C.9 (WordImportSuggestionOutcome logging) and A.4 (rejected_candidates negative
feedback) behavior, since those are the parts that specifically need a real commit()
round-trip against the DB to verify."""
from datetime import date

from sqlalchemy import select

from app.models import WordImportProfile, WordImportSuggestionOutcome
from app.schemas.word_import import WordImportAttendanceCommit, WordImportCommit, WordImportEventCommit
from app.services.word_import_quality_service import WordImportQualityService
from app.services.word_import_service import WordImportService
from tests.factories import make_event, make_template, make_tenant
from tests.test_word_import_e2e import _build_template
from tests.word_import_fixtures import default_spec, render_docx


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
                raw_title=actually_chosen_event.title,
                raw_date=actually_chosen_event.event_date,
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
                raw_title=event.title,
                raw_date=event.event_date,
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
                raw_title=event.title,
                raw_date=event.event_date,
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
                raw_title=actually_chosen_event.title,
                raw_date=actually_chosen_event.event_date,
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


def test_event_conflict_resolution_is_remembered_and_reused_across_different_dates(db):
    """Timo's real complaint (confirmed against a real screenshot: "Bruderklausentag
    25.09.2024" in the document vs. an existing Event dated 25.09.2025) is a YEARLY-
    recurring Termin whose document mention always names a different/stale date - exact
    title match, only the date conflicts, and the raw date is never the same twice. A
    Termin whose document text conflicts with an already-existing Event's title/date
    (status "changed") must not force a fresh reviewer decision every single import that
    mentions it once the SAME (event, title) conflict has already been resolved once -
    even when the raw date itself differs every time (see _event_conflict_key, which is
    deliberately NOT keyed on raw_date for exactly this reason)."""
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    # Exact title match, date a year off the fixture's "Vorstandssitzung" row (25.10.2026)
    # - day_diff > 3 so only the title-exact-match fallback clears the assignment
    # threshold (see _score_event_candidate), landing this as "changed" (date conflicts)
    # rather than "matched", exactly like the real Bruderklausentag case.
    conflicting_event = make_event(db, tenant.id, title="Vorstandssitzung", event_date=date(2025, 10, 25))
    service = WordImportService()

    first_analysis = service.analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None,
        raw_bytes=render_docx(default_spec(protocol_date=date(2026, 10, 18))),
    )
    row = next(m for m in first_analysis.event_mappings if m.raw_title == "Vorstandssitzung")
    assert row.status == "changed"
    assert row.matched_event_id == conflicting_event.id
    assert row.raw_date == date(2026, 10, 25)
    assert row.remembered_title_source is None
    assert row.remembered_date_source is None

    # Reviewer resolves the conflict by keeping the EXISTING event's date (so the
    # mismatch, and thus the conflict, persists in the DB - simulating a real recurring
    # situation instead of one that fixes itself after the first import).
    service.commit(
        db, tenant_id=tenant.id, user_id=1,
        payload=WordImportCommit(
            template_id=template.id,
            protocol_date=date(2026, 10, 18),
            events=[
                WordImportEventCommit(
                    approved=True,
                    linked_event_id=conflicting_event.id,
                    final_title=conflicting_event.title,
                    final_date=conflicting_event.event_date,
                    raw_title=row.raw_title,
                    raw_date=row.raw_date,
                    originally_suggested_event_id=row.matched_event_id,
                    originally_suggested_score=(row.candidates[0].score if row.candidates else None),
                )
            ],
        ),
    )

    profile = db.execute(
        select(WordImportProfile).where(WordImportProfile.tenant_id == tenant.id, WordImportProfile.template_id == template.id)
    ).scalar_one()
    key = f"{conflicting_event.id}|vorstandssitzung"
    assert profile.mapping_config_json["event_conflict_resolutions"][key] == {
        "title_source": "doc", "date_source": "existing",
    }

    # A LATER import mentioning the same still-unresolved Event under the same title,
    # but with a DIFFERENT raw date (2027 instead of 2026) - the Event's date in the DB
    # never changed, so this is the exact same recurring conflict, just with this year's
    # stale date instead of last year's. Must surface the remembered decision instead of
    # a fresh, unresolved "changed" row.
    spec = default_spec(protocol_date=date(2026, 10, 18))
    spec.events.rows = [row if row[1] != "Vorstandssitzung" else ["25.10.2027", "Vorstandssitzung"] for row in spec.events.rows]
    second_analysis = service.analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=render_docx(spec),
    )
    second_row = next(m for m in second_analysis.event_mappings if m.raw_title == "Vorstandssitzung")
    assert second_row.status == "changed"
    assert second_row.raw_date == date(2027, 10, 25)
    assert second_row.remembered_title_source == "doc"
    assert second_row.remembered_date_source == "existing"


def test_no_link_attendance_name_is_remembered_and_reused(db):
    """Timo's follow-up (confirmed against a real screenshot: an Anwesenheit table's own
    "Total" footer row, never a real participant, stuck on "Keinen verknüpfen" every
    import): once a raw attendance name is explicitly resolved as "Keinen verknüpfen"
    in one commit, the identical raw name recurring in a later import must auto-resolve
    the same way instead of being re-flagged as an unmatched name every time."""
    ctx = _build_template(db)
    tenant, template = ctx["tenant"], ctx["template"]
    service = WordImportService()
    spec = default_spec(protocol_date=date(2026, 10, 18))
    spec.attendance.rows = [*spec.attendance.rows, ["Total", ""]]
    raw_bytes = render_docx(spec)

    first_analysis = service.analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    row = next(m for m in first_analysis.attendance_mappings if m.raw_name == "Total")
    assert row.suggested_participant_id is None
    assert row.remembered_no_link is False
    assert 'Kein passender Teilnehmer für "Total" gefunden.' in first_analysis.warnings

    # Reviewer explicitly resolves "Total" as "Keinen verknüpfen" - no other attendance
    # rows are needed for this commit to exercise the no-link bookkeeping in isolation.
    service.commit(
        db, tenant_id=tenant.id, user_id=1,
        payload=WordImportCommit(
            template_id=template.id,
            protocol_date=date(2026, 10, 18),
            attendance=[
                WordImportAttendanceCommit(
                    raw_name="Total", participant_id=None, participant_name="Total", status="present",
                    create_new=False, originally_suggested_participant_id=None, originally_suggested_score=None,
                )
            ],
        ),
    )

    profile = db.execute(
        select(WordImportProfile).where(WordImportProfile.tenant_id == tenant.id, WordImportProfile.template_id == template.id)
    ).scalar_one()
    assert profile.mapping_config_json["no_link_names"] == ["total"]

    # A LATER import mentioning the same raw name again must surface the remembered
    # decision instead of re-flagging it as an unmatched name.
    second_analysis = service.analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    second_row = next(m for m in second_analysis.attendance_mappings if m.raw_name == "Total")
    assert second_row.suggested_participant_id is None
    assert second_row.remembered_no_link is True
    assert 'Kein passender Teilnehmer für "Total" gefunden.' not in second_analysis.warnings


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


def test_quality_service_buckets_a_perfect_score_with_the_09_band(db):
    """A suggested_score of exactly 1.0 must land in the same 0.9 bucket a 0.9-0.99
    score would - word_import_thresholds.adaptive_threshold's own Python-side bucketing
    (`min(int(score * 10), 9)`) already caps this way; the SQL side used to disagree
    (a plain `floor(score*10)/10` gives 1.0 its own separate bucket), silently desyncing
    this dashboard from what the learning logic actually bases its threshold on."""
    tenant = make_tenant(db)
    template = _template_with_protocol_number(db, tenant)
    db.add_all(
        [
            WordImportSuggestionOutcome(tenant_id=tenant.id, template_id=template.id, signal_type="name_match", suggested_score=1.0, was_accepted=True),
            WordImportSuggestionOutcome(tenant_id=tenant.id, template_id=template.id, signal_type="name_match", suggested_score=0.92, was_accepted=True),
        ]
    )
    db.flush()

    stats = WordImportQualityService().accept_rate_stats(db, tenant_id=tenant.id, template_id=template.id)
    buckets_by_score = {(b["signal_type"], b["score_bucket"]): b for b in stats}
    assert ("name_match", 1.0) not in buckets_by_score
    assert buckets_by_score[("name_match", 0.9)]["sample_count"] == 2
