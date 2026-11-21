from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    ElementDefinition,
    Event,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    Template,
    TemplateElement,
    Tenant,
)
from app.repositories.element_definition_repository import ElementDefinitionRepository
from app.schemas.template import (
    ElementDefinitionCreate,
    ElementDefinitionRead,
    ElementDefinitionUpdate,
)
from app.services import list_columns, public_id_service
from app.core.element_types import allows_multiple_values, element_type_code, is_known_element_type, render_type_id
from app.services.block_config_ids import decode_block_config, encode_block_config
from app.services.element_config import upgrade_definition_block, validate_block_config
from app.services.list_service import lock_linked_list_definitions


# Felder aus Termin bzw. Pendenz eines Blocks «Pro Termin»/«Pro Pendenz» (Auswahl, Labels,
# Reihenfolge) je Wiederholungsquelle. Reine Darstellung: die Werte kommen live aus dem Termin
# bzw. der Pendenz, im Protokoll wird diese Liste nie bearbeitet.
SOURCE_FIELD_KEYS = {"event": "event_fields", "todo": "todo_fields"}
# Protokolle, die eine geänderte Feldanordnung übernehmen: noch nicht durchgeführte. Durchgeführte
# und abgeschlossene behalten ihren Stand (abgeschlossene sind eingefroren).
SOURCE_FIELD_PROPAGATION_STATUSES = ("geplant", "vorbereitet")


class FineListPermissionError(PermissionError):
    """Bussenliste anlegen oder konfigurieren ohne Finanzzugriff (finances.read)."""


def fine_list_settings(blocks: list[dict] | None) -> dict[str, dict]:
    """Bussenlisten-Blöcke je Block-ID mit ihren Bussen-Einstellungen (Konto, Zeitraum, Status,
    Gruppierung). Titel und Darstellung zählen nicht: die darf ändern, wer Vorlagen bearbeitet."""
    result: dict[str, dict] = {}
    for block in blocks or []:
        if element_type_code(block.get("element_type_id")) != "fine_list":
            continue
        config = block.get("configuration_json") or {}
        result[str(block.get("id"))] = {key: value for key, value in config.items() if key.startswith("fine_list_")}
    return result


def ensure_fine_lists_allowed(before: list[dict] | None, after: list[dict] | None, *, can_configure_fines: bool) -> None:
    """Die Bussenliste zeigt die Bussen aller Mitglieder. Neu anlegen oder umkonfigurieren darf sie
    deshalb nur, wer Finanzen sehen darf; Entfernen und unveränderte Bussenlisten bleiben frei."""
    if can_configure_fines:
        return
    existing = fine_list_settings(before)
    for block_id, settings in fine_list_settings(after).items():
        if existing.get(block_id) != settings:
            raise FineListPermissionError("fine_list_requires_finance")


