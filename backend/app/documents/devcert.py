"""Selbstsigniertes Dev-Zertifikat für die Dokumentsignatur (nur Entwicklung, E2E und Tests).

    python -m app.documents.devcert <zielverzeichnis> [--password <passwort>]

Schreibt ``signing-key.pem`` und ``signing-cert.pem``. Produktion verwendet ein echtes
Zertifikat aus der Konfiguration (RUNBOOK, Abschnitt «Dokumentsignatur»), nie dieses.
Aufruf von aussen über ``scripts/generate-dev-signing-cert.sh``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# id-kp-documentSigning (RFC 9336)
DOCUMENT_SIGNING_OID = x509.ObjectIdentifier("1.3.6.1.5.5.7.3.36")


def generate(target: Path, *, password: str | None = None, days: int = 730, common_name: str = "hocX Dev Document Signing") -> tuple[Path, Path]:
    target.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "hocX (Entwicklung)"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CH"),
    ])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([DOCUMENT_SIGNING_OID, ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    encryption = serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption()
    key_path = target / "signing-key.pem"
    cert_path = target / "signing-cert.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption))
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Selbstsigniertes Dev-Zertifikat für die Dokumentsignatur")
    parser.add_argument("target", type=Path)
    parser.add_argument("--password", default=None)
    parser.add_argument("--days", type=int, default=730)
    args = parser.parse_args()
    key_path, cert_path = generate(args.target, password=args.password, days=args.days)
    print(f"Schlüssel: {key_path}\nZertifikat: {cert_path}")


if __name__ == "__main__":
    main()
