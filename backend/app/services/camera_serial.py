"""Kürzel der Kamera-Seriennummer (User-Entscheid E-13, Upload-Verlauf 1.6).

Zwei Kameras desselben Modells lassen sich in den Kameragruppen eines Upload-Vorgangs nur über die
Seriennummer unterscheiden (EXIF BodySerialNumber, sonst CameraSerialNumber). In der Datenbank steht
nie die Seriennummer selbst, sondern ein keyed Hash je Mandant:

    Schlüssel = HKDF-SHA256(ADMIN_AUTH_SECRET, salt="hocx-camera-serial-v1", info="tenant:<id>")
    Kürzel    = HMAC-SHA256(Schlüssel, Make \\x1f Model \\x1f Seriennummer)[:16 Hex-Zeichen]

Warum ein bestehendes Server-Secret über HKDF statt eines neuen Secrets:
- ADMIN_AUTH_SECRET ist in jeder produktiven Installation gesetzt und geprüft (validate_for_production),
  steht genau in den Prozessen bereit, die Fotos aufnehmen (Backend und job-worker; der
  document-worker bekommt ihn bewusst nicht und rechnet deshalb kein Kürzel), und wird wegen
  secret_crypto ohnehin nicht leichtfertig gewechselt. Ein neues Secret bräuchte die ganze
  Verdrahtung nach SECURITY-RULES 5.2 für einen Wert, der nur gruppiert.
- HKDF mit eigenem salt und Mandanten-ID im info trennt die Verwendung sauber (Domänentrennung):
  aus dem Kürzel lässt sich weder das Secret noch ein anderer Schlüssel ableiten, und dieselbe
  Kamera ergibt in zwei Mandanten verschiedene Kürzel (nicht mandantenübergreifend vergleichbar).
- Folge eines Secret-Wechsels: neue Uploads erhalten andere Kürzel; ältere und neuere Fotos
  derselben Kamera erscheinen dann als zwei Geräte. Nichts geht verloren.

Die Seriennummer wird nie geloggt, in keiner Datenbankspalte gespeichert und nie in API-Antworten
gegeben; nach aussen geht nur der Gruppenschlüssel (Hash über Make/Model/Kürzel) der Kameragruppen.
Grenze (Security-Review 1.6, F-7, so entschieden): die Originaldatei bleibt unverändert gespeichert -
der Upload entfernt nur GPS-Daten -, ihre EXIF-Seriennummer geht also mit Downloads, geteilten Alben
und Exporten des Originals mit (wie vor 1.6).
"""

from __future__ import annotations

import hashlib
import hmac
import re

from app.core.config import settings

_SALT = b"hocx-camera-serial-v1"
_KEY_LENGTH = 32
KEY_HEX_LENGTH = 16
# Platzhalter, die Kameras statt einer echten Nummer eintragen
_PLACEHOLDER = re.compile(r"^(0+|1+|unknown|none|n/?a|serial|xxxx+)$", re.IGNORECASE)


def _hkdf(secret: bytes, info: bytes) -> bytes:
    """HKDF-SHA256 nach RFC 5869 (Extract + Expand), ohne zusätzliche Abhängigkeit."""
    prk = hmac.new(_SALT, secret, hashlib.sha256).digest()
    output, block, counter = b"", b"", 1
    while len(output) < _KEY_LENGTH:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:_KEY_LENGTH]


def normalize_serial(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    text = re.sub(r"\s+", "", str(raw).replace("\x00", "")).upper()[:64]
    if len(text) < 3 or _PLACEHOLDER.match(text):
        return None
    return text


def serial_key(tenant_id: int | None, make: str | None, model: str | None, serial) -> str | None:
    """Kürzel oder None (keine/Platzhalter-Seriennummer, kein Mandant, Prozess ohne Secret)."""
    normalized = normalize_serial(serial)
    if normalized is None or tenant_id is None or settings.is_secretless_process:
        return None
    key = _hkdf(settings.admin_auth_secret.encode("utf-8"), f"tenant:{int(tenant_id)}".encode())
    message = "\x1f".join(((make or "").strip().lower(), (model or "").strip().lower(), normalized)).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:KEY_HEX_LENGTH]
