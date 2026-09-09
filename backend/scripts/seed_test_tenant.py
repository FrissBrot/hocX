#!/usr/bin/env python3
"""(Re-)creates a fully populated demo tenant for manual QA on the test environment.

Idempotent: deletes the tenant named DEMO_TENANT_NAME (and everything under it) if it
already exists, then rebuilds it from scratch. Safe - and intended - to run on every test
deploy (see scripts/deploy.sh, environment == test only) so the test host always has a
realistic, fully-populated tenant to click through, independent of whatever manual testing
happened to leave behind on the previous candidate. Never wired into the prod deploy path.

Covers participants, a participant list, events, protocols with text/todo/image content,
a photo gallery, and a submission assignment with actual submitted files - the same
feature surface as backend/sql/baseline_demo_data.sql's dev-only fixture, but with real
content instead of bare structure, and buildable against a fresh test database that never
ran that dev-only fixture.

Usage: python scripts/seed_test_tenant.py (from /app inside the backend container/image).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.entities import (
    AppUser,
    CycleConfig,
    DocumentTemplate,
    ElementDefinition,
    Event,
    ListDefinition,
    ListEntry,
    Participant,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    ProtocolTodo,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    StoredFile,
    Template,
    TemplateElement,
    TemplateElementBlock,
    Tenant,
    UserTenantRole,
)
from app.schemas.list_definition import ListDefinitionCreate, ListEntryCreate
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.schemas.submission import SubmissionAssignmentCreate
from app.services.admin_tenant_service import AdminTenantService
from app.services.file_service import FileService
from app.services.list_service import ListService
from app.services.protocol_service import ProtocolService
from app.services.submission_service import SubmissionService

DEMO_TENANT_NAME = "Demo Pfadi Rueeblihausen"
DEMO_TENANT_SLUG = "demo"
DEMO_PASSWORD = "ChangeMe123!"
SEED_ASSETS_DIR = Path(__file__).resolve().parents[1] / "sql" / "seed_assets"

# element_type/render_type/role/todo_status/event_category ids: fixed lookup rows from
# sql/baseline_lookup_data.sql, always present regardless of environment.
ELEMENT_TYPE_TEXT = 1
ELEMENT_TYPE_TODO = 2
ELEMENT_TYPE_IMAGE = 3
RENDER_TYPE_PARAGRAPH = 2
RENDER_TYPE_TODO_LIST = 3
RENDER_TYPE_IMAGE = 4
ROLE_ADMIN = 1
ROLE_WRITER = 2
ROLE_READER = 3
ROLE_KASSIER = 4
TODO_STATUS_OPEN = 1
TODO_STATUS_DONE = 3
EVENT_CATEGORY_GROUP_SESSION = 2
EVENT_CATEGORY_CAMP = 1

PARTICIPANTS = [
    "Lea Baumgartner", "Noah Frei", "Mia Zbinden", "Luca Steiner", "Sina Kaufmann",
    "Yannick Suter", "Alina Moser", "Timo Wenger", "Nina Graf", "Elias Furrer",
    "Jana Brunner", "Sven Krähenbühl", "Fabienne Zurbriggen", "Dario Aebischer",
]

LEADERS = [
    ("Sarah", "Zimmermann", "admin"),
    ("Michael", "Berger", "writer"),
    ("Corinne", "Marti", "reader"),
    ("Reto", "Hofmann", "kassier"),
]


def log(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def wipe_existing_tenant(db) -> None:
    existing = db.query(Tenant).filter(Tenant.name == DEMO_TENANT_NAME).one_or_none()
    if existing is not None:
        log(f"Removing existing '{DEMO_TENANT_NAME}' (id={existing.id}) before reseeding")
        AdminTenantService().delete_tenant(db, existing.id)

    # AppUser.default_tenant_id is ON DELETE SET NULL, not CASCADE (a person can belong to
    # more than one tenant) - delete_tenant() above never removes the demo leaders
    # themselves, just orphans them. Their emails are exclusive to this demo tenant
    # (@demo.hocx.local), so it's safe to remove them outright rather than end up with
    # duplicate-email failures on every re-run.
    demo_emails = [f"{role_code}@{DEMO_TENANT_SLUG}.hocx.local" for _, _, role_code in LEADERS]
    db.query(AppUser).filter(AppUser.email.in_(demo_emails)).delete(synchronize_session=False)


def create_tenant_and_users(db) -> tuple[Tenant, dict[str, AppUser]]:
    tenant = Tenant(name=DEMO_TENANT_NAME, public_slug=DEMO_TENANT_SLUG)
    db.add(tenant)
    db.flush()

    password_hash = hash_password(DEMO_PASSWORD)
    users: dict[str, AppUser] = {}
    for first_name, last_name, role_code in LEADERS:
        user = AppUser(
            default_tenant_id=tenant.id,
            first_name=first_name,
            last_name=last_name,
            display_name=f"{first_name} {last_name}",
            email=f"{role_code}@{DEMO_TENANT_SLUG}.hocx.local",
            password_hash=password_hash,
            is_active=True,
        )
        db.add(user)
        db.flush()
        role_id = {"admin": ROLE_ADMIN, "writer": ROLE_WRITER, "reader": ROLE_READER, "kassier": ROLE_KASSIER}[role_code]
        db.add(UserTenantRole(user_id=user.id, tenant_id=tenant.id, role_id=role_id, is_active=True))
        users[role_code] = user
    db.flush()
    return tenant, users


def create_template_structure(db, tenant: Tenant, created_by: AppUser) -> Template:
    cycle_config = CycleConfig(tenant_id=tenant.id, name="Vereinsjahr", reset_month=7, reset_day=31)
    db.add(cycle_config)
    db.flush()

    document_template = DocumentTemplate(
        tenant_id=tenant.id,
        code="default_protocol",
        name="Standardprotokoll",
        description="Dateisystembasierte Starter-LaTeX-Vorlage",
        filesystem_path="/app/storage/latex_templates/default_protocol/v1",
        version=1,
        is_active=True,
        is_default=True,
        configuration_json={
            "slots": {},
            "theme": {"font_size": "11pt", "font_family": "default", "primary_color": "A83F2F", "secondary_color": "6F675D"},
            "options": {"show_toc": True, "numbering_mode": "sections"},
        },
    )
    db.add(document_template)
    db.flush()

    template = Template(
        tenant_id=tenant.id,
        document_template_id=document_template.id,
        name="Sitzungsprotokoll",
        description="Vorlage fuer die woechentliche Vorstandssitzung",
        protocol_number_pattern="Sitzung {n}",
        title_pattern="Sitzung {n} - {date:DD.MM.YYYY}",
        auto_create_next_protocol=False,
        cycle_config_id=cycle_config.id,
        created_by=created_by.id,
    )
    db.add(template)
    db.flush()

    text_def = ElementDefinition(
        tenant_id=tenant.id, element_type_id=ELEMENT_TYPE_TEXT, render_type_id=RENDER_TYPE_PARAGRAPH,
        title="Besprechung", display_title="Besprechung", description="Freitext fuer die Sitzungsnotizen",
        is_editable=True, allows_multiple_values=False, export_visible=True, latex_template="elements/paragraph.tex",
        configuration_json={"blocks": [{"id": 1, "title": "Besprechungstext", "block_title": "Besprechungstext",
                                         "render_type_id": RENDER_TYPE_PARAGRAPH, "element_type_id": ELEMENT_TYPE_TEXT,
                                         "is_visible": True, "is_editable": True, "export_visible": True,
                                         "sort_index": 10, "render_order": 10, "default_content": "",
                                         "configuration_json": {}, "allows_multiple_values": False}]},
    )
    todo_def = ElementDefinition(
        tenant_id=tenant.id, element_type_id=ELEMENT_TYPE_TODO, render_type_id=RENDER_TYPE_TODO_LIST,
        title="Offene Punkte", display_title="Offene Punkte", description="Pendenzenliste",
        is_editable=True, allows_multiple_values=True, export_visible=True, latex_template="elements/todo_list.tex",
        configuration_json={"blocks": [{"id": 1, "title": "Offene Punkte", "block_title": "Offene Punkte",
                                         "render_type_id": RENDER_TYPE_TODO_LIST, "element_type_id": ELEMENT_TYPE_TODO,
                                         "is_visible": True, "is_editable": True, "export_visible": True,
                                         "sort_index": 10, "render_order": 10, "default_content": "",
                                         "configuration_json": {}, "allows_multiple_values": True}]},
    )
    image_def = ElementDefinition(
        tenant_id=tenant.id, element_type_id=ELEMENT_TYPE_IMAGE, render_type_id=RENDER_TYPE_IMAGE,
        title="Bilder", display_title="Bilder", description="Fotos zu dieser Sitzung",
        is_editable=True, allows_multiple_values=True, export_visible=True, latex_template="elements/image.tex",
        configuration_json={"blocks": [{"id": 1, "title": "Bilder", "block_title": "Bilder",
                                         "render_type_id": RENDER_TYPE_IMAGE, "element_type_id": ELEMENT_TYPE_IMAGE,
                                         "is_visible": True, "is_editable": True, "export_visible": True,
                                         "sort_index": 10, "render_order": 10, "default_content": "",
                                         "configuration_json": {}, "allows_multiple_values": True}]},
    )
    db.add_all([text_def, todo_def, image_def])
    db.flush()

    for sort_index, (section_name, section_order, definition, block_title) in enumerate([
        ("Besprechung", 1, text_def, "Besprechungstext"),
        ("Offene Punkte", 2, todo_def, "Offene Punkte"),
        ("Bilder", 3, image_def, "Bilder"),
    ], start=1):
        template_element = TemplateElement(
            template_id=template.id, element_definition_id=definition.id, sort_index=sort_index * 10,
            section_name=section_name, section_order=section_order, is_visible=True, export_visible=True,
        )
        db.add(template_element)
        db.flush()
        db.add(TemplateElementBlock(
            template_element_id=template_element.id, element_definition_id=definition.id, sort_index=10,
            render_order=10, block_title=block_title, is_visible=True, export_visible=True,
        ))
    db.flush()
    return template


def create_participants(db, tenant: Tenant) -> list[Participant]:
    participants = []
    for name in PARTICIPANTS:
        first_name, last_name = name.split(" ", 1)
        participant = Participant(
            tenant_id=tenant.id, first_name=first_name, last_name=last_name, display_name=name, is_active=True,
            joined_at=date.today() - timedelta(days=365 * 2),
        )
        db.add(participant)
        participants.append(participant)
    db.flush()
    return participants


def create_participant_list(db, tenant: Tenant, participants: list[Participant]) -> ListDefinition:
    ListService().create_definition(
        db,
        ListDefinitionCreate(
            name="Mitgliederliste",
            description="Alle aktiven Teilnehmenden der Gruppe",
            column_one_title="Name",
            column_one_value_type="participant",
            column_two_title="Bemerkung",
            column_two_value_type="text",
        ),
        tenant_id=tenant.id,
    )
    list_definition = db.query(ListDefinition).filter(ListDefinition.tenant_id == tenant.id, ListDefinition.name == "Mitgliederliste").one()
    remarks = ["Neu dazugestossen", "", "Leitungsteam-Nachwuchs", "", "", "Zieht Ende Jahr weg", "", "", "", "", "", "", "", ""]
    for index, (participant, remark) in enumerate(zip(participants, remarks)):
        ListService().create_entry(
            db,
            list_definition.id,
            ListEntryCreate(
                sort_index=index,
                column_one_value={"participant_id": str(participant.public_id)},
                column_two_value={"text_value": remark},
            ),
        )
    db.flush()
    return list_definition


def create_events(db, tenant: Tenant) -> list[Event]:
    today = date.today()
    specs = [
        (today - timedelta(days=180), None, "Gruppenstunde: Feuer machen", EVENT_CATEGORY_GROUP_SESSION),
        (today - timedelta(days=166), None, "Gruppenstunde: Knoten und Seile", EVENT_CATEGORY_GROUP_SESSION),
        (today - timedelta(days=90), today - timedelta(days=83), "Sommerlager Rueeblihausen", EVENT_CATEGORY_CAMP),
        (today - timedelta(days=42), None, "Gruppenstunde: Nachlager-Auswertung", EVENT_CATEGORY_GROUP_SESSION),
        (today - timedelta(days=14), None, "Gruppenstunde: Spielabend", EVENT_CATEGORY_GROUP_SESSION),
        (today + timedelta(days=7), None, "Gruppenstunde: Planung Herbstausflug", EVENT_CATEGORY_GROUP_SESSION),
        (today + timedelta(days=30), today + timedelta(days=31), "Herbstausflug", EVENT_CATEGORY_CAMP),
    ]
    events = []
    for event_date, event_end_date, title, category_id in specs:
        event = Event(
            tenant_id=tenant.id, event_date=event_date, event_end_date=event_end_date,
            event_category_id=category_id, title=title, description=f"{title} - automatisch angelegte Demo-Daten.",
        )
        db.add(event)
        events.append(event)
    db.flush()
    return events


def _block_by_title(db, protocol_id: int, block_title: str) -> ProtocolElementBlock:
    return (
        db.query(ProtocolElementBlock)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .filter(ProtocolElement.protocol_id == protocol_id, ProtocolElementBlock.block_title_snapshot == block_title)
        .one()
    )


def create_protocols(db, tenant: Tenant, template: Template, events: list[Event], leader: AppUser, photo_paths: list[Path]) -> None:
    service = ProtocolService()
    file_service = FileService()
    session_events = [e for e in events if e.event_date <= date.today()][:3]
    protocol_contents = [
        (
            "Traktandenliste besprochen, Budget fuers Herbstlager verabschiedet. "
            "Alle Gruppenleitenden bestaetigen ihre Teilnahme am naechsten Weiterbildungstag."
        ),
        (
            "Rueckblick auf das Sommerlager: durchwegs positives Feedback von Teilnehmenden und Eltern. "
            "Kueche und Programm werden fuers naechste Mal in der bisherigen Form uebernommen."
        ),
        (
            "Planung des Spielabends abgeschlossen. Vorschlag fuer neue T-Shirts wird an der naechsten "
            "Sitzung dem gesamten Team praesentiert."
        ),
    ]
    todo_specs = [
        [("Offerten fuer Zelte einholen", TODO_STATUS_OPEN), ("Kuechenteam fuers Herbstlager anfragen", TODO_STATUS_OPEN)],
        [("Dankesbrief an Elternrat verschicken", TODO_STATUS_DONE), ("Fotos aus dem Lager sichten und hochladen", TODO_STATUS_OPEN)],
        [("Material fuer Spielabend einkaufen", TODO_STATUS_OPEN)],
    ]
    photo_index = 0
    for i, event in enumerate(session_events):
        protocol_id = service.create_from_template(
            db,
            ProtocolCreateFromTemplate(template_id=template.public_id, protocol_date=event.event_date, event_id=event.public_id),
            tenant_id=tenant.id,
            created_by=leader.id,
        )
        db.flush()

        text_block = _block_by_title(db, protocol_id, "Besprechungstext")
        protocol_text = db.query(ProtocolText).filter(ProtocolText.protocol_element_block_id == text_block.id).one()
        protocol_text.content = protocol_contents[i % len(protocol_contents)]

        todo_block = _block_by_title(db, protocol_id, "Offene Punkte")
        # create_from_template already rolled any still-open todos from the previous
        # protocol's same block forward (see ProtocolService._open_todos_for_template_block)
        # - append after those instead of assuming the block starts empty.
        next_sort_index = (
            db.query(ProtocolTodo.sort_index)
            .filter(ProtocolTodo.protocol_element_block_id == todo_block.id)
            .count()
        )
        for offset, (task, status_id) in enumerate(todo_specs[i % len(todo_specs)]):
            db.add(ProtocolTodo(
                tenant_id=tenant.id, protocol_element_block_id=todo_block.id, sort_index=next_sort_index + offset,
                task=task, todo_status_id=status_id,
            ))

        image_block = _block_by_title(db, protocol_id, "Bilder")
        for _ in range(2):
            if photo_index >= len(photo_paths):
                break
            photo_path = photo_paths[photo_index]
            photo_index += 1
            upload = UploadFile(file=open(photo_path, "rb"), filename=photo_path.name, headers=Headers({"content-type": "image/jpeg"}))
            asyncio.run(file_service.save_protocol_image(
                db, protocol_element_block=image_block, file=upload,
                title=photo_path.stem.replace("photo-", "").replace("-", " ").title(),
                caption=None, created_by=leader.id,
            ))
        db.flush()


def create_gallery(db, tenant: Tenant, leader: AppUser, photo_paths: list[Path]) -> None:
    file_service = FileService()
    payloads = [(p.name, p.read_bytes()) for p in photo_paths]
    items, errors = file_service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=payloads, tags=["Sommerlager"], created_by=leader.id,
    )
    if errors:
        log(f"Gallery upload warnings: {errors}")
    db.flush()


def create_submission_assignment(db, tenant: Tenant, list_definition: ListDefinition) -> None:
    SubmissionService().create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Fotos vom Sommerlager hochladen",
            description="Bitte alle Fotos vom Sommerlager hier hochladen, damit wir sie fuers Jahresheft verwenden koennen.",
            public_slug="fotos-sommerlager",
            source_type="list",
            list_definition_id=list_definition.public_id,
            allowed_file_types=["jpg", "jpeg", "png", "pdf"],
            max_files_per_element=10,
            max_file_size_mb=20,
        ),
        tenant_id=tenant.id,
    )
    assignment = db.query(SubmissionAssignment).filter(SubmissionAssignment.tenant_id == tenant.id, SubmissionAssignment.public_slug == "fotos-sommerlager").one()

    entries = db.query(ListEntry).filter(ListEntry.list_definition_id == list_definition.id).order_by(ListEntry.sort_index).limit(4).all()
    demo_photos = sorted((SEED_ASSETS_DIR / "photos").glob("*.jpg"))[-3:]
    # Last entry submits the PDF instead of a photo, so "Dateien" (non-image files) has a
    # real example too, not just an empty page.
    submitted_files = demo_photos + [SEED_ASSETS_DIR / "anmeldeformular.pdf"]

    for index, entry in enumerate(entries):
        upload = SubmissionUpload(assignment_id=assignment.id, list_entry_id=entry.id, status="submitted")
        db.add(upload)
        db.flush()

        file_path = submitted_files[index]
        content = file_path.read_bytes()
        mime_type = "application/pdf" if file_path.suffix == ".pdf" else "image/jpeg"
        stored_file = StoredFile(
            tenant_id=tenant.id, original_name=file_path.name, mime_type=mime_type,
            storage_path=f"demo-seed/{file_path.name}", file_size_bytes=len(content), scan_status="clean",
        )
        db.add(stored_file)
        db.flush()

        target_dir = Path(settings.abgabebox_storage_root) / "demo-seed"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / file_path.name).write_bytes(content)

        db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.flush()


def main() -> None:
    db = SessionLocal()
    try:
        wipe_existing_tenant(db)
        db.commit()

        tenant, users = create_tenant_and_users(db)
        log(f"Created tenant '{tenant.name}' (id={tenant.id})")

        template = create_template_structure(db, tenant, users["admin"])
        participants = create_participants(db, tenant)
        list_definition = create_participant_list(db, tenant, participants)
        events = create_events(db, tenant)
        db.commit()

        photo_paths = sorted((SEED_ASSETS_DIR / "photos").glob("*.jpg"))
        create_protocols(db, tenant, template, events, users["admin"], list(photo_paths))
        db.commit()

        create_gallery(db, tenant, users["writer"], list(photo_paths[:5]))
        db.commit()

        create_submission_assignment(db, tenant, list_definition)
        db.commit()

        log(f"Demo tenant '{DEMO_TENANT_NAME}' seeded successfully.")
        log(f"Login: admin@{DEMO_TENANT_SLUG}.hocx.local / writer@{DEMO_TENANT_SLUG}.hocx.local / "
            f"reader@{DEMO_TENANT_SLUG}.hocx.local / kassier@{DEMO_TENANT_SLUG}.hocx.local, password: {DEMO_PASSWORD}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
