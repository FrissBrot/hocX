"""Nachtlauf 2026-11-19 (Verdacht «LIKE ohne Escape»): Suchen mit Benutzereingabe behandelten % und _
als Platzhalter («_» fand alles). Alle Suchen bauen ihr Muster jetzt über app.core.sql_like."""

from sqlalchemy import select

from app.core.sql_like import LIKE_ESCAPE, contains_pattern, escape_like, prefix_pattern
from app.models import Tenant
from app.repositories.file_repository import StoredFileRepository
from app.repositories.protocol_repository import ProtocolRepository
from app.repositories.template_repository import TemplateRepository
from app.services.admin_tenant_service import AdminTenantService
from tests.document_support import gallery_document
from tests.factories import make_protocol, make_template, make_tenant


def test_helper_escapes_wildcards_and_the_escape_character():
    assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"
    assert contains_pattern("a_b") == "%a\\_b%"
    assert prefix_pattern("a%") == "a\\%%"


def test_helper_matches_literally_in_postgres(db):
    tenant = make_tenant(db, "Rabatt 50% a_b")
    other = make_tenant(db, "Rabatt 500 axb")

    def names(value):
        return set(db.scalars(select(Tenant.name).where(Tenant.id.in_([tenant.id, other.id]), Tenant.name.ilike(contains_pattern(value), escape=LIKE_ESCAPE))))

    assert names("50%") == {"Rabatt 50% a_b"}
    assert names("a_b") == {"Rabatt 50% a_b"}
    assert names("rabatt") == {"Rabatt 50% a_b", "Rabatt 500 axb"}


def test_template_search_treats_underscore_as_text(db):
    tenant = make_tenant(db)
    make_template(db, tenant.id, "Vorstand_Sitzung")
    make_template(db, tenant.id, "Vorstand Sitzung")

    names = [t.name for t in TemplateRepository().list(db, tenant_id=tenant.id, query="d_S")]

    assert names == ["Vorstand_Sitzung"]


def test_protocol_search_treats_percent_as_text(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    hit = make_protocol(db, tenant.id, template.id, protocol_number="P-1")
    hit.title = "Budget 100% genehmigt"
    miss = make_protocol(db, tenant.id, template.id, protocol_number="P-2")
    miss.title = "Budget 1000 offen"
    db.flush()

    ids = {p.id for p in ProtocolRepository().list(db, tenant_id=tenant.id, query="100%")}

    assert ids == {hit.id}


def test_admin_tenant_search_treats_underscore_as_text(db):
    marker = "zz_like_test"
    make_tenant(db, f"Verein {marker}")
    make_tenant(db, "Verein zzXlikeXtest")

    names = [item.name for item in AdminTenantService().list_tenants(db, q=marker).items]

    assert names == [f"Verein {marker}"]


def test_file_search_treats_underscore_as_text(db):
    tenant = make_tenant(db)
    gallery_document(db, tenant.id, "bericht_2026.txt", b"a", mime_type="text/plain")
    gallery_document(db, tenant.id, "berichtX2026.txt", b"b", mime_type="text/plain")

    rows = StoredFileRepository().list_tenant_files(db, tenant.id, search="t_2")

    assert [row.original_name for row in rows] == ["bericht_2026.txt"]
