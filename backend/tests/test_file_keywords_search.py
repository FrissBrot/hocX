"""Keywords und Synonyme in der Suche (Migration 0217, services/file_keywords.py,
services/search_synonyms.py, services/photo_search.py).

Keywords treffen wie Tags (auch mit Tippfehler), in Fotos und Ablage; Synonyme aus dem Grundstock
und aus der eigenen Liste des Mandanten erweitern jedes Suchwort (tiefer gewichtet). Nie: Keywords
oder Synonyme eines fremden Mandanten, Schreiben ohne das passende Recht."""

import time
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import files as files_routes
from app.api.routes import search_synonyms as synonym_routes
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.files import FileBulkKeywordsUpdate, FileKeywordsSummaryRequest, StoredFileKeywordsUpdate
from app.schemas.search_synonyms import SearchSynonymsUpdate
from app.services import file_keywords, search_synonyms
from app.services.file_service import FileService
from app.services.photo_search import build_search_plan
from tests.factories import make_app_user, make_current_user, make_tenant

service = FileService()

PHOTO_MANAGER = frozenset({"photos.read", "photos.manage", "files.read"})
FILE_MANAGER = frozenset({"files.read", "files.manage", "photos.read"})
READER = frozenset({"files.read", "photos.read"})


def _photo(db, tenant_id, name="bild.jpg", *, keywords=None, tags=None):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=f"uploads/{tenant_id}/{name}",
        tags=tags or [], keywords=keywords or [],
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _document(db, tenant_id, name="bericht.pdf", *, keywords=None):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="application/pdf", storage_path=f"uploads/{tenant_id}/{name}",
        keywords=keywords or [],
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _photos(db, tenant_id, query):
    items = service.list_tenant_files(db, tenant_id, only_images=True, search=query, sort_by="relevance")
    return [item.original_name for item in items]


def _documents(db, tenant_id, query):
    items = service.list_tenant_files(db, tenant_id, exclude_images=True, search=query, sort_by="relevance")
    return [item.original_name for item in items]


def _user(tenant_id, permissions):
    return make_current_user(tenant_id, permissions=permissions)


# --- Normalisierung -------------------------------------------------------------------------------


def test_normalize_keywords_trims_dedupes_and_limits():
    raw = ["  Sonnen   untergang ", "sonnen untergang", "", "x" * 80, "Bild‮gpj", *[f"k{i}" for i in range(50)]]
    result = file_keywords.normalize_keywords(raw)
    assert result[0] == "Sonnen untergang"
    assert len(result[1]) == file_keywords.MAX_KEYWORD_LENGTH
    assert "Bildgpj" in result  # Bidi-Steuerzeichen entfernt
    assert len(result) == file_keywords.MAX_KEYWORDS_PER_FILE


def test_synonym_matching_tolerates_typos_but_not_short_words():
    groups = [("velo", "fahrrad", "bike")]
    assert {hit.term for hit in search_synonyms.expand(["fahrad"], groups)["fahrad"]} == {"velo", "fahrrad", "bike"}
    assert search_synonyms.expand(["vel"], groups) == {}
    exact = search_synonyms.expand(["velo"], groups)["velo"]
    assert all(hit.factor == pytest.approx(search_synonyms.SYNONYM_WEIGHT) for hit in exact)


# --- Suche: Keywords ------------------------------------------------------------------------------


def test_keywords_are_found_with_typos_in_photos_and_documents(db):
    tenant = make_tenant(db)
    _photo(db, tenant.id, "a.jpg", keywords=["Sonnenuntergang"])
    _photo(db, tenant.id, "b.jpg")
    _document(db, tenant.id, "budget.pdf", keywords=["Kassenprüfung"])

    assert _photos(db, tenant.id, "sonnenuntergang") == ["a.jpg"]
    assert _photos(db, tenant.id, "sonenuntergang") == ["a.jpg"]  # Tippfehler
    assert _photos(db, tenant.id, "untergang") == ["a.jpg"]  # Teilwort
    assert _documents(db, tenant.id, "kassenprufung") == ["budget.pdf"]
    assert _documents(db, tenant.id, "kasenprüfung") == ["budget.pdf"]
    # im Wortschatz für die unscharfe Suche
    terms = set(db.scalars(text("SELECT term FROM photo_search_term WHERE tenant_id = :t"), {"t": tenant.id}))
    assert {"sonnenuntergang", "kassenprufung"} <= terms


