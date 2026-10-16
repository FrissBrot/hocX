"""hocX-Metadaten im XMP des PDFs (Namespace ``hocx``): Dokument-ID, Mandant, Dokumenttyp, Version,
Inhalts-Hash und Prüf-URL.

Typst erzeugt das PDF/A-2b samt XMP-Paket. Dieses Modul hängt ein **inkrementelles Update** an
(``pypdf``): die Typst-Bytes bleiben unverändert, nur ein neues ``/Metadata``-Objekt kommt dazu.
Das hocX-Schema wird in die vorhandene ``pdfaExtension:schemas``-Liste eingetragen, wie PDF/A es
für eigene Namespaces verlangt. Der SHA-256 im Dokumentenregister wird erst danach über die
endgültigen Bytes berechnet.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from xml.sax.saxutils import escape

HOCX_XMP_NAMESPACE = "https://hocx.ch/ns/document/1.0/"
HOCX_XMP_PREFIX = "hocx"

XMP_FIELDS = {
    "documentId": "Dokument-ID (public_id im Dokumentenregister von hocX)",
    "tenantId": "public_id des Mandanten",
    "documentType": "Dokumenttyp",
    "version": "Version des Dokuments",
    "contentHash": "SHA-256 über den kanonischen Inhalt",
    "verifyUrl": "Öffentliche Prüfseite für dieses Dokument",
}

_DESCRIPTION_CLOSE = "</rdf:Description>"
_SCHEMAS_CLOSE = "</rdf:Bag></pdfaExtension:schemas>"


@dataclass(frozen=True)
class DocumentXmp:
    document_id: str
    tenant_id: str
    document_type: str
    version: str
    content_hash: str
    verify_url: str

    def values(self) -> dict[str, str]:
        return {
            "documentId": self.document_id,
            "tenantId": self.tenant_id,
            "documentType": self.document_type,
            "version": self.version,
            "contentHash": self.content_hash,
            "verifyUrl": self.verify_url,
        }


def _schema() -> str:
    properties = "".join(
        '<rdf:li rdf:parseType="Resource">'
        "<pdfaProperty:category>external</pdfaProperty:category>"
        f"<pdfaProperty:description>{escape(description)}</pdfaProperty:description>"
        f"<pdfaProperty:name>{name}</pdfaProperty:name>"
        "<pdfaProperty:valueType>Text</pdfaProperty:valueType>"
        "</rdf:li>"
        for name, description in XMP_FIELDS.items()
    )
    return (
        '<rdf:li rdf:parseType="Resource">'
        "<pdfaSchema:schema>hocX Dokument</pdfaSchema:schema>"
        f"<pdfaSchema:namespaceURI>{HOCX_XMP_NAMESPACE}</pdfaSchema:namespaceURI>"
        f"<pdfaSchema:prefix>{HOCX_XMP_PREFIX}</pdfaSchema:prefix>"
        f"<pdfaSchema:property><rdf:Seq>{properties}</rdf:Seq></pdfaSchema:property>"
        "</rdf:li>"
    )


def extend_xmp(xmp: str, info: DocumentXmp) -> str:
    """hocX-Felder und Extension-Schema in ein vorhandenes XMP-Paket (Typst) einfügen."""
    if _DESCRIPTION_CLOSE not in xmp:
        raise ValueError("XMP ohne rdf:Description")
    fields = "".join(f"<{HOCX_XMP_PREFIX}:{key}>{escape(value)}</{HOCX_XMP_PREFIX}:{key}>" for key, value in info.values().items())
    if _SCHEMAS_CLOSE in xmp:
        xmp = xmp.replace(_SCHEMAS_CLOSE, _schema() + _SCHEMAS_CLOSE, 1)
    else:
        fields += f"<pdfaExtension:schemas><rdf:Bag>{_schema()}</rdf:Bag></pdfaExtension:schemas>"
    head, tail = xmp.rsplit(_DESCRIPTION_CLOSE, 1)
    xmp = head + fields + _DESCRIPTION_CLOSE + tail
    namespaces = [f'xmlns:{HOCX_XMP_PREFIX}="{HOCX_XMP_NAMESPACE}"']
    for prefix, uri in (
        ("pdfaExtension", "http://www.aiim.org/pdfa/ns/extension/"),
        ("pdfaSchema", "http://www.aiim.org/pdfa/ns/schema#"),
        ("pdfaProperty", "http://www.aiim.org/pdfa/ns/property#"),
    ):
        if f"xmlns:{prefix}=" not in xmp:
            namespaces.append(f'xmlns:{prefix}="{uri}"')
    return xmp.replace('<rdf:Description rdf:about=""', '<rdf:Description rdf:about="" ' + " ".join(namespaces), 1)


def add_document_xmp(pdf: bytes, info: DocumentXmp) -> bytes:
    """Hängt das erweiterte XMP als inkrementelles Update an; die bisherigen Bytes bleiben gleich."""
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, StreamObject

    writer = PdfWriter(io.BytesIO(pdf), incremental=True)
    root = writer._root_object
    current = root.get("/Metadata")
    xmp = current.get_object().get_data().decode("utf-8") if current is not None else ""
    if not xmp:
        raise ValueError("PDF ohne XMP-Metadaten (PDF/A erwartet)")
    data = extend_xmp(xmp, info).encode("utf-8")
    stream = StreamObject()
    stream.set_data(data)
    stream.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
    root[NameObject("/Metadata")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    result = output.getvalue()
    if not result.startswith(pdf):
        # Sicherheitsnetz: das Typst-PDF darf nur ergänzt, nie umgeschrieben werden.
        raise RuntimeError("XMP-Update hat das PDF umgeschrieben statt ergänzt")
    return result
