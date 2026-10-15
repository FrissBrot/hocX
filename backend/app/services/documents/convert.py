"""PDF-Erzeugung (und DOC->DOCX für die Extraktion) über LibreOffice im Sandbox-Kindprozess.

Jede Konvertierung bekommt ein frisches, leeres LibreOffice-Profil mit gehärteten Einstellungen
(Makros aus, keine Aktualisierung externer Verknüpfungen, keine nicht vertrauenswürdigen
Referer-Links). Damit kann ein Dokument weder Code ausführen noch beim Laden selbständig
Ressourcen nachladen; zusätzlich hat der document-worker im Deployment keinen Internetzugang."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from app.services.documents import formats, sandbox
from app.services.documents.parsers.text import decode_text

SOFFICE_CANDIDATES = ("soffice", "libreoffice")

# Officecfg-Werte: Makros nie ausführen, Verknüpfungen nie aktualisieren, keine Links mit nicht
# vertrauenswürdigem Referer. Achtung, unterschiedliche Skalen (geprüft gegen main.xcd von
# LibreOffice 25.2): Writer "Content/Update/Link" 0 = nie, 1 = auf Anfrage (Default), 2 = immer;
# Calc 0 = immer, 1 = nie, 2 = auf Anfrage (Default). Zusätzlich ein manueller Proxy auf den
# Discard-Port 127.0.0.1:9: was LibreOffice trotzdem per HTTP(S)/FTP laden wollte, läuft ins Leere.
_PROFILE_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="UseLocking" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetProxyType" oor:op="fuse"><value>2</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPProxyName" oor:op="fuse"><value>127.0.0.1</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPProxyPort" oor:op="fuse"><value>9</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPSProxyName" oor:op="fuse"><value>127.0.0.1</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetHTTPSProxyPort" oor:op="fuse"><value>9</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetFTPProxyName" oor:op="fuse"><value>127.0.0.1</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetFTPProxyPort" oor:op="fuse"><value>9</value></prop></item>
<item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetNoProxy" oor:op="fuse"><value></value></prop></item>
</oor:items>
"""

_CSV_DELIMITER_CODES = {",": 44, ";": 59, "\t": 9, "|": 124}


class ConversionUnavailable(Exception):
    """LibreOffice ist in diesem Prozess nicht installiert."""


def soffice_binary() -> str | None:
    for name in SOFFICE_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _prepare_profile(work_dir: Path) -> Path:
    profile = work_dir / "profile"
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(_PROFILE_XCU, encoding="utf-8")
    return profile


def _prepare_input(work_dir: Path, data: bytes, mime_type: str) -> tuple[Path, str | None]:
    """Legt die Eingabe unter festem Namen ab (nie der vom Benutzer gelieferte Dateiname) und
    wählt bei Text/CSV einen expliziten UTF-8-Importfilter, damit LibreOffice die Kodierung nicht
    selbst raten muss."""
    extension = formats.CONVERTIBLE_TO_PDF.get(mime_type)
    if extension is None and mime_type == formats.DOC:
        extension = ".doc"
    if extension is None:
        raise ValueError(f"Format nicht konvertierbar: {mime_type}")
    in_dir = work_dir / "in"
    in_dir.mkdir(exist_ok=True)
    source = in_dir / f"input{extension}"
    infilter = None
    if mime_type in (formats.TXT, formats.MD):
        text, _encoding = decode_text(data)
        source.write_text(text, encoding="utf-8")
        infilter = "Text (encoded):UTF8,LF,,,"
    elif mime_type == formats.CSV:
        text, _encoding = decode_text(data)
        source.write_text(text, encoding="utf-8")
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        infilter = f"CSV:{_CSV_DELIMITER_CODES.get(delimiter, 44)},34,76,1"
    else:
        source.write_bytes(data)
    return source, infilter


def convert(data: bytes, mime_type: str, *, target: str, work_dir: Path, limits: sandbox.Limits) -> bytes:
    """Konvertiert mit LibreOffice nach target ("pdf" oder "docx") und gibt die Bytes zurück."""
    binary = soffice_binary()
    if binary is None:
        raise ConversionUnavailable("LibreOffice ist nicht installiert")
    profile = _prepare_profile(work_dir)
    source, infilter = _prepare_input(work_dir, data, mime_type)
    out_dir = work_dir / "out"
    out_dir.mkdir(exist_ok=True)
    target_filter = {"pdf": "pdf", "docx": "docx:MS Word 2007 XML"}[target]
    args = [
        binary, "--headless", "--norestore", "--nologo", "--nodefault", "--nofirststartwizard", "--nolockcheck",
        f"-env:UserInstallation={profile.as_uri()}",
    ]
    if infilter:
        args.append(f"--infilter={infilter}")
    args += ["--convert-to", target_filter, "--outdir", str(out_dir), str(source)]
    sandbox.run(args, work_dir=work_dir, limits=limits, env=sandbox.minimal_env(work_dir, {"SAL_USE_VCLPLUGIN": "svp"}))
    result = out_dir / f"{source.stem}.{target}"
    if not result.is_file() or result.stat().st_size == 0:
        raise sandbox.SandboxError("LibreOffice hat keine Ausgabe erzeugt")
    output = result.read_bytes()
    if target == "pdf" and not output.startswith(b"%PDF-"):
        raise sandbox.SandboxError("Ausgabe ist kein PDF")
    return output