class ElementDefinitionService:
    def __init__(self, repository: ElementDefinitionRepository | None = None) -> None:
        self.repository = repository or ElementDefinitionRepository()

    def _referenced_list_definition_ids(self, config: dict | None) -> set[int]:
        """Collects both whole-list `linked_list_id` and any row-link `rows[].linked_list_id`
        values out of a single block's configuration_json. Mirrors
        TemplateElementService._referenced_list_definition_ids - keep both in sync if the
        list-linkage JSON shape ever changes."""
        config = config or {}
        ids: set[int] = set()
        top_level = config.get("linked_list_id")
        if top_level:
            ids.add(int(top_level))
        rows = config.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("linked_list_id"):
                    ids.add(int(row["linked_list_id"]))
        return ids

    def _referenced_auto_source_list_ids(self, config: dict | None) -> set[int]:
        """Matrix-Automodus: a block's configuration_json can carry auto_source.list_id
        instead of linked_list_id - the id that drives the "auto" column generation in
        ProtocolService.create_from_template."""
        config = config or {}
        auto_source = config.get("auto_source")
        list_id = (auto_source or {}).get("list_id") if isinstance(auto_source, dict) else None
        return {int(list_id)} if list_id else set()

    def _referenced_participant_and_event_ids(self, config: dict | None) -> tuple[set[int], set[int]]:
        """template_participant_id/template_participant_ids/template_event_id are embedded
        per-row values (matrix/form rows) baked directly into every protocol created from
        this element definition, via ProtocolService.create_from_template - without a tenant
        check here, a definition could permanently embed another tenant's participant/event
        data into every protocol using it."""
        config = config or {}
        participant_ids: set[int] = set()
        event_ids: set[int] = set()
        rows = config.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get("template_participant_id"):
                    participant_ids.add(int(row["template_participant_id"]))
                for pid in row.get("template_participant_ids") or []:
                    if pid:
                        participant_ids.add(int(pid))
                if row.get("template_event_id"):
                    event_ids.add(int(row["template_event_id"]))
        return participant_ids, event_ids

    def _validate_linked_lists(self, db: Session, blocks: list[dict], *, tenant_id: int) -> None:
        """Every linked_list_id/auto_source.list_id referenced from any of this element
        definition's blocks must point at a ListDefinition belonging to the same tenant -
        otherwise a matrix/list block built from this element definition would spread a
        foreign tenant's list content (column titles, row contents, potentially participant
        data) into every protocol that uses it (audit D8, 2026-08-16; matrix-automode gap
        closed 2026-08-25). Mirrors TemplateElementService._validate_linked_lists, which
        already closes the equivalent gap for template-element-level configuration. Also
        validates embedded template_participant_id(s)/template_event_id row values for the
        same reason - see _referenced_participant_and_event_ids."""
        referenced_list_ids: set[int] = set()
        referenced_participant_ids: set[int] = set()
        referenced_event_ids: set[int] = set()
        for block in blocks:
            config = block.get("configuration_json")
            referenced_list_ids |= self._referenced_list_definition_ids(config)
            referenced_list_ids |= self._referenced_auto_source_list_ids(config)
            participant_ids, event_ids = self._referenced_participant_and_event_ids(config)
            referenced_participant_ids |= participant_ids
            referenced_event_ids |= event_ids
        # Sperrt die Listen bis zum Commit, damit gleichzeitiges Löschen nicht dazwischenkommt (C10)
        found_list_ids = lock_linked_list_definitions(db, referenced_list_ids, tenant_id=tenant_id)
        for list_id in sorted(referenced_list_ids):
            if list_id not in found_list_ids:
                raise ValueError(f"Linked list {list_id} not found")
        for participant_id in referenced_participant_ids:
            participant = db.get(Participant, participant_id)
            if participant is None or participant.tenant_id != tenant_id:
                raise ValueError(f"Participant {participant_id} not found")
        for event_id in referenced_event_ids:
            event = db.get(Event, event_id)
            if event is None or event.tenant_id != tenant_id:
                raise ValueError(f"Event {event_id} not found")

    def _normalize_blocks(self, db: Session, blocks: list[dict], *, tenant_id: int) -> list[dict]:
        normalized: list[dict] = []
        for block in blocks:
            element_type_id = int(block.get("element_type_id", 1))
            if not is_known_element_type(element_type_id):
                raise ValueError(f"Unbekannter Elementtyp {element_type_id}")
            # Altformate (z. B. von einem älteren Client oder einer Kopie) auf das aktuelle
            # Schema heben und Schlüssel entfernen, die der Typ nicht kennt.
            next_block = upgrade_definition_block({**block, "element_type_id": element_type_id})
            # Render-Typ und Mehrfachwerte kommen aus der Registry, nicht vom Client.
            next_block["render_type_id"] = render_type_id(element_type_id)
            next_block["allows_multiple_values"] = allows_multiple_values(element_type_id)
            # The client sends this JSON with public ids embedded (linked_list_id,
            # template_participant_id(s), template_event_id, ...) - decode back to
            # internal ints before _validate_linked_lists/storage, see block_config_ids.py.
            config = decode_block_config(db, next_block["configuration_json"], tenant_id=tenant_id)
            # Spalten-Keys der verknüpften Listen prüfen (fremde/gelöschte -> keine, alte -> neue)
            config = list_columns.normalize_config_column_keys(db, config, tenant_id=tenant_id)
            validate_block_config(element_type_id, config)
            next_block["configuration_json"] = config
            normalized.append(next_block)
        return normalized

    @staticmethod
    def usage_counts(db: Session, definition_ids: list[int]) -> dict[int, int]:
        """Anzahl Vorlagen-Traktanden je Elementdefinition (eine Abfrage für die ganze Liste)."""
        if not definition_ids:
            return {}
        rows = db.execute(
            select(TemplateElement.element_definition_id, func.count())
            .where(TemplateElement.element_definition_id.in_(definition_ids))
            .group_by(TemplateElement.element_definition_id)
        )
        return {definition_id: count for definition_id, count in rows}

    @staticmethod
    def usage_stats(db: Session, definition_ids: list[int]) -> dict[int, tuple[int, int]]:
        """Je Elementdefinition (Anzahl Traktanden, Anzahl verschiedener Sitzungsvorlagen).

        Die Bausteinliste zeigt «Verwendet in N Vorlagen»; ein Baustein, der zweimal in derselben
        Vorlage steckt, zählt dort einmal. ``definition_ids`` stammen immer aus einer bereits auf
        den Mandanten gefilterten Liste, die Traktanden gehören über die Definition demselben
        Mandanten (Anlegen löst die Definition mandantengescoped auf) - RLS gilt zusätzlich."""
        if not definition_ids:
            return {}
        rows = db.execute(
            select(
                TemplateElement.element_definition_id,
                func.count(),
                func.count(distinct(TemplateElement.template_id)),
            )
            # Nur Traktanden aus Vorlagen desselben Mandanten wie die Definition zählen - unabhängig
            # von der Schreib-Invariante und RLS (Security-Review, Härtung).
            .join(Template, Template.id == TemplateElement.template_id)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.element_definition_id.in_(definition_ids))
            .where(Template.tenant_id == ElementDefinition.tenant_id)
            .group_by(TemplateElement.element_definition_id)
        )
        return {definition_id: (usages, templates) for definition_id, usages, templates in rows}

    def _read_model(
        self, db: Session, entity: ElementDefinition, usage: tuple[int, int] | None = None
    ) -> ElementDefinitionRead:
        if usage is None:
            usage = self.usage_stats(db, [entity.id]).get(entity.id, (0, 0))
        config = entity.configuration_json or {}
        # Each block's own configuration_json is stored with internal ints embedded
        # (linked_list_id, ...) - encode to public ids for this API response, see
        # block_config_ids.py.
        blocks = [
            {**block, "configuration_json": encode_block_config(db, block.get("configuration_json"))}
            for block in config.get("blocks", [])
        ]
        return ElementDefinitionRead(
            id=entity.public_id,
            tenant_id=public_id_service.resolve_public_id(db, Tenant, entity.tenant_id),
            title=entity.title,
            description=entity.description,
            is_active=entity.is_active,
            is_library=entity.is_library,
            usage_count=usage[0],
            template_count=usage[1],
            blocks=blocks,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def list_element_definitions(self, db: Session, *, tenant_id: int, library_only: bool = False):
        entities = [entity for entity in self.repository.list(db, tenant_id=tenant_id) if entity.is_library or not library_only]
        stats = self.usage_stats(db, [entity.id for entity in entities])
        return [self._read_model(db, entity, stats.get(entity.id, (0, 0))) for entity in entities]

    def get_element_definition(self, db: Session, element_definition_id: int):
        entity = self.repository.get(db, element_definition_id)
        return self._read_model(db, entity) if entity else None

    def create_element_definition(self, db: Session, payload: ElementDefinitionCreate, *, tenant_id: int, can_configure_fines: bool = True):
        normalized_blocks = self._normalize_blocks(db, [block.model_dump() for block in payload.blocks], tenant_id=tenant_id)
        ensure_fine_lists_allowed([], normalized_blocks, can_configure_fines=can_configure_fines)
        self._validate_linked_lists(db, normalized_blocks, tenant_id=tenant_id)
        entity = ElementDefinition(
            tenant_id=tenant_id,
            element_type_id=1,
            render_type_id=2,
            title=payload.title,
            display_title=payload.title,
            description=payload.description,
            is_editable=False,
            allows_multiple_values=False,
            export_visible=True,
            configuration_json={"blocks": normalized_blocks},
            is_active=payload.is_active,
            is_library=payload.is_library,
        )
        created = self.repository.create(db, entity)
        return self._read_model(db, created)

    def update_element_definition(
        self,
        db: Session,
        element_definition_id: int,
        payload: ElementDefinitionUpdate,
        *,
        can_configure_fines: bool = True,
        changed_protocol_blocks: list[ProtocolElementBlock] | None = None,
    ):
        """changed_protocol_blocks sammelt (falls übergeben) die Protokollblöcke, deren Feldanordnung
        «aus Termin/Pendenz» angepasst wurde - die Route meldet sie offenen Editoren."""
        entity = self.repository.get(db, element_definition_id)
        if entity is None:
            return None

        values = payload.model_dump(exclude_unset=True)
        if "blocks" in values:
            previous_blocks = (entity.configuration_json or {}).get("blocks") or []
            normalized_blocks = self._normalize_blocks(db, values.pop("blocks"), tenant_id=entity.tenant_id)
            ensure_fine_lists_allowed(previous_blocks, normalized_blocks, can_configure_fines=can_configure_fines)
            self._validate_linked_lists(db, normalized_blocks, tenant_id=entity.tenant_id)
            values["configuration_json"] = {"blocks": normalized_blocks}
            # Im selben Commit wie die Definition (repository.update committet)
            changed_blocks = self.propagate_source_fields(db, entity, previous_blocks, normalized_blocks)
            if changed_protocol_blocks is not None:
                changed_protocol_blocks.extend(changed_blocks)
        if "title" in values:
            values["display_title"] = values["title"]
        if not values:
            return self._read_model(db, entity)
        updated = self.repository.update(db, entity, values)
        return self._read_model(db, updated)

    def propagate_source_fields(
        self, db: Session, entity: ElementDefinition, previous_blocks: list[dict], blocks: list[dict]
    ) -> list[ProtocolElementBlock]:
        """Feldanordnung «aus Termin/Pendenz» (event_fields/todo_fields: Auswahl, Labels,
        Reihenfolge) in die Blöcke noch nicht durchgeführter Protokolle übernehmen.

        Protokollblöcke tragen einen Schnappschuss der Block-Konfiguration; ohne diesen Abgleich
        zeigte ein bereits geplantes Protokoll (und sein PDF) die Felder weiter in der alten
        Reihenfolge, bis jemand «Mit Vorlage abgleichen» auslöste. Die Liste ist reine
        Darstellung (Werte kommen live aus Termin/Pendenz, im Protokoll wird sie nie bearbeitet),
        darum wird sie ersetzt statt zusammengeführt. Betroffen sind Protokolle der Vorlagen, deren
        Traktandum diese Definition aktuell verwendet (nach «nur in dieser Vorlage ändern» gilt
        also die Kopie), Zuordnung des Blocks wie beim Vorlagen-Abgleich über source_sort_index
        (Stand vor dem Speichern), Elementtyp und Wiederholungsquelle. Mandant: Protokoll und
        Vorlage gehören dem Mandanten der Definition."""
        previous_sort_index = {
            str(block.get("id")): block.get("sort_index", 0) for block in previous_blocks if isinstance(block, dict)
        }
        targets: dict[tuple[int, int], dict] = {}
        for block in blocks:
            sort_index = previous_sort_index.get(str(block.get("id")))
            config = block.get("configuration_json") or {}
            fields = {
                source: config[key] for source, key in SOURCE_FIELD_KEYS.items() if isinstance(config.get(key), list)
            }
            if sort_index is None or not fields:
                continue
            targets[(int(sort_index), int(block["element_type_id"]))] = fields
        if not targets:
            return []

        template_element_ids = (
            select(TemplateElement.id)
            .join(Template, Template.id == TemplateElement.template_id)
            .where(TemplateElement.element_definition_id == entity.id, Template.tenant_id == entity.tenant_id)
        )
        candidates = db.scalars(
            select(ProtocolElementBlock)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .where(
                Protocol.tenant_id == entity.tenant_id,
                Protocol.status.in_(SOURCE_FIELD_PROPAGATION_STATUSES),
                ProtocolElement.template_element_id.in_(template_element_ids),
                ProtocolElementBlock.element_type_id.in_({element_type_id for _, element_type_id in targets}),
            )
            .order_by(ProtocolElementBlock.id)
            # Zeilensperre wie beim Bearbeiten im Protokoll (CONC-005); config_version steigt per Trigger
            .with_for_update(of=ProtocolElementBlock)
        ).all()
        changed: list[ProtocolElementBlock] = []
        for protocol_block in candidates:
            config = protocol_block.configuration_snapshot_json or {}
            source = str(config.get("repeat_source_type") or "")
            key = SOURCE_FIELD_KEYS.get(source)
            try:
                fields = targets.get((int(config.get("source_sort_index")), protocol_block.element_type_id))
            except (TypeError, ValueError):
                continue
            if key is None or fields is None or source not in fields or config.get(key) == fields[source]:
                continue
            protocol_block.configuration_snapshot_json = {**config, key: fields[source]}
            db.add(protocol_block)
            changed.append(protocol_block)
        if changed:
            db.flush()
        return changed

    def copy_element_definition(self, db: Session, source: ElementDefinition, *, is_library: bool = False) -> ElementDefinition:
        """Eigenständige Kopie (gleiche Block-IDs, damit Vorlagen-Übersteuerungen weiter passen)."""
        entity = ElementDefinition(
            tenant_id=source.tenant_id,
            element_type_id=source.element_type_id,
            render_type_id=source.render_type_id,
            title=source.title,
            display_title=source.display_title,
            description=source.description,
            is_editable=source.is_editable,
            allows_multiple_values=source.allows_multiple_values,
            export_visible=source.export_visible,
            configuration_json=dict(source.configuration_json or {}),
            is_active=source.is_active,
            is_library=is_library,
        )
        db.add(entity)
        db.flush()
        return entity

    def delete_unused_singles(self, db: Session, definition_ids: list[int]) -> None:
        """Einzelstücke einer Vorlage (nicht in der Bibliothek) entfernen, sobald kein Traktandum
        sie mehr verwendet. Protokolle behalten ihren Schnappschuss (FK auf SET NULL)."""
        from app.models import TemplateElementBlock

        counts = self.usage_counts(db, definition_ids)
        # Alte Vorlagenblöcke (template_element_block, nur noch Altbestand) halten sie ebenfalls
        legacy = set(db.scalars(select(TemplateElementBlock.element_definition_id).where(TemplateElementBlock.element_definition_id.in_(definition_ids)))) if definition_ids else set()
        removed = False
        for definition_id in set(definition_ids):
            entity = db.get(ElementDefinition, definition_id)
            if entity is not None and not entity.is_library and not counts.get(definition_id) and definition_id not in legacy:
                db.delete(entity)
                removed = True
        if removed:
            db.commit()

    def delete_element_definition(self, db: Session, element_definition_id: int) -> bool:
        entity = self.repository.get(db, element_definition_id)
        if entity is None:
            return False
        self.repository.delete(db, entity)
        return True
