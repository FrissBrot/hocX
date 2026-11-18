"""SECURITY-DEFINER-Funktionen der öffentlichen Abgabebox nur für den Mandanten des gesetzten Links
(Migration 0183_abgabebox_link_scope).

0133_abgabebox_rls bindet die Rolle hocx_abgabebox an das Link-Token: wer den Dienst übernimmt,
soll ohne gültiges Token keinen anderen Mandanten erreichen. Ein paar Funktionen und ein
Spaltenrecht nahmen den Mandanten bzw. Speicherpräfix aber frei entgegen und umgingen so die RLS:
Speicherbelegung und Kontingent jedes Mandanten, Objektregister des Haupt-Namespace.

Die Funktionen erkennen die Rolle wie storage_active_config (0115) an `session_user`; deshalb
läuft die Probe hier mit SET LOCAL SESSION AUTHORIZATION statt nur SET LOCAL ROLE.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.entities import StoredFile
from app.schemas.submission import SubmissionLinkCreate
from app.services.submission_link_service import SubmissionLinkService
from tests.factories import make_tenant

links = SubmissionLinkService()


def _as_abgabebox(db, sql: str, params: dict | None = None, *, link_token: str | None = None):
    """(rows, None) oder (None, Fehlertext); SAVEPOINT-Rollback setzt Autorisierung und Fehlerzustand zurück."""
    connection = db.connection()
    connection.execute(text("SAVEPOINT abgabebox_function_probe"))
    try:
        connection.execute(text("SET LOCAL SESSION AUTHORIZATION hocx_abgabebox"))
        connection.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": link_token or ""})
        result = connection.execute(text(sql), params or {})
        return (result.all() if result.returns_rows else []), None
    except DBAPIError as exc:
        return None, str(exc.orig)
    finally:
        connection.execute(text("ROLLBACK TO SAVEPOINT abgabebox_function_probe"))


def _tenants_with_files(db):
    tenant, other = make_tenant(db), make_tenant(db)
    link = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)
    db.add_all([
        StoredFile(tenant_id=tenant.id, original_name="a.pdf", mime_type="application/pdf", storage_path="u/a.pdf", file_size_bytes=111),
        StoredFile(tenant_id=other.id, original_name="b.pdf", mime_type="application/pdf", storage_path="u/b.pdf", file_size_bytes=222_222),
    ])
    tenant.storage_quota_bytes = 5_000
    other.storage_quota_bytes = 9_999_999
    db.flush()
    return tenant, other, link


def test_storage_usage_only_for_the_tenant_of_the_link(db):
    tenant, other, link = _tenants_with_files(db)
    sql = "SELECT public.upload_storage_usage(:tenant_id)"

    rows, error = _as_abgabebox(db, sql, {"tenant_id": tenant.id}, link_token=link.token)
    assert error is None and rows[0][0] == 111

    rows, error = _as_abgabebox(db, sql, {"tenant_id": other.id}, link_token=link.token)
    assert rows is None and "not permitted" in error
    rows, error = _as_abgabebox(db, sql, {"tenant_id": tenant.id})
    assert rows is None and "not permitted" in error


def test_object_register_only_in_the_abgabebox_namespace_of_the_link(db):
    tenant, other, link = _tenants_with_files(db)
    usage = "SELECT public.storage_usage_bytes(:ns, :prefix)"

    for prefix in (f"tenant-{tenant.id}/", f"quarantine/tenant-{tenant.id}/"):
        rows, error = _as_abgabebox(db, usage, {"ns": "abgabebox", "prefix": prefix}, link_token=link.token)
        assert error is None and rows[0][0] == 0, prefix
    for namespace, prefix in (
        ("abgabebox", f"tenant-{other.id}/"),
        ("abgabebox", f"quarantine/tenant-{other.id}/"),
        ("abgabebox", "tenant-"),
        ("abgabebox", ""),
        ("main", f"uploads/tenant-{tenant.id}/"),
    ):
        rows, error = _as_abgabebox(db, usage, {"ns": namespace, "prefix": prefix}, link_token=link.token)
        assert rows is None and "not permitted" in error, (namespace, prefix)

    hold = "SELECT * FROM public.storage_backup_hold(:ns, 'x/y.pdf', 1)"
    # Quarantäne-Aufräumen läuft ohne Link: im eigenen Namespace weiter erlaubt.
    rows, error = _as_abgabebox(db, hold, {"ns": "abgabebox"})
    assert error is None
    rows, error = _as_abgabebox(db, hold, {"ns": "main"}, link_token=link.token)
    assert rows is None and "not permitted" in error


def test_quota_only_for_the_tenant_of_the_link(db):
    tenant, other, link = _tenants_with_files(db)

    rows, error = _as_abgabebox(db, "SELECT id, storage_quota_bytes FROM tenant", link_token=link.token)
    assert rows is None and "permission denied" in error

    rows, error = _as_abgabebox(db, "SELECT public.abgabebox_storage_quota()", link_token=link.token)
    assert error is None and rows[0][0] == 5_000
    rows, error = _as_abgabebox(db, "SELECT public.abgabebox_storage_quota()")
    assert error is None and rows[0][0] is None


def test_the_main_backend_keeps_using_the_functions_freely(db):
    tenant, other, _link = _tenants_with_files(db)
    assert db.scalar(text("SELECT public.upload_storage_usage(:t)"), {"t": other.id}) == 222_222
    assert db.scalar(text("SELECT public.storage_usage_bytes('main', '')")) >= 0
