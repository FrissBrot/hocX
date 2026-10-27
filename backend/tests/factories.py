"""Minimal ORM row builders for tests - not a full fixture framework, just enough to
satisfy FK constraints for the tables these tests actually touch."""
import uuid
from datetime import date

from sqlalchemy import delete, select

from app.core.secret_crypto import encrypt_secret
from app.core.permissions import SYSTEM_ROLE_PERMISSIONS, expand
from app.core.security import CurrentUser, hash_password
from app.core.totp import generate_totp_secret
from app.models.entities import (
    AppUser,
    AttendanceFine,
    CycleConfig,
    ElementDefinition,
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
    TemplateElement,
    TemplateParticipant,
    Tenant,
    TenantDomain,
    TenantFeature,
    TenantRole,
    TodoStatus,
    UserMfaFactor,
    UserRole,
    WordImportProfile,
)


# Bis 0158 frei verfügbar, seither buchbar - Bestandsmandanten haben sie per Backfill
GRANDFATHERED_FEATURES = ("task_packages", "custom_roles", "photo_sharing", "document_designer")


def make_tenant(db, name="Test Tenant", *, features: tuple[str, ...] = GRANDFATHERED_FEATURES) -> Tenant:
    """Mandant wie ein Bestandsmandant: mit den seit 0158 buchbaren Features (Bestandsschutz).
    finance/abgabebox/custom_domain bleiben wie bisher ungebucht (grant_tenant_feature)."""
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    for code in features:
        db.add(TenantFeature(tenant_id=tenant.id, feature_code=code))
    if features:
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
    """tenant_id muss nur für Todos ohne Block angegeben werden; bei Todos mit Block setzt ihn die
    Datenbank aus dem Protokoll (Migration 0131_todo_tenant_id)."""
    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    todo = ProtocolTodo(
        protocol_element_block_id=protocol_element_block_id,
        sort_index=sort_index,
        task=task,
        todo_status_id=open_status_id,
    )
    if tenant_id is not None:
        todo.tenant_id = tenant_id
    db.add(todo)
    db.flush()
    return todo


def system_role(db, tenant_id: int, code: str) -> TenantRole:
    """Standardrollen (admin/writer/kassier/reader) legt der Trigger beim Anlegen jedes Mandanten
    an (Migration 0156_rbac) - Tests legen sie nie selbst an, sie schlagen sie nur nach."""
    return db.scalar(select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.system_key == code))


def assign_roles(db, user: AppUser, *codes: str) -> AppUser:
    """Ersetzt die Rollen eines Kontos durch die Standardrollen ``codes`` (ohne Schutzregeln)."""
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for code in codes:
        db.add(UserRole(tenant_id=user.tenant_id, user_id=user.id, role_id=system_role(db, user.tenant_id, code).id))
    db.flush()
    return user


def make_app_user(
    db,
    email: str = "test@example.com",
    password: str = "correct horse battery staple",
    is_active: bool = True,
    first_name: str = "Test",
    last_name: str = "User",
    *,
    tenant_id: int | None = None,
    role_code: str = "reader",
) -> AppUser:
    """A user always belongs to exactly one tenant; role_code is the standard role it gets
    (see assign_roles for several). Without an explicit tenant_id the user gets a fresh tenant of
    their own, so tests that don't care which tenant they are in stay a one-liner."""
    if tenant_id is None:
        tenant_id = make_tenant(db, f"Tenant of {email}").id
    user = AppUser(
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(password),
        login_enabled=True,
        first_name=first_name,
        last_name=last_name,
        display_name=f"{first_name} {last_name}",
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return assign_roles(db, user, role_code)


def make_mfa_enrolled_user(
    db,
    email: str = "mfa-test@example.com",
    password: str = "correct horse battery staple",
    *,
    tenant_id: int | None = None,
    role_code: str = "admin",
) -> tuple[AppUser, str]:
    """An AppUser with a TOTP factor already enrolled - mirrors what
    MfaService._complete_totp_enrollment persists, so tests can exercise the "MFA verification
    required" login branch (mfa_service.prepare_login) directly, without driving the
    interactive QR-code enrollment flow first.

    Returns (user, raw_secret): pass raw_secret to app.core.totp.current_totp_code(secret) to
    compute a valid 6-digit code for AuthService.verify_login_totp()/MfaService.verify_login_totp()
    at the point of use (a code is only valid for a ~30s window, so don't compute it ahead of
    time)."""
    user = make_app_user(db, email=email, password=password, tenant_id=tenant_id, role_code=role_code)
    secret = generate_totp_secret()
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Test Authenticator",
            secret_encrypted=encrypt_secret(secret),
            totp_last_counter=0,
        )
    )
    user.preferred_mfa_factor_type = "totp"
    db.flush()
    return user, secret


# Bestehende Mandanten haben per Backfill alle Features ausser verify_domain (0084-0086, 0158)
DEFAULT_TEST_FEATURES = frozenset({"finance", "abgabebox", "custom_domain", "task_packages", "custom_roles", "photo_sharing", "document_designer"})


