from sqlalchemy.orm import Session

from app.models import ProtocolText
from app.repositories.protocol_element_repository import ProtocolTextRepository
from app.services import block_field_sync


class AutosaveService:
    def __init__(self, text_repository: ProtocolTextRepository | None = None) -> None:
        self.text_repository = text_repository or ProtocolTextRepository()

    def save_text_block(
        self,
        db: Session,
        protocol_element_block_id: int,
        content: str,
        *,
        tenant_id: int,
        track_changes_active: bool = False,
        block_config: dict | None = None,
    ) -> dict[str, str | int | bool | None]:
        protocol_text = self.text_repository.get_by_protocol_element_block_id(db, protocol_element_block_id)
        if protocol_text is None:
            # A block with no ProtocolText row yet has an implicit '' baseline - the first
            # ever content is "added" content just like any other tracked edit.
            protocol_text = ProtocolText(
                protocol_element_block_id=protocol_element_block_id,
                content=content,
                tracked_baseline_content="" if track_changes_active else None,
                tracked_dirty=track_changes_active,
            )
        else:
            # Pin the pre-edit value exactly once, on the first tracked edit - later edits
            # (still tracked) must not overwrite it, so the "before" box keeps showing what
            # the block looked like when vorbereitet-tracking started, not the last edit.
            if track_changes_active and not protocol_text.tracked_dirty:
                protocol_text.tracked_baseline_content = protocol_text.content
                protocol_text.tracked_dirty = True
            protocol_text.content = content
        saved = self.text_repository.save(db, protocol_text)
        if block_config:
            block_field_sync.apply_text_sync(
                db,
                tenant_id=tenant_id,
                repeat_source_type=block_config.get("repeat_source_type"),
                repeat_source_id=block_config.get("repeat_source_id"),
                sync_target_field=block_config.get("sync_target_field"),
                content=content,
            )
        return self._result(saved, protocol_element_block_id)

    def accept_tracked_changes(self, db: Session, protocol_element_block_id: int) -> dict[str, str | int | bool | None] | None:
        """'Ausblenden' for a text block's red tracked-change highlighting: resets the
        baseline to the block's current content, so the word-diff has nothing left to
        show. Whole-block granularity (not per-word) - splicing a single word-run back
        into the markdown baseline risks corrupting surrounding formatting (lists, bold)
        on rejoin, so accepting resolves everything in the block at once."""
        protocol_text = self.text_repository.get_by_protocol_element_block_id(db, protocol_element_block_id)
        if protocol_text is None:
            return None
        protocol_text.tracked_baseline_content = protocol_text.content
        saved = self.text_repository.save(db, protocol_text)
        return self._result(saved, protocol_element_block_id)

    def _result(self, saved: ProtocolText, protocol_element_block_id: int) -> dict[str, str | int | bool | None]:
        return {
            "status": "saved",
            "protocol_element_block_id": protocol_element_block_id,
            "content": saved.content,
            "tracked_dirty": saved.tracked_dirty,
            "tracked_baseline_content": saved.tracked_baseline_content,
        }
