# hocX – Vollständiger Feature-Katalog

Stand: 2026-10-27. Zentraler Katalog aller bestehenden und vorgeschlagenen Features. Modulstruktur:
`docs/PRODUCT_MODULE_ARCHITECTURE.md`; Abo-Zuordnung: `docs/SAAS_SUBSCRIPTION_STRATEGY.md`;
neue Features im Detail: `docs/FEATURE_EXPANSION_ROADMAP.md`.

**Zwei Arten von Features.** Die meisten Features sind immer Teil eines Abos (Grundfunktion) und
haben keinen eigenen technischen Schalter. Nur **buchbare Features** (Entitlements) haben einen Code
in `permissions/features.json`, werden in `tenant_feature` geführt und im Backend mit
`require_feature`/`require_permission` geprüft. Sie sind unten mit «Entitlement-Code» markiert.

Status: **EXISTING** vorhanden · **PARTIAL** teilweise · **PLANNED** geplant · **PROPOSED** neu vorgeschlagen.
Priorität: **P0** Kernprodukt/kritische Lücke · **P1** hoher Nutzen · **P2** mittelfristig · **P3** optional.
Aufwand: S (≤ 3 Tage), M (1–2 Wochen), L (> 2 Wochen) für eine Person [A: Schätzung].
Abo: Basic = Plan `starter`, Pro = `standard`, Business = `premium` (Codes bleiben, Anzeigenamen siehe Abo-Strategie).

## Übersicht

| Status | Anzahl |
|---|---|
| EXISTING | 44 |
| PARTIAL | 6 |
| PLANNED | 1 |
| PROPOSED | 18 |
| **Total** | **69** |

| Key | Modul | Name | Status | Prio | Abo | Entitlement |
|---|---|---|---|---|---|---|
| `meetings.protocols` | Sitzungen und Protokolle | Protokolle führen | EXISTING | P0 | Basic | – |
| `meetings.collaboration` | Sitzungen und Protokolle | Live-Zusammenarbeit | EXISTING | P0 | Basic | – |
| `meetings.track_changes` | Sitzungen und Protokolle | Änderungsverfolgung | PARTIAL | P2 | Basic | – |
| `meetings.closing` | Sitzungen und Protokolle | Abschluss und Archiv | EXISTING | P0 | Basic | – |
| `meetings.session_templates` | Sitzungen und Protokolle | Sitzungsvorlagen | EXISTING | P0 | Basic | – |
| `meetings.building_blocks` | Sitzungen und Protokolle | Bausteine | EXISTING | P0 | Basic | – |
| `meetings.cycles` | Sitzungen und Protokolle | Zyklen | EXISTING | P1 | Basic | – |
| `meetings.agenda_items` | Sitzungen und Protokolle | Anliegen | EXISTING | P1 | Basic | – |
| `meetings.todos` | Sitzungen und Protokolle | Pendenzen | PARTIAL | P0 | Basic | – |
| `meetings.events` | Sitzungen und Protokolle | Termine und Jahresprogramm | EXISTING | P0 | Basic | – |
| `meetings.attendance` | Sitzungen und Protokolle | Anwesenheit | EXISTING | P0 | Basic | – |
| `meetings.lists` | Sitzungen und Protokolle | Listen und Jahresstände | EXISTING | P1 | Basic | – |
| `meetings.statistics` | Sitzungen und Protokolle | Auswertungen | EXISTING | P1 | Basic | – |
| `meetings.calendar_feeds` | Sitzungen und Protokolle | Kalender-Abos | EXISTING | P1 | Basic | – |
| `meetings.word_import` | Sitzungen und Protokolle | Word-/PDF-Import | PARTIAL | P1 | Basic | – |
| `meetings.task_packages` | Sitzungen und Protokolle | Aufgabenpakete | EXISTING | P1 | Pro | `task_packages` |
| `meetings.distribution` | Sitzungen und Protokolle | Versand von Einladung und Protokoll | PROPOSED | P0 | Basic | – |
| `meetings.reminders` | Sitzungen und Protokolle | Erinnerungen | PROPOSED | P1 | Pro | – |
| `meetings.rsvp` | Sitzungen und Protokolle | An-/Abmeldung per Link | PROPOSED | P1 | Pro | – |
| `meetings.decisions` | Sitzungen und Protokolle | Beschlussregister | PROPOSED | P1 | Pro | – |
| `meetings.search` | Sitzungen und Protokolle | Globale Suche | PROPOSED | P2 | Basic | – |
| `meetings.committees` | Sitzungen und Protokolle | Gremien und Bereiche | PROPOSED | P2 | Business | – |
| `meetings.reports` | Sitzungen und Protokolle | Jahresbericht | PROPOSED | P2 | Pro | – |
| `people.participants` | Mitglieder und Zugänge | Teilnehmende und Mitgliedschaft | EXISTING | P0 | Basic | – |
| `people.accounts` | Mitglieder und Zugänge | Konten mit Login | EXISTING | P0 | Basic | – |
| `people.user_limit` | Mitglieder und Zugänge | Benutzerlimit | EXISTING | P0 | Basic | – |
| `people.standard_roles` | Mitglieder und Zugänge | Standardrollen | EXISTING | P0 | Basic | – |
| `people.custom_roles` | Mitglieder und Zugänge | Eigene Rollen | EXISTING | P1 | Business | `custom_roles` |
| `people.personal_data` | Mitglieder und Zugänge | Datenauskunft | EXISTING | P0 | Basic | – |
| `people.password_reset` | Mitglieder und Zugänge | Passwort per E-Mail zurücksetzen | PROPOSED | P0 | Basic | – |
| `people.invitations` | Mitglieder und Zugänge | Login-Einladung | PROPOSED | P1 | Basic | – |
| `people.sso` | Mitglieder und Zugänge | Anmeldung mit Microsoft/Google (SSO) | PROPOSED | P2 | Business | – |
| `documents.exports` | Dokumente und Erscheinungsbild | Dokumente und Exporte | EXISTING | P0 | Basic | – |
| `documents.system_templates` | Dokumente und Erscheinungsbild | Systemvorlagen | EXISTING | P0 | Basic | – |
| `documents.brand` | Dokumente und Erscheinungsbild | Erscheinungsbild | EXISTING | P0 | Basic | – |
| `documents.design_examples` | Dokumente und Erscheinungsbild | Gestaltungsbeispiele | EXISTING | P1 | Pro | – |
| `documents.designer` | Dokumente und Erscheinungsbild | Dokument-Designer | EXISTING | P1 | Pro | `document_designer` |
| `documents.verification` | Dokumente und Erscheinungsbild | Echtheitsprüfung | EXISTING | P1 | Basic | – |
| `documents.verified_org` | Dokumente und Erscheinungsbild | Verifizierte Organisation | EXISTING | P2 | Basic | – |
| `documents.verify_domain` | Dokumente und Erscheinungsbild | Eigene Prüf-Domain | EXISTING | P2 | Add-on | `verify_domain` |
| `documents.signature` | Dokumente und Erscheinungsbild | Digitale Signatur | PLANNED | P3 | Add-on | – |
| `finance.ledger` | Finanzen | Kassenbuch | EXISTING | P1 | Pro | `finance` |
| `finance.fines` | Finanzen | Bussen | EXISTING | P1 | Pro | `finance` |
| `finance.reports` | Finanzen | Finanzberichte | EXISTING | P1 | Pro | `finance` |
| `finance.dues` | Finanzen | Mitgliederbeiträge | PROPOSED | P1 | Pro | – |
| `finance.import` | Finanzen | Bankimport | PROPOSED | P2 | Pro | – |
| `finance.categories` | Finanzen | Kategorien und Budget | PROPOSED | P3 | Pro | – |
| `media.photos` | Medien und Dateien | Fotos und Alben | EXISTING | P1 | Basic | – |
| `media.photo_intelligence` | Medien und Dateien | Fotos sortieren | EXISTING | P2 | Basic | – |
| `media.files` | Medien und Dateien | Dateien | EXISTING | P1 | Basic | – |
| `media.sharing` | Medien und Dateien | Teilen von Fotos | EXISTING | P1 | Pro | `photo_sharing` |
| `submissions.box` | Abgaben | Abgabebox | EXISTING | P1 | Basic | `abgabebox` |
| `submissions.notifications` | Abgaben | Eingangsbenachrichtigung | PROPOSED | P2 | Pro | – |
| `admin.tenant_settings` | Verwaltung und Datenschutz | Vereinsprofil und Einstellungen | EXISTING | P0 | Basic | – |
| `admin.custom_domain` | Verwaltung und Datenschutz | Eigene Domain | EXISTING | P2 | Business | `custom_domain` |
| `admin.privacy` | Verwaltung und Datenschutz | Datenschutzeinstellungen | EXISTING | P0 | Basic | – |
| `admin.retention` | Verwaltung und Datenschutz | Aufbewahrung und Löschvorschläge | EXISTING | P1 | Basic | – |
| `admin.activity` | Verwaltung und Datenschutz | Aktivitätsprotokoll | EXISTING | P1 | Basic | – |
| `admin.data_export` | Verwaltung und Datenschutz | Vereinsexport | EXISTING | P0 | Basic | – |
| `admin.subscription` | Verwaltung und Datenschutz | Abo und Nutzung | PARTIAL | P1 | Basic | – |
| `admin.api` | Verwaltung und Datenschutz | API und Webhooks | PROPOSED | P3 | Add-on | – |
| `platform.tenants` | Plattform (intern) | Mandantenverwaltung | EXISTING | P0 | intern | – |
| `platform.catalog` | Plattform (intern) | Pläne, Features, Preise | EXISTING | P0 | intern | – |
| `platform.billing` | Plattform (intern) | Forderungen und Cashflow | PARTIAL | P1 | intern | – |
| `platform.operations` | Plattform (intern) | Betrieb | EXISTING | P0 | intern | – |
| `platform.website` | Plattform (intern) | Website mit Preisen | PARTIAL | P1 | intern | – |
| `platform.email` | Plattform (intern) | E-Mail-Versand | PROPOSED | P0 | intern | – |
| `platform.self_signup` | Plattform (intern) | Registrierung und Testphase | PROPOSED | P1 | intern | – |
| `platform.payments` | Plattform (intern) | Online-Zahlung | PROPOSED | P2 | intern | – |

