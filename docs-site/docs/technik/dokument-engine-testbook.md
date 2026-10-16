# Testbook: Dokument-Engine und Document Studio

Dieses Testbook prüft die PDF-Erzeugung mit Typst, das Document Studio (Vorlagen, Visual
Designer, Corporate Design), Versionierung, Dokumentenregister und öffentliche Prüfseite sowie
die Migration der früheren TeX-Vorlagen. Architektur: [Dokument-Engine](dokument-engine.md),
[Document Studio](document-studio.md); Betrieb: RUNBOOK Abschnitt 13.

## Vorbereitung und Ausführung

Testdatenbank auf `alembic upgrade head` (Release 1.2.0). Die Dokumenttests synchronisieren die
mitgelieferten Systemvorlagen selbst (Fixture in `backend/tests/documents/conftest.py`).

```bash
./scripts/test.sh backend              # enthält tests/documents und die Migrationstests
./scripts/test.sh frontend             # Studio, Designer, Export-Dialog
./scripts/test.sh abgabebox-frontend   # Prüfseite /verify
python3 scripts/check-document-catalog.py   # Katalog und Studio-Texte (im Backend-Container)
```

Gezielt im Backend-Testcontainer:

```bash
python -m pytest tests/documents tests/test_document_verification.py \
  tests/test_document_engine_migration.py tests/test_document_studio_migration.py \
  tests/test_document_registry_migration.py tests/test_export_retention.py
```

Golden-Bilder nach einer gewollten Layoutänderung neu erzeugen:
`./scripts/update-document-goldens.sh` (Änderung im Review sichtbar machen, nie still
übernehmen). Testdaten des Frontends: `./scripts/update-document-studio-fixtures.sh`.

## Automatisierte Prüfungen

Testdateien unter `backend/tests/documents/`, sofern nicht anders angegeben.

### Rendern (Typst)

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| REN-01 | Lange Tabelle (500 Zeilen), Kopf-/Fusszeilen, erste Seite mit eigener Seitenvorlage | alle Zeilen, Tabellenkopf auf jeder Folgeseite, Kopf/Fuss je Seite | `test_renderer.py::test_long_table_keeps_all_500_rows_and_repeats_header`, `::test_repeated_header_and_footer_on_every_page`, `::test_first_page_master_differs` |
| REN-02 | Benutzerinhalte mit Typst-/Markdown-Sonderzeichen, Unicode, Emoji | nie ausgewertet, nie fatal; fehlende Glyphen ersetzt | `test_renderer.py::test_user_content_is_never_evaluated`, `::test_unicode_and_emoji_do_not_break_export`, `::test_uncovered_characters_are_replaced_not_fatal`, `test_richtext.py` |
| REN-03 | PDF/A-2b und XMP | gültiges PDF/A-2b; XMP mit Dokument-ID, Prüf-URL; Mandanten-ID nur bei freigegebener Anzeige | `test_renderer.py::test_pdf_is_pdfa_2b`, `test_registry.py::test_each_export_registers_the_delivered_bytes` |
| REN-04 | Assets ausserhalb des Compile-Roots, Timeout, fehlerhafter Knoten | verweigert bzw. kuratierte Meldung mit Knoten-ID | `test_renderer.py::test_assets_cannot_escape_root`, `::test_timeout_is_curated`, `::test_failing_node_is_named_with_id` |
| REN-05 | Fehlersuche nach gescheitertem Compile | endet beim ersten gescheiterten Probe-Compile bzw. nach 2 × Timeout | `test_renderer.py::test_diagnosis_stops_at_first_failed_probe`, `::test_diagnosis_respects_time_budget` |
| REN-06 | Warteschlange und Abbruch | ohne freien Platz `error.busy` (503); abgebrochene Vorschau hält den Platz bis Prozessende | `test_renderer.py::test_queue_wait_is_bounded`, `::test_cancelled_preview_keeps_the_slot_until_the_compile_finished` |
| REN-07 | Vorschau/Thumbnail mit Seitenlimit | nur die angeforderten Seiten gerastert, Gesamtzahl gemeldet | `test_renderer.py::test_png_with_page_limit_rasterizes_only_those_pages_but_reports_all`, `::test_preview_returns_limited_png_pages` |
| REN-08 | Alle Brand-Startprofile, Überschriften- und Tabellenstile | ohne Warnungen | `test_renderer.py::test_every_brand_preset_renders_without_warnings`, `::test_heading_and_table_styles_render` |
| REN-09 | Visuelle Regression | Seiten der Szenarien entsprechen den Golden-Bildern | `test_goldens.py::test_scenario_pages_match_goldens` |
| REN-10 | Jede Systemvorlage mit echten Daten | Export aller Dokumenttypen und Varianten gelingt | `test_gallery.py::test_every_system_template_exports_with_real_data` |
| REN-11 | Vorbereitung blockiert die Event-Loop nicht | `prepare()` im Threadpool | `test_versioning.py::test_prepare_does_not_block_event_loop` |