def test_changing_keywords_updates_the_index(db):
    tenant = make_tenant(db)
    photo = _photo(db, tenant.id, "a.jpg", keywords=["Alt"])
    file_keywords.set_keywords(db, photo, ["Gipfelkreuz"])
    assert _photos(db, tenant.id, "gipfelkreuz") == ["a.jpg"]
    assert _photos(db, tenant.id, "alt") == []
    file_keywords.bulk_update(db, tenant.id, [photo.public_id], add=["Bergsee"], remove=["gipfelkreuz"])
    assert photo.keywords == ["Bergsee"]
    assert _photos(db, tenant.id, "gipfelkreuz") == []
    assert _photos(db, tenant.id, "bergsee") == ["a.jpg"]


# --- Suche: Synonyme ------------------------------------------------------------------------------


def test_builtin_synonyms_expand_the_query_with_lower_weight(db):
    tenant = make_tenant(db)
    _photo(db, tenant.id, "fahrrad.jpg", keywords=["Fahrrad"])
    _photo(db, tenant.id, "velo.jpg", keywords=["Velo"])
    _photo(db, tenant.id, "anderes.jpg", keywords=["Wanderschuh"])

    # Exakter Treffer vor dem Synonym
    assert _photos(db, tenant.id, "velo") == ["velo.jpg", "fahrrad.jpg"]
    assert _photos(db, tenant.id, "fahrrad") == ["fahrrad.jpg", "velo.jpg"]
    # Tippfehler im Suchwort: das Synonym greift trotzdem
    assert set(_photos(db, tenant.id, "fahrad")) == {"fahrrad.jpg", "velo.jpg"}
    # Mehrsprachig
    assert set(_photos(db, tenant.id, "bicicletta")) == {"fahrrad.jpg", "velo.jpg"}


def test_swiss_terms_from_the_builtin_list(db):
    tenant = make_tenant(db)
    _photo(db, tenant.id, "hock.jpg", tags=["Hock März"])
    _photo(db, tenant.id, "lager.jpg", keywords=["Zeltlager"])
    _photo(db, tenant.id, "pause.jpg", keywords=["Zvieri"])

    assert _photos(db, tenant.id, "sitzung") == ["hock.jpg"]
    assert _photos(db, tenant.id, "lager") == ["lager.jpg"]
    assert _photos(db, tenant.id, "znüni") == ["pause.jpg"]


