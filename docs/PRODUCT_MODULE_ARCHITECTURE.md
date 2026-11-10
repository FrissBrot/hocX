# hocX – Produkt- und Modularchitektur

Stand: 2026-10-27. Grundlage: vollständige Bestandsaufnahme des Repositorys (Backend-Routen, Services,
Modelle, Migrationen, Frontend-Seiten und Navigation, Jobs, Tests, Doku). Zusammengehörige Dokumente:

| Dokument | Inhalt |
|---|---|
| `docs/COMPLETE_FEATURE_CATALOG.md` | Zentraler Katalog aller bestehenden und vorgeschlagenen Features |
| `docs/FEATURE_EXPANSION_ROADMAP.md` | Neue Features mit Problem, Lösung, Aufwand, Bewertung |
| `docs/SAAS_SUBSCRIPTION_STRATEGY.md` | Abostufen, Feature-Matrix, Gap-Analyse, Upselling |
| `docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md` | Technische Feature-/Abo-Architektur (umgesetzt) |
| `docs/PRODUCT_IMPLEMENTATION_ROADMAP.md` | Phasenplan |

Kennzeichnung: **[F]** Fakt mit Fundstelle, **[A]** Annahme oder Bewertung.

---

## 1. Ausgangslage in Zahlen [F]

| Kennzahl | Wert | Quelle |
|---|---|---|
| Seiten Hauptapp / Plattform-Admin / Abgabebox | 49 / 22 / 5 | `frontend/app`, `abgabebox-frontend/app` |
| Backend-Router / Endpunkte | 46 / 492 (davon 132 Plattform-Admin) | `backend/app/main.py`, `permissions/route-map.json` |
| Tabellen (ORM) | 121 | `backend/app/models` |
| Berechtigungen (RBAC) | 15 in 8 Bereichen, 4 Standardrollen | `permissions/catalog.json` |
| Buchbare Features vor dieser Änderung | 4 (`finance`, `abgabebox`, `custom_domain`, `verify_domain`) | Migrationen 0084, 0085, 0126 |
| Buchbare Features nach dieser Änderung | 8 (zusätzlich `task_packages`, `custom_roles`, `photo_sharing`, `document_designer`) | `permissions/features.json`, Migration 0158 |
| Pläne (Seeds) | `legacy`, `starter` (CHF 99), `standard` (CHF 199), `premium` (CHF 349) | `0085_plan_pricing.py`; Produktivwerte im Adminportal änderbar |
| Hintergrundjobs | 30+ | `backend/app/core/job_registry.py` |
| Tests | ~2300 Backend, ~640 Frontend (Vitest), 24 E2E-Specs | `backend/tests`, `frontend/**/*.test.*`, `frontend/e2e` |

Zielgruppe laut Website und Doku: Vereine und KMU in der Schweiz (Vorstand, Geschäftsleitung),
Preise in CHF, mehrsprachig (de/en/fr/it) [F: `frontend/messages/de/website.json`, `README.md`].

## 2. Vollständige Bestandsaufnahme

Die Bestandsaufnahme ist nach den neuen Modulen gegliedert (Abschnitt 4). Statuswerte:
**vollständig**, **teilweise**, **experimentell**, **vorhanden, nicht zugänglich**, **nur geplant**.
Jede Zeile ist im Feature-Katalog (`docs/COMPLETE_FEATURE_CATALOG.md`) einem Feature-Key zugeordnet.

### 2.1 Sitzungen und Protokolle