### Layout, Compiler, Fachkomponenten

| ID | Prüfung | Erwartung | Testdatei |
|---|---|---|---|
| LAY-01 | Layoutschema: Struktur, IDs, Tiefe, Seitengrössen, Grösse, Schema-Migration | ungültige oder unsichere Werte abgelehnt, alte Schemata migriert | `test_layout_schema.py` |
| LAY-02 | Bindungen, Bedingungen (ohne eval), Wiederholungen, Seitenumbrüche | korrekt aufgelöst; unbekannte Farbe nur Warnung | `test_compiler.py`, `test_conditions.py`, `test_bindings.py` |
| LAY-03 | Entwurfskennzeichnung | Wasserzeichen bei Entwürfen auch ohne Knoten in der Vorlage | `test_compiler.py::test_draft_watermark_is_enforced_without_template_node` |
| LAY-04 | Jede Fachkomponente baut mit Vorgaben; Filter, Gruppierung, Zeiträume | vollständig und leer-erkennend | `test_providers.py`, `test_model.py` |
| LAY-05 | Rechte der exportierenden Person | Mitgliederliste/Listen nur Schreibende, Finanzen nur mit Feature, eingeschränkte Leser sehen nur ihre Todos | `test_providers.py::test_member_list_requires_writer_and_finance_requires_feature`, `::test_restricted_reader_sees_only_accessible_todos`, `test_bindings.py::test_data_mode_enforces_rights_of_exporting_user` |
| LAY-06 | Bilder | nur vom Virenscan freigegebene Bilder eingebettet, aus dem Objektspeicher gelesen | `test_providers.py::test_unscanned_images_are_not_embedded` |
| LAY-07 | Systemvorlagen und Katalog | gültig, nur Textschlüssel, Standard je Dokumenttyp, Sync idempotent | `test_system_templates.py`, `scripts/check-document-catalog.py` |

### Document Studio (API)

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| STU-01 | Vorlagen-Lebenszyklus: Entwurf, Autosave mit Konflikt, Veröffentlichen, Versionen | Konflikt bei veraltetem `lock_version`; Fehler blockieren Veröffentlichung | `test_document_studio_api.py::test_template_lifecycle`, `::test_invalid_layout_is_never_saved`, `::test_publish_is_blocked_by_errors` |
| STU-02 | Parallele Speicherungen | optimistische Sperre atomar, ein Standardprofil bei gleichzeitigen Erstaufrufen | `test_document_studio_race.py` |
| STU-03 | Rollen und Mandantentrennung | Leser nur veröffentlichte Revision; fremde IDs (Assets, Komponenten, Zuweisungen, Revisionen) 404/422 | `test_document_studio_api.py::test_roles`, `::test_readers_only_see_the_published_revision`, `::test_tenant_isolation*` |
| STU-04 | Brand-Profile | Brand veröffentlichter Vorlagen nur mit Veröffentlichungsrecht; festgehaltene Revisionen verhindern Löschen | `test_document_studio_api.py::test_brand_*`, `test_brand.py` |
| STU-05 | Zuweisungen je Dokumenttyp/Protokollvorlage | Priorität korrekt, Export nutzt sie, Kopie/Löschen behält sie | `test_document_studio_api.py::test_assignment_priority_and_export_uses_it`, `::test_duplicating_a_protocol_template_keeps_its_pdf_assignment`, `::test_deleting_an_assigned_template_keeps_the_brand_assignment` |
| STU-06 | Assets: Upload, Validierung, Verwendung, Löschen | nur Rasterbilder/Schriften, verwendete nicht löschbar; Datei im Objektspeicher, Löschen als Tombstone | `test_document_studio_api.py::test_asset_upload_validation_and_usage` |
| STU-07 | Bibliothek, Thumbnails | keine N+1-Abfragen, Thumbnail-Cache auf Platte | `test_document_studio_api.py::test_library_query_count_does_not_grow_with_templates`, `::test_thumbnail_is_cached_on_disk` |

