"""PAdES-Signatur: gültig, unverändert, XMP-Metadaten, Manipulation bricht die Prüfung."""
from __future__ import annotations

import asyncio
import io

import pytest
from pyhanko.keys import load_cert_from_pemder
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from app.core.config import settings
from app.documents import signing
from tests.documents.conftest import load_fixture

INFO = signing.SignatureInfo(document_id="0192f0aa-0000-7000-8000-000000000001", tenant_id="t-1", document_type="protocol", version="v1.2", content_hash="ab" * 32)


def _signed(renderer, signing_cert) -> bytes:
    document = load_fixture("short")
    pdf = asyncio.run(renderer.render_pdf(document)).pdf
    return signing.sign_pdf(pdf, INFO)


def _status(data: bytes, cert_path):
    reader = PdfFileReader(io.BytesIO(data))
    signature = reader.embedded_signatures[0]
    context = ValidationContext(trust_roots=[load_cert_from_pemder(str(cert_path))])
    return validate_pdf_signature(signature, context), reader


def test_signature_is_valid_and_covers_document(renderer, signing_cert):
    data = _signed(renderer, signing_cert)
    status, reader = _status(data, signing_cert)
    assert status.intact and status.valid and status.trusted
    assert status.bottom_line
    assert reader.embedded_signatures[0].field_name == signing.SIGNATURE_FIELD
    assert signing.signature_level() == "PAdES-B-B"


def test_xmp_metadata_and_pdfa_identification(renderer, signing_cert):
    data = _signed(renderer, signing_cert)
    _, reader = _status(data, signing_cert)
    xmp = reader.root["/Metadata"].get_object().data.decode("utf-8")
    for key, value in INFO.as_xmp().items():
        assert f'hocx:{key}="{value}"' in xmp or f"<hocx:{key}>{value}</hocx:{key}>" in xmp
    assert signing.HOCX_XMP_NAMESPACE in xmp
    # Präfix vergibt pyHanko selbst; geprüft wird die PDF/A-Kennung über den Namespace.
    import re

    prefix = re.search(r'xmlns:(\w+)="http://www.aiim.org/pdfa/ns/id/"', xmp).group(1)
    assert f'{prefix}:part="2"' in xmp and f'{prefix}:conformance="B"' in xmp
    assert xmp.count("pdfaExtension:schemas") >= 1 and "hocX Dokument" in xmp


def test_incremental_update_keeps_original_bytes(renderer, signing_cert):
    pdf = asyncio.run(renderer.render_pdf(load_fixture("short"))).pdf
    data = signing.sign_pdf(pdf, INFO)
    assert data.startswith(pdf)


def test_tampered_byte_breaks_validation(renderer, signing_cert):
    data = bytearray(_signed(renderer, signing_cert))
    position = data.find(b"/Contents", 200) - 50
    data[position] = (data[position] + 1) % 256
    try:
        status, _ = _status(bytes(data), signing_cert)
    except Exception:  # noqa: BLE001 - unlesbar ist auch «gebrochen»
        return
    assert not (status.intact and status.valid)


def test_certificate_status_and_production_requirement(signing_cert, monkeypatch):
    status = signing.certificate_status()
    assert status.configured and status.readable and status.days_left > 600
    monkeypatch.setattr(settings, "document_signing_cert_path", None)
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(signing.SigningNotConfiguredError):
        signing.validate_signing_configuration()
    monkeypatch.setattr(settings, "environment", "development")
    signing.validate_signing_configuration()  # nur Warnung