| Funktion | Status | Fundstellen |
|---|---|---|
| Protokoll-Workflow geplant → vorbereitet → durchgeführt → abgeschlossen, Vorwärtssprünge, Rückstufung um einen Schritt, Transition-Hooks | vollständig | `services/protocol_service.py` (`_STATUS_ORDER`, `_run_status_transition_hooks`), `routes/protocols.py` |
| Protokoll aus Vorlage, Vorschau Nummer/Titel, zuletzt genutzte Vorlage, Löschen mit Vorschau, Scroll-Position | vollständig | `routes/protocols.py` |
| Nummerierung (Muster, Zyklus-Rang, Neunummerierung bei Datumswechsel) | vollständig | `Template.protocol_number_pattern`, `_renumber_for_date_change` |
| Editor mit Autosave, Konfliktschutz, Sprungsuche | vollständig | `components/protocol/protocol-editor.tsx`, `focused-element-editor.tsx`, `autosave_service.py` |
| Live-Zusammenarbeit (Feldsperren, Anwesenheit, Live-Updates, Listenänderungen) | vollständig | `routes/collaboration_ws.py`, `collaboration_service.py` |
| Änderungsverfolgung | teilweise (nur im Status geplant, Default-Inkonsistenz) | `routes/protocol_elements.py:275`, `schemas/protocol.py:46/85` |
| Abschluss: Einfrieren von Todos, Listen, Verantwortlichen, Mitgliedschaft; automatisches Folgeprotokoll | vollständig | `_freeze_responsible_titles`, `list_snapshot_service.freeze_*`, `_maybe_auto_create_next_protocol` |
| 13 wählbare Blocktypen (Text, Pendenzen, Bild, Formular, Matrix, Termine, Anwesenheit, nächste Sitzung, Diagramm, Ein-/Austritte, Sitzungsnotizen, 3 Finanzblöcke) | vollständig | `element-types/registry.json` |
| Blocktypen `display`, `static_text`, `bullet_list` | vorhanden, nicht wählbar (Legacy) | Registry `pickable: false` |
| Sitzungsvorlagen (CRUD, Duplizieren, Archiv, Teilnehmende, Busstarif, Sync bestehender Protokolle) | vollständig | `routes/templates.py`, `template-builder.tsx` |
| Bausteinbibliothek | vollständig (nur Desktop) | `/elements`, `element-definition-manager.tsx` |
| Verantwortliche je Traktandum (Personen oder Tabellenzeile, live) | vollständig | `responsible_label_service.py` |
| Zyklen und Nummernmuster | vollständig | `routes/cycle_configs.py`, `/cycles` |
| Anliegen (Traktandenvorschläge, Verschieben, feste Bindung) | vollständig | `routes/agenda_items.py`, `/agenda` |
| Termine (mehrtägig, Uhrzeit, Tags, Absage, CSV-Import, Export) | vollständig | `routes/events.py`, `/events` |
| `EventCategory` | vorhanden, kaum zugänglich | 5 Backend-Dateien, 1 Frontend-Treffer |
| Pendenzen (Mehrfachzuständige, Fälligkeit inkl. «nächste Sitzung», Dateien, Tags, «Meine») | vollständig; Status `cancelled` nicht setzbar | `routes/todos.py`, `/todos` |
| Anwesenheit, Abmelden aus dem Dashboard | vollständig | `routes/protocols.py` (`/excuse`), Dashboard |
| Strukturierte Listen und Jahresstände (Tabellen-Snapshots je Zyklus) | vollständig | `routes/lists.py`, `routes/table_snapshots.py`, Job `cycle_snapshot` |
| Aufgabenpakete (wiederkehrende Aufgaben je Zyklus) | vollständig (nur Desktop) | `routes/task_packages.py`, Job `task_package_rollover` |
| Word-/PDF-Import (Analyse, Warteschlange, Assistent, Lernmodell) | vollständig; zwei parallele Oberflächen | `routes/word_import.py`, `/tools/import`, `/tools/word-import` |
| Dashboard und Statistik | vollständig | `/`, `/statistics`, `routes/statistics.py` |
| Kalender-Abos (ICS für Termine und Pendenzen) | vollständig | `routes/calendar_feeds.py`, `/connections` |
| Einladung und Traktandenliste als PDF | vollständig (Versand fehlt) | Dokumenttypen `invitation`, `agenda` |
| Mitglieder-Benachrichtigungen (E-Mail, In-App) | nicht vorhanden | – |
| Globale Suche | nicht vorhanden | – |

### 2.2 Mitglieder und Zugänge