### Quick Wins

Wenig Aufwand, hoher Nutzen (Details in der Roadmap):

1. Status «abgebrochen» für Pendenzen in der Oberfläche setzbar machen (`meetings.todos`, S).
2. Upgrade-Anfrage auf der Abo-Seite (`admin.subscription`, S).
3. Website-Aussage «30 Tage testen» an die Realität anpassen oder Demo-Anfrage daraus machen (`platform.website`, S).
4. Feature-Beschreibung `finance` («Beiträge») bis zur Umsetzung von `finance.dues` korrigieren (S).
5. Job-Text «Gesichtserkennung» → «Gesichtsqualität» korrigieren (`media.photo_intelligence`, S).
6. Verwaiste Texte und Endpunkte entfernen (`events.exportModal.markdownSoon`, `collaborationViewSoon`, `GET /files/stats`) (S).
7. Seiten-Gates für `/documents*` und `/tools/*` an die Backend-Rechte angleichen (S).
8. Default von `track_changes_enabled` vereinheitlichen (`meetings.track_changes`, S).
9. Jahresbericht aus vorhandenen Bausteinen als Systemvorlage (`meetings.reports`, S–M).

## Modul: Sitzungen und Protokolle (`meetings`)

### `meetings.protocols` – Protokolle führen

Protokolle aus Vorlagen erstellen, im Workflow geplant → vorbereitet → durchgeführt → abgeschlossen bearbeiten.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Erstellen aus Vorlage mit Vorschau von Nummer und Titel; Status-Workflow mit Rückstufung um einen Schritt; Editor mit Autosave und Konfliktschutz; Sprungsuche im Protokoll; Löschen mit Vorschau betroffener Dateien; Nummerierung nach Muster und Zyklus; Scroll-Position und zuletzt genutzte Vorlage merken |
| Kundennutzen | Kernnutzen: Protokoll ohne Nacharbeit |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Sitzungsvorlagen |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion jedes Abos; ohne sie kein Produkt |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/protocols.py`, `services/protocol_service.py`, `components/protocol/protocol-editor.tsx` |
| Migrationsbedarf | keiner |

### `meetings.collaboration` – Live-Zusammenarbeit

Mehrere Personen bearbeiten ein Protokoll gleichzeitig.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Feldsperren per WebSocket; Anwesenheitsanzeige; Live-Updates von Feldern, Status und verknüpften Tabellen; Sitzungsrevalidierung |
| Kundennutzen | Protokoll entsteht während der Sitzung |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Redis, WebSocket |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Versprechen der Website («gemeinsam live schreiben»); kein Abo-Hebel |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/collaboration_ws.py`, `services/collaboration_service.py` |
| Migrationsbedarf | keiner |

### `meetings.track_changes` – Änderungsverfolgung

Änderungen an vorbereiteten Inhalten werden markiert und einzeln übernommen.

