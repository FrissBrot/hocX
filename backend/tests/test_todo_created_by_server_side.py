"""Audit MAIN-SEC-010: created_by neuer Todos kommt vom angemeldeten Benutzer, nie aus dem
Request."""
from app.api.routes import todos as todos_routes
from app.models import ProtocolTodo
from app.schemas.protocol import ProtocolTodoCreate
from app.services.protocol_todo_service import ProtocolTodoService
from tests.factories import make_app_user, make_current_user, make_tenant


def test_client_supplied_created_by_is_ignored(db):
    tenant = make_tenant(db, "Eigener")
    other_tenant = make_tenant(db, "Fremder")
    actor = make_app_user(db, email="actor-sec010@example.com", tenant_id=tenant.id, role_code="writer")
    foreign = make_app_user(db, email="foreign-sec010@example.com", tenant_id=other_tenant.id, role_code="writer")
    user = make_current_user(tenant.id, role="writer", user_id=actor.id)

    item = todos_routes.create_standalone_todo(
        ProtocolTodoCreate(task="x", created_by=foreign.public_id), db=db, user=user
    )

    todo = db.query(ProtocolTodo).filter(ProtocolTodo.public_id == item.id).one()
    assert todo.created_by == actor.id


def test_actor_from_other_tenant_is_not_recorded(db):
    tenant = make_tenant(db, "Eigener 2")
    other_tenant = make_tenant(db, "Fremder 2")
    foreign = make_app_user(db, email="foreign2-sec010@example.com", tenant_id=other_tenant.id, role_code="writer")

    todo = ProtocolTodoService().create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="y"), actor_user_id=foreign.id)

    assert todo.created_by is None
