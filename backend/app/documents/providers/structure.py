"""Struktur-Blöcke und frei erfasste Inhalte (Text, Formular, Aufzählung, Tabelle, Unterschriften, QR)."""
from __future__ import annotations

import segno

from app.documents.catalog import (
    BlockSpec,
    BulletListParams,
    FormParams,
    GenericTableParams,
    HeadingParams,
    MarkdownParams,
    NoParams,
    QrLinkParams,
    SignatureFieldsParams,
    SpacerParams,
    TocParams,
)
from app.documents.context import BuildContext
from app.documents.model import (
    BulletListBlock,
    DividerBlock,
    FormBlock,
    FormRow,
    GenericTableBlock,
    HeadingBlock,
    PageBreakBlock,
    QrLinkBlock,
    RichTextBlock,
    SignatureField,
    SignatureFieldsBlock,
    SpacerBlock,
    StaticTextBlock,
    TableColumn,
    TableRow,
    TocBlock,
    table_from_rows,
)
from app.documents.providers.common import spec_fields, text_cell
from app.documents.richtext import markdown_to_rich, plain_to_rich


def heading(ctx: BuildContext, spec: BlockSpec, params: HeadingParams):
    return [HeadingBlock(**spec_fields(spec, title=None), text=params.text or spec.title or "")]


def richtext(ctx: BuildContext, spec: BlockSpec, params: MarkdownParams):
    return [RichTextBlock(**spec_fields(spec), content=markdown_to_rich(params.markdown))]


def static_text(ctx: BuildContext, spec: BlockSpec, params: MarkdownParams):
    return [StaticTextBlock(**spec_fields(spec), content=markdown_to_rich(params.markdown))]


def page_break(ctx: BuildContext, spec: BlockSpec, params: NoParams):
    return [PageBreakBlock(**spec_fields(spec, title=None, hide_if_empty=False))]


def toc(ctx: BuildContext, spec: BlockSpec, params: TocParams):
    return [TocBlock(**spec_fields(spec, hide_if_empty=False), depth=params.depth)]


def spacer(ctx: BuildContext, spec: BlockSpec, params: SpacerParams):
    return [SpacerBlock(**spec_fields(spec, title=None, hide_if_empty=False), size=params.size)]


def divider(ctx: BuildContext, spec: BlockSpec, params: NoParams):
    return [DividerBlock(**spec_fields(spec, title=None, hide_if_empty=False))]


def form(ctx: BuildContext, spec: BlockSpec, params: FormParams):
    rows = [FormRow(label=row.label, value=plain_to_rich(row.value)) for row in params.rows if row.label.strip() or row.value.strip()]
    return [FormBlock(**spec_fields(spec), label_heading=params.label_heading, value_heading=params.value_heading, rows=rows)]


def bullet_list(ctx: BuildContext, spec: BlockSpec, params: BulletListParams):
    return [BulletListBlock(**spec_fields(spec), items=[item for item in params.items if item.strip()])]


def signature_fields(ctx: BuildContext, spec: BlockSpec, params: SignatureFieldsParams):
    return [
        SignatureFieldsBlock(
            **spec_fields(spec),
            fields=[SignatureField(label=field.label, name=field.name) for field in params.fields],
            with_place_date=params.with_place_date,
        )
    ]


def generic_table(ctx: BuildContext, spec: BlockSpec, params: GenericTableParams):
    width = max([len(params.headers), *(len(row) for row in params.rows)] or [0])
    if width == 0:
        return [GenericTableBlock(**spec_fields(spec), table=table_from_rows([TableColumn(key="c0")], []))]
    columns = [TableColumn(key=f"c{index}", label=(params.headers[index] if index < len(params.headers) else "")) for index in range(width)]
    rows = [TableRow(cells=[text_cell(row[index] if index < len(row) else "") for index in range(width)]) for row in params.rows if any(str(cell).strip() for cell in row)]
    table = table_from_rows(columns, rows, show_header=any(header.strip() for header in params.headers))
    return [GenericTableBlock(**spec_fields(spec), table=table)]


def qr_modules(url: str) -> list[str]:
    qr = segno.make(url, error="m")
    return ["".join("1" if bit else "0" for bit in row) for row in qr.matrix]


def qr_link(ctx: BuildContext, spec: BlockSpec, params: QrLinkParams):
    from app.models import Protocol

    url = None
    label = params.label
    if params.target == "url":
        url = params.url
    else:
        protocol = ctx.entity_by_ref(Protocol, params.protocol_id) if params.protocol_id else ctx.protocol
        if protocol is not None and ctx.public_base_url:
            ctx.ensure_can_read_protocol(protocol.id)
            url = f"{ctx.public_base_url.rstrip('/')}/protocols/{protocol.public_id}"
            label = label or protocol.title or protocol.protocol_number
    if not url:
        return [QrLinkBlock(**spec_fields(spec), url="https://", label=label, modules=[])]
    return [QrLinkBlock(**spec_fields(spec), url=url, label=label, modules=qr_modules(url))]
