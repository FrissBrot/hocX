"""Datei-Import (Plan 2026-11-21 «Cloud-Datei-Importer», Phase P0).

P0 kennt nur die anbieterneutralen Quellen «ZIP» (inkl. Google-Takeout) und «Ordner-Upload im
Browser». Aufbau:

- ``paths``: Pfad-Normalisierung, Dateiart nach Endung, Takeout-Erkennung (rein, ohne I/O)
- ``rules``: Regel-Engine (Glob/Ordner/RE2-Regex → Tags, Schätzdatum, Überspringen, Alben)
- ``jobs``: Auftrag anlegen, Quellen einlesen, Vorschau, Start, Abbruch (Routen-Seite)
- ``worker``: Hintergrundverarbeitung im job-worker (Loop ``cloud_import``)

Jede Datei läuft durch die bestehende Upload-Pipeline (FileService.save_gallery_uploads bzw.
save_document_uploads): Grössenlimit, Magic-Byte, ClamAV, Duplikate, Kontingent.
"""