### Export, Versionierung, Register und Prüfseite

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| EXP-01 | Export Protokoll und Listen, Zusatzformate | PDF bzw. CSV/XLSX/ICS/Markdown | `test_documents_api.py::test_render_protocol_and_list_exports`, `::test_extra_formats` |
| EXP-02 | Vorschau | PNG-Seiten mit Diagnosen, nichts gespeichert; ungespeicherte Inhalte nur mit Bearbeitungsrecht | `test_documents_api.py::test_preview_*`, `test_registry.py::test_preview_creates_no_entry`, `test_versioning.py::test_preview_does_not_persist` |
| EXP-03 | Rechte | fremde Protokolle/Vorlagen 404; Listen nur Schreibende; Leser laden eigene PDFs; Entwurf ohne Wasserzeichen nur Schreibende | `test_documents_api.py::test_foreign_protocol_and_template_are_not_found`, `::test_list_sources_and_list_export_require_writer`, `::test_reader_can_download_own_rendered_pdf`, `::test_readers_cannot_export_protocol_drafts_without_watermark`, `tests/test_audit_2026_08_16_critical_fixes.py::test_s1_*`, `::test_s2_*` |
| EXP-04 | Versionierung | gleicher Inhalt gleiche Version, Inhalt ändert sie, Design/Sprache nie; erste Endfassung v1.0 | `test_versioning.py::test_version_rules`, `::test_first_final_export_is_v1_0_even_after_content_change` |
| EXP-05 | Register | jeder Export genau ein Eintrag mit SHA-256 der ausgelieferten Bytes; gescheiterte Registrierung hinterlässt weder Objekt noch Zeilen; überschriebener Titel vermerkt | `test_registry.py`, `test_documents_api.py::test_overridden_protocol_title_is_noted_in_the_registry` |
| EXP-06 | Aufbewahrung | Exporte ohne Protokollbezug nach Frist freigegeben, Register bleibt; neueste Datei abgeschlossener Protokolle und Dokumentversionen bleiben | `test_registry.py::test_retention_deletes_files_but_never_registry_entries`, `tests/test_export_retention.py` |
| VER-01 | Prüfseite (Datenbank) | Identität nur mit Zustimmung, Abzeichen nur nach Bestätigung, neuere Version nur bei Protokollen; Abgabebox-Rolle sieht nur die Funktion | `tests/test_document_verification.py` |
| VER-02 | Prüfseite (Abgabebox) | Ergebnisse inkl. «Titel überschrieben» und «importiert, nicht verifiziert» | `abgabebox-backend/tests/test_verify.py`, `abgabebox-frontend/lib/verify.test.ts` |

### Migration und Mandanten-Transfer