| Feld | Wert |
|---|---|
| Status / Priorität | PARTIAL / P2 |
| Enthaltene Funktionen | Markierungen für Text, Pendenzen, Listen; Einzeln akzeptieren; Bereinigung beim Statuswechsel |
| Kundennutzen | Nachvollziehbare Vorbereitung im Vorstand |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Protokolle |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Aktiv nur im Status «geplant», Default-Inkonsistenz (DB true, Schema False); vor Vermarktung als eigenes Argument vereinheitlichen |
| Implementierungsaufwand | S–M |
| Codefundstellen | `routes/protocol_elements.py:275`, `schemas/protocol.py:46`, `protocol-editor.tsx:164` |
| Migrationsbedarf | keiner |

### `meetings.closing` – Abschluss und Archiv

Abgeschlossene Protokolle werden eingefroren und bleiben unverändert.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Pendenzen-, Listen-, Verantwortlichen- und Mitgliedschafts-Momentaufnahmen; Ersetzen früherer Abschluss-PDFs; Automatisches Folgeprotokoll aus der nächsten Sitzung |
| Kundennutzen | Revisionssichere Protokolle |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Protokolle, Dokumente |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `protocol_service.py` (`_run_status_transition_hooks`, `_maybe_auto_create_next_protocol`) |
| Migrationsbedarf | keiner |

### `meetings.session_templates` – Sitzungsvorlagen

Wiederkehrende Sitzungen als Vorlage mit Traktanden, Bausteinen, Teilnehmenden und Verantwortlichen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Vorlagen anlegen, duplizieren, archivieren; Teilnehmende je Vorlage; Verantwortliche je Traktandum (Personen oder Tabellenzeile, live); Bestehende Protokolle mit der Vorlage synchronisieren; Busstarif je Vorlage (mit Finanzen) |
| Kundennutzen | Protokoll in Sekunden vorbereitet |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Bausteine |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/templates.py`, `template-builder.tsx`, `responsible_label_service.py` |
| Migrationsbedarf | keiner |

### `meetings.building_blocks` – Bausteine

Bibliothek wiederverwendbarer Traktanden-Bausteine mit 13 Blocktypen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Text, Pendenzen, Bild, Formular, Matrix, Termine, Anwesenheit, nächste Sitzung, Diagramm, Ein-/Austritte, Sitzungsnotizen; Übernahme vom letzten Protokoll; Zeilen-Designer |
| Kundennutzen | Einheitliche Protokolle |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion; Legacy-Typen `display`, `static_text`, `bullet_list` entfernen |
| Implementierungsaufwand | – |
| Codefundstellen | `element-types/registry.json`, `services/element_config.py`, `/elements` |
| Migrationsbedarf | Legacy-Blocktypen migrieren (Phase 2) |

### `meetings.cycles` – Zyklen

Vereinsjahre/Perioden mit Namensmuster; Grundlage für Nummerierung, Listenstände und Aufgabenpakete.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Zyklen mit Stichtag; Namens- und Nummernmuster |
| Kundennutzen | Ordnung über Jahre |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/cycle_configs.py`, `/cycles` |
| Migrationsbedarf | keiner |

### `meetings.agenda_items` – Anliegen

Traktandenvorschläge für kommende Sitzungen sammeln und einplanen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Anliegen erfassen, verschieben; Ziel-Traktandum, nächste Sitzung oder Monat; Feste Bindung beim Durchführen |
| Kundennutzen | Nichts geht vergessen |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Sitzungsvorlagen |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/agenda_items.py`, `/agenda` |
| Migrationsbedarf | keiner |

### `meetings.todos` – Pendenzen

Aufgaben aus Sitzungen mit Verantwortlichen, Fälligkeit und Status.

| Feld | Wert |
|---|---|
| Status / Priorität | PARTIAL / P0 |
| Enthaltene Funktionen | Mehrere Zuständige; Fälligkeit als Datum, Termin oder «nächste Sitzung»; Dateien, Tags, Notizen; «Meine Pendenzen», Dashboard; PDF/Markdown-Export |
| Kundennutzen | Pendenzen werden erledigt |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Protokolle |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion; Status «abgebrochen» existiert im Backend, ist in der Oberfläche nicht setzbar (Quick Win) |
| Implementierungsaufwand | S |
| Codefundstellen | `routes/todos.py`, `/todos`, `todos/todo-list-view.tsx` |
| Migrationsbedarf | keiner |

### `meetings.events` – Termine und Jahresprogramm

Termine mit Tags, Uhrzeit, Ort, Rollenlisten; Kalenderansichten.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Mehrtägige Termine, Absagen; CSV-Import mit Vorschau; Tags mit Farben, Umbenennen; Export PDF/CSV/XLSX/ICS |
| Kundennutzen | Jahresplanung an einem Ort |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion; `EventCategory` kaum zugänglich → entfernen oder in Tags aufgehen lassen |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/events.py`, `events/event-manager.tsx` |
| Migrationsbedarf | keiner |

### `meetings.attendance` – Anwesenheit

Anwesenheit je Sitzung erfassen, Abmeldungen aus dem Dashboard.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Status anwesend/verspätet/entschuldigt/abwesend; Teilnehmerkreis aus der Vorlage; Abmelden aus dem Dashboard; Präsenzliste als PDF |
| Kundennutzen | Beschlussfähigkeit und Bussen belegbar |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Teilnehmende |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/protocol_elements.py`, `use-session-attendance.ts` |
| Migrationsbedarf | keiner |

### `meetings.lists` – Listen und Jahresstände

Zweispaltige Stammlisten (z. B. Ämtli) mit Jahresständen je Zyklus.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Listen mit Text/Person/Personen/Termin; Verknüpfung in Protokolle; Jahresstände (Snapshots) und Rekonstruktion |
| Kundennutzen | Ämtli und Zuständigkeiten aktuell |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Zyklen |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/lists.py`, `routes/table_snapshots.py` |
| Migrationsbedarf | keiner |

### `meetings.statistics` – Auswertungen

Dashboard und Statistik über Sitzungen, Anwesenheit, Pendenzen, Bussen, Finanzen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Kennzahlen; Anwesenheit je Person und Zeitraum; Zeitraum- und Zyklusfilter; Export |
| Kundennutzen | Überblick für den Vorstand |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Finanzteil nur mit `finance` |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion; erweiterte Berichte siehe `meetings.reports` |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/statistics.py`, `/statistics` |
| Migrationsbedarf | keiner |

### `meetings.calendar_feeds` – Kalender-Abos

Persönliche ICS-Abos für Termine und Pendenzen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Abos für Termine/Pendenzen, eigene oder alle; Token-Erneuerung; Anleitungen Apple/Google/Android |
| Kundennutzen | Termine im eigenen Kalender |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion, ersetzt teilweise Benachrichtigungen |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/calendar_feeds.py`, `/connections` |
| Migrationsbedarf | keiner |