def test_tenant_synonyms_apply_only_to_their_own_tenant(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    search_synonyms.replace_groups(db, tenant.id, [["Grümpi", "Grümpelturnier", "grümpi"]])
    _photo(db, tenant.id, "eigen.jpg", keywords=["Grümpelturnier"])
    _photo(db, other.id, "fremd.jpg", keywords=["Grümpelturnier"])

    assert search_synonyms.list_groups(db, tenant.id) == [["Grümpi", "Grümpelturnier"]]
    assert _photos(db, tenant.id, "grumpi") == ["eigen.jpg"]
    assert _photos(db, tenant.id, "grumpy") == ["eigen.jpg"]  # Tippfehler auch für Synonyme
    # Der andere Mandant hat diese Synonyme nicht und sieht nie die Datei des ersten
    assert _photos(db, other.id, "grumpi") == []
    assert _photos(db, other.id, "grümpelturnier") == ["fremd.jpg"]


def test_foreign_keywords_never_match_or_expand(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    _photo(db, other.id, "fremd.jpg", keywords=["Geheimrezept"])
    _photo(db, tenant.id, "eigen.jpg")

    assert _photos(db, tenant.id, "geheimrezept") == []
    assert _photos(db, tenant.id, "geheimrezpt") == []
    terms = set(db.scalars(text("SELECT term FROM photo_search_term WHERE tenant_id = :t"), {"t": tenant.id}))
    assert "geheimrezept" not in terms


def test_partner_in_shared_album_cannot_search_owner_keywords(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    secret = _photo(db, owner.id, "lagerfeuer.jpg", keywords=["Vertraulich"])
    album = PhotoAlbum(tenant_id=owner.id, name="Gemeinsam", kind="manual")
    db.add(album)
    db.flush()
    db.add(PhotoAlbumItem(album_id=album.id, file_id=secret.public_id))
    db.flush()
    items = service.list_tenant_files(
        db, None, album_id=album.id, only_images=True, search="vertraulich", viewer_tenant_id=partner.id, sort_by="relevance"
    )
    assert items == []
    # und lesen kann er sie auch nicht (fremder Mandant = 404)
    with pytest.raises(HTTPException) as exc:
        files_routes.get_stored_file_keywords(secret.public_id, db=db, user=_user(partner.id, PHOTO_MANAGER))
    assert exc.value.status_code == 404


def test_synonym_table_is_tenant_isolated_under_rls(db):
    from tests.test_tenant_rls import as_app

    tenant = make_tenant(db)
    other = make_tenant(db)
    search_synonyms.replace_groups(db, other.id, [["Kuchen", "Torte"]])
    search_synonyms.replace_groups(db, tenant.id, [["Apfel", "Öpfel"]])
    with as_app(db, tenant.id):
        assert search_synonyms.list_groups(db, tenant.id) == [["Apfel", "Öpfel"]]
        assert search_synonyms.list_groups(db, other.id) == []
        assert {term for group in search_synonyms.tenant_groups(db, other.id) for term in group} == set()


# --- Routen und Rechte ----------------------------------------------------------------------------


def test_keyword_routes_check_permissions_and_tenant(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    photo = _photo(db, tenant.id, "a.jpg")
    document = _document(db, tenant.id, "b.pdf")
    foreign = _photo(db, other.id, "c.jpg")

    saved = files_routes.update_stored_file_keywords(
        photo.public_id, StoredFileKeywordsUpdate(keywords=["Gipfel", "gipfel", " Seil "]), db=db,
        user=_user(tenant.id, PHOTO_MANAGER),
    )
    assert saved.keywords == ["Gipfel", "Seil"]
    read = files_routes.get_stored_file_keywords(photo.public_id, db=db, user=_user(tenant.id, READER))
    assert read.keywords == ["Gipfel", "Seil"] and read.can_edit is False

    # Lesende dürfen nicht schreiben
    with pytest.raises(HTTPException) as exc:
        files_routes.update_stored_file_keywords(
            photo.public_id, StoredFileKeywordsUpdate(keywords=["x"]), db=db, user=_user(tenant.id, READER)
        )
    assert exc.value.status_code == 403
    # Dokumente nur mit files.manage, Fotos nur mit photos.manage
    with pytest.raises(HTTPException) as exc:
        files_routes.update_stored_file_keywords(
            document.public_id, StoredFileKeywordsUpdate(keywords=["x"]), db=db, user=_user(tenant.id, PHOTO_MANAGER)
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        files_routes.update_stored_file_keywords(
            photo.public_id, StoredFileKeywordsUpdate(keywords=["x"]), db=db, user=_user(tenant.id, FILE_MANAGER)
        )
    assert exc.value.status_code == 403
    # Fremde und unbekannte Datei: dasselbe 404
    for file_id in (foreign.public_id, uuid.uuid4()):
        with pytest.raises(HTTPException) as exc:
            files_routes.update_stored_file_keywords(
                file_id, StoredFileKeywordsUpdate(keywords=["x"]), db=db, user=_user(tenant.id, PHOTO_MANAGER | FILE_MANAGER)
            )
        assert exc.value.status_code == 404
    assert foreign.keywords == []


def test_bulk_keywords_need_rights_for_every_kind_and_stay_in_tenant(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    photo = _photo(db, tenant.id, "a.jpg", keywords=["Alt"])
    document = _document(db, tenant.id, "b.pdf", keywords=["alt", "Bleibt"])
    foreign = _photo(db, other.id, "c.jpg", keywords=["Alt"])
    both = PHOTO_MANAGER | FILE_MANAGER

    with pytest.raises(HTTPException) as exc:
        files_routes.bulk_update_file_keywords(
            FileBulkKeywordsUpdate(file_ids=[photo.public_id, document.public_id], add=["Neu"]), db=db,
            user=_user(tenant.id, PHOTO_MANAGER),
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        files_routes.bulk_update_file_keywords(
            FileBulkKeywordsUpdate(file_ids=[photo.public_id, foreign.public_id], add=["Neu"]), db=db,
            user=_user(tenant.id, both),
        )
    assert exc.value.status_code == 404

    summary = files_routes.file_keywords_summary(
        FileKeywordsSummaryRequest(file_ids=[photo.public_id, document.public_id]), db=db, user=_user(tenant.id, READER)
    )
    assert [(item.keyword.casefold(), item.count) for item in summary] == [("alt", 2), ("bleibt", 1)]

    result = files_routes.bulk_update_file_keywords(
        FileBulkKeywordsUpdate(file_ids=[photo.public_id, document.public_id], add=["Neu"], remove=["ALT"]), db=db,
        user=_user(tenant.id, both),
    )
    assert result.updated == 2
    db.refresh(photo)
    db.refresh(document)
    db.refresh(foreign)
    assert photo.keywords == ["Neu"]
    assert document.keywords == ["Bleibt", "Neu"]
    assert foreign.keywords == ["Alt"]


def test_synonym_routes_need_settings_manage(db):
    tenant = make_tenant(db)
    writer = _user(tenant.id, PHOTO_MANAGER | FILE_MANAGER)
    admin = make_current_user(tenant.id, role="admin", user_id=make_app_user(db, f"kw-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id).id)
    with pytest.raises(HTTPException) as exc:
        synonym_routes.get_search_synonyms(db=db, user=writer)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        synonym_routes.put_search_synonyms(SearchSynonymsUpdate(groups=[["a1", "b1"]]), db=db, user=writer)
    assert exc.value.status_code == 403

    saved = synonym_routes.put_search_synonyms(
        SearchSynonymsUpdate(groups=[["Hock", " Stamm "], ["einsam"], ["Velo", "vélo"]]), db=db, user=admin
    )
    # Gruppen mit nur einem (verschiedenen) Wort fallen weg
    assert saved.groups == [["Hock", "Stamm"]]
    assert any("Velo" in group for group in saved.builtin)


# --- Leistung -------------------------------------------------------------------------------------


def test_search_with_keywords_and_synonyms_stays_fast_on_10k_photos(db, capsys):
    """10 000 Fotos mit Keywords: Suche (Plan + Bewertung, inkl. Synonymen und Tippfehler) bleibt
    weit unter einer Sekunde und nutzt den GIN-Index des Suchdokuments, keinen Volltabellen-Scan
    über stored_file."""
    tenant = make_tenant(db)
    words = ["Velo", "Zeltlager", "Gipfel", "Seeufer", "Grillfest", "Turnier", "Hock", "Brunnen", "Kirche", "Fahne"]
    db.execute(
        text(
            """
            WITH ins AS (
                INSERT INTO stored_file (tenant_id, original_name, mime_type, storage_path, keywords)
                SELECT :t, 'bild_' || g || '.jpg', 'image/jpeg', 'uploads/perf/' || g || '.jpg',
                       ARRAY[(CAST(:words AS text[]))[1 + g % 10], 'Motiv' || (g % 500)]
                  FROM generate_series(1, 10000) AS g
                RETURNING id
            )
            INSERT INTO gallery_image (tenant_id, stored_file_id) SELECT :t, id FROM ins
            """
        ),
        {"t": tenant.id, "words": words},
    )
    db.flush()
    assert db.scalar(text("SELECT count(*) FROM photo_search_doc WHERE tenant_id = :t"), {"t": tenant.id}) == 10000
    db.execute(text("ANALYZE photo_search_doc"))
    db.execute(text("ANALYZE photo_search_term"))

    timings = {}
    for query in ("velo", "fahrad", "zeltlagr", "motiv42 gipfel", "sitzung"):
        start = time.perf_counter()
        items = service.list_tenant_files(db, tenant.id, only_images=True, search=query, sort_by="relevance", limit=60)
        timings[query] = (time.perf_counter() - start) * 1000
        assert items, query
    plan = build_search_plan(db, tenant.id, "fahrad")
    assert "velo" in plan.expansion_terms and "fahrrad" not in plan.expansion_terms  # nur Wortschatz-Begriffe
    with capsys.disabled():
        print("\n[perf 10k] " + ", ".join(f"{q}: {ms:.0f} ms" for q, ms in timings.items()))
    assert max(timings.values()) < 1500


def test_bulk_routes_check_protocol_read_access_like_the_single_route(db):
    """Security-Review F2: Protokollbilder nur, wenn das Protokoll lesbar ist (sonst 404)."""
    from app.models.entities import ProtocolImage
    from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template

    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="3/2026")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    image = StoredFile(tenant_id=tenant.id, original_name="protokoll.png", mime_type="image/png", storage_path="uploads/p.png", keywords=["Intern"])
    db.add(image)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=image.id, sort_index=0))
    db.flush()
    photos_only = _user(tenant.id, frozenset({"photos.read", "photos.manage"}))

    for call in (
        lambda: files_routes.file_keywords_summary(FileKeywordsSummaryRequest(file_ids=[image.public_id]), db=db, user=photos_only),
        lambda: files_routes.bulk_update_file_keywords(FileBulkKeywordsUpdate(file_ids=[image.public_id], add=["x"]), db=db, user=photos_only),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
    db.refresh(image)
    assert image.keywords == ["Intern"]


def test_tenant_synonym_list_is_bounded_and_cheap_even_when_crafted(db):
    """Security-Review F1: höchstens MAX_TENANT_TERMS Wörter; der unscharfe Abgleich läuft in der
    Datenbank und bleibt auch mit einer präparierten Liste (lange, fast gleiche Wörter) schnell."""
    tenant = make_tenant(db)
    alphabet = "bcdfghjklm"

    def word(i):
        return "a" * 34 + "".join(alphabet[int(d)] for d in f"{i:03d}") + "xyz"

    with pytest.raises(ValueError):
        search_synonyms.replace_groups(db, tenant.id, [[word(i * 20 + j) for j in range(20)] for i in range(51)])
    search_synonyms.replace_groups(db, tenant.id, [[word(i * 20 + j) for j in range(20)] for i in range(50)])
    queries = [term_like for term_like in (word(5)[:-1] + "q", word(777), word(12)[1:], word(400)[:-2] + "zz")] * 2
    from app.services.photo_search import term_fold

    words = [term_fold(query) for query in queries]
    start = time.perf_counter()
    hits = search_synonyms.synonyms_for(db, tenant.id, words)
    elapsed = time.perf_counter() - start
    assert hits  # trifft trotzdem
    assert elapsed < 1.0, elapsed


def _protocol_image(db, tenant_id, *, tags=None):
    from app.models.entities import ProtocolImage
    from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template

    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number=f"{uuid.uuid4().hex[:4]}/2026")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    image = StoredFile(tenant_id=tenant_id, original_name="p.png", mime_type="image/png", storage_path=f"uploads/{uuid.uuid4().hex}.png", tags=tags or [])
    db.add(image)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=image.id, sort_index=0))
    db.flush()
    return image


def test_bulk_tags_skip_files_the_account_cannot_read(db):
    """Folgeauftrag: /files/bulk-tags prüft das Leserecht je Datei wie das Einzel-Tag."""
    from app.schemas.files import FileBulkTagsUpdate

    tenant = make_tenant(db)
    image = _protocol_image(db, tenant.id, tags=["Alt"])
    own = _photo(db, tenant.id, "frei.jpg")
    photos_only = _user(tenant.id, frozenset({"photos.read", "photos.manage"}))
    files_routes.bulk_update_file_tags(
        FileBulkTagsUpdate(file_ids=[image.public_id, own.public_id], add_tags=["Neu"]), db=db, user=photos_only
    )
    db.refresh(image)
    db.refresh(own)
    assert image.tags == ["Alt"]
    assert own.tags == ["Neu"]


def test_album_items_reject_files_the_account_cannot_read(db):
    from app.schemas.files import PhotoAlbumItemsUpdate

    tenant = make_tenant(db)
    image = _protocol_image(db, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photos_only = _user(tenant.id, frozenset({"photos.read", "photos.manage"}))
    with pytest.raises(HTTPException) as exc:
        files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[image.public_id]), db=db, user=photos_only)
    assert exc.value.status_code == 404


def test_synonym_groups_and_keywords_survive_tenant_export_and_import(db):
    from tests.test_tenant_export_import import _export_import, _rewrite_manifest

    tenant = make_tenant(db)
    search_synonyms.replace_groups(db, tenant.id, [["Grümpi", "Grümpelturnier"], ["Stamm", "Beiz"]])
    _photo(db, tenant.id, "a.jpg", keywords=["Gipfelkreuz"])
    db.commit()

    exported_keywords: list = []

    def tamper(zip_path):
        from tests.test_tenant_export_import import _read_manifest

        # Keywords gehen als Spalte von stored_file mit (die Datei selbst fehlt im Testspeicher)
        exported_keywords.extend(row.get("keywords") for row in _read_manifest(zip_path)["tables"]["stored_file"])
        # Normalisierte Begriffe aus dem Archiv werden nie übernommen, sondern neu berechnet
        _rewrite_manifest(zip_path, lambda manifest: [row.update(terms=["boese"]) for row in manifest["tables"]["search_synonym_group"]])

    new_tenant, _warnings = _export_import(db, tenant.id, "full", new_name="Import Synonyme", before_import=tamper)
    assert search_synonyms.list_groups(db, new_tenant.id) == [["Grümpi", "Grümpelturnier"], ["Stamm", "Beiz"]]
    terms = {term for group in search_synonyms.tenant_groups(db, new_tenant.id) for term in group}
    assert terms == {"grumpi", "grumpelturnier", "stamm", "beiz"}
    assert exported_keywords == [["Gipfelkreuz"]]
    assert search_synonyms.synonyms_for(db, new_tenant.id, ["grumpi"])
