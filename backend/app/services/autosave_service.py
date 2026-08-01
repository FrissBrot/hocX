from sqlalchemy.orm import Session

from app.models import ProtocolText
from app.repositories.protocol_element_repository import ProtocolTextRepository


class AutosaveService:
    def __init__(self, text_repository: ProtocolTextRepository | None = None) -> None:
        self.text_repository = text_repository or ProtocolTextRepository()

    def save_text_block(
        self, db: Session, protocol_element_block_id: int, content: str, *, track_changes_active: bool = False
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
        return {
            "status": "saved",
            "protocol_element_block_id": protocol_element_block_id,
            "content": saved.content,
            "tracked_dirty": saved.tracked_dirty,
            "tracked_baseline_content": saved.tracked_baseline_content,
        }