### `meetings.word_import` – Word-/PDF-Import

Bestehende Protokolle aus Word/PDF übernehmen.

| Feld | Wert |
|---|---|
| Status / Priorität | PARTIAL / P1 |
| Enthaltene Funktionen | Analyse mit Zuordnung von Anwesenheit, Listen, Terminen, Pendenzen; Warteschlange und Assistent; Lernmodell; Historische Listenlücken füllen |
| Kundennutzen | Einstieg ohne Datenverlust |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Protokolle |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Onboarding-Argument («übernehmen wir für Sie»), kein Upsell; zwei Oberflächen zusammenführen |
| Implementierungsaufwand | M |
| Codefundstellen | `routes/word_import.py`, `/tools/import`, `/tools/word-import` |
| Migrationsbedarf | keiner |

### `meetings.task_packages` – Aufgabenpakete

Wiederkehrende Aufgaben je Zyklus automatisch als Pendenzen erzeugen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Pakete mit Aufgaben, Verantwortlichen aus Listen, Wiederholung (einmalig/monatlich/wöchentlich/je Termin); Zyklen zuordnen; Täglicher Job; Manuelle Änderungen bleiben erhalten |
| Kundennutzen | Spart wiederkehrende Planungsarbeit |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Zyklen, Listen, Pendenzen |
| Abo | Pro |
| Entitlement-Code | `task_packages` |
| Wirtschaftliche Begründung | Automatisierung mit klarem Zeitgewinn – natürlicher Upgrade-Grund; nach Downgrade nur lesend |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/task_packages.py`, `services/task_package_service.py` |
| Migrationsbedarf | 0158 (Feature + Backfill) |

### `meetings.distribution` – Versand von Einladung und Protokoll

Einladung, Traktandenliste und Protokoll per E-Mail an Teilnehmende senden.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P0 |
| Enthaltene Funktionen | Empfänger aus der Vorlage; PDF als Anhang oder Link; Versandprotokoll |
| Kundennutzen | Schliesst den Workflow «Vorher – Während – Nachher» |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | `platform.email` |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Kunden erwarten Versand; heute Medienbruch (PDF herunterladen, selbst mailen) |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Tabelle für Versandprotokoll |

### `meetings.reminders` – Erinnerungen

Automatische Erinnerungen an fällige Pendenzen und bevorstehende Sitzungen.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P1 |
| Enthaltene Funktionen | Pendenzen fällig/überfällig; Sitzung in X Tagen mit Abmeldelink; Einstellungen je Person |
| Kundennutzen | Weniger Nachfassen durch den Vorstand |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | `platform.email`, `meetings.rsvp` |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Automatisierung, messbar weniger Aufwand – starker Upgrade-Anreiz |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Einstellungen je Konto, Job |

### `meetings.rsvp` – An-/Abmeldung per Link

Teilnehmende melden sich ohne Login über einen persönlichen Link an oder ab.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P1 |
| Enthaltene Funktionen | Persönlicher Link je Sitzung; Status fliesst in Anwesenheit; Frist |
| Kundennutzen | Planbarkeit ohne Login-Zwang |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | `platform.email`, Anwesenheit |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Erweitert vorhandene Abmeldung (Dashboard) auf Personen ohne Login |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Token-Tabelle |

### `meetings.decisions` – Beschlussregister

Beschlüsse als eigener Inhalt im Protokoll, durchsuchbar über alle Sitzungen.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P1 |
| Enthaltene Funktionen | Beschluss-Block mit Abstimmungsresultat; Register über alle Protokolle; Export |
| Kundennutzen | Nachweis «wer hat wann was beschlossen» |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | Protokolle, Dokumente (Zitat-Darstellung «Beschluss» existiert) |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Typische Erwartung bei GL/Vorständen; Differenzierung gegenüber Textprotokollen |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Neuer Blocktyp |

### `meetings.search` – Globale Suche

Suche über Protokolle, Pendenzen, Anliegen, Termine und Dateien.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | Volltext; Berechtigungsgefiltert |
| Kundennutzen | Wissen wiederfinden |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | PostgreSQL-Volltext |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundnutzen, kein Upsell; wird mit wachsendem Archiv wichtiger |
| Implementierungsaufwand | M–L |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Volltext-Indizes |

### `meetings.committees` – Gremien und Bereiche

Mehrere Gremien (Vorstand, Kommissionen) mit eigenem Zugriff innerhalb eines Mandanten.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | Vorlagen und Protokolle je Gremium; Zugriff je Gremium |
| Kundennutzen | Ein Verband statt mehrerer Mandanten |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | RBAC, `UserTemplateAccess` (heute ungenutzt) |
| Abo | Business |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Skalierung mit Organisationsgrösse – Business-Argument |
| Implementierungsaufwand | L |
| Codefundstellen | `models/entities.py` (`UserTemplateAccess`) |
| Migrationsbedarf | Ressourcenbezogene Rechte |

### `meetings.reports` – Jahresbericht

Jahresbericht aus Protokollen, Anwesenheit, Pendenzen und Finanzen als Dokument.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | Vorlage im Document Studio; Kennzahlen je Zyklus |
| Kundennutzen | GV-Unterlagen auf Knopfdruck |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Dokument-Engine, Statistik |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Weitgehend aus vorhandenen Bausteinen (Dokumenttyp `statistics`) baubar |
| Implementierungsaufwand | S–M |
| Codefundstellen | `documents/doc_types.py` |
| Migrationsbedarf | keiner |

## Modul: Mitglieder und Zugänge (`people`)

### `people.participants` – Teilnehmende und Mitgliedschaft

Personen mit und ohne Login, Eintritt/Austritt, Zuordnung zu Vorlagen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | CRUD, Massenlöschen, CSV-Import; Eintritt/Austritt, Ein-/Austritte-Block; Filter aktiv/inaktiv/ausgetreten |
| Kundennutzen | Eine Personenliste für alles |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/participants.py`, `/participants` |
| Migrationsbedarf | keiner |

### `people.accounts` – Konten mit Login

