"""Kontext-Freigaben: wer sieht welche Dateien (Plan «Berechtigungen», Phase 5, Migration 0196).

Ebene 2 neben den Rollenrechten: ein Kontext (Abgabe, Album; Protokolle fest «nur Rolle») kann
seine Dateien zusätzlich für Konten ohne passendes Rollenrecht freigeben.

Regeln:
- **Nur additiv und nur lesend.** ``context_grant_allows`` wird erst gefragt, wenn die
  Rollenprüfung (access_service.ensure_can_read_stored_file) ablehnt; Schreibrouten fragen sie nie.
- **Objekt-Override vor Modul-Standard:** für eine Abgabe gilt die Zeile des Auftrags, sonst der
  Standard des Moduls; fehlt auch der (Mandant ohne Seed), gilt ``DEFAULTS`` (nur Rolle).
- ``all_participants``: jedes Konto mit Login dieses Mandanten (eine Session gibt es nur mit
  Login - Teilnehmende ohne Login sehen nie etwas). ``own_submissions``: nur Dateien von Elementen,
  für die das Konto verantwortlich ist (Quelle der Verantwortlichen oder zugewiesene Aufgabe,
  gleiche Regel wie der persönliche Abgabe-Link). ``images``: nur ``image/*``.
- Zurückgezogene und gelöschte Einreichungen sowie fremde Mandanten sind nie freigegeben.
- Eine Datei kann in mehreren Kontexten verknüpft sein (Phase 2): freigegeben ist sie, wenn einer
  davon sie freigibt.

Zusätzlich hier: die Reichweite «nur zugewiesene» (Phase 4) für Abgabe-Dateien ausserhalb der
Abgabe-Routen (``readable_assignment_ids``/``abgabe_scope_allows``, Security-Review Phase 4).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import BigInteger, Text, and_, cast, exists, false, null, or_, select, union_all
from sqlalchemy.orm import Session

from app.core.permissions import P
from app.core.security import CurrentUser
from app.models import ContextVisibility, GalleryImage, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile

MODULES = ("abgabe", "protokoll", "album")
AUDIENCES = ("role_only", "all_participants", "own_submissions")
FILE_FILTERS = ("all", "images")


@dataclass(frozen=True)
class Rule:
    audience: str
    file_filter: str

    def as_dict(self) -> dict[str, str]:
        return {"audience": self.audience, "file_filter": self.file_filter}


# Gleich wie der Seed der Migration 0196: nichts zusätzlich sichtbar
DEFAULTS = {
    "abgabe": Rule("role_only", "images"),
    "protokoll": Rule("role_only", "all"),
    "album": Rule("role_only", "all"),
}


def validate(module: str, rule: Rule, *, override: bool = False) -> None:
    """Gleiche Regeln wie die CHECKs der Tabelle - als ValueError für eine 400 statt 500."""
    if module not in MODULES:
        raise ValueError("Unbekanntes Modul")
    if rule.audience not in AUDIENCES or rule.file_filter not in FILE_FILTERS:
        raise ValueError("Ungültige Freigabe")
    if module == "protokoll" and rule.audience != "role_only":
        raise ValueError("Protokoll-Dateien folgen immer dem Protokoll")
    if rule.audience == "own_submissions" and module != "abgabe":
        raise ValueError("«Eigene Einreichungen» gibt es nur bei Abgaben")
    if override and module != "abgabe":
        raise ValueError("Überschreiben ist nur je Abgabe-Auftrag möglich")


# ── Lesen ───────────────────────────────────────────────────────────────────────────────────


def module_rules(db: Session, tenant_id: int) -> dict[str, Rule]:
    rows = db.scalars(
        select(ContextVisibility).where(ContextVisibility.tenant_id == tenant_id, ContextVisibility.context_id.is_(None))
    ).all()
    rules = dict(DEFAULTS)
    for row in rows:
        rules[row.module] = Rule(row.audience, row.file_filter)
    return rules


def assignment_overrides(db: Session, tenant_id: int, assignment_ids: list[int] | None = None) -> dict[int, Rule]:
    statement = select(ContextVisibility).where(
        ContextVisibility.tenant_id == tenant_id, ContextVisibility.module == "abgabe", ContextVisibility.context_id.is_not(None),
    )
    if assignment_ids is not None:
        if not assignment_ids:
            return {}
        statement = statement.where(ContextVisibility.context_id.in_(assignment_ids))
    return {row.context_id: Rule(row.audience, row.file_filter) for row in db.scalars(statement)}


def effective_assignment_rule(db: Session, tenant_id: int, assignment_id: int) -> Rule:
    override = assignment_overrides(db, tenant_id, [assignment_id]).get(assignment_id)
    return override or module_rules(db, tenant_id)["abgabe"]


def any_submission_grant(db: Session, tenant_id: int) -> bool:
    """Gibt der Mandant irgendwo Abgabe-Dateien frei? (Menüpunkt «Fotos aus Abgaben»)"""
    rules = module_rules(db, tenant_id)
    if rules["abgabe"].audience != "role_only":
        return True
    return db.scalar(
        select(ContextVisibility.id).where(
            ContextVisibility.tenant_id == tenant_id, ContextVisibility.module == "abgabe",
            ContextVisibility.context_id.is_not(None), ContextVisibility.audience != "role_only",
        ).limit(1)
    ) is not None


# ── Schreiben (nur aus den Routen mit settings.manage bzw. submissions.manage) ──────────────────


def _upsert(db: Session, *, tenant_id: int, module: str, context_id: int | None, rule: Rule, user_id: int | None) -> None:
    row = db.scalar(
        select(ContextVisibility).where(
            ContextVisibility.tenant_id == tenant_id, ContextVisibility.module == module,
            ContextVisibility.context_id.is_(None) if context_id is None else ContextVisibility.context_id == context_id,
        )
    )
    if row is None:
        db.add(ContextVisibility(
            tenant_id=tenant_id, module=module, context_id=context_id, audience=rule.audience, file_filter=rule.file_filter, updated_by=user_id,
        ))
    else:
        row.audience, row.file_filter, row.updated_by = rule.audience, rule.file_filter, user_id
    db.flush()


def set_module_rule(db: Session, user: CurrentUser, module: str, rule: Rule) -> tuple[Rule, Rule]:
    """Modul-Standard setzen (ohne Commit). Liefert (vorher, nachher) für das Audit."""
    validate(module, rule)
    before = module_rules(db, user.current_tenant_id)[module]
    _upsert(db, tenant_id=user.current_tenant_id, module=module, context_id=None, rule=rule, user_id=user.user_id)
    return before, rule


def set_assignment_override(db: Session, user: CurrentUser, assignment: SubmissionAssignment, rule: Rule | None) -> tuple[Rule | None, Rule | None]:
    """Override eines Auftrags setzen (``None`` = Standard übernehmen), ohne Commit. Liefert
    (vorher, nachher); None heisst «Standard»."""
    if assignment.tenant_id != user.current_tenant_id:
        raise ValueError("Abgabe nicht gefunden")
    before = assignment_overrides(db, assignment.tenant_id, [assignment.id]).get(assignment.id)
    if rule is None:
        row = db.scalar(
            select(ContextVisibility).where(
                ContextVisibility.tenant_id == assignment.tenant_id, ContextVisibility.module == "abgabe",
                ContextVisibility.context_id == assignment.id,
            )
        )
        if row is not None:
            db.delete(row)
            db.flush()
        return before, None
    validate("abgabe", rule, override=True)
    _upsert(db, tenant_id=assignment.tenant_id, module="abgabe", context_id=assignment.id, rule=rule, user_id=user.user_id)
    return before, rule


# ── Verknüpfungen einer Datei mit Abgaben ───────────────────────────────────────────────────


def abgabe_links(*, include_withdrawn: bool = True):
    """(stored_file_id, assignment_id, event_id, list_entry_id, manual_element_id, element_ref) jeder Verknüpfung
    einer Datei mit einem Abgabe-Auftrag: Einreichung über die Abgabebox oder Direkt-Upload in
    der Galerie mit Abgabe-Bezug (inkl. Clip eines Live Photos)."""
    upload = (
        select(
            SubmissionUploadFile.stored_file_id.label("stored_file_id"),
            SubmissionUpload.assignment_id.label("assignment_id"),
            SubmissionUpload.event_id.label("event_id"),
            SubmissionUpload.list_entry_id.label("list_entry_id"),
            SubmissionUpload.manual_element_id.label("manual_element_id"),
            cast(null(), Text).label("element_ref"),
        )
        .select_from(SubmissionUploadFile)
        .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
    )
    if not include_withdrawn:
        upload = upload.where(SubmissionUploadFile.withdrawn_at.is_(None), SubmissionUploadFile.delete_comment.is_(None))
    branches = [upload]
    for column in (GalleryImage.stored_file_id, GalleryImage.live_video_stored_file_id):
        # Direkt-Upload mit Abgabe-Bezug: das Element steht nur als Referenz da
        branch = select(
            column.label("stored_file_id"),
            GalleryImage.submission_assignment_id.label("assignment_id"),
            cast(null(), BigInteger).label("event_id"),
            cast(null(), BigInteger).label("list_entry_id"),
            cast(null(), BigInteger).label("manual_element_id"),
            GalleryImage.submission_element_ref.label("element_ref"),
        ).where(GalleryImage.submission_assignment_id.is_not(None), column.is_not(None))
        if not include_withdrawn:
            branch = branch.where(GalleryImage.submission_withdrawn_at.is_(None))
        branches.append(branch)
    return union_all(*branches).subquery("abgabe_links")


# ── Reichweite «nur zugewiesene» für Abgabe-Dateien (Phase 4, Security-Review) ───────────────


def album_gallery_clause(file_id_column, tenant_id: int):
    """Die Datei ist ein Foto der Galerie (oder der Clip eines Live Photos) ohne Abgabe-Bezug.
    ``gallery_image`` enthält auch Dokument-Uploads der Ablage und Direkt-Uploads zu einer Abgabe:
    die Album-Freigabe deckt nur Zeilen ab, deren Hauptdatei ein Bild ist und die zu keiner Abgabe
    gehören - für Abgabe-Uploads gilt allein die Abgabe-Regel (inkl. «zurückgezogen»)."""
    main = StoredFile.__table__.alias("album_main_file")
    return exists(
        select(GalleryImage.id)
        .join(main, main.c.id == GalleryImage.stored_file_id)
        .where(
            GalleryImage.tenant_id == tenant_id,
            GalleryImage.submission_assignment_id.is_(None),
            main.c.mime_type.like("image/%"),
            or_(GalleryImage.stored_file_id == file_id_column, GalleryImage.live_video_stored_file_id == file_id_column),
        )
    )


def readable_assignment_ids(db: Session, user: CurrentUser) -> set[int] | None:
    """Aufträge, deren Dateien das Konto über Rollenrechte (files.read/photos.read/…) sehen darf:
    ``None`` = alle (submissions.read für alle, submissions.manage oder gar kein submissions.read -
    dann gilt wie bisher nur files.read/photos.read). Wer submissions.read nur für zugewiesene
    Aufträge hat, sieht Dateien anderer Aufträge auch in Galerie, Ablage und Suche nicht."""
    if user.sees_all(P.SUBMISSIONS_READ):
        return None
    from app.services import submission_reviewer_service

    return submission_reviewer_service.visible_assignment_ids(db, user) or set()


def abgabe_scope_clause(file_id_column, readable: set[int]):
    """SQL-Bedingung für Listen: die Datei hängt an keinem Auftrag, an mindestens einem lesbaren
    Auftrag oder zusätzlich an einem Protokoll (dort gilt die Protokoll-Regel, additiv)."""
    from app.models import ProtocolImage

    links = abgabe_links()
    linked = exists(select(links.c.stored_file_id).where(links.c.stored_file_id == file_id_column))
    readable_link = exists(
        select(links.c.stored_file_id).where(links.c.stored_file_id == file_id_column, links.c.assignment_id.in_(list(readable)))
    )
    in_protocol = exists(select(ProtocolImage.id).where(ProtocolImage.stored_file_id == file_id_column))
    return or_(~linked, readable_link, in_protocol)


def abgabe_scope_allows(db: Session, user: CurrentUser, stored_file_id: int) -> bool:
    readable = readable_assignment_ids(db, user)
    if readable is None:
        return True
    return bool(db.scalar(select(abgabe_scope_clause(StoredFile.id, readable)).where(StoredFile.id == stored_file_id)))


# ── Zentrale Prüfung ────────────────────────────────────────────────────────────────────────


def _is_image(mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.startswith("image/"))


def _type_ok(rule: Rule, mime_type: str | None) -> bool:
    return rule.file_filter == "all" or _is_image(mime_type)


def _responsible_refs(
    db: Session, assignment: SubmissionAssignment, participant_id: int
) -> tuple[set[tuple[int | None, int | None, int | None]], set[str]]:
    """Elemente des Auftrags, für die die Person verantwortlich ist: als (event_id, list_entry_id,
    manual_element_id) und als element_ref (Galerie-Direkt-Uploads speichern nur die Referenz)."""
    from app.services.submission_access_service import _still_responsible
    from app.services.submission_service import SubmissionService, raw_element_key, raw_element_ref

    keys: set[tuple[int | None, int | None, int | None]] = set()
    refs: set[str] = set()
    for raw in SubmissionService()._resolve_raw_elements(db, assignment):
        ref = raw_element_ref(raw)
        if _still_responsible(db, assignment, ref, participant_id, raw):
            keys.add(raw_element_key(raw))
            refs.add(ref)
    return keys, refs


def _own_file_ids(db: Session, user: CurrentUser, assignment_ids: set[int]) -> set[int]:
    """Datei-IDs eigener Einreichungen in diesen Aufträgen (nicht zurückgezogen/gelöscht)."""
    if not assignment_ids:
        return set()
    links = abgabe_links(include_withdrawn=False)
    rows = db.execute(select(links).where(links.c.assignment_id.in_(list(assignment_ids)))).all()
    result: set[int] = set()
    assignments = {
        assignment.id: assignment
        for assignment in db.scalars(
            select(SubmissionAssignment).where(SubmissionAssignment.id.in_(list(assignment_ids)), SubmissionAssignment.tenant_id == user.current_tenant_id)
        )
    }
    for assignment_id, assignment in assignments.items():
        keys, refs = _responsible_refs(db, assignment, user.user_id)
        if not keys and not refs:
            continue
        for row in rows:
            if row.assignment_id != assignment_id:
                continue
            if (row.element_ref is not None and row.element_ref in refs) or (
                row.element_ref is None and (row.event_id, row.list_entry_id, row.manual_element_id) in keys
            ):
                result.add(row.stored_file_id)
    return result


def context_grant_allows(db: Session, user: CurrentUser, stored_file: StoredFile | int) -> bool:
    """Gibt ein Kontext der Datei sie für dieses Konto frei? Nur lesen, nur eigener Mandant."""
    if isinstance(stored_file, int):
        stored_file = db.get(StoredFile, stored_file)
    if stored_file is None or user.current_tenant_id is None or stored_file.tenant_id != user.current_tenant_id:
        return False
    tenant_id = stored_file.tenant_id
    rules = module_rules(db, tenant_id)

    # Album: Galerie-Foto bzw. Clip eines Live Photos (album_gallery_clause)
    album = rules["album"]
    if album.audience == "all_participants" and _type_ok(album, stored_file.mime_type):
        if db.scalar(select(album_gallery_clause(StoredFile.id, tenant_id)).where(StoredFile.id == stored_file.id)):
            return True

    # Abgaben: jede (nicht zurückgezogene) Verknüpfung mit ihrer Regel
    links = abgabe_links(include_withdrawn=False)
    rows = db.execute(select(links).where(links.c.stored_file_id == stored_file.id)).all()
    if not rows:
        return False
    assignment_ids = {row.assignment_id for row in rows}
    overrides = assignment_overrides(db, tenant_id, list(assignment_ids))
    own_candidates: set[int] = set()
    for assignment_id in assignment_ids:
        rule = overrides.get(assignment_id) or rules["abgabe"]
        if not _type_ok(rule, stored_file.mime_type):
            continue
        if rule.audience == "all_participants":
            return True
        if rule.audience == "own_submissions":
            own_candidates.add(assignment_id)
    return stored_file.id in _own_file_ids(db, user, own_candidates)


def visible_files_query(db: Session, user: CurrentUser, *, module: str = "abgabe", only_images: bool = False):
    """IDs der Dateien (``select(StoredFile.id)``), die Kontext-Freigaben dieses Moduls dem Konto
    zeigen - dieselbe Regel wie context_grant_allows, als eine Abfrage für Listen. Nur saubere
    Dateien (Virenscan) des eigenen Mandanten."""
    tenant_id = user.current_tenant_id
    base = select(StoredFile.id).where(StoredFile.tenant_id == tenant_id, StoredFile.scan_status == "clean")
    if only_images:
        base = base.where(StoredFile.mime_type.like("image/%"))
    image = StoredFile.mime_type.like("image/%")
    rules = module_rules(db, tenant_id)
    if module == "album":
        rule = rules["album"]
        if rule.audience != "all_participants":
            return base.where(false())
        in_gallery = album_gallery_clause(StoredFile.id, tenant_id)
        return base.where(in_gallery, image) if rule.file_filter == "images" else base.where(in_gallery)
    if module != "abgabe":
        return base.where(false())

    assignment_ids = list(db.scalars(select(SubmissionAssignment.id).where(SubmissionAssignment.tenant_id == tenant_id)))
    overrides = assignment_overrides(db, tenant_id, assignment_ids)
    all_any: list[int] = []
    all_images: list[int] = []
    own: dict[int, Rule] = {}
    for assignment_id in assignment_ids:
        rule = overrides.get(assignment_id) or rules["abgabe"]
        if rule.audience == "all_participants":
            (all_any if rule.file_filter == "all" else all_images).append(assignment_id)
        elif rule.audience == "own_submissions":
            own[assignment_id] = rule
    links = abgabe_links(include_withdrawn=False)

    def linked_to(ids: list[int]):
        return exists(select(links.c.stored_file_id).where(links.c.stored_file_id == StoredFile.id, links.c.assignment_id.in_(ids)))

    conditions = []
    if all_any:
        conditions.append(linked_to(all_any))
    if all_images:
        conditions.append(and_(linked_to(all_images), image))
    if own:
        # Je Dateityp-Gruppe getrennt: «eigen» gilt nur in dem Auftrag, in dem man verantwortlich ist
        own_any = {aid for aid, rule in own.items() if rule.file_filter == "all"}
        own_images = {aid for aid, rule in own.items() if rule.file_filter == "images"}
        own_any_ids = _own_file_ids(db, user, own_any)
        own_image_ids = _own_file_ids(db, user, own_images)
        if own_any_ids:
            conditions.append(StoredFile.id.in_(list(own_any_ids)))
        if own_image_ids:
            conditions.append(and_(StoredFile.id.in_(list(own_image_ids)), image))
    if not conditions:
        return base.where(false())
    return base.where(or_(*conditions))
