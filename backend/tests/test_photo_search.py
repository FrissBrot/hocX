"""Fotosuche (Migration 0204_photo_search, app/services/photo_search.py): Tippfehler, Reihenfolge,
Umlaute, Daten, Ranking, alle Infos (Tags, Termin, Abgabe, Album, Protokoll, Hochgeladen von,
Kamera) - und nie Treffer aus fremden Mandanten, dem Papierkorb oder dem Kontext eines Partners."""

from datetime import UTC, date, datetime

from sqlalchemy import select, text

from app.models.entities import (
    GalleryImage,
    PhotoAlbum,
    PhotoAlbumItem,
    PhotoSearchDoc,
    StoredFile,
    SubmissionAssignment,
)
from app.services.file_service import FileService
from app.services.photo_search import DateSpec, parse_query, term_fold
from tests.factories import make_app_user, make_event, make_tenant

service = FileService()


def _photo(db, tenant_id, name="bild.jpg", *, tags=None, taken=None, event=None, assignment=None, element=None,
           created_by=None, camera=None):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=f"uploads/{tenant_id}/{name}",
        tags=tags or [], exif_taken_at=taken, created_by=created_by,
        camera_make=camera[0] if camera else None, camera_model=camera[1] if camera else None,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(
        tenant_id=tenant_id, stored_file_id=stored_file.id, event_id=event.id if event else None,
        submission_assignment_id=assignment.id if assignment else None, submission_element_label=element,
    ))
    db.flush()
    return stored_file


def _event(db, tenant_id, title, day):
    return make_event(db, tenant_id, title=title, event_date=day)


def _names(db, tenant_id, query, **kwargs):
    kwargs.setdefault("sort_by", "relevance")
    return [item.original_name for item in service.list_tenant_files(db, tenant_id, only_images=True, search=query, **kwargs)]


def _taken(year, month, day):
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


# --- Erkennen von Datumsangaben ------------------------------------------------------------------


def test_parse_query_understands_dates_in_all_languages():
    assert parse_query("02.05.2026").dates == [DateSpec("range", date(2026, 5, 2), date(2026, 5, 2))]
    assert parse_query("2026-05-02").dates == [DateSpec("range", date(2026, 5, 2), date(2026, 5, 2))]
    assert parse_query("2.5.").dates == [DateSpec("month_day", month=5, day=2)]
    assert parse_query("2. Mai 2026").dates == [DateSpec("range", date(2026, 5, 2), date(2026, 5, 2))]
    assert parse_query("mai 2026").dates == [DateSpec("range", date(2026, 5, 1), date(2026, 5, 31), text_word="mai")]
    for word in ("März", "Maerz", "march", "mars", "marzo"):
        assert parse_query(f"{word} 2026").dates[0].start == date(2026, 3, 1), word
    assert parse_query("août").dates[0].month == 8
    assert parse_query("dicembre").dates[0].month == 12
    year = parse_query("Sola 2026")
    assert year.dates == [DateSpec("range", date(2026, 1, 1), date(2026, 12, 31), text_word="2026")]
    assert year.text.strip() == "sola"
    assert parse_query("05/2026").dates[0].end == date(2026, 5, 31)


def test_parse_query_leaves_non_dates_alone():
    assert parse_query("Maibummel").dates == []
    assert parse_query("31.02.2026").dates == []  # gibt es nicht
    assert parse_query("version 1.5").dates == []
    assert parse_query("IMG_1234").dates == []
    assert term_fold("Müller") == term_fold("Mueller") == term_fold("muller") == "muller"
    assert term_fold("Straße") == "strasse"


# --- Suche ---------------------------------------------------------------------------------------


def test_typos_and_word_order_are_tolerated(db):
    tenant = make_tenant(db)
    lager = _event(db, tenant.id, "Pfingstlager Thun", date(2026, 5, 24))
    _photo(db, tenant.id, "a.jpg", tags=["Sommerlager"])
    _photo(db, tenant.id, "b.jpg", event=lager, tags=["Zelt"])
    _photo(db, tenant.id, "c.jpg", tags=["Bräteln"])

    assert _names(db, tenant.id, "somerlager") == ["a.jpg"]  # Buchstabe fehlt
    assert _names(db, tenant.id, "sommerlagre") == ["a.jpg"]  # Buchstabendreher am Ende
    assert _names(db, tenant.id, "zlet") == ["b.jpg"]  # Buchstabendreher, kurzes Wort
    assert _names(db, tenant.id, "thun pfingstlager") == ["b.jpg"]
    assert _names(db, tenant.id, "Pfingstlagr Thun") == ["b.jpg"]
    assert _names(db, tenant.id, "lager") == ["a.jpg", "b.jpg"] or set(_names(db, tenant.id, "lager")) == {"a.jpg", "b.jpg"}
    assert _names(db, tenant.id, "somm") == ["a.jpg"]  # Präfix beim Tippen