Login, MFA (TOTP, Passkeys), Sprache, Sitzungsentzug.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Login aktivieren; MFA; Passwort ändern; Sitzungen beenden |
| Kundennutzen | Sicherer Zugang |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/users.py`, `mfa_service.py` |
| Migrationsbedarf | keiner |

### `people.user_limit` – Benutzerlimit

Anzahl aktiver Konten mit Login je Abo.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Limit aus Plan oder Override; Durchsetzung beim Aktivieren; Anzeige in Abo-Ansicht |
| Kundennutzen | Faire Paketgrenzen |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Plan |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Bisher nur angezeigt, jetzt durchgesetzt; Teilnehmende ohne Login zählen nicht |
| Implementierungsaufwand | – |
| Codefundstellen | `services/user_limit_service.py` |
| Migrationsbedarf | keiner (Zählweise geändert: Konten mit Login) |

### `people.standard_roles` – Standardrollen

Administrator, Schreiber, Kassier, Leser mit festen Rechten.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Mehrfachrollen; Schutzregeln (letzter Admin, keine Rechteausweitung) |
| Kundennutzen | Rechte ohne Konfiguration |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | RBAC |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `permissions/catalog.json`, `role_service.py` |
| Migrationsbedarf | keiner |

### `people.custom_roles` – Eigene Rollen

Eigene Rollen anlegen und Rechte der Standardrollen anpassen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Rollen mit beliebigen Berechtigungen; Standardrollen anpassen |
| Kundennutzen | Rechte passend zur Organisation |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | RBAC |
| Abo | Business |
| Entitlement-Code | `custom_roles` |
| Wirtschaftliche Begründung | Relevant für grössere Organisationen; nach Downgrade bleiben Rollen wirksam und zuweisbar, nur Änderungen gesperrt |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/roles.py`, `/users/roles` |
| Migrationsbedarf | 0158 (Feature + Backfill) |

### `people.personal_data` – Datenauskunft

Persönliche Datenauskunft (DSG/DSGVO) für sich oder Teilnehmende.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Passwortgeschütztes ZIP |
| Kundennutzen | Rechtspflicht erfüllt |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Rechtliche Pflicht – nie abostufen |
| Implementierungsaufwand | – |
| Codefundstellen | `services/data_export/personal.py` |
| Migrationsbedarf | keiner |

### `people.password_reset` – Passwort per E-Mail zurücksetzen

Selbstständiges Zurücksetzen des Passworts.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P0 |
| Enthaltene Funktionen | Einmal-Link per E-Mail; Rate-Limit |
| Kundennutzen | Weniger Support |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | `platform.email` |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Fehlt heute ganz; verursacht Supportaufwand bei jedem vergessenen Passwort |
| Implementierungsaufwand | S–M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Token-Tabelle |

### `people.invitations` – Login-Einladung

Konten per E-Mail einladen statt Passwort zu setzen.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P1 |
| Enthaltene Funktionen | Einladung mit Ablauf; Erstanmeldung setzt Passwort und MFA |
| Kundennutzen | Einfaches Onboarding neuer Vorstandsmitglieder |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | `platform.email` |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Senkt Einstiegshürde; heute setzt der Admin ein Passwort |
| Implementierungsaufwand | S–M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Token-Tabelle |

### `people.sso` – Anmeldung mit Microsoft/Google (SSO)

OIDC-Anmeldung für Mandanten-Benutzer.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | OIDC je Mandant; Zuordnung per E-Mail |
| Kundennutzen | Ein Login für KMU |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | Plattform-OIDC existiert für Admins |
| Abo | Business |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Business-Anforderung bei KMU; Wiederverwendung von `platform_oidc_service.py` |
| Implementierungsaufwand | M–L |
| Codefundstellen | `services/platform_oidc_service.py` |
| Migrationsbedarf | OIDC-Konfiguration je Mandant |

## Modul: Dokumente und Erscheinungsbild (`documents`)

### `documents.exports` – Dokumente und Exporte

16 Dokumenttypen als PDF/A, dazu CSV, XLSX, ICS, Markdown; Exportverlauf.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Protokoll, Einladung, Traktandenliste, Anwesenheit, Mitglieder, Pendenzen, Termine, Kalender, Finanzen, Statistik, Listen; Exporte als Job; Exportverlauf |
| Kundennutzen | Fertige Dokumente ohne Nacharbeit |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Dokument-Engine |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `backend/app/documents/`, `routes/documents.py` |
| Migrationsbedarf | keiner |

### `documents.system_templates` – Systemvorlagen

Fertige Vorlagen je Dokumenttyp und Zuweisung je Dokumenttyp/Sitzungsvorlage.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | 26 Systemvorlagen; Zuweisung |
| Kundennutzen | Gute Dokumente ab Tag 1 |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Dokument-Engine |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `documents/system_templates.py` |
| Migrationsbedarf | keiner |

### `documents.brand` – Erscheinungsbild

Farben, Schriften, Logo, Kopf-/Fusszeile, Darstellungsvarianten aller Elemente.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Brand Studio mit Revisionen; Eigene Schriften und Bilder; Grundstile und Varianten (inkl. Mockup-Darstellungen: Karten, Checkliste, Badges, Verantwortliche rechts, leere Bausteine ausblenden) |
| Kundennutzen | Dokumente im eigenen Auftritt |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Dokument-Engine |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Gehört zum Kernversprechen «PDF im eigenen Erscheinungsbild» |
| Implementierungsaufwand | – |
| Codefundstellen | `documents/brand.py`, `documents/appearance.py`, `/documents/brand` |
| Migrationsbedarf | keiner |

### `documents.design_examples` – Gestaltungsbeispiele

Sechs fertige Protokoll-Designs (Verein Band/Hell, Bau, Tech, Kanzlei, Corporate) zum Übernehmen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Import von Vorlage und Brand |
| Kundennutzen | Schneller Start mit gutem Design |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Dokument-Designer (Import legt eine eigene Vorlage an) |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Schaufenster für den Designer; in Basic als Vorschau sichtbar |
| Implementierungsaufwand | – |
| Codefundstellen | `documents/examples.py` |
| Migrationsbedarf | keiner |

### `documents.designer` – Dokument-Designer

