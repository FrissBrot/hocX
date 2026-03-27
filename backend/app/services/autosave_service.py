from sqlalchemy.orm import Session

from app.models import ProtocolText
from app.repositories.protocol_element_repository import ProtocolTextRepository


class AutosaveService:
    def __init__(self, text_repository: ProtocolTextRepository | None = None) -> None:
        self.text_repository = text_repository or ProtocolTextRepository()

    def save_text_block(self, db: Session, protocol_element_block_id: int, content: str) -> dict[str, str | int]:
        protocol_text = self.text_repository.get_by_protocol_element_block_id(db, protocol_element_block_id)
        if protocol_text is None:
            protocol_text = ProtocolText(protocol_element_block_id=protocol_element_block_id, content=content)
        else:
            protocol_text.content = content
        saved = self.text_repository.save(db, protocol_text)
        return {"status": "saved", "protocol_element_block_id": protocol_element_block_id, "content": saved.content}