| Funktion | Status | Fundstellen |
|---|---|---|
| Teilnehmende mit und ohne Login (vereinheitlicht), Mitgliedschaft (Ein-/Austritt), CSV-Import | vollständig | `routes/participants.py`, `/participants` |
| Konten, MFA (TOTP, Passkeys), Sprache, Sitzungsentzug | vollständig | `routes/users.py`, `mfa_service.py` |
| RBAC: Standardrollen, eigene Rollen, Mehrfachrollen, Schutzregeln | vollständig | `role_service.py`, `/users/roles` |
| Datenauskunft (DSG/DSGVO) | vollständig | `services/data_export/personal.py` |
| Benutzerlimit des Abos | jetzt durchgesetzt (vorher nur Anzeige) | `services/user_limit_service.py` |
| `UserTemplateAccess`, `UserProtocolAccess`, `GroupEntity`, `Leader` | vorhanden, nicht zugänglich | nur Modelle und Mandanten-Transfer |
| Passwort-Reset per E-Mail, Login-Einladung, Mandanten-SSO | nicht vorhanden | – |

### 2.3 Dokumente und Erscheinungsbild

| Funktion | Status | Fundstellen |
|---|---|---|
| Dokument-Engine (Typst, PDF/A-2b, 16 Dokumenttypen, CSV/XLSX/ICS/Markdown) | vollständig | `backend/app/documents/`, `doc_types.py` |
| Systemvorlagen, Plattform-Standard, Zuweisung je Dokumenttyp | vollständig | `system_templates.py`, `/document-template-assignments` |
| Brand Studio (Farben, Schriften, Logo, Kopf/Fuss, Darstellungsvarianten) | vollständig | `/documents/brand`, `brand.py`, `appearance.py` |
| Designer für eigene Vorlagen und Bausteine, Revisionen, Vergleich | vollständig | `/documents/templates/[id]`, `routes/document_studio.py` |
| Gestaltungsbeispiele (sechs Protokoll-Designs) inkl. aller Mockup-Darstellungen | vollständig | `documents/examples.py` |
| Exportverlauf / Dokumentenregister, versionierte Protokollexporte | vollständig | `/documents/exports`, `protocol_export_document_service.py` |
| Echtheitsprüfung (Hash, QR, öffentliche Prüfseite), verifizierte Organisation, eigene Prüf-Domain | vollständig | `abgabebox-backend/app/routes/verify.py`, `identity_verification_service.py`, `verify_domain_service.py` |
| Digitale Signatur (PAdES) | nur geplant | `docs-site/docs/technik/dokument-engine.md` |

### 2.4 Finanzen

| Funktion | Status | Fundstellen |
|---|---|---|
| Konten, Buchungen, laufender Saldo, Saldo per Stichtag, Einfrieren mit Protokoll | vollständig | `routes/finance.py`, `finance_repository.py` |
| Bussen (Tarif, Vorschläge aus Anwesenheit, Einziehen mit Buchung, Wiederherstellen) | vollständig | `routes/fines.py` |
| Finanzberichte über die Dokument-Engine | vollständig | Dokumenttypen `finance`, `transactions`, `fines` |
| Mitgliederbeiträge (in der Feature-Beschreibung versprochen) | nicht vorhanden | `0084_tenant_feature.py` |
| Bank-/CSV-Import, Kategorien, Periodenabschluss | nicht vorhanden | – |

### 2.5 Medien und Dateien

| Funktion | Status | Fundstellen |
|---|---|---|
| Upload-Pipeline (Magic Bytes, ClamAV, HEIC, Live Photos, EXIF, GPS entfernen, Kontingent) | vollständig | `upload_pipeline.py`, `apple_media.py` |
| Galerie mit ZIP-Upload, automatische Alben, Termin-Zuordnung | vollständig | `routes/files.py`, `photo_album_service.py` |
| Ähnlichkeit/Duplikate, «beste Fotos», Qualitätswerte | vollständig | `photo_similarity.py`, `photo_quality.py` |
| Gesichtsqualitäts-Analyse | experimentell (nur Detektion, Zeitfenster) | `photo-analysis-worker/` |
| Dateien mit Konvertierung und Texterkennung | vollständig | `document_service.py`, `document-worker` |
| Öffentliche Freigabelinks, mit Partnervereinen geteilte Alben | vollständig | `routes/share_links.py`, `photo_album_share_service.py` |
| `GET /files/stats` | vorhanden, nicht zugänglich | `routes/files.py:210` |

### 2.6 Abgaben (Abgabebox)

| Funktion | Status | Fundstellen |
|---|---|---|
| Abgaben aus Terminen/Listen, Zeitfenster, Links, Upload ohne Login, Captcha, Quarantäne, Virenscan, ZIP, Pendenzen schliessen | vollständig | `routes/submission_assignments.py`, `abgabebox-backend/`, `abgabebox-frontend/` |
| Benachrichtigung bei neuer Abgabe | nicht vorhanden | – |

