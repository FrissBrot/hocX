"""Frei erfasste Fachinhalte: Formular (Beschriftung/Wert) und Unterschriftenfelder.

Strukturelemente (Text, Überschrift, Tabelle, Liste, QR-Code …) sind Layoutknoten des
Document Studio (layout.py) und haben keinen Provider."""
from __future__ import annotations

from app.documents.catalog import BlockSpec, FormParams, SignatureFieldsParams
from app.documents.context import BuildContext
from app.documents.model import FormBlock, FormRow, SignatureField, SignatureFieldsBlock
from app.documents.providers.common import spec_fields
from app.documents.richtext import plain_to_rich


def form(ctx: BuildContext, spec: BlockSpec, params: FormParams):
    rows = [FormRow(label=row.label, value=plain_to_rich(row.value)) for row in params.rows if row.label.strip() or row.value.strip()]
    return [FormBlock(**spec_fields(spec), label_heading=params.label_heading, value_heading=params.value_heading, rows=rows)]


def signature_fields(ctx: BuildContext, spec: BlockSpec, params: SignatureFieldsParams):
    return [
        SignatureFieldsBlock(
            **spec_fields(spec),
            fields=[SignatureField(label=field.label, name=field.name) for field in params.fields],
            with_place_date=params.with_place_date,
        )
    ]
