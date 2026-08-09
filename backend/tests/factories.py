"""Minimal ORM row builders for tests - not a full fixture framework, just enough to
satisfy FK constraints for the tables these tests actually touch."""
from datetime import date

from sqlalchemy import select

from app.core.security import CurrentUser
from app.models.entities import (
    AttendanceFine,
    ElementType,
    Event,
    FinanceAccount,
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    ProtocolTodo,
    RenderType,
    Template,
    TemplateParticipant,
    Tenant,
    TodoStatus,
    WordImportProfile,
)


def make_tenant(db, name="Test Tenant") -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    return tenant


def make_template(db, tenant_id: int, name="Test Template") -> Template:
    template = Template(tenant_id=tenant_id, name=name)
    db.add(template)
    db.flush()
    return template


def make_protocol(
    db,
    tenant_id: int,
    template_id: int,
    protocol_number: str = "P-1",
    protocol_date: date = date(2026, 1, 1),
    status: str = "geplant",
    track_changes_enabled: bool = True,
) -> Protocol:
    protocol = Protocol(
        tenant_id=tenant_id,
        template_id=template_id,
        template_version=1,
        protocol_number=protocol_number,
        protocol_date=protocol_date,
        status=status,
        track_changes_enabled=track_changes_enabled,
    )
    db.add(protocol)
    db.flush()
    return protocol


def make_finance_account(db, tenant_id: int, name="Test Account") -> FinanceAccount:
    account = FinanceAccount(tenant_id=tenant_id, name=name, currency_label="CHF")
    db.add(account)
    db.flush()
    return account


def make_list_definition(
    db,
    tenant_id: int,
    name: str = "Test List",
    column_one_title: str = "Name",
    column_one_value_type: str = "text",
    column_two_title: str = "Wert",
    column_two_value_type: str = "text",
) -> ListDefinition:
    definition = ListDefinition(
        tenant_id=tenant_id,
        name=name,
        column_one_title=column_one_title,
        column_one_value_type=column_one_value_type,
        column_two_title=column_two_title,
        column_two_value_type=column_two_value_type,
    )
    db.add(definition)
    db.flush()
    return definition


def make_list_entry(
    db,
    list_definition_id: int,
    sort_index: int = 0,
    column_one_value: dict | None = None,
    column_two_value: dict | None = None,
) -> ListEntry:
    entry = ListEntry(
        list_definition_id=list_definition_id,
        sort_index=sort_index,
        column_one_value_json=column_one_value or {},
        column_two_value_json=column_two_value or {},
    )
    db.add(entry)
    db.flush()
    return entry


def make_protocol_element(db, protocol_id: int, sort_index: int = 0, section_name: str = "Traktandum") -> ProtocolElement:
    element = ProtocolElement(protocol_id=protocol_id, sort_index=sort_index, section_name_snapshot=section_name)
    db.add(element)
    db.flush()
    return element


def make_protocol_element_block(
    db,
    protocol_element_id: int,
    configuration_snapshot_json: dict,
    sort_index: int = 0,
    element_type_code: str = "form",
) -> ProtocolElementBlock:
    element_type_id = db.scalar(select(ElementType.id).where(ElementType.code == element_type_code))
    render_type_id = db.scalar(select(RenderType.id))
    block = ProtocolElementBlock(
        protocol_element_id=protocol_element_id,
        element_type_id=element_type_id,
        render_type_id=render_type_id,
        title_snapshot="Test Block",
        is_editable_snapshot=True,
        sort_index=sort_index,
        configuration_snapshot_json=configuration_snapshot_json,
    )
    db.add(block)
    db.flush()
    return block


def make_protocol_text(db, protocol_element_block_id: int, content: str = "Hello") -> ProtocolText:
    protocol_text = ProtocolText(protocol_element_block_id=protocol_element_block_id, content=content)
    db.add(protocol_text)
    db.flush()
    return protocol_text


def make_protocol_todo(
    db,
    protocol_element_block_id: int,
    task: str = "Test Task",
    sort_index: int = 0,
    tenant_id: int | None = None,
) -> ProtocolTodo:
    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    todo = ProtocolTodo(
        tenant_id=tenant_id,
        protocol_element_block_id=protocol_element_block_id,
        sort_index=sort_index,
        task=task,
        todo_status_id=open_status_id,
    )
    db.add(todo)
    db.flush()
    return todo


def make_current_user(tenant_id: int, role: str = "writer", user_id: int = 1) -> CurrentUser:
    """A plain CurrentUser for calling route functions directly (bypassing Depends/auth
    entirely - route functions are still ordinary callables, no ASGI/TestClient needed)."""
    return CurrentUser(
        user_id=user_id,
        first_name="Test",
        last_name="User",
        display_name="Test User",
        email="test@example.com",
        preferred_language="de",
        is_participant_account=False,
        default_tenant_id=tenant_id,
        current_tenant_id=tenant_id,
        current_tenant_name="Test Tenant",
        current_tenant_profile_image_path=None,
        current_role=role,
        available_tenants=[],
    )


def make_participant(db, tenant_id: int, display_name: str = "Test Person") -> Participant:
    participant = Participant(tenant_id=tenant_id, display_name=display_name)
    db.add(participant)
    db.flush()
    return participant


def make_template_participant(db, template_id: int, participant_id: int, exclude_from_attendance: bool = False) -> TemplateParticipant:
    row = TemplateParticipant(template_id=template_id, participant_id=participant_id, exclude_from_attendance=exclude_from_attendance)
    db.add(row)
    db.flush()
    return row


def make_event(
    db,
    tenant_id: int,
    title: str = "Test Event",
    event_date: date = date(2026, 1, 1),
    event_category_id: int = 1,
) -> Event:
    # event_category is global seeded reference data (not tenant-scoped), id 1 ("camp")
    # already exists in every environment - no factory needed for it.
    event = Event(tenant_id=tenant_id, title=title, event_date=event_date, event_category_id=event_category_id)
    db.add(event)
    db.flush()
    return event


def make_word_import_profile(db, tenant_id: int, template_id: int, mapping_config_json: dict | None = None) -> WordImportProfile:
    profile = WordImportProfile(tenant_id=tenant_id, template_id=template_id, mapping_config_json=mapping_config_json or {})
    db.add(profile)
    db.flush()
    return profile


def make_fine(
    db,
    protocol_id: int,
    account_id: int,
    amount: float = 5.0,
    fine_type: str = "late",
    participant_name_snapshot: str = "Test Participant",
) -> AttendanceFine:
    fine = AttendanceFine(
        protocol_id=protocol_id,
        account_id=account_id,
        amount=amount,
        fine_type=fine_type,
        participant_name_snapshot=participant_name_snapshot,
    )
    db.add(fine)
    db.flush()
    return fine