### 2.7 Verwaltung und Datenschutz

| Funktion | Status | Fundstellen |
|---|---|---|
| Mandantenprofil, Tags, Dokumenteinstellungen | vollständig | `/tenant-settings` |
| Eigene Domain inkl. Domain-Bridge | vollständig | `routes/tenants.py`, `domain_bridge_service.py` |
| Datenschutzeinstellungen, Aufbewahrungsfristen mit Vorschlägen, Aktivitätsprotokoll | vollständig | `routes/privacy_settings.py`, `routes/retention.py`, `routes/activity.py` |
| Vereinsexport (verschlüsselt) | vollständig | `routes/tenant_data_export.py` |
| Abo- und Speicheransicht | vollständig (nur lesend, kein Upgrade-Weg) | `/tenant-settings/abo` |

### 2.8 Plattformbetrieb (intern, nicht verkauft)

Mandanten, Pläne und Preise, Speicherpakete, Cashflow/Forderungen, Systemmonitoring (23 Prüfungen,
ntfy), Jobs, Fehlerprotokoll, Audit, Backups (Borg), Storage-Profile und Migrationen, Wartungsfenster,
Überlast-Priorisierung, SSO für Plattform-Admins, Systemvorlagen, Verifizierungen, Website mit
Preisen, Katalog-Import/-Export [F: `backend/app/api/routes/admin*.py`, `frontend/app/admin`].
Lücken: kein E-Mail-Versand, keine Zahlungsanbindung, keine Selbstregistrierung oder Testphase
(Website-CTA «30 Tage testen» führt nur zu Preisen bzw. `mailto:`), Offboarding nur als Hinweis.

## 3. Bewertung der bisherigen Modulstruktur

Bisher gab es kein ausdrückliches Modulmodell. Faktisch bestimmten drei Achsen die Struktur:
Navigationsgruppen (`app-shell-nav.ts`: Arbeit, Stammdaten, Konfiguration, Administration), die
RBAC-Bereiche (`meetings`, `templates`, `participants`, `finances`, `reports`, `files`,
`submissions`, `administration`) und vier buchbare Features. Bewertung je bisherigem Bereich:

| Bisheriger Bereich | Fachl. Zusammenhang | Kundenverständnis | Eigener Nutzen | Wirtschaftl. Wert | Entscheidung |
|---|---|---|---|---|---|
| Protokolle, Pendenzen, Anliegen, Termine (Nav «Arbeit») | hoch | hoch | Kern | Kern aller Abos | **beibehalten** als Modul «Sitzungen und Protokolle» |
| Vorlagen-Bereich (Sitzungsvorlagen, Bausteine, Aufgabenpakete, Zyklen, Dokumentvorlagen) | gemischt: Sitzungskonfiguration und Dokumentgestaltung | mittel | hoch | Designer und Aufgabenpakete upsell-fähig | **aufteilen**: Sitzungskonfiguration zu «Sitzungen», Dokumentvorlagen zu «Dokumente»; Navigation bleibt als Tab-Gruppe «Vorlagen» |
| Stammdaten (Teilnehmende, Listen) | Teilnehmende = Personen, Listen = Sitzungsdaten | mittel | hoch | Kern | **aufteilen**: Teilnehmende zu «Mitglieder», Listen zu «Sitzungen» |
| Dateien/Fotos/Freigaben | hoch | hoch | hoch | Teilen upsell-fähig | **beibehalten** als «Medien und Dateien» |
| Finanzen inkl. Bussen | hoch | hoch | hoch | klares Upgrade-Modul | **beibehalten**, Bussen bleiben Teil |
| Abgabebox | hoch | hoch | eigenständig | Differenzierung | **beibehalten** als «Abgaben» |
| Import (Nav-Eintrag) | gehört zu Protokollen | gering (eigener Menüpunkt für Einmalaufgabe) | Onboarding | Verkaufsargument, kein Upsell | **als Feature integrieren** in «Sitzungen»; Menüpunkt in die Protokollliste verlegen (Roadmap) |
| Statistik (Tab im Dashboard) | Auswertung über Sitzungen, Finanzen, Pendenzen | hoch | mittel | Kern | **Feature** in «Sitzungen» (Auswertungen), Finanzteil nur mit Finanzen |
| Konten, Rollen | Zugangsverwaltung | hoch | Kern | eigene Rollen upsell-fähig | **zusammenlegen** mit Teilnehmenden zu «Mitglieder und Zugänge» |
| Mandanteneinstellungen, Domains, Datenschutz, Aufbewahrung, Aktivität | Verwaltung | mittel | Pflicht | eigene Domain upsell-fähig | **beibehalten** als «Verwaltung und Datenschutz» |
| Dokument-Engine, Brand Studio, Echtheitsprüfung | hoch | hoch | hoch | Designer, Prüf-Domain upsell-fähig | **eigenes Modul** «Dokumente und Erscheinungsbild» |
| Plattform-Admin, Monitoring, Backups, Storage | technisch | – (intern) | – | – | **technische Querschnittsfunktion**, kein Kundenmodul |
| Legacy: `GroupEntity`, `Leader`, `UserTemplateAccess`, `UserProtocolAccess`, Blocktypen `display`/`static_text`/`bullet_list`, `/files/stats`, verwaiste «bald»-Texte | – | – | keiner | keiner | **perspektivisch entfernen** (`UserTemplateAccess` ggf. für Gremien wiederverwenden, Roadmap) |

