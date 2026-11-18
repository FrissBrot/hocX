# Abweichungen Plan ↔ Code (Plan «Berechtigungen, Datei-Kontexte und Kontext-Freigaben»)

Der Plan entstand ohne Einblick in den Code. Hier steht je Phase, wo die Umsetzung bewusst davon
abweicht und warum. «OFFEN» markiert fachliche Punkte, die noch eine Entscheidung brauchen.

## Phase 0 – Inventar und Sicherheitsnetz

- Inventar wird **generiert** (`docs/permissions-inventory.md` aus `scripts/sync-route-permissions.py`)
  statt von Hand gepflegt; CI/Pre-Commit prüfen mit `--check`, dass es aktuell ist.
- Matrix-Test: statische Matrix (`permissions/permission-matrix.json`, Standardrolle × Route) plus
  Laufzeitprüfung aller **GET**-Routen (`tests/test_permission_matrix.py`). Schreibende Routen
  prüft der Laufzeittest nicht (Body-Validierung vor der Rechteprüfung); sie deckt die statische
  Matrix ab, deren Diff jede Änderung zeigt.

## Phase 1 – Katalog und can()

- Bereits vorhanden und nicht neu gebaut: Katalog im Code (`permissions/catalog.json`, mit
  `implies`, MFA, Feature-Bindung; generiert nach Backend/Frontend), zentrale Prüfung
  `require_permission`/`require_any_permission`/`user.can` (= `can()` des Plans), Texte als
  Übersetzungen `roles.permissions.*` (Vollständigkeit prüft `sync-permission-catalog.py --check`).
- «Unbekannter Schlüssel ⇒ Fehler»: Die Prüfung nimmt nur das generierte Enum `P` an – ein
  unbekannter Schlüssel ist in jeder Umgebung ein sofortiger Fehler (nicht nur in Dev/Test).
- «Kein direkter Rollen-Check»: erzwungen durch die Sicherheitsregel `role-code-comparison`
  (Hook, Pre-Commit, CI); Suche am 18.11.2026 ohne Fund.
- Schlüssel bleiben englisch (`files.manage`, `meetings.edit` …), Entscheid vom 18.11.2026.

## Phase 2 – Dateien bekommen einen Kontext

- Kontexte `protokoll | abgabe | album | ablage` wie im Plan; `context_id` = Protokoll bzw.
  Abgabe-Auftrag (bei Album/Ablage leer – Galerie-Fotos gehören zur Galerie, nicht zu einem
  bestimmten Album).
- **Eine Datei kann in mehreren Kontexten verwendet werden** (z. B. ein Galerie-Foto in einem
  Protokoll, ein eingereichtes Foto in der Galerie). Gespeichert wird der primäre Kontext
  (Herkunft, Priorität abgabe > protokoll > album > ablage); der **Zugriff gilt, wenn einer der
  verknüpften Kontexte ihn erlaubt** (additiv). Sonst verlören Protokoll-Leser den Zugriff auf
  eingebundene Galerie-Fotos.
- «Upload-Pfade setzen den Kontext explizit»: stattdessen setzt die Datenbank ihn beim Verknüpfen
  (Trigger auf `submission_upload_file`, `gallery_image`, `protocol_image`, `document_export`,
  `word_import_document`; Funktion `hocx_file_context`). Grund: Dateien legen auch die Abgabebox und
  der Foto-Worker an; ein Weg, der eine Stelle vergisst, ist so ausgeschlossen. Neue Dateien
  starten als «ablage».
- Dry-Run: `app.services.file_context_service.report(db, tenant_id=…)` berechnet die Zuordnung
  ohne zu schreiben (Zählung je Kontext, Liste der Ablage-Fälle, Abweichungen); reversibel über
  `alembic downgrade` (Zuordnung ist jederzeit aus den Verknüpfungen neu berechenbar).
- Pendenz-Anhänge, Dokumentregister und Exporte ohne Protokoll sind «ablage» – wie heute gelten
  für sie dieselben Regeln wie für die freie Ablage.
- Keine Verhaltensänderung: `access_service.ensure_can_read_stored_file` prüft unverändert; die
  Rechte je Kontext kommen in Phase 3 (Mapping ohne Rechteverlust) und 5 (Freigaben).
