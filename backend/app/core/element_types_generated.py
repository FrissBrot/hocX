# GENERATED FILE - do not edit by hand. Source of truth: element-types/registry.json (repo root).
# Regenerate with: python3 scripts/sync-element-types.py
from __future__ import annotations

ELEMENT_TYPES: tuple[dict, ...] = (
    {"id": 1, "code": "text", "category": "basics", "render_type_id": 2, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": True, "repeat": ("event", "todo",), "carry_over": True, "matrix_embeddable": True},
    {"id": 2, "code": "todo", "category": "basics", "render_type_id": 3, "allows_multiple_values": True, "default_editable": True, "pickable": True, "content": False, "repeat": ("event", "todo",), "carry_over": False, "matrix_embeddable": True},
    {"id": 3, "code": "image", "category": "basics", "render_type_id": 4, "allows_multiple_values": True, "default_editable": True, "pickable": True, "content": False, "repeat": ("event", "todo",), "carry_over": True, "matrix_embeddable": True},
    {"id": 4, "code": "display", "category": "basics", "render_type_id": 6, "allows_multiple_values": False, "default_editable": False, "pickable": False, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 5, "code": "static_text", "category": "basics", "render_type_id": 6, "allows_multiple_values": False, "default_editable": False, "pickable": False, "content": True, "repeat": (), "carry_over": True, "matrix_embeddable": False},
    {"id": 6, "code": "form", "category": "basics", "render_type_id": 5, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": ("event", "todo",), "carry_over": False, "matrix_embeddable": True},
    {"id": 7, "code": "event_list", "category": "organisation", "render_type_id": 5, "allows_multiple_values": False, "default_editable": False, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": True},
    {"id": 8, "code": "bullet_list", "category": "basics", "render_type_id": 2, "allows_multiple_values": False, "default_editable": True, "pickable": False, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 9, "code": "attendance", "category": "organisation", "render_type_id": 5, "allows_multiple_values": False, "default_editable": False, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": True},
    {"id": 10, "code": "session_date", "category": "organisation", "render_type_id": 6, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": True},
    {"id": 11, "code": "matrix", "category": "basics", "render_type_id": 5, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 12, "code": "finance_balance", "category": "finance", "render_type_id": 6, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 13, "code": "finance_transactions", "category": "finance", "render_type_id": 5, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 14, "code": "fine_list", "category": "finance", "render_type_id": 5, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 15, "code": "chart", "category": "organisation", "render_type_id": 6, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 16, "code": "entry_exit", "category": "organisation", "render_type_id": 5, "allows_multiple_values": False, "default_editable": False, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
    {"id": 17, "code": "session_notes", "category": "organisation", "render_type_id": 6, "allows_multiple_values": False, "default_editable": True, "pickable": True, "content": False, "repeat": (), "carry_over": False, "matrix_embeddable": False},
)
