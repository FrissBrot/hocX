"""Minimal ORM row builders for tests - not a full fixture framework, just enough to
satisfy FK constraints for the tables these tests actually touch."""
from datetime import date

from app.models.entities import AttendanceFine, FinanceAccount, Protocol, Template, Tenant


def make_tenant(db, name="Test Tenant") -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    return tenant


def make_template(db, tenant_id: int, name="Test Template") -> Template:
    template = Template(tenant_id=tenant_id, name=name)
    db.add(template)
    db.flush()
    return template


def make_protocol(
    db,
    tenant_id: int,
    template_id: int,
    protocol_number: str = "P-1",
    protocol_date: date = date(2026, 1, 1),
    status: str = "geplant",
) -> Protocol:
    protocol = Protocol(
        tenant_id=tenant_id,
        template_id=template_id,
        template_version=1,
        protocol_number=protocol_number,
        protocol_date=protocol_date,
        status=status,
    )
    db.add(protocol)
    db.flush()
    return protocol


def make_finance_account(db, tenant_id: int, name="Test Account") -> FinanceAccount:
    account = FinanceAccount(tenant_id=tenant_id, name=name, currency_label="CHF")
    db.add(account)
    db.flush()
    return account


def make_fine(
    db,
    protocol_id: int,
    account_id: int,
    amount: float = 5.0,
    fine_type: str = "late",
    participant_name_snapshot: str = "Test Participant",
) -> AttendanceFine:
    fine = AttendanceFine(
        protocol_id=protocol_id,
        account_id=account_id,
        amount=amount,
        fine_type=fine_type,
        participant_name_snapshot=participant_name_snapshot,
    )
    db.add(fine)
    db.flush()
    return fine
