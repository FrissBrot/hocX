"""PAdES-Signatur jedes erzeugten PDFs (pyHanko).

- Baseline B-B, mit ``DOCUMENT_SIGNING_TSA_URL`` B-T (RFC-3161-Zeitstempel).
- Signiert wird nach der PDF/A-Erzeugung als inkrementelles Update; das unsichtbare
  Signaturfeld heisst ``hocxSignature``. Die sichtbare Zeile «Digital signiert von hocX …»
  rendert der Hausstil (render.signed).
- Im selben Update ergänzt pyHanko die XMP-Metadaten um den Namespace ``hocx`` (Dokument-ID,
  Mandant, Dokumenttyp, Version, Inhalts-Hash) samt PDF/A-Extension-Schema - Grundlage der
  späteren Prüffunktion.

Schlüssel und Zertifikat kommen aus der Konfiguration (``DOCUMENT_SIGNING_*``), nie aus dem
Repo. Fehlt die Konfiguration in Produktion, startet das Backend nicht
(``validate_signing_configuration``); in der Entwicklung bleibt es bei einer Warnung und
unsignierten PDFs.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

HOCX_XMP_NAMESPACE = "https://hocx.ch/ns/document/1.0/"
HOCX_XMP_PREFIX = "hocx"
SIGNATURE_FIELD = "hocxSignature"
_PDFA_EXTENSION = "http://www.aiim.org/pdfa/ns/extension/"
_PDFA_SCHEMA = "http://www.aiim.org/pdfa/ns/schema#"
_PDFA_PROPERTY = "http://www.aiim.org/pdfa/ns/property#"

XMP_FIELDS = {
    "documentId": "Dokument-ID (public_id des Exports in hocX)",
    "tenantId": "public_id des Mandanten",
    "documentType": "Dokumenttyp",
    "version": "Version des Dokuments",
    "contentHash": "SHA-256 über den kanonischen Inhalt",
}


class SigningNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class SignatureInfo:
    document_id: str
    tenant_id: str
    document_type: str
    version: str
    content_hash: str

    def as_xmp(self) -> dict[str, str]:
        return {
            "documentId": self.document_id,
            "tenantId": self.tenant_id,
            "documentType": self.document_type,
            "version": self.version,
            "contentHash": self.content_hash,
        }


def signing_configured() -> bool:
    return bool(settings.document_signing_key_path and settings.document_signing_cert_path)


def signature_level() -> str:
    return "PAdES-B-T" if settings.document_signing_tsa_url else "PAdES-B-B"


_signer_lock = threading.Lock()
_signer_cache: dict[tuple, object] = {}


def _load_signer():
    from pyhanko.sign import signers

    if not signing_configured():
        raise SigningNotConfiguredError("DOCUMENT_SIGNING_KEY_PATH/DOCUMENT_SIGNING_CERT_PATH fehlen")
    key = (
        settings.document_signing_key_path,
        settings.document_signing_cert_path,
        settings.document_signing_chain_path,
        settings.document_signing_key_password,
    )
    with _signer_lock:
        if key not in _signer_cache:
            password = settings.document_signing_key_password
            signer = signers.SimpleSigner.load(
                settings.document_signing_key_path,
                settings.document_signing_cert_path,
                ca_chain_files=(settings.document_signing_chain_path,) if settings.document_signing_chain_path else None,
                key_passphrase=password.encode() if password else None,
            )
            if signer is None:
                raise SigningNotConfiguredError("Signaturschlüssel oder Zertifikat nicht lesbar")
            _signer_cache.clear()
            _signer_cache[key] = signer
        return _signer_cache[key]


def reset_signer_cache() -> None:
    with _signer_lock:
        _signer_cache.clear()


def _xmp_extension(info: SignatureInfo):
    from pyhanko.pdf_utils.metadata import model

    model.NS.setdefault(HOCX_XMP_PREFIX, HOCX_XMP_NAMESPACE)
    name = model.ExpandedName
    value = model.XmpValue
    fields = model.XmpStructure.of(*[(name(HOCX_XMP_NAMESPACE, key), value(text)) for key, text in info.as_xmp().items()])
    properties = [
        value(model.XmpStructure.of(
            (name(_PDFA_PROPERTY, "name"), value(key)),
            (name(_PDFA_PROPERTY, "valueType"), value("Text")),
            (name(_PDFA_PROPERTY, "category"), value("external")),
            (name(_PDFA_PROPERTY, "description"), value(description)),
        ))
        for key, description in XMP_FIELDS.items()
    ]
    schema = value(model.XmpStructure.of(
        (name(_PDFA_SCHEMA, "schema"), value("hocX Dokument")),
        (name(_PDFA_SCHEMA, "namespaceURI"), value(model.XmpUri(HOCX_XMP_NAMESPACE))),
        (name(_PDFA_SCHEMA, "prefix"), value(HOCX_XMP_PREFIX)),
        (name(_PDFA_SCHEMA, "property"), value(model.XmpArray.ordered(properties))),
    ))
    return fields, schema


def sign_pdf(pdf: bytes, info: SignatureInfo) -> bytes:
    """Synchrone Variante (Skripte, Tests ohne Event-Loop)."""
    import asyncio

    return asyncio.run(sign_pdf_async(pdf, info))


async def sign_pdf_async(pdf: bytes, info: SignatureInfo) -> bytes:
    """Signiert ein (PDF/A-)PDF inkrementell und ergänzt die hocX-XMP-Metadaten. Async, weil
    pyHankos synchrone Variante eine eigene Event-Loop startet (geht im Request nicht)."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.metadata import model
    from pyhanko.sign import signers, timestamps
    from pyhanko.sign.fields import SigSeedSubFilter

    signer = _load_signer()
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
    fields, schema = _xmp_extension(info)

    # Extension-Schema in die bestehende pdfaExtension:schemas-Liste (Typst) einhängen, damit
    # die Eigenschaft nicht doppelt vorkommt; ohne Liste eine neue anlegen.
    extended = False
    if "/Metadata" in writer.root:
        stream = writer.root["/Metadata"]
        for root in getattr(stream, "xmp", []) or []:
            for key, entry in root:
                if key == model.ExpandedName(_PDFA_EXTENSION, "schemas") and isinstance(entry.value, model.XmpArray):
                    entry.value.entries.append(schema)
                    extended = True
    extra = [fields]
    if not extended:
        extra.append(model.XmpStructure.of((model.ExpandedName(_PDFA_EXTENSION, "schemas"), model.XmpValue(model.XmpArray.unordered([schema])))))
    writer.document_meta.xmp_extra = extra

    timestamper = timestamps.HTTPTimeStamper(settings.document_signing_tsa_url) if settings.document_signing_tsa_url else None
    metadata = signers.PdfSignatureMetadata(field_name=SIGNATURE_FIELD, subfilter=SigSeedSubFilter.PADES, md_algorithm="sha256")
    output = await signers.PdfSigner(metadata, signer=signer, timestamper=timestamper).async_sign_pdf(writer)
    return output.getvalue()


