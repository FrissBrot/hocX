#!/usr/bin/env bash
# Erzeugt ein selbstsigniertes Zertifikat für die Dokumentsignatur (nur Entwicklung/E2E/Tests).
#   ./scripts/generate-dev-signing-cert.sh [zielverzeichnis]   (Vorgabe: storage-local/signing)
# Schreibt signing-key.pem und signing-cert.pem. Produktion nutzt ein echtes Zertifikat
# (RUNBOOK, Abschnitt «Dokumentsignatur»). Bestehende Dateien bleiben unverändert.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$ROOT/storage-local/signing}"

if [[ -f "$TARGET/signing-key.pem" && -f "$TARGET/signing-cert.pem" ]]; then
  echo "Dev-Signaturzertifikat vorhanden: $TARGET"
  exit 0
fi
mkdir -p "$TARGET"

if command -v openssl >/dev/null 2>&1; then
  # RSA 3072, 2 Jahre, Verwendung digitale Signatur + Nichtabstreitbarkeit,
  # erweiterte Verwendung id-kp-documentSigning (RFC 9336).
  openssl req -x509 -newkey rsa:3072 -sha256 -days 730 -nodes \
    -keyout "$TARGET/signing-key.pem" -out "$TARGET/signing-cert.pem" \
    -subj "/CN=hocX Dev Document Signing/O=hocX (Entwicklung)/C=CH" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,digitalSignature,nonRepudiation,keyCertSign" \
    -addext "extendedKeyUsage=1.3.6.1.5.5.7.3.36,emailProtection" >/dev/null 2>&1
else
  # Fallback ohne openssl: gleiches Zertifikat über das Backend-Image
  docker compose run --rm --no-deps -v "$TARGET:/signing" backend python -m app.documents.devcert /signing
fi
chmod 600 "$TARGET/signing-key.pem"
# Der Backend-Container läuft als hocx (uid 5000) und muss den Schlüssel lesen können.
chown 5000 "$TARGET/signing-key.pem" "$TARGET/signing-cert.pem" 2>/dev/null || chmod 644 "$TARGET/signing-key.pem"
echo "Dev-Signaturzertifikat erzeugt: $TARGET"