## 4. Neue Modulstruktur

Sieben kundenseitige Module plus die interne Plattform. Die Module sind Produktbereiche für
Navigation, Vertrieb und Doku, keine technische Grenze: ein Modul ist nicht automatisch buchbar.
Buchbar sind nur einzelne Features (Abschnitt 5 und `permissions/features.json`).

| Key | Modul | Zweck für den Kunden | Buchbare Features darin |
|---|---|---|---|
| `meetings` | **Sitzungen und Protokolle** | Sitzungen vorbereiten, durchführen, dokumentieren; Pendenzen, Anliegen, Termine, Listen, Auswertungen | `task_packages` |
| `people` | **Mitglieder und Zugänge** | Teilnehmende, Mitgliedschaft, Konten mit Login, Rollen, Datenauskunft | `custom_roles` |
| `documents` | **Dokumente und Erscheinungsbild** | PDF und Exporte im eigenen Erscheinungsbild, Vorlagen, Echtheitsprüfung | `document_designer`, `verify_domain` |
| `finance` | **Finanzen** | Kassenbuch, Bussen, Finanzberichte | `finance` |
| `media` | **Medien und Dateien** | Fotos, Alben, Dateien, Teilen | `photo_sharing` |
| `submissions` | **Abgaben** | Dokumente und Fotos von Mitgliedern ohne Login einsammeln | `abgabebox` |
| `administration` | **Verwaltung und Datenschutz** | Vereinsprofil, Domain, Datenschutz, Aufbewahrung, Aktivität, Export, Abo | `custom_domain` |
| – | Plattform (intern) | Betrieb, Abrechnung, Monitoring | – |

### 4.1 Zuordnung sämtlicher bestehender Funktionen

| Modul | Features (Keys aus dem Katalog) | Bisherige Bereiche |
|---|---|---|
| Sitzungen und Protokolle | `meetings.protocols`, `meetings.collaboration`, `meetings.track_changes`, `meetings.closing`, `meetings.session_templates`, `meetings.building_blocks`, `meetings.cycles`, `meetings.agenda_items`, `meetings.todos`, `meetings.events`, `meetings.attendance`, `meetings.lists`, `meetings.statistics`, `meetings.calendar_feeds`, `meetings.word_import`, `meetings.task_packages` | Nav Arbeit, Listen, Import, Vorlagen (Sitzung), Statistik, Verknüpfungen |
| Mitglieder und Zugänge | `people.participants`, `people.accounts`, `people.standard_roles`, `people.custom_roles`, `people.personal_data`, `people.user_limit` | Stammdaten Teilnehmende, Konten, Rollen |
| Dokumente und Erscheinungsbild | `documents.exports`, `documents.system_templates`, `documents.brand`, `documents.design_examples`, `documents.designer`, `documents.verification`, `documents.verified_org`, `documents.verify_domain` | Vorlagen (Dokument), Brand, Exporte, Echtheit |
| Finanzen | `finance.ledger`, `finance.fines`, `finance.reports` | Finanzen, Bussen |
| Medien und Dateien | `media.photos`, `media.photo_intelligence`, `media.files`, `media.sharing` | Fotos, Dateien, Freigabelinks |
| Abgaben | `submissions.box` | Abgabebox |
| Verwaltung und Datenschutz | `admin.tenant_settings`, `admin.custom_domain`, `admin.privacy`, `admin.retention`, `admin.activity`, `admin.data_export`, `admin.subscription` | Mandanteneinstellungen |
| Plattform (intern) | `platform.*` (siehe Katalog) | Plattform-Admin |