# ── Betrieb ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CertificateStatus:
    configured: bool
    readable: bool
    subject: str | None = None
    not_after: dt.datetime | None = None
    days_left: int | None = None
    error: str | None = None


def certificate_status() -> CertificateStatus:
    """Für den Systemcheck: Zertifikat vorhanden, lesbar, Restlaufzeit."""
    if not signing_configured():
        return CertificateStatus(configured=False, readable=False)
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(Path(settings.document_signing_cert_path).read_bytes())
        _load_signer()
    except Exception as exc:  # noqa: BLE001 - Status, kein Abbruch
        return CertificateStatus(configured=True, readable=False, error=type(exc).__name__)
    not_after = cert.not_valid_after_utc
    days_left = (not_after - dt.datetime.now(dt.UTC)).days
    return CertificateStatus(configured=True, readable=True, subject=cert.subject.rfc4514_string(), not_after=not_after, days_left=days_left)


def validate_signing_configuration() -> None:
    """Beim Start: Produktion ohne lesbare Signaturkonfiguration bricht ab (wie AUTH_SECRET),
    in der Entwicklung gibt es eine deutliche Warnung."""
    status = certificate_status()
    if status.configured and status.readable:
        return
    message = (
        "Dokumentsignatur nicht konfiguriert: DOCUMENT_SIGNING_KEY_PATH und DOCUMENT_SIGNING_CERT_PATH setzen "
        "(Dev: scripts/generate-dev-signing-cert.sh, siehe RUNBOOK «Dokumentsignatur»)."
        if not status.configured
        else f"Dokumentsignatur: Schlüssel oder Zertifikat nicht lesbar ({status.error})."
    )
    if settings.is_production:
        raise SigningNotConfiguredError(message)
    logger.warning("WARNUNG: %s Erzeugte PDFs bleiben unsigniert.", message)
