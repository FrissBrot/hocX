"""Public API references for snapshot configs whose stored IDs remain internal."""
from sqlalchemy import select

from app.models import FinanceAccount, ListDefinition


def snapshot_reference_ids(db, config: dict, tenant_id: int) -> dict:
    list_ids = [config.get("linked_list_id"), (config.get("auto_source") or {}).get("list_id")]
    for row in config.get("rows") or []:
        if isinstance(row, dict):
            list_ids.extend([row.get("linked_list_id"), (row.get("row_config") or {}).get("linked_list_id")])
    account_ids = [config.get("finance_account_id")]
    result = {}
    for name, model, values in (("lists", ListDefinition, list_ids), ("finance_accounts", FinanceAccount, account_ids)):
        ids = {value for value in values if isinstance(value, int) and not isinstance(value, bool)}
        result[name] = {
            str(internal_id): str(public_id)
            for internal_id, public_id in db.execute(
                select(model.id, model.public_id).where(model.id.in_(ids), model.tenant_id == tenant_id)
            ).all()
        } if ids else {}
    return result