def test_umlauts_accents_and_case_do_not_matter(db):
    tenant = make_tenant(db)
    _photo(db, tenant.id, "a.jpg", tags=["Bräteln am Fluss"])
    _photo(db, tenant.id, "b.jpg", tags=["Café Crème"])

    for query in ("braeteln", "BRÄTELN", "brateln", "Brätel"):
        assert _names(db, tenant.id, query) == ["a.jpg"], query
    assert _names(db, tenant.id, "cafe creme") == ["b.jpg"]
    assert _names(db, tenant.id, "fluß") == ["a.jpg"]


def test_dates_match_capture_date_and_termin(db):
    tenant = make_tenant(db)
    pfingsten = _event(db, tenant.id, "Pfingstlager", date(2025, 6, 8))
    _photo(db, tenant.id, "mai.jpg", taken=_taken(2026, 5, 2))
    _photo(db, tenant.id, "juni.jpg", taken=_taken(2026, 6, 14))
    _photo(db, tenant.id, "lager.jpg", taken=_taken(2024, 1, 1), event=pfingsten)

    assert _names(db, tenant.id, "02.05.2026") == ["mai.jpg"]
    assert _names(db, tenant.id, "2.5.") == ["mai.jpg"]
    assert _names(db, tenant.id, "mai 2026") == ["mai.jpg"]
    assert _names(db, tenant.id, "May 2026") == ["mai.jpg"]
    assert set(_names(db, tenant.id, "2026")) == {"mai.jpg", "juni.jpg"}
    assert _names(db, tenant.id, "juin") == ["juni.jpg", "lager.jpg"] or set(_names(db, tenant.id, "juin")) == {"juni.jpg", "lager.jpg"}
    # Termin-Datum zählt auch (Foto selbst von 2024)
    assert _names(db, tenant.id, "8.6.2025") == ["lager.jpg"]


def test_corrected_capture_date_wins_over_exif(db):
    tenant = make_tenant(db)
    photo = _photo(db, tenant.id, "falsche-kamera.jpg", taken=_taken(2019, 1, 1))
    photo.capture_corrected_at = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    db.flush()

    assert _names(db, tenant.id, "4.7.2026") == ["falsche-kamera.jpg"]
    assert _names(db, tenant.id, "2019") == []


def test_ranking_puts_all_words_and_strong_fields_first(db):
    tenant = make_tenant(db)
    sola = _event(db, tenant.id, "Sola", date(2026, 7, 10))
    _photo(db, tenant.id, "nur-sola.jpg", event=sola)
    _photo(db, tenant.id, "zeltbau.jpg")  # nur im Dateinamen
    _photo(db, tenant.id, "beides.jpg", event=sola, tags=["Zeltbau"])
    _photo(db, tenant.id, "anderes.jpg", tags=["Küche"])

    result = _names(db, tenant.id, "zeltbau sola")
    assert result[0] == "beides.jpg"
    assert set(result) == {"beides.jpg", "nur-sola.jpg", "zeltbau.jpg"}
    # exakter Tag vor unscharfem Treffer
    _photo(db, tenant.id, "zeltbaau.jpg", tags=["Zeltbaau"])
    assert _names(db, tenant.id, "zeltbau")[0] == "beides.jpg"


def test_searches_all_information(db):
    tenant = make_tenant(db)
    uploader = make_app_user(db, "hanna@example.com", first_name="Hanna", last_name="Fotografin", tenant_id=tenant.id)
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Wanderbilder Herbst", public_slug="wb-herbst",
                                      source_type="manual")
    db.add(assignment)
    db.flush()
    _photo(db, tenant.id, "abgabe.jpg", assignment=assignment, element="Etappe Rigi")
    _photo(db, tenant.id, "person.jpg", created_by=uploader.id)
    _photo(db, tenant.id, "kamera.jpg", camera=("FUJIFILM", "X-T5"))
    album_photo = _photo(db, tenant.id, "album.jpg")
    album = PhotoAlbum(tenant_id=tenant.id, name="Jahresbericht Titelbilder", kind="manual")
    db.add(album)
    db.flush()
    db.add(PhotoAlbumItem(album_id=album.id, file_id=album_photo.public_id))
    db.flush()

    assert _names(db, tenant.id, "wanderbilder") == ["abgabe.jpg"]
    assert _names(db, tenant.id, "rigi") == ["abgabe.jpg"]
    assert _names(db, tenant.id, "hanna") == ["person.jpg"]
    assert _names(db, tenant.id, "fujifilm") == ["kamera.jpg"]
    assert _names(db, tenant.id, "titelbilder") == ["album.jpg"]


