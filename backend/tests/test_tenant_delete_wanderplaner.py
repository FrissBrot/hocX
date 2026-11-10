"""Mandantenlöschung räumt auch die Touren im Wanderplaner-Service ab - über delete_tenant, damit
jeder Weg (Admin-Route, Erasure-Replay nach einem Restore, Aufräumen eines Imports) es tut."""
from app.services import wanderplaner_client
from app.services.admin_tenant_service import AdminTenantService
from tests.factories import make_tenant


def test_delete_tenant_deletes_wanderplaner_data(db, monkeypatch):
    tenant = make_tenant(db)
    deleted = []
    monkeypatch.setattr(wanderplaner_client, "is_configured", lambda: True)
    monkeypatch.setattr(wanderplaner_client, "delete_tenant_data", lambda tenant_id: deleted.append(tenant_id))

    assert AdminTenantService().delete_tenant(db, tenant.id) is not None

    assert deleted == [tenant.id]


def test_wanderplaner_failure_does_not_block_tenant_deletion(db, monkeypatch):
    from app.services import admin_tenant_service

    tenant = make_tenant(db)
    logged = []

    def broken(tenant_id):
        raise wanderplaner_client.WanderplanerUnavailableError("nicht erreichbar (Test)")

    monkeypatch.setattr(wanderplaner_client, "is_configured", lambda: True)
    monkeypatch.setattr(wanderplaner_client, "delete_tenant_data", broken)
    monkeypatch.setattr(admin_tenant_service, "record_system_error", lambda db, **kw: logged.append(kw))

    assert AdminTenantService().delete_tenant(db, tenant.id) is not None

    assert [type(entry["exc"]) for entry in logged] == [wanderplaner_client.WanderplanerUnavailableError]
