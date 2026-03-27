from fastapi import APIRouter

router = APIRouter()


@router.get("/protocol-elements/{protocol_element_id}/todos", response_model=list[dict])
def list_todos(protocol_element_id: int):
    return [{"protocol_element_id": protocol_element_id, "status": "scaffolded"}]


@router.post("/protocol-elements/{protocol_element_id}/todos", response_model=dict[str, str])
def create_todo(protocol_element_id: int):
    return {"message": f"POST /protocol-elements/{protocol_element_id}/todos scaffolded"}


@router.patch("/protocol-todos/{todo_id}", response_model=dict[str, str])
def patch_todo(todo_id: int):
    return {"message": f"PATCH /protocol-todos/{todo_id} scaffolded"}


@router.delete("/protocol-todos/{todo_id}", response_model=dict[str, str])
def delete_todo(todo_id: int):
    return {"message": f"DELETE /protocol-todos/{todo_id} scaffolded"}