def test_changes_to_linked_records_update_the_index(db):
    tenant = make_tenant(db)
    event = _event(db, tenant.id, "Hock", date(2026, 2, 1))
    photo = _photo(db, tenant.id, "a.jpg", event=event)
    event.title = "Jubiläumsfeier"
    db.flush()
    assert _names(db, tenant.id, "jubilaum") == ["a.jpg"]
    assert _names(db, tenant.id, "hock") == []

    photo.tags = ["Fackelzug"]
    db.flush()
    assert _names(db, tenant.id, "fackelzug") == ["a.jpg"]


def test_relevance_paging_is_stable_and_complete(db):
    tenant = make_tenant(db)
    for index in range(7):
        _photo(db, tenant.id, f"turnfest-{index}.jpg", tags=["Turnfest"] if index % 2 else [])
    pages = [
        _names(db, tenant.id, "turnfest", skip=skip, limit=3)
        for skip in (0, 3, 6)
    ]
    flat = [name for page in pages for name in page]
    assert len(flat) == 7 and len(set(flat)) == 7
    # Tag-Treffer (stark) vor reinen Dateinamen-Treffern
    tagged = {f"turnfest-{index}.jpg" for index in range(7) if index % 2}
    assert set(flat[:3]) == tagged


def test_other_tenant_never_matches_or_expands(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    _photo(db, other.id, "fremd.jpg", tags=["Geheimprojekt"])
    _photo(db, tenant.id, "eigen.jpg", tags=["Ausflug"])

    assert _names(db, tenant.id, "geheimprojekt") == []
    assert _names(db, tenant.id, "geheimprojek") == []
    assert _names(db, other.id, "geheimprojekt") == ["fremd.jpg"]
    terms = set(db.scalars(text("SELECT term FROM photo_search_term WHERE tenant_id = :t"), {"t": tenant.id}))
    assert "geheimprojekt" not in terms


def test_trashed_photos_are_not_found(db):
    tenant = make_tenant(db)
    photo = _photo(db, tenant.id, "weg.jpg", tags=["Papierkorbtest"])
    photo.deleted_at = datetime.now(UTC)
    db.flush()

    assert _names(db, tenant.id, "papierkorbtest") == []
    # Das Suchdokument bleibt für das Wiederherstellen bestehen
    assert db.scalar(select(PhotoSearchDoc.stored_file_id).where(PhotoSearchDoc.stored_file_id == photo.id)) == photo.id


def test_partner_album_only_matches_partner_photos_by_file_name(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    secret = _photo(db, owner.id, "lagerfeuer.jpg", tags=["Vertraulich"])
    album = PhotoAlbum(tenant_id=owner.id, name="Gemeinsam", kind="manual")
    db.add(album)
    db.flush()
    db.add(PhotoAlbumItem(album_id=album.id, file_id=secret.public_id))
    db.flush()

    def partner_search(query):
        return [
            item.original_name
            for item in service.list_tenant_files(
                db, None, album_id=album.id, only_images=True, search=query, viewer_tenant_id=partner.id, sort_by="relevance"
            )
        ]

    assert partner_search("vertraulich") == []
    assert partner_search("gemeinsam") == []  # Albumname des Besitzers nicht als Suchtreffer
    assert partner_search("lagerfeuer") == ["lagerfeuer.jpg"]


def test_legacy_substring_search_still_works(db):
    tenant = make_tenant(db)
    _photo(db, tenant.id, "bericht_2026.jpg")
    _photo(db, tenant.id, "berichtX2026.jpg")

    assert _names(db, tenant.id, "t_2") == ["bericht_2026.jpg"]
    assert _names(db, tenant.id, "50%") == []


def test_timeline_counts_use_the_same_search(db):
    tenant = make_tenant(db)
    _photo(db, tenant.id, "a.jpg", tags=["Sommerlager"], taken=_taken(2026, 7, 1))
    _photo(db, tenant.id, "b.jpg", tags=["Winter"], taken=_taken(2026, 1, 1))

    days = service.tenant_files_timeline(db, tenant.id, only_images=True, search="somerlager")
    assert [(day.date, day.count) for day in days] == [(date(2026, 7, 1), 1)]


def test_works_as_runtime_role_with_row_level_security(db):
    """Als hocx_app (RLS aktiv): Trigger schreiben die Suchdokumente trotzdem (SECURITY DEFINER),
    die Suche sieht nur den eigenen Mandanten."""
    from tests.test_tenant_rls import as_app

    tenant = make_tenant(db)
    other = make_tenant(db)
    _photo(db, other.id, "fremd.jpg", tags=["Sternwanderung"])
    with as_app(db, tenant.id):
        _photo(db, tenant.id, "eigen.jpg", tags=["Sternwanderung"])
        assert _names(db, tenant.id, "sternwanderng") == ["eigen.jpg"]
        visible = set(db.scalars(text("SELECT tenant_id FROM photo_search_doc")))
        assert visible == {tenant.id}
        assert db.scalar(text("SELECT count(*) FROM photo_search_term WHERE tenant_id = :t"), {"t": other.id}) == 0


def test_list_files_route_searches_by_relevance(db):
    from app.api.routes import files as files_routes
    from tests.factories import make_current_user

    tenant = make_tenant(db)
    _photo(db, tenant.id, "a.jpg", tags=["Kantonales Turnfest"])
    _photo(db, tenant.id, "b.jpg", tags=["Turnfest"], taken=_taken(2026, 6, 20))
    reader = make_current_user(tenant.id, role="writer")

    items = files_routes.list_files(
        skip=0, limit=60, source=None, album_id=None, exclude_album_id=None, share_pending=None, only_images=True,
        exclude_images=False, search="turnfest juni 2026", tags=None, sort_by="relevance", sort_dir="desc",
        date_from=None, date_to=None, db=db, user=reader,
    )
    assert [item.original_name for item in items] == ["b.jpg", "a.jpg"]


def test_definer_functions_are_not_callable_by_runtime_roles(db):
    """SECURITY DEFINER umgeht RLS: kein EXECUTE für PUBLIC/Laufzeitrollen, pg_temp zuletzt im
    search_path (Security-Review F1 - sonst liessen sich fremde Mandantendaten in eine eigene
    Temp-Tabelle umlenken)."""
    from sqlalchemy import text as sql_text

    rows = db.execute(sql_text(
        "SELECT p.proname, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE') AS public_exec"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = 'public' AND p.prosecdef AND p.proname LIKE 'hocx_photo_search_%'"
    )).all()
    assert rows, "keine SECURITY-DEFINER-Funktionen gefunden"
    for row in rows:
        assert not row.public_exec, row.proname
        assert any(setting.startswith("search_path=") and setting.endswith("pg_temp") for setting in row.proconfig or []), row.proname
    for role in ("hocx_app", "hocx_abgabebox", "hocx_photo_worker"):
        if db.execute(sql_text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first():
            assert not db.execute(sql_text(
                "SELECT has_function_privilege(:r, 'public.hocx_photo_search_refresh(bigint[])', 'EXECUTE')"
            ), {"r": role}).scalar(), role


def test_expansion_timeout_falls_back_to_exact_words_without_breaking_the_session(db, monkeypatch):
    """Security-Review F3: Läuft die unscharfe Wortsuche in den Timeout, sucht sie exakt weiter -
    die Transaktion der Anfrage bleibt benutzbar (kein geschlossener Savepoint)."""
    from sqlalchemy import text as sql_text

    from app.services import photo_search

    tenant = make_tenant(db, "Suche Timeout")
    monkeypatch.setattr(photo_search, "EXPANSION_TIMEOUT_MS", 1)
    monkeypatch.setattr(photo_search, "_EXPANSION_SQL", sql_text("SELECT 1 AS idx, 'x' AS term, 1.0 AS quality FROM pg_sleep(0.05)"))
    rows = photo_search._expand_terms(db, tenant.id, [1, 2], ["sommer", "lager"])
    assert [(row.idx, row.term, row.quality) for row in rows] == [(1, "sommer", 1.0), (2, "lager", 1.0)]
    assert db.execute(sql_text("SELECT 1")).scalar() == 1
    assert db.execute(sql_text("SHOW statement_timeout")).scalar() != "1ms"