| ID | Prüfung | Erwartung | Testdatei / Test |
|---|---|---|---|
| MIG-01 | `0115`: TeX-Vorlagen → Hausstile, Parts → Assets, Exporte übernommen; zweiter Lauf No-op | wie beschrieben, fremde Parts nie übernommen | `tests/test_document_engine_migration.py` |
| MIG-02 | `0118`: Hausstile → Brand-Profile, Rezepte → Vorlagen; eingefrorene Übersetzung | Ergebnis unabhängig vom App-Code; 0115/0118 importieren keinen App-Code | `tests/test_document_studio_migration.py`, `test_legacy.py` |
| MIG-03 | `0116`: Signatur-Hashes ins Register | übernommen | `tests/test_document_registry_migration.py` |
| MIG-04 | Mandanten-Export/-Import/-Klon | Studio-Inhalte geprüft übernommen, alte Archive umgewandelt, Register ohne belegende PDF «nicht verifiziert» | `tests/test_tenant_export_import.py::test_import_skips_invalid_document_studio_content`, `::test_import_converts_house_styles_and_recipes_of_format_6_archives`, `::test_import_marks_registry_entries_without_matching_pdf_as_unverified`, `tests/test_tenant_clone_service.py` |
| MIG-05 | Mandanten-Löschung | übernommene Asset-Dateien entfernt, fremde bleiben | `test_tenant_delete_assets.py` |

### Frontend (Vitest)

| ID | Prüfung | Testdatei |
|---|---|---|
| FE-01 | Bibliothek | `frontend/components/documents/template-library.test.tsx` |
| FE-02 | Visual Designer (Baum, Tastatur, Speichern vor Verlassen, Undo/Redo) | `designer/designer.test.tsx`, `designer/canvas.test.ts`, `frontend/lib/documents/history.test.ts`, `layout.test.ts` |
| FE-03 | Brand Studio | `brand-studio.test.tsx` |
| FE-04 | Export-Dialog und PDF-Export | `export-dialog.test.tsx`, `frontend/lib/hooks/use-pdf-export.test.ts` |
| FE-05 | Einstellungen Echtheitsprüfung | `frontend/components/settings/document-verification-settings.test.tsx` |

## Manuelle Prüfungen

| ID | Durchführung | Erwartung |
|---|---|---|
| DOC-M1 | Protokoll über den Export-Dialog mit zwei Vorlagen und zwei Brand-Profilen exportieren | Gestaltung wechselt, Versionsnummer bleibt; PDF in Acrobat/Preflight als PDF/A-2b gültig |
| DOC-M2 | Exportiertes PDF auf `/verify` der Abgabebox ablegen, danach eine Seite verändern und erneut prüfen | «Original» bzw. «nicht gefunden»; die Datei verlässt den Browser nicht (Netzwerkprotokoll) |
| DOC-M3 | Protokoll ändern, neu exportieren, alte Datei prüfen | Hinweis auf neuere Version (wenn freigegeben) |
| DOC-M4 | Designer: Vorlage per Drag-and-drop und per Tastatur bauen, Seite verlassen mit ungespeicherten Änderungen | Warnung vor dem Verlassen, Autosave, Vorschau mit Beispiel- und echten Daten |
| DOC-M5 | Light/Dark, 1440 und 390 px: Bibliothek, Designer, Brand Studio, Export-Dialog | Design-Regeln eingehalten, bedienbar |
| DOC-M6 | Nach dem Update von 1.1.13 mit echten alten Vorlagen | jede Vorlage ein Brand-Profil, Logo/Schrift vorhanden, Migrationslog nennt Mandanten mit Slots |
| DOC-M7 | Viele gleichzeitige Vorschauen (mehrere Tabs) | kurze Wartezeit oder «viele Dokumente werden erstellt», kein Hänger |

## Grenzen

- Golden-Bilder belegen die Darstellung mit den gebündelten Schriften im Testimage, nicht die
  Anzeige in jedem PDF-Viewer (DOC-M1).
- Die automatisierten Tests laufen gegen die Dateisystem-Generation des Objektspeichers; das
  Zusammenspiel mit S3 prüft das [Release-Testbook](release-1.2.0-testbook.md) (REL-M3).
- E2E-Abläufe im Browser sind für Studio und Prüfseite nicht automatisiert.
