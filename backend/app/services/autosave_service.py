class AutosaveService:
    def save_text_block(self, protocol_element_id: int, content: str) -> dict[str, str | int]:
        return {"status": "saved", "protocol_element_id": protocol_element_id, "content": content}