### 4.2 Zusammengelegte, aufgelöste und verschobene Bereiche

- **Import** ist kein eigener Bereich mehr, sondern das Feature `meetings.word_import`. Die zwei
  Oberflächen (Warteschlange, Assistent) werden zusammengeführt (Roadmap P2).
- **Vorlagen** wird fachlich geteilt (Sitzungskonfiguration ↔ Dokumentgestaltung), bleibt aber
  als gemeinsame Tab-Gruppe in der Navigation, weil Kunden beides als «Vorlagen» verstehen.
- **Stammdaten** löst sich auf: Teilnehmende zu «Mitglieder», Listen zu «Sitzungen».
- **Konten und Rollen** gehören mit den Teilnehmenden zusammen (eine Person, ein Datensatz seit 0108).
- **Statistik** ist ein Feature von «Sitzungen» und zeigt Modulteile (Finanzen) nur bei Buchung.
- **Legacy** (siehe Abschnitt 3, letzte Zeile) wird in Phase 2 der Roadmap entfernt.

## 5. Neue fachliche Modulgrenzen

- Ein **Modul** ist ein Produktbereich. Er hat Features, die immer enthalten sind, und kann
  buchbare Features enthalten.
- Ein **buchbares Feature** (Entitlement) existiert nur, wenn es einen echten wirtschaftlichen oder
  technischen Grund gibt: Kosten (Speicher, Rechenzeit), klarer Mehrwert für grössere Kunden oder
  Verwaltungsaufwand. Heute: acht Features (`permissions/features.json`).
- Keine Feature-Flags für Buttons oder Einstellungen. Grundfunktionen (Protokolle, Pendenzen,
  Termine, Standardrollen, Datenschutz, Echtheitsprüfung, Export) sind in jedem Abo enthalten.
- **Berechtigungen** (RBAC) bleiben unabhängig von Modulen. Eine Berechtigung kann an ein Feature
  gebunden sein (`finances.*` → `finance`, `submissions.*` → `abgabebox`).

## 6. Empfehlungen für die Navigation

| Gruppe | Einträge (Reihenfolge) | Änderung gegenüber heute |
|---|---|---|
| (oben) | Übersicht (Dashboard, Statistik als Tab) | – |
| Sitzungen | Protokolle (mit «Import» als Aktion), Pendenzen, Anliegen, Termine, Listen | Import wandert aus der Administration in die Protokollliste; Listen von «Stammdaten» hierher |
| Mitglieder | Teilnehmende, Konten und Rollen | Konten/Rollen aus «Administration» hierher (Gate `access.manage` bleibt) |
| Medien | Fotos, Dateien, Freigabelinks | – |
| Module | Finanzen, Abgaben | nur sichtbar, wenn gebucht oder nur lesend |
| Vorlagen | Sitzungsvorlagen, Bausteine, Aufgabenpakete, Zyklen, Dokumentvorlagen, Erscheinungsbild | Aufgabenpakete zeigen ohne Buchung einen Hinweis statt zu verschwinden (Upgrade-Anreiz) |
| Verwaltung | Einstellungen, Abo und Nutzung | Abo-Seite bekommt Upgrade-Anfrage (Roadmap) |

Umgesetzt in diesem Change: Hinweis «nicht im Abo» bzw. «nur noch lesend» auf Aufgabenpaketen,
Rollen und Freigabelinks (`components/ui/feature-notice.tsx`), Seiten von Finanzen, Bussen und Abgaben
bleiben im Nur-Lesen-Zustand erreichbar. Die Umgruppierung der Navigation ist Phase 2 der Roadmap.