def make_current_user(
    tenant_id: int,
    role: str = "writer",
    user_id: int = 1,
    features: frozenset[str] | None = None,
    *,
    permissions: frozenset[str] | None = None,
) -> CurrentUser:
    """A plain CurrentUser for calling route functions directly (bypassing Depends/auth
    entirely - route functions are still ordinary callables, no ASGI/TestClient needed).

    user_id/tenant_id are frequently synthetic ints with no backing row (see e.g.
    user_id=999 in test_audit_2026_08_12_high_fixes_B.py), so there's no real row to
    resolve a public_id from here - the *_public_id fields below are just fresh random
    UUIDs, consistent with this factory's existing "plain, not DB-backed" contract. Route
    logic under test cares about the internal ids (tenant isolation, role checks); tests
    that need a public_id to line up with a real row already fetch it themselves from the
    ORM object made via make_tenant/make_app_user.

    features defaults to DEFAULT_TEST_FEATURES rather than empty - every existing tenant is
    backfilled with these (see migrations 0084_tenant_feature/0085_plan_pricing/
    0086_custom_domain_enforcement/0158_feature_entitlements), so this default keeps
    every pre-existing role/permission test green without needing to know about feature-gating.
    Tests for feature-gating itself pass an explicit `features` set."""
    return CurrentUser(
        user_id=user_id,
        user_public_id=uuid.uuid4(),
        first_name="Test",
        last_name="User",
        display_name="Test User",
        email="test@example.com",
        preferred_language="de",
        current_tenant_id=tenant_id,
        current_tenant_public_id=uuid.uuid4(),
        current_tenant_name="Test Tenant",
        current_tenant_profile_image_path=None,
        current_tenant_features=features if features is not None else DEFAULT_TEST_FEATURES,
        # role: eine Standardrolle (admin/writer/kassier/reader) als Abkürzung für ihre
        # Berechtigungen; permissions überschreibt das für eigene Rollen (RBAC-Tests).
        permissions=permissions if permissions is not None else system_role_permissions(role),
    )


def system_role_permissions(*roles: str) -> frozenset[str]:
    """Effektive Berechtigungen einer Kombination von Standardrollen (Vereinigungsmenge)."""
    result: set[str] = set()
    for role in roles:
        result |= {str(key) for key in SYSTEM_ROLE_PERMISSIONS.get(role, frozenset())}
    return frozenset(str(key) for key in expand(result))


def make_cycle_config(
    db,
    tenant_id: int,
    name: str = "Test Cycle",
    reset_month: int = 12,
    reset_day: int = 31,
) -> CycleConfig:
    cycle_config = CycleConfig(tenant_id=tenant_id, name=name, reset_month=reset_month, reset_day=reset_day)
    db.add(cycle_config)
    db.flush()
    return cycle_config


def make_participant(db, tenant_id: int, display_name: str = "Test Person") -> Participant:
    participant = Participant(tenant_id=tenant_id, display_name=display_name, login_enabled=False)
    db.add(participant)
    db.flush()
    assign_roles(db, participant, "reader")
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
    event_end_date: date | None = None,
    event_category_id: int = 1,
    is_cancelled: bool = False,
) -> Event:
    # event_category is global seeded reference data (not tenant-scoped), id 1 ("camp")
    # already exists in every environment - no factory needed for it.
    event = Event(
        tenant_id=tenant_id,
        title=title,
        event_date=event_date,
        event_end_date=event_end_date,
        event_category_id=event_category_id,
        is_cancelled=is_cancelled,
    )
    db.add(event)
    db.flush()
    return event


def element_type_id(db, code: str) -> int:
    return db.scalar(select(ElementType.id).where(ElementType.code == code))


def make_element_definition(
    db,
    tenant_id: int,
    title: str,
    blocks: list[dict],
    element_type_id_: int = 1,
    render_type_id: int = 2,
) -> ElementDefinition:
    definition = ElementDefinition(
        tenant_id=tenant_id,
        element_type_id=element_type_id_,
        render_type_id=render_type_id,
        title=title,
        is_editable=True,
        configuration_json={"blocks": blocks},
    )
    db.add(definition)
    db.flush()
    return definition


def make_template_element(
    db,
    template_id: int,
    element_definition_id: int,
    sort_index: int,
    section_name: str,
    configuration_json: dict | None = None,
) -> TemplateElement:
    entity = TemplateElement(
        template_id=template_id,
        element_definition_id=element_definition_id,
        sort_index=sort_index,
        section_name=section_name,
        configuration_json=configuration_json or {},
    )
    db.add(entity)
    db.flush()
    return entity


def make_word_import_profile(db, tenant_id: int, template_id: int, mapping_config_json: dict | None = None) -> WordImportProfile:
    profile = WordImportProfile(tenant_id=tenant_id, template_id=template_id, mapping_config_json=mapping_config_json or {})
    db.add(profile)
    db.flush()
    return profile


def make_tenant_domain(
    db,
    tenant_id: int,
    domain: str = "example.org",
    purpose: str = "app",
    status: str = "active",
) -> TenantDomain:
    row = TenantDomain(
        tenant_id=tenant_id,
        purpose=purpose,
        domain=domain,
        verification_token=uuid.uuid4().hex,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def grant_tenant_feature(db, tenant_id: int, feature_code: str = "custom_domain") -> TenantFeature:
    """A real `tenant_feature` DB row - distinct from `make_current_user`'s
    `current_tenant_features` frozenset, which only fakes what a request-scoped `CurrentUser`
    saw and is never read by code that queries the table directly (e.g.
    traefik_config_service.tenant_ids_with_custom_domain_feature)."""
    row = TenantFeature(tenant_id=tenant_id, feature_code=feature_code)
    db.add(row)
    db.flush()
    return row


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