Eigene Dokumentvorlagen und Bausteine gestalten, mit Revisionen und Veröffentlichung.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Designer mit Vorschau; Eigene Bausteine; Revisionen, Vergleich, Wiederherstellen; Gestaltung je Sitzungsvorlage |
| Kundennutzen | Volle Gestaltungsfreiheit |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Dokument-Engine |
| Abo | Pro |
| Entitlement-Code | `document_designer` |
| Wirtschaftliche Begründung | Hoher Mehrwert für Organisationen mit Corporate Design; nach Downgrade bleiben Vorlagen nutzbar, Änderungen gesperrt |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/document_studio.py`, `documents/permissions.py::require_design`, `components/documents/designer/` |
| Migrationsbedarf | 0158 (Feature + Backfill) |

### `documents.verification` – Echtheitsprüfung

Prüfvermerk mit Hash und QR, öffentliche Prüfseite, Dokumentenregister.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Prüf-URL im PDF/XMP; Öffentliche Prüfung; Register |
| Kundennutzen | Vertrauen in Dokumente |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Abgabebox-Dienst (öffentliche Seite) |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Differenzierung, aber Vertrauensfunktion – in allen Abos |
| Implementierungsaufwand | – |
| Codefundstellen | `abgabebox-backend/app/routes/verify.py`, `routes/document_verification.py` |
| Migrationsbedarf | keiner |

### `documents.verified_org` – Verifizierte Organisation

Bestätigung der Organisation durch hocX auf der Prüfseite.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P2 |
| Enthaltene Funktionen | Antrag; Prüfung im Adminportal |
| Kundennutzen | Vertrauen |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Echtheitsprüfung |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Manuelle Prüfung kostet Betreiberzeit – bei Bedarf als Add-on bepreisen [A] |
| Implementierungsaufwand | – |
| Codefundstellen | `identity_verification_service.py` |
| Migrationsbedarf | keiner |

### `documents.verify_domain` – Eigene Prüf-Domain

Echtheitsprüfung unter eigener Domain (z. B. verify.verein.ch).

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P2 |
| Enthaltene Funktionen | Domain-Verifizierung; Routing |
| Kundennutzen | Professioneller Auftritt |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | Echtheitsprüfung, Traefik |
| Abo | Add-on |
| Entitlement-Code | `verify_domain` |
| Wirtschaftliche Begründung | Nischenwunsch, Betriebsaufwand pro Domain – als Add-on |
| Implementierungsaufwand | – |
| Codefundstellen | `verify_domain_service.py` |
| Migrationsbedarf | 0126 |

### `documents.signature` – Digitale Signatur

PAdES-Signatur je Mandant.

| Feld | Wert |
|---|---|
| Status / Priorität | PLANNED / P3 |
| Enthaltene Funktionen | Signatur beim Abschluss |
| Kundennutzen | Rechtsverbindlichkeit |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | Zertifikate, HSM/Schlüsselverwaltung |
| Abo | Add-on |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Hoher Aufwand und Betriebsrisiko, Nutzen nur für wenige Kunden – zurückstellen |
| Implementierungsaufwand | L |
| Codefundstellen | `docs-site/docs/technik/dokument-engine.md` |
| Migrationsbedarf | Schlüsselverwaltung |

## Modul: Finanzen (`finance`)

### `finance.ledger` – Kassenbuch

Konten und Buchungen mit laufendem Saldo.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Konten; Buchungen mit Protokollbezug; Saldo per Stichtag; Einfrieren mit dem Protokoll |
| Kundennutzen | Kasse ohne Excel |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | – |
| Abo | Pro |
| Entitlement-Code | `finance` |
| Wirtschaftliche Begründung | Klarer Modulnutzen, klassischer Upgrade-Grund; nach Downgrade nur lesend |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/finance.py`, `/finances` |
| Migrationsbedarf | 0084 |

### `finance.fines` – Bussen

Bussen aus Anwesenheit mit Tarif, Einziehen als Buchung.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Tarif je Mandant/Vorlage; Vorschläge aus Anwesenheit; Einziehen, Wiedereröffnen, Wiederherstellen |
| Kundennutzen | Bussen automatisch richtig |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Kassenbuch, Anwesenheit |
| Abo | Pro |
| Entitlement-Code | `finance` |
| Wirtschaftliche Begründung | Teil von Finanzen |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/fines.py`, `/fines` |
| Migrationsbedarf | 0084 |

### `finance.reports` – Finanzberichte

Kontostand, Buchungen, Bussen als PDF/CSV/XLSX.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Berichte über die Dokument-Engine; Finanzblöcke im Protokoll |
| Kundennutzen | Rechenschaft an GV |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Dokument-Engine |
| Abo | Pro |
| Entitlement-Code | `finance` |
| Wirtschaftliche Begründung | Teil von Finanzen |
| Implementierungsaufwand | – |
| Codefundstellen | `documents/providers/finance.py` |
| Migrationsbedarf | keiner |

### `finance.dues` – Mitgliederbeiträge

Beiträge je Person/Kategorie, Rechnung mit QR-Einzahlungsschein, Zahlungsabgleich manuell.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P1 |
| Enthaltene Funktionen | Beitragskategorien; Rechnungslauf; QR-Rechnung (Swiss QR Bill); Offene Beiträge |
| Kundennutzen | Grösster Kassier-Aufwand im Verein |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Kassenbuch, Teilnehmende, Dokument-Engine |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Feature-Beschreibung verspricht «Beiträge» bereits; schliesst diese Lücke; hoher Nutzen |
| Implementierungsaufwand | M–L |
| Codefundstellen | `0084_tenant_feature.py` (Beschreibung) |
| Migrationsbedarf | Neue Tabellen mit tenant_id + RLS |

### `finance.import` – Bankimport

Buchungen aus CSV/camt.054 importieren und zuordnen.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | Import mit Vorschau; Zuordnung zu Beiträgen |
| Kundennutzen | Weniger Abtippen |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Kassenbuch, Beiträge |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Sinnvoll nach Beiträgen |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | keiner |

### `finance.categories` – Kategorien und Budget

Kategorien je Buchung, Budget je Jahr.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P3 |
| Enthaltene Funktionen | Kategorien; Budgetvergleich |
| Kundennutzen | Bessere Übersicht |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Kassenbuch |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Nice-to-have; keine echte Buchhaltung anstreben |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | keiner |

## Modul: Medien und Dateien (`media`)

### `media.photos` – Fotos und Alben

Galerie mit sicherer Upload-Pipeline und automatischen Alben.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Upload inkl. ZIP, HEIC, Live Photos; Virenscan, Magic Bytes; EXIF, Aufnahmedatum, GPS entfernen; Automatische Alben je Zyklus/Abgabe; Tags, Bulk-Aktionen |
| Kundennutzen | Vereinsfotos an einem Ort |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Speicherkontingent |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Begrenzung über Speicher, nicht über Funktionen |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/files.py`, `upload_pipeline.py`, `/photos` |
| Migrationsbedarf | keiner |

### `media.photo_intelligence` – Fotos sortieren

