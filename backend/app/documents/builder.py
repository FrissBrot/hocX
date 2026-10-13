"""Zusammenstellung → Dokumentmodell.

Prüft jeden Block gegen den Katalog (Parameter, Zugriffsrecht), ruft den Provider auf, setzt
die Leer-Markierung und lässt leere Blöcke mit ``hide_if_empty`` weg. Meta und Optionen kommen
aus Kontext (Protokoll), Hausstil und den Export-Optionen."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.documents.catalog import CATALOG, BlockSpec, validate_spec
from app.documents.context import BuildContext, format_date
from app.documents.model import Document, DocumentMeta, DocumentOptions, ProtocolElementBlock, RenderInfo, ResolvedStyle
from app.documents.providers import PROVIDERS
from app.documents.providers.common import PROTOCOL_STATUS_CODES
from app.documents.strings import normalize_language, strings_for
from app.documents.style_tokens import DocumentStyleTokens, ExportOptions

MAX_BLOCKS = 200


class BlockSpecError(ValueError):
    """Ungültige Blockparameter (kuratiert, wird als 422 gemeldet)."""

    def __init__(self, index: int, block_type: str, detail: str) -> None:
        super().__init__(f"Block {index + 1} ({block_type}): {detail}")
        self.index = index
        self.block_type = block_type


def _mark_empty(blocks: list[Any]) -> list[Any]:
    result = []
    for block in blocks:
        if isinstance(block, ProtocolElementBlock):
            block.children = _mark_empty(block.children)
        block.empty = block.is_empty()
        if block.empty and block.hide_if_empty:
            continue
        result.append(block)
    return result


def build_blocks(ctx: BuildContext, specs: list[BlockSpec]) -> list[Any]:
    if len(specs) > MAX_BLOCKS:
        raise BlockSpecError(MAX_BLOCKS, "*", f"höchstens {MAX_BLOCKS} Blöcke")
    blocks: list[Any] = []
    for index, spec in enumerate(specs):
        entry = CATALOG.get(spec.type)
        if entry is None:
            raise BlockSpecError(index, spec.type, "unbekannter Block-Typ")
        try:
            params = validate_spec(spec)
        except ValidationError as exc:
            raise BlockSpecError(index, spec.type, exc.errors()[0].get("msg", "ungültig")) from exc
        ctx.require(entry.access)
        blocks.extend(PROVIDERS[spec.type](ctx, spec, params))
    return _mark_empty(blocks)


def build_document(
    ctx: BuildContext,
    *,
    document_type: str,
    specs: list[BlockSpec],
    style: ResolvedStyle,
    tokens: DocumentStyleTokens,
    options: ExportOptions | None = None,
    tenant_name: str = "",
    version: str | None = None,
) -> Document:
    options = options or ExportOptions()
    language = normalize_language(ctx.language)
    strings = strings_for(language)
    protocol = ctx.protocol

    if protocol is not None and document_type in ("protocol", "invitation"):
        title = protocol.title or protocol.protocol_number or strings.get(f"docType.{document_type}", "")
        meta = DocumentMeta(
            document_type=document_type,
            title=options.title or title,
            subtitle=options.subtitle or (strings.get("docType.invitation") if document_type == "invitation" else None),
            number=protocol.protocol_number,
            date=format_date(protocol.protocol_date),
            status=PROTOCOL_STATUS_CODES.get(protocol.status),
            version=version if document_type == "protocol" else None,
            tenant_name=tenant_name,
            language=language,
        )
    else:
        meta = DocumentMeta(
            document_type=document_type,
            title=options.title or strings.get(f"docType.{document_type}", strings.get("docType.custom", "")),
            subtitle=options.subtitle,
            date=format_date(ctx.today),
            tenant_name=tenant_name,
            language=language,
        )

    is_draft = protocol is not None and document_type == "protocol" and protocol.status != "abgeschlossen"
    watermark = options.watermark if options.watermark is not None else (is_draft and tokens.watermark_draft)
    document_options = DocumentOptions(
        title_page=options.title_page or tokens.title_page,
        toc=options.toc or tokens.toc,
        toc_block_titles=tokens.toc_block_titles if options.toc_block_titles is None else options.toc_block_titles,
        numbering=tokens.numbering if options.numbering is None else options.numbering,
        orientation=options.orientation or tokens.orientation,
        watermark=bool(watermark),
    )
    blocks = build_blocks(ctx, specs)
    return Document(meta=meta, options=document_options, style=style, strings=strings, render=RenderInfo(), blocks=blocks)