Duplikate, ähnliche Serien, beste Fotos automatisch.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P2 |
| Enthaltene Funktionen | Perceptual Hash, Gruppen; Qualitätswerte; Beste je Album mit Override; Gesichtsqualität (experimentell) |
| Kundennutzen | Weniger Sortierarbeit |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Jobs, Foto-Worker |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Rechenkosten laufen im Zeitfenster; Gesichtsqualität experimentell (Job-Text «Gesichtserkennung» korrigieren) |
| Implementierungsaufwand | – |
| Codefundstellen | `photo_similarity.py`, `photo_quality.py`, `photo-analysis-worker/` |
| Migrationsbedarf | keiner |

### `media.files` – Dateien

Dateiverwaltung mit Versionen, Konvertierung und Texterkennung.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Upload; PDF-Konvertierung, OCR; Löschen mit Vorschau |
| Kundennutzen | Ablage für Vereinsdokumente |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | document-worker |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion; ungenutzten Endpunkt `/files/stats` entfernen |
| Implementierungsaufwand | – |
| Codefundstellen | `document_service.py`, `/files` |
| Migrationsbedarf | keiner |

### `media.sharing` – Teilen von Fotos

Öffentliche Freigabelinks und mit Partnervereinen geteilte Alben.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Links mit Ablauf und Metadatenfilter; Öffentliche Galerie mit ZIP; Partner-Alben (Einladung, Rechte, Freigabe) |
| Kundennutzen | Fotos sicher teilen |
| Zielgruppe | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen |
| Technische Abhängigkeiten | Fotos |
| Abo | Pro |
| Entitlement-Code | `photo_sharing` |
| Wirtschaftliche Begründung | Aufbauender Nutzen; Annehmen von Einladungen bleibt in jedem Abo (Netzwerkeffekt); nach Downgrade bleiben Links gültig |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/share_links.py`, `routes/files.py` (Album-Freigaben) |
| Migrationsbedarf | 0158 (Feature + Backfill) |

## Modul: Abgaben (`submissions`)

### `submissions.box` – Abgabebox

Dateien und Fotos von Mitgliedern ohne Login einsammeln.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Abgaben aus Terminen/Listen/manuell; Zeitfenster, Limits, Sortierung; Öffentliche Upload-Seite mit Captcha, Quarantäne, Virenscan; ZIP, Pendenzen automatisch schliessen; Automatische Alben |
| Kundennutzen | Kein Nachrennen nach Unterlagen |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Abgabebox-Dienst, Speicher |
| Abo | Basic |
| Entitlement-Code | `abgabebox` |
| Wirtschaftliche Begründung | Heute in allen Plänen; Differenzierung gegenüber Wettbewerb – bleibt in Basic, Kosten über Speicher; nach Downgrade nur lesend |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/submission_assignments.py`, `abgabebox-backend/` |
| Migrationsbedarf | 0085 |

### `submissions.notifications` – Eingangsbenachrichtigung

Verantwortliche erhalten eine Nachricht bei neuer Abgabe.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | E-Mail je Abgabe oder als Tageszusammenfassung |
| Kundennutzen | Schnelle Reaktion |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | `platform.email` |
| Abo | Pro |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Kleiner Aufwand nach E-Mail-Infrastruktur |
| Implementierungsaufwand | S |
| Codefundstellen | – (neu) |
| Migrationsbedarf | keiner |

## Modul: Verwaltung und Datenschutz (`administration`)

### `admin.tenant_settings` – Vereinsprofil und Einstellungen

Name, Bild, Tags, Dokumenteinstellungen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Profil; Tag-Farben; Dokumenteinstellungen |
| Kundennutzen | Grundkonfiguration |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Grundfunktion |
| Implementierungsaufwand | – |
| Codefundstellen | `/tenant-settings` |
| Migrationsbedarf | keiner |

### `admin.custom_domain` – Eigene Domain

App und Abgabebox unter eigener Domain.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P2 |
| Enthaltene Funktionen | Domain-Verifizierung (DNS-TXT); Domain-Bridge für die Anmeldung; Health-Check |
| Kundennutzen | Professioneller Auftritt |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | Traefik |
| Abo | Business |
| Entitlement-Code | `custom_domain` |
| Wirtschaftliche Begründung | Betriebsaufwand je Domain; nach Downgrade wird die Domain nicht mehr bedient |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/tenants.py`, `traefik_config_service.py` |
| Migrationsbedarf | 0085/0086 |

### `admin.privacy` – Datenschutzeinstellungen

Sichtbarkeit von Personenstatistiken, Link zum Datenschutzhinweis.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Einstellungen |
| Kundennutzen | Datenschutz |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | – |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Rechtliche Grundlage – nie abostufen |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/privacy_settings.py` |
| Migrationsbedarf | keiner |

### `admin.retention` – Aufbewahrung und Löschvorschläge

Fristen für Einreichungen, ehemalige Mitglieder, alte Galeriebilder.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Richtlinie; Vorschläge bestätigen/verwerfen; Automatikmodus |
| Kundennutzen | DSG-konforme Datenhaltung |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Job `retention_proposals` |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Rechtliche Grundlage |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/retention.py` |
| Migrationsbedarf | keiner |

### `admin.activity` – Aktivitätsprotokoll

Änderungen, Löschungen, Exporte, Logins und Plattform-Zugriffe.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P1 |
| Enthaltene Funktionen | Filter |
| Kundennutzen | Nachvollziehbarkeit |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Audit-Log |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Basis für alle; Export/Langzeitaufbewahrung als Business-Erweiterung denkbar |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/activity.py` |
| Migrationsbedarf | keiner |

### `admin.data_export` – Vereinsexport

Alle Daten als verschlüsseltes ZIP (XLSX, PDFs, Fotos).

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Export mit Passwort; Löschung nach 7 Tagen |
| Kundennutzen | Keine Abhängigkeit vom Anbieter |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Job `tenant_data_export` |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Vertrauens- und Rechtsfrage – nie abostufen |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/tenant_data_export.py` |
| Migrationsbedarf | keiner |

### `admin.subscription` – Abo und Nutzung

Abo, Speicher, Benutzer und Forderungen ansehen.

| Feld | Wert |
|---|---|
| Status / Priorität | PARTIAL / P1 |
| Enthaltene Funktionen | Plan, Module, Speicher; Forderungen; Upgrade-Anfrage (vorgeschlagen) |
| Kundennutzen | Transparenz |
| Zielgruppe | Vereine und KMU jeder Grösse |
| Technische Abhängigkeiten | Plattform-Billing |
| Abo | Basic |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Heute nur lesend ohne Upgrade-Weg; Upgrade-Anfrage ist Quick Win für Upselling |
| Implementierungsaufwand | S |
| Codefundstellen | `/tenant-settings/abo`, `tenant-subscription-view.tsx` |
| Migrationsbedarf | keiner |

### `admin.api` – API und Webhooks

API-Schlüssel je Mandant und Webhooks bei Ereignissen.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P3 |
| Enthaltene Funktionen | Lesende API; Webhooks für Protokoll abgeschlossen, Abgabe eingegangen |
| Kundennutzen | Integration in bestehende Systeme |
| Zielgruppe | grosse Vereine, Verbände, KMU mit mehreren Gremien |
| Technische Abhängigkeiten | Tokenverwaltung, Rate-Limits |
| Abo | Add-on |
| Entitlement-Code | – (immer enthalten) |
| Wirtschaftliche Begründung | Nur bei Nachfrage; Sicherheits- und Wartungsaufwand hoch |
| Implementierungsaufwand | L |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Token-Tabelle |

## Modul: Plattform (intern) (`platform`)

### `platform.tenants` – Mandantenverwaltung

Mandanten anlegen, klonen, exportieren/importieren, bereinigen.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | CRUD; Export/Import/Klon verschlüsselt; Bereinigung |
| Kundennutzen | – |
| Zielgruppe | Betreiber |
| Technische Abhängigkeiten | – |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Betrieb |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/admin.py`, `admin_tenant_service.py` |
| Migrationsbedarf | keiner |

### `platform.catalog` – Pläne, Features, Preise

Pläne mit Features und Limits, Speicherpakete, Katalog-Import/-Export.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Pläne; Features mit Nur-Lesen-Zustand; Speicherpakete; Katalogdatei |
| Kundennutzen | – |
| Zielgruppe | Betreiber |
| Technische Abhängigkeiten | `permissions/features.json` |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Grundlage der Abos |
| Implementierungsaufwand | – |
| Codefundstellen | `routes/admin.py`, `catalog_config_service.py`, `admin-tenant-settings-modal.tsx` |
| Migrationsbedarf | 0158 |

### `platform.billing` – Forderungen und Cashflow

Forderungen je Periode, Kosten, Cashflow-Übersicht.

| Feld | Wert |
|---|---|
| Status / Priorität | PARTIAL / P1 |
| Enthaltene Funktionen | Forderungen; Kosten; Status manuell |
| Kundennutzen | – |
| Zielgruppe | Betreiber |
| Technische Abhängigkeiten | Katalog |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Keine Rechnungs-PDFs, keine Zahlungsanbindung, Forderungen entstehen beim Öffnen statt per Job |
| Implementierungsaufwand | M |
| Codefundstellen | `cashflow_service.py`, `/admin/cashflow` |
| Migrationsbedarf | keiner |

### `platform.operations` – Betrieb

Monitoring (23 Prüfungen, ntfy), Jobs, Fehlerprotokoll, Audit, Backups, Storage, Wartung, Überlast-Priorität.

| Feld | Wert |
|---|---|
| Status / Priorität | EXISTING / P0 |
| Enthaltene Funktionen | Siehe Bestandsaufnahme |
| Kundennutzen | – |
| Zielgruppe | Betreiber |
| Technische Abhängigkeiten | – |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Betrieb |
| Implementierungsaufwand | – |
| Codefundstellen | `system_health_service.py`, `job_registry.py`, `admin_backups.py`, `db_admission.py` |
| Migrationsbedarf | keiner |

### `platform.website` – Website mit Preisen

Landingpage mit Preisen live aus dem Katalog.

| Feld | Wert |
|---|---|
| Status / Priorität | PARTIAL / P1 |
| Enthaltene Funktionen | Preise; Kundenliste |
| Kundennutzen | – |
| Zielgruppe | Interessenten |
| Technische Abhängigkeiten | Katalog |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | CTA «30 Tage testen» ohne Testphase – Aussage anpassen (Quick Win) oder Testphase bauen |
| Implementierungsaufwand | S |
| Codefundstellen | `frontend/app/website/page.tsx` |
| Migrationsbedarf | keiner |

### `platform.email` – E-Mail-Versand

SMTP/Provider-Anbindung mit Vorlagen, Versandprotokoll, Abmeldung.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P0 |
| Enthaltene Funktionen | Versanddienst; Mehrsprachige Vorlagen; Bounce-Handling |
| Kundennutzen | Voraussetzung für Versand, Erinnerungen, Passwort-Reset |
| Zielgruppe | – |
| Technische Abhängigkeiten | Secret-Verdrahtung (SECURITY-RULES §5.2) |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Infrastruktur für sechs vorgeschlagene Features; ohne sie bleibt der Workflow lückenhaft |
| Implementierungsaufwand | M |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Secrets, Versandtabelle |

### `platform.self_signup` – Registrierung und Testphase

Selbstregistrierung mit 30-Tage-Test.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P1 |
| Enthaltene Funktionen | Registrierung; Testphase mit Ablauf; Umwandlung in Abo |
| Kundennutzen | Weniger Vertriebsaufwand |
| Zielgruppe | Interessenten |
| Technische Abhängigkeiten | `platform.email`, Mandantenanlage |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Website verspricht es; senkt Akquisekosten [A] |
| Implementierungsaufwand | M–L |
| Codefundstellen | – (neu) |
| Migrationsbedarf | Trial-Felder am Mandanten |

### `platform.payments` – Online-Zahlung

Rechnungen mit QR-Bill und Zahlungsabgleich für Abos.

| Feld | Wert |
|---|---|
| Status / Priorität | PROPOSED / P2 |
| Enthaltene Funktionen | Rechnungs-PDF; QR-Bill; Abgleich |
| Kundennutzen | Weniger manuelle Abrechnung |
| Zielgruppe | Betreiber |
| Technische Abhängigkeiten | Forderungen |
| Abo | intern |
| Entitlement-Code | – (intern) |
| Wirtschaftliche Begründung | Lohnt ab grösserer Kundenzahl [A] |
| Implementierungsaufwand | M |
| Codefundstellen | `cashflow_service.py` |
| Migrationsbedarf | keiner |

## Vollständigkeit

Jede Zeile der Bestandsaufnahme in `docs/PRODUCT_MODULE_ARCHITECTURE.md` (Abschnitt 2) ist einem Key
zugeordnet. Kleine Funktionen sind Teil eines grösseren Features (z. B. Scroll-Position in
`meetings.protocols`, GPS entfernen in `media.photos`). Legacy ohne Kundennutzen ist kein Feature,
sondern als Aufräumarbeit in der Roadmap (Phase 2): `GroupEntity`, `Leader`, `UserProtocolAccess`,
Blocktypen `display`/`static_text`/`bullet_list`, `EventCategory`, `GET /files/stats`, verwaiste «bald»-Texte.
