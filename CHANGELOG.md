# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [SemVer](https://semver.org/lang/de/). Die Beta-Historie
(`v0.1.0-beta.1` bis `v0.1.1.1-beta.9.9`) wird hier nicht rekonstruiert; 1.0.0
ist der erste offiziell unterstützte Stand und muss keine älteren
Installationen aktualisieren können.

## [Unveröffentlicht]

### Geändert

- **Gestaltungen: wer sie verwendet, was beim Anpassen passiert.** Im Vorlagen-Editor (PDF,
  Einladung) zeigt eine Zuweisungs-Leiste die verwendete Gestaltung, die anderen Vorlagen, die
  sie auch verwenden, und drei Wege: «Andere wählen» (sofort gespeichert, inkl. Standard des
  Vereins), «Bearbeiten» (wirkt auf alle Vorlagen, die sie verwenden) und «Nur hier anpassen»
  (Kopie; der Hinweis sagt, dass Änderungen an der Ausgangsgestaltung hier nicht mehr gelten).
  «Eigene/Gemeinsame Gestaltung» entfällt, die Tabs zeigen den Namen der Gestaltung.
- Designer: Hinweis, auf wie viele Vorlagen eine Änderung wirkt, mit «Nur für … ändern». Der
  Hinweis lässt sich wegklicken und erscheint wieder, wenn sich die Verwendung ändert.
- Bibliothek der Protokollgestaltung: jede Gestaltung zeigt «Verwendet in» und bei Kopien
  «Kopie von …»; Kopien einzelner Vorlagen erscheinen jetzt ebenfalls.
- Dokument-Designer mit zwei Modi wie im Entwurf v2: «Einfach» und «Erweitert». Der bisherige
  Modus «Experte» ist in «Erweitert» aufgegangen, damit u. a. die Position frei platzierter
  Elemente (z. B. Adresse in einer freien Ebene) wieder bearbeitbar ist; für solche Elemente
  entfallen die wirkungslosen Felder «Abstand oben/unten».
- Abhängigkeiten aktualisiert (Dependabot und npm/PyPI): Node 24 LTS in den Frontend-Images und
  der CI (statt 22; das vorgeschlagene Node 26 ist noch kein LTS), Next.js 16.4.3, React 19.3.1,
  TypeScript 6.0, Vitest 5, Recharts 3, Playwright 1.64.1; FastAPI 0.162, SQLAlchemy 2.1,
  Alembic 1.20, psycopg 3.3, Pydantic 2.14, Uvicorn 0.54, redis-py 8, pytest 9; Traefik 3.7.15,
  Garage 2.4.1, aktuelle Digests für ClamAV, PostgreSQL 16, Python und nginx; GitHub Actions auf
  die aktuellen Hauptversionen (Node-24-Laufzeit). PostgreSQL bleibt bewusst bei 16: der
  Sprung auf 18 braucht ein Upgrade der Datenbank (`pg_upgrade` bzw. Dump/Restore) und ein
  anderes Volume-Layout und wird separat geplant.
- PDF: grösserer Abstand zwischen den Traktanden. «Abstand vor Abschnitten» (Corporate Design →
  Seitenaufbau) hat neu 8 statt 6 mm als Standard (Vorlage «Kompakt»: 5 statt 4 mm). Profile mit
  dem bisherigen Standardwert bekommen per Migration `0159_brand_section_gap` eine neue Revision
  mit dem neuen Wert; eigene Werte bleiben, die vorherige Revision lässt sich wiederherstellen.

## [1.2.0] - 2026-10-23

Feature-Release auf 1.1.13. Fünf Entwicklungszweige sind zusammengeführt und aufeinander
abgestimmt: die neue **Dokument-Engine mit Document Studio** (Typst statt TeX, Corporate Design,
Vorlagen, Echtheitsprüfung), ein einheitlicher **Objektspeicher** (Dateisystem oder S3) mit
Wartungsmodus, ein **Offsite-Backup mit BorgBackup** inklusive Restore, eine
**Dokumentverwaltung** mit PDF-Ansicht und Textextraktion sowie **Bild-Metadaten** mit
Vorab-Abgleich beim Upload. Dazu die Audit-Reparaturen aus `main` (Abschnitt «Betrieb») und
die Umsetzung von vier Audits: **Datenschutz** (DSG/DSGVO: Löschung, Auskunft, Fristen,
Sicherheitsprotokoll), **Sicherheit** (u. a. Row-Level-Security in PostgreSQL, verschlüsselte
Exporte), **Stabilität unter Last** (neuer `job-worker`, Überlast-Schutz nach Abo) und
**Feature-Recovery**. Neu ausserdem **Anliegen**: Punkte für kommende Sitzungen, die
automatisch im nächsten Protokoll erscheinen. **Breaking Changes** - vor dem Update die
Schritte unten lesen.

### Update von 1.1.13 auf 1.2.0

1. **Backup ziehen.** `deploy.sh` legt vor den Migrationen einen Datenbank-Dump an, die
   Dateiablage (`HOCX_STORAGE_PATH`) zusätzlich selbst sichern. Migration
   `0115_document_engine_migrate` (TeX-Vorlagen → Hausstile → Brand-Profile) ist **nicht
   umkehrbar**, mehrere weitere Migrationen verlieren beim Downgrade Daten (u. a. `0116`,
   `0118`, `0136`, `0139`, `0141`). Der Rückweg auf 1.1.13 geht nur über `restore_db.sh` mit
   diesem Dump plus dem alten Deploy-Code. Der automatische App-Rollback von `deploy.sh` startet
   zwar die alten Images, rollt aber keine Migration zurück, und das 1.1.13-Backend erreicht das
   jetzt passwortgeschützte Redis nicht.
2. **Dump-Verschlüsselung vorbereiten (empfohlen).** `gpg` auf dem Host installieren und den
   öffentlichen Schlüssel unter `~/.hocx-backup/dump-public.asc` ablegen (oder
   `BACKUP_DUMP_PUBLIC_KEY_PATH` setzen, RUNBOOK Abschnitt 10). Ohne Schlüssel schreibt
   `deploy.sh` den Dump unverschlüsselt mit Warnung; mit `HOCX_REQUIRE_DUMP_ENCRYPTION=true`
   bricht er ab. Pre-Deploy-Dumps werden auf 10 Stück und höchstens 30 Tage gekürzt.
3. **Platz und Wartungsfenster.** Das Backend-Image wird grösser (LibreOffice, Tesseract,
   Poppler für den `document-worker`; BorgBackup, SSH und PostgreSQL-Client für den
   `backup-worker`; TeX Live entfällt). Lokales S3 (Garage) belegt erst nach einer
   Storage-Migration nennenswert Platz. PostgreSQL (`max_connections=150`) und Redis (neu mit
   Passwort im internen Netz `cache`) werden vor den Migrationen neu gestartet; ab dann bis zum
   Ende des Deploys ist die App nicht nutzbar. Wartungsfenster einplanen.
4. **Code und Version.** Release 1.2.0 muss auf `main` stehen und den CI-Nachweis haben
   (`update_deploy_code.sh` akzeptiert nur `main`). `HOCX_VERSION=v1.2.0` in `.env`, dann
   `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>`. `deploy.sh` ergänzt
   die neuen Secrets (`STORAGE_CREDENTIALS_KEY`, `EXPORT_ENCRYPTION_KEY`, `REDIS_PASSWORD`,
   Zugangsdaten des lokalen S3, leere Backup-Platzhalter) und stellt `HOCX_ENVIRONMENT=prod` auf
   `production` um; die ergänzte `.env` danach neu sichern. Keine neuen Pflicht-Variablen.
   Optional (siehe `.env.prod.example`): `DOCUMENT_VERIFY_BASE_URL` (Standard
   `ABGABEBOX_BASE_URL/verify`), `ABGABEBOX_DEFAULT_PRIVACY_URL`, `HOCX_SERVER_LOCATION`
   (Standard `ch`), `STORAGE_ALLOWED_LOCATIONS`, `TENANT_OFFBOARDING_GRACE_DAYS`,
   `FRIENDLY_CAPTCHA_PUZZLE_URL`/`_VERIFY_URL` (EU-Endpunkt), `GARAGE_CAPACITY`, die
   Lastparameter `DB_POOL_*`, `DB_ADMISSION_*`, `OVERLOAD_*` und die Alarmschwellen
   `SECURITY_*` (RUNBOOK Abschnitt 17). `BACKUP_ENABLED=true` erst **nach** dem ersten
   1.2.0-Deploy setzen (vorher läuft kein `backup-worker`, `deploy.sh` bricht sonst ab).
5. **Migrationen** `0113` bis `0153` laufen automatisch (getestet von 1.1.13 mit Demo- und
   Testdaten); neue Dienste `storage-init`, `storage-worker`, `local-s3`, `backup-worker`,
   `document-worker` und `job-worker` startet `deploy.sh` mit `up -d`. Die Smoke-Checks prüfen
   zusätzlich `document-worker`, `storage-worker` und `job-worker`.
6. **Nach dem Deploy:**
   - `/admin/system`: Checks «Öffentliche Prüfseite», «Dateispeicher» und
     «Dokumentverarbeitung» grün; ein Protokoll exportieren und auf `/verify` der Abgabebox
     prüfen (Ergebnis «Original»).
   - Alte TeX-Vorlagen-Dateien entfernen, **solange noch das Dateisystem aktiv ist** (vor einer
     Umstellung auf S3): `./scripts/cleanup-legacy-document-templates.sh --dry-run`, dann ohne
     `--dry-run` (RUNBOOK Abschnitt 13).
   - `document_sync` übernimmt bestehende Dateien und Protokollexporte schrittweise als
     logische Dokumente; Fortschritt: `docker compose exec backend python -m app.workers.document_admin status`
     (RUNBOOK Abschnitt 16).
   - Optional einmalig den Bild-Metadaten-Backfill:
     `docker compose exec backend python -m scripts.backfill_image_metadata`
     (`backend/UPLOAD_DUPLICATES.md`, Abschnitt 12).
7. **Später, bewusst entscheiden:** Erstmigration der Dateien in den Objektspeicher (RUNBOOK
   Abschnitt 14) und Einrichtung des Borg-Offsite-Backups mit Ablösung der Cronjobs
   `backup_db`/`backup_storage` (RUNBOOK Abschnitt 15). Bis dahin bleibt das Dateisystem aktiv und
   die bisherigen Backup-Cronjobs gelten weiter.

**Wer einen Vorabstand mit digitaler Dokumentsignatur installiert hatte:** Die Signatur entfällt
vollständig. Die Variablen `DOCUMENT_SIGNING_*` werden ignoriert und können aus `.env` entfernt
werden, ebenso das Verzeichnis `.signing/` bzw. `DOCUMENT_SIGNING_DIR` und die Datei
`.secrets/document_signing_key_password`. Bereits signiert exportierte PDFs bleiben über die
Prüfseite prüfbar, weil ihr Hash gespeichert war (Migration `0116_document_registry`).

### Update-Werkzeuge (Nachtrag vom 2026-10-24, nach dem ersten Test-Update)

- **Deploy und Rollback brachen ab**: `deploy.sh` schreibt `HOCX_BACKEND_WORKERS` ins
  Release-Manifest, der Env-Loader lehnte den Schlüssel ab. Ein Test prüft jetzt jeden
  Manifest-Schlüssel gegen die Allowlist.
- **Lokales S3 blieb uneingerichtet**: `storage-init` las den Garage-Admin-Token nur aus der
  Umgebung, Compose übergibt ihn als Secret-Datei (`GARAGE_ADMIN_TOKEN_FILE`). Garage blieb ohne
  Schlüssel und Buckets (AccessDenied). Eine Teilkonfiguration beendet `storage-init` jetzt mit
  Fehler, und die Smoke-Checks von `deploy.sh` führen es aus - ein Fehler führt zum Rollback.
- **`.env`-Migration**: leere Platzhalter aus `.env.example` (`STORAGE_CREDENTIALS_KEY=`) werden
  ersetzt statt den Schlüssel ein zweites Mal anzuhängen.
- `deploy.sh` verweigert einen Test-Candidate, dessen Commit der Checkout nicht enthält
  (neues Image mit altem Stack) - zuerst `./scripts/update_deploy_code.sh --deploy`.
- `deploy.sh` und `update_deploy_code.sh` prüfen vor jeder Änderung, dass der Checkout dem
  Deploy-Benutzer gehört, und nennen sonst den `chown`-Befehl für root. Vorher brach das Update
  mittendrin ab.
- Optionale, nicht versionierte `docker-compose.local.yml` für host-spezifische Anpassungen
  (Vorlage `docker-compose.local.example.yml`); wird überall automatisch mitgeladen.
- `deploy.sh` richtet den Cronjob `storage_controller` selbst ein (`HOCX_MANAGE_CRON=false`
  schaltet das ab).
- `verify_release.sh` prüft die Domains per `curl` mit SNI direkt gegen Traefik, ohne DNS;
  eigene CA über `HOCX_VERIFY_CA_FILE`. Private Hosts überspringen die Checks nicht mehr.
- `infra/garage/` ist Teil des signierten Deploy-Code-Nachweises.
- **Traefik-Rechte nach Code-Updates**: Git schreibt die versionierte
  `infra/traefik/dynamic/security.yml` als Deploy-Benutzer neu, danach brach `deploy.sh` mit
  «muss für die Container-Gruppe 5001 vorbereitet werden» ab. `deploy.sh` setzt die Gruppe 5001
  jetzt selbst, ohne root, über einen kurzlebigen Container aus dem geprüften Backend-Image.
- **`infra/traefik/letsencrypt`** gehört root mit Rechten 0711 statt 0700. Git erreicht die
  versionierte `.gitkeep` wieder, Traefiks `acme.json` (0600) bleibt geschützt. `deploy.sh` und
  `provision_deploy_user.sh` setzen die Rechte selbst.
- **Demo-Mandant (Testumgebung)**: Die Abgabe-Dateien des Demo-Mandanten verschwanden nach
  jedem weiteren Deploy. Der Seed schrieb sie unter festen Schlüsseln direkt auf die Platte, der
  Purge-Job entfernte sie über die Tombstones des gelöschten Vorgänger-Mandanten. Sie laufen
  jetzt über den Objektspeicher (auch bei S3) und liegen unter einem Schlüssel je Mandant.
- **Fester TOTP-Seed auf Testhosts**: `deploy.sh` erzeugt `DEMO_TOTP_SEED` auf Testhosts einmalig
  und behält ihn. Der Demo-Seed hinterlegt ihn für alle Demo-Konten und zusätzlich als Faktor
  «Dev-Seed» für jeden Plattform-Admin. Ein Authenticator-Eintrag reicht damit für Mandant und
  Admin-Seite, auch nach jedem Neuaufbau.

### Breaking Changes

- Der TeX-Export ist entfernt (inkl. TeX Live im Backend-Image). Dokumentvorlagen werden
  automatisch zu **Brand-Profilen** des Document Studio (Migrationen `0115` und `0118`): Farben,
  Schrift (inkl. hochgeladener Schriften), Format, Kopf-/Fuss-/Titelseiten-/TOC-Variante,
  Nummerierung, Ort, Absender, Logo und Fussbild werden übernommen, ebenso TOC-Abstand, Farbe des
  Absenders, «Metadaten anzeigen» und die Kopfzeile «Logo mit Farbbalken». **Eigener
  Vorlagen-Code (Slots) entfällt ersatzlos**; betroffene Mandanten schreibt die Migration ins Log.
- Die Element-Option `latex_template` entfällt. Das Render-Format «Raw LaTeX» wird entfernt,
  sofern es nirgends verwendet wird; die PDF-Ausgabe richtet sich nur noch nach dem Element-Typ.
- API: `/api/exports/*` und die alten `/api/document-templates/*` sind entfernt, neu sind
  `/api/documents/*`, `/api/document-templates` (Document Studio), `/api/document-brands`,
  `/api/document-assets`, `/api/document-components`, `/api/document-template-assignments`,
  `/api/document-studio/*`, `/api/document-settings` und `/api/document-verification`. Die
  Dokumentverwaltung belegt `/api/documents/{uuid}…` (Details, Dateien, Text, Neuverarbeitung).
- Protokollvorlagen verweisen nicht mehr direkt auf eine Dokumentvorlage. Welche Vorlage und
  welches Corporate Design gelten, regeln Zuweisungen pro Dokumenttyp und Protokollvorlage.
- Mandanten-Export: Archivformat 7 mit Brand-Profilen, Assets, Vorlagen samt Revisionen,
  Komponenten, Zuweisungen, Export-Historie und Dokumentenregister. Archive der Formate 2-6
  lassen sich weiter importieren (alte Vorlagen und Hausstile werden umgewandelt). Die
  Verifizierung einer Organisation durch hocX wird nie mit importiert.
- Die Abgabebox-Datenbankrolle `hocx_abgabebox` liest von `tenant` nur noch `id` und
  `storage_quota_bytes` (vorher die ganze Tabelle).
- Abgabe-Link-Tokens können nicht `verify` lauten (Route der Prüfseite).
- Protokoll-PDFs, die Version eines logischen Dokuments sind (Dateien-Tab), fallen nicht mehr
  unter `EXPORT_RETENTION_DAYS` und die Regel «nur die neueste Datei je Protokoll»; nur ersetzte
  Darstellungen (gleicher Inhalt neu exportiert) und Exporte ohne Protokollbezug werden
  freigegeben. Das Speicherkontingent wächst dadurch mit jeder inhaltlich neuen Protokollfassung.
- Aus den Audits (Details in den Abschnitten unten): Mandanten-Export ist `POST` und liefert ein
  verschlüsseltes Archiv; der PDF-Export (`POST /api/documents/render`) antwortet mit `202` und
  einer Auftrags-ID statt mit der Datei; schreibende Requests mit fremdem `Origin` werden
  abgelehnt; Zugriffe auf fremde Datensätze antworten wegen Row-Level-Security teils mit `404`
  statt `403`; das Domain-Bridge-Token steht im URL-Fragment. Entfernt:
  `PATCH /api/admin/tenants/{id}/storage-quota`,
  `POST /api/submission-assignments/{id}/sync-todos`, `GET /api/tools/word-import/quality-stats`
  und `POST/GET /api/files/analysis-jobs`.

### Neu: Anliegen für kommende Sitzungen

- Neuer Bereich **Arbeiten → Anliegen** (Seite `/agenda`). Ein Anliegen hat Titel und Text und
  gehört zu einer Protokollvorlage und einem ihrer Traktanden. Das Popup wählt die zuletzt
  verwendete Vorlage vor (gespeichert je Person). Als Termin gilt entweder *nächste Sitzung* oder
  ein Monat («ab November 2026»).
- Das Anliegen erscheint ohne eigenen Block im Vorlagen-Aufbau im nächsten Protokoll der Vorlage,
  das *geplant* oder *vorbereitet* ist und ab dem Termin datiert. Dort steht es unter seinem
  Traktandum; ohne passendes Traktandum unter «Weitere Anliegen». Im Editor lassen sich Titel und
  Text direkt ändern, das Anliegen vertagen (neuer Termin) oder löschen. Den Ersteller zeigt nur
  die Liste, nicht änderbar.
- Im Mini-Menü des Editors (Sitzung läuft) erfasst *Anliegen erfassen* ein Anliegen direkt im
  aktuellen Protokoll, standardmässig unter dem gewählten Traktandum.
- Beim Wechsel auf *durchgeführt* gehören die angezeigten Anliegen fest zum Protokoll (Liste:
  *behandelt*). Nach dem Abschluss sind sie schreibgeschützt. Im Protokoll-PDF stehen sie unter
  ihrem Traktandum.
- Mit in Mandanten-Export/-Import/-Klon und in der Datenauskunft (selbst erfasste Anliegen).
  Migration `0153_agenda_item`: Tabellen `agenda_item` und `user_agenda_template_preference`,
  beide mit RLS. Benutzerdoku: `docs-site/docs/benutzer/anliegen.md`.

### Neu: Designs für Protokolle (Nachtrag vom 2026-10-25, ergänzt 2026-10-27)

- Sechs fertig gestaltete Designs: **Alpin**, **Kreide**, **Signal**, **Fokus**, **Siegel** und
  **Atlas**. Jedes gestaltet das ganze Dokument einheitlich: Titelseite (Farbband, Kennzahlen,
  Inhaltsverzeichnis oder Traktandenliste, Verteiler, Fussbild), Kopf- und Fusszeilen,
  Überschriften, Tabellen und die Darstellung **aller** Elemente.
- Gewählt wird das Design beim Anlegen: **Neue Vorlage** zeigt für Protokolle eine
  Design-Galerie (Admins). Das Design legt die Vorlage und ein passendes Brand-Profil (Farben,
  Schriften, Beispiellogo, Beispieladresse) an. Stellt man die Vorlage im Designer auf das
  eigene Brand-Profil um, erscheint sie mit den Farben, dem Logo und den Angaben des Vereins.
  Der frühere Dialog **Beispiele** entfällt.
- Im Brand Studio sind die sechs Designs die Grundstile. Die bisherigen Grundstile
  «Abgerundet», «Kräftig» und «Schlicht» bleiben für Profile erhalten, die sie nutzen, stehen
  aber nicht mehr zur Wahl.
- Neue Darstellungen für Text, feste Texte und Anzeigen (Hinweis-Kasten, Akzentlinie),
  Aufzählungen (Nummern, Striche, Kästchen), Bilder (Rahmen, Karte), Diagramme (Rahmen) und Ein-
  und Austritte (nebeneinander). Damit hat jeder Baustein eines Protokolls eine Darstellung.
- **Bausteine einzeln gestalten:** In der PDF-Gestaltung einer Sitzungsvorlage listet der
  Designer unter «Protokollinhalt» deren Traktanden und Bausteine. Ein Baustein übernimmt die
  Darstellung des Dokuments und lässt sich je Elementart abweichend darstellen. Die Einstellung
  gehört zur Gestaltung (Entwurf, Vorschau, Veröffentlichen). Die Darstellungs-Auswahl im
  Sitzungsvorlagen-Editor entfällt; dort führt ein Link in die PDF-Gestaltung.

### Geändert: Vorlagen-Editor einer Protokollvorlage (Nachtrag vom 2026-10-27)

- Zwei Spalten statt drei: links die Traktanden mit ihren Bausteinen, Verantwortlichen als
  Avatare und Pfeilen zum Umsortieren, darunter «+ Neues Traktandum» und «Aus «Meine
  Bausteine» einfügen»; rechts ein Panel mit «Meine Bausteine» (inkl. Verwendungen), dem
  gewählten Traktandum (Titel, Einladung, Verantwortliche, Bausteine, Wiederverwenden) oder
  dem gewählten Baustein (Inhalt bearbeiten, «Wo und wie» als Schalter, Darstellung im PDF).
- Kopf mit Nummer-Muster, Teilnehmenden-Zähler und Bussentarif («eigener»/«Mandant»); die
  Tabs PDF und Einladung zeigen, ob die Gestaltung gemeinsam oder eigen ist.

### Neu: Funktionsvergleich auf der Landing Page (Nachtrag vom 2026-10-27)

- Unter den Preiskarten zeigt «Alle Funktionen im Vergleich» alle buchbaren Abos als Spalten:
  Preis pro Monat und Jahr, Benutzer, Speicher und jedes verkäufliche Feature, nach
  Produktmodul gruppiert (✓ enthalten, «zubuchbar» mit Monatspreis oder –).
- Die Daten kommen bei jedem Aufruf aus der Datenbank (`GET /api/public/plan-comparison`,
  öffentlich, ohne interne Felder): Änderungen an Abos, Preisen und Features im Adminportal
  sind sofort sichtbar. Preiskarten und Tabelle nutzen denselben Abruf.
- `features_generated.py` enthält jetzt die Produktmodule (`MODULES`) in fester Reihenfolge.

### Neu: Modus «Einfach» im Dokument-Designer (Nachtrag vom 2026-10-27)

- Der Designer startet im Modus **Einfach**: drei Schritte (Aussehen, Inhalt, Seite), die
  PDF-Vorschau ist die Arbeitsfläche. Ein Klick in die Vorschau öffnet den passenden Baustein,
  bei Protokollen auch einzelne Bausteine eines Traktandums mit ihrer Darstellung.
- **Aussehen:** Stilkarten mit den sechs Designs, Logo, Hauptfarbe, Schrift - nur für diese
  Vorlage (neue Felder in `BrandOverrides`: `appearance_base`, Kopf-/Fusszeilen-Schalter,
  Fusszeilentext).
- **Inhalt:** Bausteine mit Ein/Aus, Reihenfolge und 1–3 Einstellungen in Alltagssprache
  (Beschreibung in `backend/app/documents/simple.py`), fertige Bedingungen statt Regel-Editor,
  «+ Baustein hinzufügen» mit acht häufigen Bausteinen; frei gestaltete Bereiche bleiben als
  «Eigener Bereich» erhalten.
- **Seite:** Titelseite, Kopf- und Fusszeile, Hoch-/Querformat.
- Werkzeugleiste reduziert (Name, Status, Speicherstand, Rückgängig, «Erweitert öffnen»,
  Veröffentlichen). Wer kein Corporate Design verwaltet, startet immer im Einfach-Modus.
- Vorschau: `node_boxes` (Positionen der Knoten per Typst-Query), Server-Cache gerenderter
  Vorschauen, kürzere Entprellung im Einfach-Modus. Die Seitenvorlagen der Designs folgen jetzt
  den Kopf-/Fusszeilen-Schaltern.

### Neu: Dokument-Engine und Document Studio

- **Document Studio** (Navigation «Dokument-Studio», eigenes Icon zur Unterscheidung von «Dateien»):
  - **Vorlagen:** Bibliothek mit 26 mitgelieferten Vorlagen für alle 16 Dokumenttypen
    (Protokoll in fünf Varianten), eigene Vorlagen und angepasste Kopien, Entwurf und
    Veröffentlichung, Versionen vergleichen und wiederherstellen, Standardvorlagen pro
    Dokumenttyp und Protokollvorlage.
  - **Visual Designer:** Elemente per Drag-and-drop, Struktur, Datenfelder aus hocX mit Format
    und Ersatztext, Bedingungen und Wiederholen ohne Code, Seitenvorlagen, Titelseite,
    Wasserzeichen, Inhaltsverzeichnis, drei Modi (Einfach, Erweitert, Experte), Undo/Redo,
    Autosave mit Konflikterkennung, verbindliche PDF-Vorschau mit Beispiel- oder echten Daten.
  - **Corporate Design (Brand Studio):** mehrere Profile mit Farben, Schriften, Logos,
    Seitenaufbau, Angaben zur Organisation und Prüfvermerk, Live-Vorschau, Versionen.
  - **Bilder und Schriften**, **wiederverwendbare Komponenten**, **Export-Verlauf**.
- Ein Export-Dialog für alle Dokumente (Protokolle, Todos, Termine, Listen, Statistik): Vorlage
  wählen, Vorschau mit echten Daten, Optionen, PDF oder Zusatzformat (CSV, XLSX, ICS, Markdown).
- Fachkomponenten u. a. Monatskalender, Agenda, Präsenzliste zum Unterschreiben,
  Mitgliederliste, Kennzahlen-Kacheln, Diagramme als Vektorgrafik, QR-Code, Unterschriftsfelder.
- Datenfelder werden beim Export mit den Rechten der exportierenden Person gefüllt (z. B.
  Finanzdaten nur mit Finanz-Feature, Listen und Mitgliederdaten nur für Schreibende).
- Dokumentsprache pro Verein, pro Export änderbar; alle festen PDF-Texte in allen Sprachen.
- PDFs als PDF/A-2b; Metadaten (Dokument-ID, Typ, Version, Inhalts-Hash, Prüf-URL, Mandant nur
  bei freigegebener Anzeige) im XMP.
- **Dokumentenregister und Echtheitsprüfung:** Jedes PDF wird mit seinem SHA-256 registriert und
  trägt (je nach Corporate Design) Prüf-URL, Kurz-ID und QR-Code. Die öffentliche Prüfseite
  `/verify` der Abgabebox zeigt ohne Konto, ob eine Datei unverändert aus hocX stammt, mit
  Status, Version, Hinweis auf eine neuere Version, einem beim Export überschriebenen Titel und
  importierten, nicht verifizierten Einträgen. Die Datei verlässt dabei nie den Browser.
- **Mandanten-Einstellungen → Echtheitsprüfung:** Name und Logo auf der Prüfseite anzeigen (Standard aus), auf
  neuere Versionen hinweisen (Standard an), Verifizierung durch hocX beantragen, Vorschau.
- **Adminportal → Verifizierungen:** Anträge bestätigen oder ablehnen, Verifizierung entziehen;
  eine Namensänderung hebt sie automatisch auf. Bestätigte Organisationen erhalten auf der
  Prüfseite das Abzeichen «Verifizierte Organisation».
- Version steigt nur bei geändertem Inhalt (Inhalts-Hash). Eine andere Vorlage, ein anderes
  Corporate Design oder eine andere Sprache erzeugt keine neue Version (Design-Hash separat); die
  erste Endfassung ist immer v1.0. Jeder Export wird mit Vorlagen- und Brand-Revision protokolliert.
- Entwürfe tragen immer ein Wasserzeichen, ausser Schreibende schalten es ab.
- Render-Warteschlange begrenzt (HTTP 503 statt Stau), abgebrochene Vorschauen beenden das
  Warten, Vorschau und Thumbnails rastern nur die benötigten Seiten.
- Systemcheck «Öffentliche Prüfseite» inkl. ntfy.
- CI: visuelle Regressionstests (Golden-Bilder), Galerie-PDF als Artefakt, Katalogprüfung inkl.
  aller Studio-Texte.

### Neu: Eigene Prüf-Domain je Mandant

- Neues Feature **«Eigene Prüf-Domain»** (`verify_domain`), im Adminportal unabhängig von
  «Eigene Domain» Plänen oder einzelnen Mandanten zuzuordnen (keinem Plan vorbelegt). Mandanten
  richten unter Domains eine Domain mit dem Zweck **Prüfseite** ein (z. B. `verify.verein.ch`, DNS
  wie bei den anderen Domains).
- Die Prüfseite unter dieser Domain zeigt Logo und Name des Vereins; seine Dokumente erhalten die
  Stufe «Prüf-Domain verifiziert», schwächer als «Verifizierte Organisation».
- Neue PDFs verweisen in Prüfvermerk, QR-Code und XMP auf die Prüf-Domain. Die zentrale Prüfseite
  leitet Dokumente solcher Vereine automatisch weiter (mit «Hier bleiben»), ohne dass die Datei
  erneut ausgewählt werden muss; fremde Dokumente gehen von einer Vereinsseite weiter zur
  richtigen Prüf-Domain bzw. zu hocX. Voraussetzung: Name und Logo sind freigegeben.
- Migration `0126_verify_domain`; neuer Endpoint `GET /api/public/verify/site` (Abgabebox).
  Optional `DOCUMENT_VERIFY_BASE_URL` jetzt auch für `abgabebox-backend`.

### Neu: Cashflow im Adminportal

- Adminportal **Mandanten → Cashflow** mit drei Bereichen. **Kosten:** fixe Ausgaben mit
  Abo-Datum (monatlich, jährlich oder einmalig, optional mit Enddatum) und prozentuale Ausgaben
  wie Zahlungsgebühren, die von jeder bezahlten Forderung abgehen. Jede Ausgabe ist **aktiv**
  (wird verrechnet) oder **geplant** (nur in der Rechnung «inkl. geplanter Kosten»).
- **Forderungen:** was jeder Mandant je Abrechnungsperiode schuldet, ohne echte Rechnung.
  Sie entstehen automatisch ab dem neuen Feld **Abo-Start** (Tab «Plan & Abo», leer =
  Erstellungsdatum). Der Betrag (Plan + Zusatzmodule − Rabatt + Speicherpakete) wird beim
  Entstehen festgehalten und lässt sich bei offenen Forderungen neu berechnen. Status **offen**,
  **bezahlt** (mit Zahlungsdatum) oder **erlassen**; nur bezahlte zählen als Einnahme.
- **Überfällig:** offene Forderungen, deren Zahlungsfrist (30 Tage ab Periodenbeginn) abgelaufen
  ist; eigener Filter und Hinweis in Liste und Übersicht.
- **Mandanten sehen ihre Forderungen** unter Mandanten-Einstellungen → Abo & Nutzung (nur
  Mandanten-Admins, auch mobil): Periode, Betrag, Fälligkeit, Status bezahlt, offen, überfällig
  oder erlassen, Zahlungsdatum. Interne Notizen des Betreibers bleiben verborgen. Neuer Endpoint
  `GET /api/tenants/{id}/charges`.
- **Übersicht:** Einnahmen, Ausgaben und Ergebnis des Jahres, Bilanz seit Beginn (real und mit
  geplanten Kosten), Monatsrechnung nach aktuellem Stand, Verlauf je Monat mit Prognose.
- Migration `0127_cashflow` (Tabellen `cashflow_cost`, `tenant_charge`, Spalten
  `tenant.billing_start_date`/`billing_charged_until`). Beim ersten Öffnen entstehen für alle
  Mandanten mit Preis die Forderungen seit Erstellung zum heutigen Preis: falls das nicht stimmt,
  den Abo-Start setzen (offene Forderungen werden neu erzeugt) oder alte Forderungen erlassen.

### Neu: Notizen und Dateien an Todos

- Im Todo-Popup der Todo-Liste gibt es ein Feld **Notizen** mit demselben Markdown-Editor wie im
  Protokoll (fett, kursiv, Listen) und den Bereich **Dateien**: bereits hochgeladene Dateien
  (Dateien- und Fotos-Seite) lassen sich per Suche verknüpfen, öffnen und wieder entfernen.
  Gespeichert wird mit «Speichern».
- Notizen und Dateien erscheinen bewusst nur im Popup, nicht in Liste, Übersicht, Protokoll oder
  Exporten. Wird eine Datei gelöscht, verschwindet nur ihre Verknüpfung.
- Migration `0128_todo_notes_files` (Spalte `protocol_todo.notes`, Tabelle `protocol_todo_file`);
  Endpoints `GET`/`PUT /api/protocol-todos/{id}/details`. Mandanten-Export, -Import und -Klon
  übernehmen beides.

### Neu: Objektspeicher (S3), Live-Migration und Wartungssystem

- Alle persistenten Dateien (Uploads, Abgabebox inkl. Quarantäne, Document-Studio-Assets,
  erzeugte PDFs, Dateien logischer Dokumente, Mandantenlogos, Klon-/Import-Dateien) laufen über
  eine einheitliche Objektspeicher-Abstraktion (Dateisystem oder S3: AWS, Hetzner, Garage,
  S3-kompatibel).
- Lokales S3 (Garage v2.3.0) wird beim Deployment automatisch bereitgestellt; ein Host-Controller
  stoppt es nur, wenn es nachweislich nicht mehr gebraucht wird, und löscht nie Daten.
- Adminportal **System → Storage**: verschlüsselte Speicherprofile, Verbindungstest,
  Erstmigration (in voller Wartung) und Live-Migrationen mit Änderungsjournal, Prüfung,
  Schreib-Fence und atomarem Cutover in neue Speichergenerationen; Fortschritt, Raten, Restzeit,
  Heartbeat, Verlauf, Prüfbericht, Bereinigung alter Generationen.
- Adminportal **System → Wartung**: Wartungsfenster planen/starten/beenden; Freigabe nur bei
  erfüllten Bedingungen. Serverseitige Sperre (503 + Retry-After, WebSocket 1013) für Backend
  und Abgabebox, Wartungshinweis auf der Anmeldeseite, konservative Dauerabschätzung.
- Gelöschte Dateien werden erst nach dem Commit physisch entfernt (Tombstone + Job
  `storage_purge`): scheitert eine Löschung in der Datenbank, bleibt die Datei erhalten.
- Die Adresse eines S3-Endpunkts wird bei jeder Verbindung neu aufgelöst und geprüft
  (Schutz vor DNS-Rebinding auf interne Ziele).
- Neue Jobs: `storage_migration_worker`, `maintenance_supervisor`, `storage_journal_cleanup`,
  `storage_purge`, `storage_controller`, `backup_storage`; neue Systemprüfungen
  `object_storage`, `storage_migration`.

### Neu: Offsite-Backup mit BorgBackup

- Dienst `backup-worker` (einziger Dienst mit Borg-Schlüssel und -Passphrase): verschlüsselte,
  deduplizierte Backups von Datenbank und allen Objekten auf eine Hetzner Storage Box
  (append-only), inkrementelle Objektsicherung, Retention, Integritätsprüfung und monatlicher
  Restore-Test.
- Konsistente Sicherung im laufenden Betrieb: Während eines Backups sichert jeder Schreiber und
  der Purge-Job den bisherigen Inhalt eines Objekts vor dem Überschreiben bzw. Löschen
  (Copy-on-Write-Hold).
- Adminportal **System → Backups**: Status, Einstellungen, Sicherungspunkte, Wiederherstellung
  eines Mandanten **als Kopie** oder **vollständig** (Rettungspunkt, isolierte Datenbank, neue
  Speichergeneration, Tausch mit automatischem Rücktausch), jede Wiederherstellung mit frischer
  TOTP-Bestätigung; Recovery-CLI für den Notfall ohne laufende App.
- `deploy.sh` legt vor den Migrationen ein geschütztes Backup an, sobald Borg eingerichtet ist
  (`HOCX_PRE_DEPLOY_BACKUP`, `..._ALLOW_PARTIAL`, `..._TIMEOUT`).
- Neue Systemprüfungen `backup`, `backup_repository`, `backup_verification` inkl. ntfy.

### Neu: Dokumentverwaltung mit PDF-Ansicht und Textextraktion

- Hochgeladene Dokumente (Dateien-Tab, Word-/PDF-Import, Abgabebox) sind logische Dokumente:
  genau ein Eintrag im Dateien-Tab, bevorzugt als PDF angezeigt. Originaldatei, extrahierter
  Text und ältere Versionen stehen in den Dokumentdetails.
- Automatische PDF-Konvertierung (LibreOffice, isoliert) und formatspezifische Textextraktion
  (PDF, DOCX, DOC, ODT, RTF, TXT, Markdown, CSV, XLSX; OCR für gescannte PDFs) im neuen Dienst
  `document-worker`, mit persistenten Aufträgen, Wiederholungen und Statusanzeige. Der
  Dateien-Tab zeigt laufende Verarbeitung unter dem Dateinamen samt Stufe («Wird verarbeitet ·
  Virenprüfung / PDF-Ansicht / Texterkennung», `DocumentSummary.processing_stage`); Filter und
  Tabelle in einer Karte, Download und Teilen als Symbol-Buttons.
- Einheitliches, versioniertes Inhaltsformat (`hocx.document-content` v1) als Grundlage für das
  spätere Zusammenführen mehrerer Dokumente.
- **Protokollexporte der Dokument-Engine** bilden je Protokoll und Dokumenttyp ein Dokument mit
  Versionshistorie (neue Version nur bei neuem Inhalt); der Dateien-Tab zeigt die aktuelle
  Version (Filter «Protokollexporte»).
- Bestehende Dateien und Exporte werden automatisch übernommen (`document_sync`, wiederholbar).
- Neue Jobs `document_sync`, `document_worker`; neue Systemprüfung `document_queue`
  (gestaute oder endgültig gescheiterte Aufträge, inkl. ntfy).

### Neu: Bild-Metadaten und Vorab-Abgleich beim Upload

- Bild-Upload prüft Bilder vorab im Browser (Web Worker): SHA-256, Aufnahmedatum,
  Zeitzone, GPS, Kamera, Abmessungen, Ausrichtung – für JPEG, PNG, WebP, TIFF und HEIC/HEIF.
  Bereits vorhandene Bilder werden nicht erneut übertragen (`POST /api/files/upload-precheck`);
  fehlende Metadaten vorhandener Bilder werden dabei ohne Upload ergänzt. Auch Dokumente und
  Protokollbilder nutzen den Vorab-Abgleich (nur Hash).
- Drei getrennte Datumsarten: echtes Aufnahmedatum, neues **geschätztes Aufnahmedatum**
  (reines Kalenderdatum) und Uploaddatum. Galerie-Sortierung, -Gruppierung und Bilddetails
  folgen zentral dieser Reihenfolge; geschätzte Daten und der Uploaddatum-Fallback sind in den
  Datumsüberschriften mit einer beschrifteten Pille gekennzeichnet («Geschätztes Datum»,
  «Uploaddatum», bei gemischten Tagen mit Anteil).
- Upload-Popup: Hinweis und optionales Schätzdatum für Bilder ohne Aufnahmedatum, Ordner per
  Drag & Drop oder „Ordner auswählen“, automatische Aufteilung grosser Auswahlen in Aufträge zu
  höchstens 50 Dateien, Abbrechen während der Übertragung.
- Upload-Ergebnis je Datei: Hochgeladen, Übersprungen, Übersprungen · Metadaten ergänzt,
  Fehlgeschlagen – mit Zusammenfassung und Detailliste; Upload-Fehler übersetzt (Fehlercodes).
- Bilddetails: Aufnahmedatum als eigener Kasten oben (Herkunft «aus EXIF», geschätzt mit «Ändern»
  oder unbekannt), übrige Angaben in festem Raster. Echtes Aufnahmedatum (in Kamerazeit, mit Offset), geschätztes Datum
  (bearbeiten/entfernen, `PATCH /api/stored-files/{id}/capture-date`; nur bei Bildern ohne
  echtes Aufnahmedatum), Uploaddatum und Standort getrennt.
- GPS-Daten werden gespeichert (Breite, Länge, Höhe, Blickrichtung, Genauigkeit, Herkunft).
  **Standort je Album-Freigabe schaltbar:** Freigaben an Partner-Mandanten teilen ihn
  standardmässig, Freigabe-Links nicht; ohne Freigabe entfernen Downloads, Vorschau und
  Live-Photo-Clips den Standort.
- Downloads, Mehrfachdownload und Freigabe-Links schreiben ein geschätztes Datum in EXIF/XMP
  einer temporären Kopie, wenn kein echtes Aufnahmedatum existiert; Originale bleiben
  unverändert.
- Abgabebox und Protokollbilder speichern Aufnahmedatum, GPS und Kamera beim Upload.
- Gezielter Metadaten-Backfill für ältere Bilder (fortsetzbar, wiederholbar, mit Auswertung).
- Ein nur geschätztes Datum führt nie zu einer automatischen Termin-Zuordnung; Aufnahmezeiten
  werden in der Detailansicht nicht mehr um die App-Zeitzone verschoben.

### Datenschutz (Datenschutz-Audit vom 2026-10-21, Paket 1)

- **Statistik:** Bussen und Anwesenheit je Person sehen nur noch Schreibende, Kassier und Admins.
  Leser sehen dort ihre eigenen Werte, auch in PDF-Diagrammen. Mandanten-Admins können die
  Ranglisten unter Mandanten-Einstellungen → Datenschutz für alle freigeben (Migration `0138`,
  standardmässig aus). Finanzzahlen in der Statistik nur noch mit gebuchtem Modul Finanzen.
- **Fehlerprotokoll:** keine Werte aus SQL-Parametern oder Postgres-Details mehr
  (`hide_parameters`, Redaktion von E-Mail-Adressen). Der Auslöser wird als Konto-ID gespeichert
  und beim Anzeigen aufgelöst; nach dem Löschen eines Kontos bleibt keine Adresse zurück
  (Migration `0139`, leert bestehende Adressen). Fehler werden dem Mandanten des Kontos zugeordnet.
- **Kalender-Abos** übertragen standardmässig nur Titel und Datum (Migration `0140`, bestehende
  Abos unverändert).
- **Offline-Entwürfe** im Browser gehören dem angemeldeten Konto und werden beim Abmelden
  gelöscht (Rückfrage bei ungesendeten Änderungen).
- **Freigabelinks:** gelöschte Fotos verschwinden aus Dateilinks; ein Dateilink liefert nur Dateien
  seines Mandanten.
- **Fristen** für Upload- und Analyse-Jobs (30 Tage), Abgabebox-Uploadverlauf (90 Tage),
  Betriebsereignisse (2 Jahre), entschiedene Verifizierungsanträge und Word-Import-Lernsignale
  (1 Jahr) sowie widerrufene/abgelaufene Freigabelinks (90 Tage); Job `log_cleanup`.
  Die Prüfkopie zusammengeführter Bussen aus Migration 0116 wird entfernt (Migration `0141`).
- **Dumps:** Pre-Deploy-, Cron- und Restore-Sicherungen werden mit einem öffentlichen GPG-Schlüssel
  verschlüsselt (`BACKUP_DUMP_PUBLIC_KEY_PATH`, RUNBOOK Abschnitt 10), Pre-Deploy-Dumps nach
  30 Tagen entfernt. Unverschlüsselte Dumps gehen nur auf ein rclone-crypt-Remote, alte
  Offsite-Kopien werden gelöscht.
- Backends schreiben kein Access-Log mehr (Pfade enthielten Link-Tokens).

### Datenschutz (Paket 2: vollständige Dateilöschung)

- **Protokoll löschen:** ein Dialog zeigt die Bilder des Protokolls; standardmässig werden sie
  mitgelöscht, abgewählte wandern mit Tag «Protokoll …» in die Galerie. Bilder, die noch ein anderes
  Protokoll verwendet, bleiben. Erzeugte PDFs verschwinden mit. Vorher blieben alle Bilder liegen.
- **Abgabe löschen:** gleicher Dialog für eingereichte Dateien und Galeriefotos der Abgabe;
  behaltene Einreichungen werden aus dem Abgabebox-Speicher in die Galerie übernommen.
- **Einzelne Einreichungen** lassen sich im Abgabe-Detail löschen (z. B. auf Wunsch der
  einreichenden Person), samt Vorschau, Dokumenten, Album- und Linkeinträgen.
- Eine gemeinsame Löschfunktion räumt bei jeder Dateilöschung Objekt, Vorschaubild, Dokumente,
  Album- und Freigabelink-Einträge ab. `/admin/system` meldet Dateien, die zu nichts mehr gehören.

### Datenschutz (Paket 3: Sicherheitsprotokoll)

- **Audit-Log:** fehlgeschlagene Anmeldungen (App, MFA, Plattform-Admin), Plattform-Logins,
  hinzugefügte MFA-Faktoren und Einblicke des Plattform-Supports in Mandantendaten werden
  protokolliert. Statt IP-Adressen steht ein gekürzter, gehashter Netz-Fingerabdruck (`ip_hash`),
  dazu `outcome` (Migration `0143`). Die App-Rolle darf das Protokoll nicht mehr ändern oder löschen;
  Aufbewahrung (mindestens 30 Tage) und das Entfernen von E-Mail-Adressen gelöschter Personen bzw.
  Mandanten laufen über eigene DB-Funktionen.
- **Verlauf für Mandanten-Admins** unter Mandanten-Einstellungen → Verlauf (nur eigener Mandant,
  Plattform-Zugriffe als «Plattform-Support»), **Plattform-Ansicht** unter `/admin/audit` (Owner).
- **Sicherheitsalarme:** neuer Check `security` in `/admin/system` und ntfy (viele fehlgeschlagene
  Logins, auffällig viele Exporte, Restores, Admin-Änderungen; Schwellen per `SECURITY_*`, RUNBOOK).
- Mandanten löschen liefert einen Bericht (Personen, Dateien, Fehler beim Objektlöschen).

### Datenschutz (Paket 4: Löschjournal)

- Endgültige Löschungen (Mandant, Person, Protokoll, Termin, Abgabe, Einreichung, Datei) landen im
  Löschjournal (Migration `0144`, nur Einfügen für die App-Rolle, Aufbewahrung ≥ 400 Tage). Ein
  Voll-Restore und eine Mandanten-Kopie wenden sie vor dem Umschalten erneut an, damit gelöschte
  Daten nicht aus dem Backup zurückkehren. Abschalten nur beim einzelnen Restore mit Begründung.
- **Behoben:** Termin oder Listeneintrag löschen entfernt jetzt auch die zugehörigen
  Abgabebox-Einreichungen samt Dateien (blieben vorher verwaist liegen).

### Datenschutz (Paket 5: Datenauskunft)

- **Datenauskunft je Person** (Personen → Menü → Datenauskunft, nur Admin) und **«Meine Daten»** im
  Profil: passwortgeschützte ZIP-Datei (AES-256) mit `Auskunft.xlsx` (ein Blatt je Bereich),
  `daten.json` und Lesehinweis. Enthält nur die eigenen Zeilen (Anwesenheit, Bussen, Aufgaben,
  Termine, Dateien, Sicherheitsereignisse, Erwähnungen in Protokolltexten), keine Zugangsdaten.
  Abruf wird protokolliert, Selbstauskunft max. 3× pro Stunde. Öffnen mit 7-Zip, Keka oder WinRAR
  (der macOS-Finder kann AES-ZIP nicht öffnen). Neue Abhängigkeit `pyzipper`.

### Datenschutz (Paket 6: Vereinsexport)

- **Vereinsexport** unter Mandanten-Einstellungen → Datenschutz (Mandanten-Admin, Anmeldung mit
  Zwei-Faktor-Bestätigung): AES-ZIP für die Weiterarbeit mit `Mitglieder.xlsx`, `Termine.xlsx`,
  `Anwesenheit.xlsx` (Person × Sitzung), `Bussen.xlsx`, `Finanzen.xlsx` (Blatt je Konto),
  `Aufgaben.xlsx`, `Listen/`, den PDFs abgeschlossener Protokolle und auf Wunsch `Fotos/`
  (nach Album bzw. Termin), `Abgaben/` und `Dokumente/` als Originaldateien. Namen statt IDs,
  Datum TT.MM.JJJJ, keine Zugangsdaten. Gebaut vom neuen Job `tenant_data_export` (Migration
  `0145`, RLS), danach 7 Tage abrufbar. Abgeschlossene Protokolle ohne gespeichertes PDF werden im
  Lesehinweis aufgeführt (nicht automatisch erzeugt).
- **Plattform-Export ohne Zugangsdaten als Standard:** Passwort-Hashes, MFA-Secrets und Link-/Abo-
  Tokens nur noch mit der neuen Option «Zugangsdaten mitexportieren» (`include_credentials`). Ohne
  sie erhalten importierte Konten ein zufälliges Passwort und Links neue URLs. Die Mandanten-Kopie
  aus dem Backup nimmt sie weiterhin mit.
- Datenauskunft: Passwort-Mindestlänge auch im API-Schema, Rate-Limit für die Admin-Auskunft,
  temporäre Dateien werden auch bei Fehlern gelöscht (Security-Review).

### Datenschutz (Paket 7: Korrekturweg abgeschlossener Protokolle)

- Abschliessen → zurückstufen → korrigieren → abschliessen: beim erneuten Abschluss verschwinden
  die Änderungsmarkierungen samt alter Fassung, die PDFs des früheren Abschlusses werden sofort
  gelöscht und ihre Registereinträge verlieren den Titel (nur der Prüfwert bleibt, die Prüfseite
  meldet sie als ersetzt). Beschrieben in der Benutzerdoku unter Protokolle.

### Datenschutz (Paket 8: Aufbewahrungsfristen je Verein)

- Neuer Tab **Mandanten-Einstellungen → Aufbewahrung** (Migration `0146`, RLS): Einreichungen der
  Abgabebox X Monate nach Abgabeschluss löschen, ehemalige Mitglieder X Jahre nach Austritt
  **deaktivieren** (Login aus, Sitzungen beendet, Daten bleiben), alte Galeriebilder ohne Album und
  Termin nach X Jahren vorschlagen. Alle Regeln standardmässig aus. Der neue tägliche Job
  `retention_proposals` legt Vorschläge an; der Admin setzt sie um oder verwirft sie, wahlweise
  automatisch (Galeriebilder nie automatisch). Löschung über die bestehenden Löschpfade mit
  Löschjournal und Verlauf.
- **Offboarding:** Vertragsende je Mandant im Adminportal (Abo); `/admin/system` meldet Mandanten
  nach Vertragsende plus `TENANT_OFFBOARDING_GRACE_DAYS` (Standard 90) zur Löschung (Check
  `tenant_offboarding`, gelöscht wird von Hand).

### Datenschutz (Paket 9: Abgabebox-Hinweise, GPS-Wahl, Speicherstandort)

- **Abgabebox:** vor dem Upload stehen der verantwortliche Verein, ein Link zu dessen
  Datenschutzhinweisen (Mandanten-Einstellungen → Datenschutz, sonst `ABGABEBOX_DEFAULT_PRIVACY_URL`)
  und ein Hinweis zu Friendly Captcha. Die Abgabebox liest Name und Link nur über die DB-Funktion
  `abgabebox_privacy_notice()` für den Mandanten ihres Links (Migration `0147`).
- **Friendly Captcha in der EU:** Puzzle- und Verify-Endpunkt per `FRIENDLY_CAPTCHA_PUZZLE_URL` /
  `FRIENDLY_CAPTCHA_VERIFY_URL` einstellbar (CSP folgt automatisch); `/admin/system` zeigt, ob der
  EU- oder der globale Endpunkt aktiv ist.
- **«GPS-Daten des Bildes mitsenden»** (Standard an) bei Galerie-Upload, Protokollbild (auch mobil)
  und Abgabebox. Aus: der Server entfernt vor dem Speichern nur die Standortangaben (EXIF-GPS in
  JPEG/HEIC/WebP/PNG/TIFF, XMP-GPS, Ortsangaben in Live-Photo-Clips) ohne Neukodierung; Datum,
  Kamera und Bild bleiben, die GPS-Spalten leer. Gespeichert wird mit GPS wie bisher.
- **GPS erst ab Rolle Schreiber:** Leser sehen keine Koordinaten in den Fotodetails und erhalten
  Originale ohne Standort.
- **Datenstandort der Speicherprofile:** Schweiz / EU-EWR / angemessen / Drittland, bei AWS und
  Hetzner aus der Region abgeleitet, bei S3-kompatibel gewählt. Drittland nur mit
  Übermittlungsgrundlage und Bestätigung, Migration dorthin fragt erneut nach; optional
  `STORAGE_ALLOWED_LOCATIONS`. Badge in `/admin/storage`. Neu: serverseitige Verschlüsselung (S3
  `AES256`) je Profil, im Verbindungstest geprüft.

### Stabilität unter Last (Concurrency-Audit vom 2026-10-21, Lasttest vom 2026-10-22)

- **Neuer Dienst `job-worker`** (Backend-Image): Galerie-Ingest, Qualitäts-Backfill,
  Vereinsexport, Album-Sync, Virenscan-Nachprüfungen, Thumbnail-Backfill und Aufräumjobs laufen
  nicht mehr in den Backend-Workern. Eigenes Budget (3 GiB / 1,5 CPU), Backend jetzt
  4 GiB / 2,5 CPU. `deploy.sh` startet und prüft ihn, Heartbeat unter `/admin/jobs`.
- **PDF-Export als Auftrag** (Migration `0150`): der Export antwortet sofort, der `job-worker`
  rendert reihum je Mandant, die Oberfläche meldet «PDF bereit» auch nach einem Seitenwechsel.
  Das automatische PDF nach Protokollabschluss läuft ebenfalls als Auftrag; dabei behoben, dass
  der Abschluss weder Audit-Eintrag noch PDF auslöste.
- **Typst-Renderer** mit eigenen Worker-Prozessen: ein Timeout beendet nur den betroffenen
  Compile, Exporte haben Vorrang vor Vorschauen und Thumbnails.
- **Keine Lost Updates in Protokollblöcken** (Migration `0149`): gleichzeitige Änderungen an
  derselben Blockkonfiguration enden mit einem Hinweis und dem aktuellen Stand statt still
  überschrieben zu werden; Anwesenheits-Klicks gehen nicht mehr verloren. Live-Updates aus
  Listen- und Anwesenheitsänderungen kommen bei anderen Bearbeitenden wieder an.
- **Uploads:** der Virenscan läuft ohne den Upload-Lock des Vereins (vorher warteten alle Uploads
  eines Vereins, auch die öffentliche Abgabebox, auf ClamAV); Galerie und Abgabebox nehmen mit
  begrenzten Plätzen an und lassen kurz warten statt sofort 503 zu melden, die Abgabebox
  wiederholt bei 503 automatisch. Galerie-Ingest reihum je Mandant.
- **Verbindungen kurz gehalten:** Downloads und Streams geben die DB-Verbindung vor der
  Auslieferung frei, Pools je Prozess einstellbar (`DB_POOL_*`), ein voller Pool antwortet mit
  503 `db_busy` und `Retry-After` statt nach 30 s mit 500; nichts Blockierendes mehr im
  Event-Loop.
- **Hintergrundjobs:** Singleton-Locks laufen nach 30 min nicht mehr ab (Jobs liefen doppelt),
  hängende Fotoanalyse-Aufträge werden nach 6 h beendet, Backup-Prüfung und Restore-Test nur im
  Nachtfenster (`BACKUP_HEAVY_WINDOW_HOURS`).
- **Redis/Kollaboration:** Timeouts, Feldsperren atomar, Redis-Ausfall blockiert das Speichern
  von Protokollen nicht mehr, `maxmemory` mit `noeviction` statt OOM-Kill.
- **Öffentliche Album-ZIPs** werden 10 min wiederverwendet und begrenzt gebaut, Abgaben-ZIPs auf
  der Platte statt im Speicher; Diagramme aktualisieren nur bei sichtbarem Tab und höchstens
  minütlich; Thumbnails auf Abruf begrenzt; Ähnlichkeitsgruppen mit Cache (Duplikate-Tab grosser
  Galerien vorher über 70 s).
- **Monitoring:** Laufzeitkennzahlen je Prozess (Migration `0148`: Event-Loop-Verzögerung,
  Pool- und Threadpool-Belegung) mit Check `runtime` und `render_queue` in `/admin/system`.
- **Behoben:** Abgabebox-Einreichungen im Dateisystem-Speicher waren für das Backend nicht lesbar
  (Dateien mit 0600 statt umask-Rechten), lokales S3 (Garage) startete im Release-Stack wegen
  der Rechte der Secret-Dateien nicht, Traefik-Admin brach grosse Mandantenimporte nach 60 s ab.
- **Request-Annahme je Backend-Worker:** höchstens so viele gleichzeitige Requests wie
  DB-Verbindungen (Standard 16), der Rest wartet kurz und bekommt erst nach 20 s ein 503
  `db_busy`. Vorher konnte der Server bei rund 250 aktiven Nutzern in einen Stau kippen, in dem
  fast jede Anfrage erst nach Sekunden mit 503 endete. Einstellbar über `DB_ADMISSION_*` (RUNBOOK).
- **Priorität bei Überlast je Abo:** Jeder Plan hat im Preiskatalog eine Priorität (niedrig,
  normal, hoch). Wird es knapp, sehen neue Nutzer von Abos mit niedriger Priorität zuerst eine
  Überlast-Seite, die automatisch weiterleitet, sobald wieder Platz ist. Wer bereits arbeitet,
  bleibt angemeldet. Wartende Anfragen werden nach Priorität bedient. Jede Abweisung wird
  protokolliert. Das Adminportal zeigt sie unter System → Überlast je Mandant und meldet sie als
  Warnung (Migration `0151`, `OVERLOAD_*` im RUNBOOK).

### Geändert (Nachtrag vom 2026-10-24)

- **Fotos: Duplikate und Ähnliche werden im Hintergrund gruppiert.** Die beiden Tabs rechneten
  bisher bei jedem Aufruf im Request (bis 1500 Bilder paarweise samt Originalen) und brachen bei
  grösseren Galerien mit «Ähnliche Fotos konnten nicht geladen werden» ab, weil der Browser nach
  15 s aufgab. Neu berechnet der `job-worker` (Job `photo_similarity_refresh`, Takt
  `PHOTO_SIMILARITY_REFRESH_INTERVAL_MINUTES`, Standard 2 Minuten) die Gruppen je Mandant, sobald
  sich dessen Fotos ändern, und legt sie in `photo_similarity_result` ab (Migration 0152). Die
  Tabs rufen nur noch das Ergebnis ab, zeigen den Stand der Berechnung und behalten es beim
  Tabwechsel. Gelöschte Fotos fallen sofort heraus, neue erscheinen nach dem nächsten Lauf. Bis
  zum ersten Lauf nach dem Update zeigen die Tabs «wird im Hintergrund gruppiert». Obergrenze
  10 000 Fotos je Mandant (statt 1500 je Filter).
- **Seitenleiste:** Das Dokument-Studio steht unter *Konfiguration* statt unter *Arbeiten*
  (sichtbar ab Schreibrecht).

### Behoben

- **Verlauf:** Aktionen mit mehreren Punkten (z. B. `backup.restore.create`) wurden falsch benannt.
- **Foto-Analyse:** Der Foto-Worker konnte seit Migration `0134` keine Dateien mehr laden
  (`permission denied for table submission_assignment`), die Gesichtsanalyse fiel aus. Korrigiert
  in Migration `0142`.

### Sicherheit (Security-Audit release/1.2.0 vom 2026-10-17)

- **Mandantenimport:** Album-Freigaben und Vertrauensbeziehungen zu anderen Mandanten werden
  nicht mehr aus dem Archiv übernommen. Eigene Alben gehen als neue Einladung an den Partner
  (Zustimmung erneut nötig), Freigaben fremder Alben fallen weg (Warnung beim Import).
- **Album-Freigaben, öffentliche Links:** zwei Schalter je Freigabe (Migration `0130`, beide
  standardmässig an): der Besitzer legt fest, ob der Partner das Album öffentlich verlinken darf,
  der Partner, ob seine Fotos in öffentlichen Links erscheinen. Öffentliche Links geben den
  Standort eines Fotos nur weiter, wenn der anlegende Mandant ihn auch intern sehen darf.
- Tags von Partner-Fotos aus geteilten Alben sind nicht mehr änderbar; Album-Einladungen sind
  auf 30 pro Stunde und Mandant begrenzt.
- **Custom-Domains:** eindeutig ist nur noch eine aktive Domain (Migration `0129`); eine
  unbestätigte Domain eines anderen Mandanten blockiert nicht mehr.
- Schreibende API-Requests mit fremdem `Origin` werden abgelehnt (CSRF-Schutz zusätzlich zu
  `SameSite=Lax`); offene Collaboration-WebSockets prüfen Session und Protokollrecht alle 30 s.
- Löscht ein Admin den MFA-Faktor eines anderen Kontos, enden dessen Sessions. Passkey-
  Registrierung prüft gegen die konfigurierte Domain (neu: `TRAEFIK_ADMIN_DOMAIN` im Backend).
- Abgabebox: Nonce-CSP statt `script-src 'unsafe-inline'`; die Ähnlichkeitswarnung vergleicht nur
  noch mit Bildern derselben Abgabe. Traefik setzt `Permissions-Policy`, Next.js kein
  `X-Powered-By` mehr. Fotoworker lädt nur Dateien des Job-Mandanten.
- Abhängigkeiten: PyJWT 2.15.1, Next.js 16.4.2, sharp 0.35.5, Tiptap 3 (inkl. tiptap-markdown 0.9).
- **Todos:** jedes Todo gehört fest seinem Mandanten (Migration `0131`, `protocol_todo.tenant_id`
  Pflicht); bei Todos in Protokollen setzt die Datenbank den Wert aus dem Protokoll. Behebt, dass
  Mandanten-Export und -Klon Todos aus Protokollen nicht mitnahmen. Todos ohne jeden Bezug (in
  keiner Ansicht erreichbar) werden bei der Migration entfernt.
- **Row-Level-Security** (Migration `0132`): PostgreSQL prüft die Mandantentrennung jetzt
  zusätzlich zum Code. Angemeldete Mandanten-Anfragen sehen und ändern nur Zeilen ihres Mandanten,
  auch wenn einer Abfrage der Filter fehlt; Ausnahmen sind die Daten gemeinsamer Fotoalben.
  Plattform-Admin, Hintergrundjobs, Worker und öffentliche Links bleiben unbeschränkt.
  Zugriffe auf fremde Datensätze antworten dadurch teils mit 404 statt 403.
- **Abgabebox unter RLS** (Migration `0133`): die öffentliche DB-Rolle sieht ohne Upload-Link
  nichts mehr und mit Link nur dessen Mandanten; gebunden wird das geheime Token, nicht die
  Mandanten-ID. Von `stored_file` liest sie nur noch Prüfsummen (keine Namen, Pfade, GPS-Daten).
- **Domain-Bridge:** das Einmal-Token steht im URL-Fragment statt in der Query und geht nur im
  Request-Body ans Backend (`POST /api/auth/bridge/preview`); Einlösen prüft zusätzlich
  `login_enabled` und eine seither erfolgte Session-Beendigung.
- **Lokales S3:** RPC und Admin-API von Garage nur noch auf `127.0.0.1`; `storage-init` teilt den
  Netz-Namespace von `local-s3`.
- **Datenbank-Performance:** Protokoll-, Todo- und Albenliste laden zugehörige Daten gesammelt statt
  je Eintrag (20 Einträge: 44 → 6, 41 → 4, 66 → 10 Abfragen; Session-Cache für public_ids, Tests
  gegen N+1). Migration `0135`: Indizes für 43 Fremdschlüssel (schnelleres Löschen von Konten und
  Mandanten, Abfragen je Zyklus/Abgabe/Vorlage) und Timeouts für die Laufzeitrollen (Abgabebox und
  Fotoworker erstmals mit statement_timeout, alle mit idle_in_transaction_session_timeout).
- **RLS für Untertabellen** (Migration `0134`): Mandantendaten ohne eigene `tenant_id`
  (Traktanden, Blöcke, Texte, Listeneinträge, Buchungen, Bussen, Vorlagen-Elemente, Album-Einträge,
  Dokumentversionen …) sind jetzt über ihre Elterntabelle geschützt; MFA-Faktoren nur im eigenen
  Mandanten.
- **Sicherheitsregeln für Menschen und AI-Agents:** `SECURITY-RULES.md` (über `CLAUDE.md` für alle
  Agents verbindlich, auch Gemini/Tabnine), `scripts/check-security-rules.py` meldet neu
  eingeführte Verstösse (ungescopte Lookups, SQL-f-Strings, `HTTPException` ohne `from exc`,
  Secrets in URLs, `dangerouslySetInnerHTML`) als Claude-Code-Hook, im Pre-Commit und in der CI
  (`security-lint`); Review-Agent `security-reviewer`.
- **Systemstatus, lokales S3:** neuer Eintrag „Lokales S3 (Garage)“ mit Bedarf (aktiver Speicher,
  Migration, Rückfallfrist, nicht benötigt …), Objektanzahl und belegten GB. Ein vom
  Storage-Controller gestopptes Garage gilt nicht mehr als Ausfall (vorher roter Container und
  ntfy-Alarm, sobald die Dateien bei einem anderen Anbieter liegen).
- **Mandanten-Exporte verschlüsselt:** ohne Passwort mit dem Server-Schlüssel (nur auf diesem
  Server importierbar), mit Passwort auch auf einem anderen Server. Neues Secret
  `EXPORT_ENCRYPTION_KEY`, das `deploy.sh` einmalig erzeugt; zusammen mit `.env` sichern. Ältere
  `.zip`-Exporte bleiben importierbar. Der Export-Endpunkt ist jetzt `POST`.
- **CI/Release:** `pip-audit` und `npm audit` (ab HIGH) blockieren; neue `public_id`-Lookups ohne
  `tenant_id=` blockieren Pull-Requests (Semgrep); Trivy-Scan vor jeder Image-Promotion und
  wöchentlich für die `latest`-Images.

### Korrekturen (Feature-Recovery-Audit v1.2)

- **Live-Photo-Videos nach ClamAV-Ausfall:** Der Nachscan (`upload_pipeline_rescan`) erfasst
  jetzt auch das Video eines Live Photos. Vorher blieb ein Clip, der beim Upload nicht geprüft
  werden konnte, dauerhaft `pending` und war nie abspielbar; betroffene Clips werden beim
  nächsten Lauf automatisch nachgeprüft.
- **Protokollkopf:** zeigt wieder Erstellungsdatum und Vorlagenversion des Protokolls (seit der
  neuen Ansicht für abgeschlossene Protokolle nirgends mehr sichtbar).
- Ungenutzte Komponente `SnapshotSwitcher` samt Texten entfernt.
- **Manuelles Speicherkontingent vollständig entfernt** (Migration `0136`): Der API-Endpunkt
  `PATCH /api/admin/tenants/{id}/storage-quota` und das Feld `storage_quota_manual_override`
  entfallen; das Kontingent ergibt sich nur noch aus Plan + Zusatzpaketen. Mandanten mit einem
  per API gesetzten Sonderwert (auch eine Einschränkung, die 0088 stehen liess) bekommen beim
  Update wieder Plan + Pakete; IDs und alte Werte stehen im Migrationslog.
- **Bussentarif je Protokollvorlage** (Migration `0137`): Im Vorlagen-Editor (Button
  «Bussentarif», nur mit Finanzen) kann eine Vorlage statt des Mandantentarifs eigene Beträge und
  ein eigenes Konto haben. Der Tarif gilt sofort für alle offenen Protokolle der Vorlage; bereits
  erfasste Bussen behalten ihren Betrag. Duplizieren, Klonen und Export/Import nehmen ihn mit.
  Ersetzt die Tarife je Anwesenheitsblock, die mit `0113` weggefallen waren.
- **Todos zu Abgaben entstehen automatisch:** beim Anlegen und Ändern einer Abgabe mit
  Verantwortlichen, bei Terminen mit passendem Tag und bei neuen/geänderten Listeneinträgen.
  Vorher bekamen Listen-Abgaben nie Todos und bestehende Termine erst nach einer Bearbeitung;
  Fehler beim Abgleich wurden verschluckt und landen jetzt im Fehlerprotokoll. Der nie
  angebundene Endpunkt `POST /api/submission-assignments/{id}/sync-todos` entfällt.
- **Adminportal «Dokumentvorlagen»** (`/admin/document-templates`): mitgelieferte Vorlagen des
  Document Studio ansehen, je Dokumentart den Plattform-Standard setzen, Vorlagen archivieren
  oder wieder anbieten (die Routen gab es schon, die Oberfläche fehlte).
- Entfernt, ohne Oberfläche: `GET /api/tools/word-import/quality-stats` (das Lernen der
  Schwellwerte im Word-Import bleibt) und `POST/GET /api/files/analysis-jobs` (die Fotoanalyse
  läuft automatisch nachts, `photo_analysis_auto_queue`).

### Abstimmung beim Zusammenführen (Release 1.2.0)

- Document Studio liest und schreibt Assets und erzeugte PDFs über den Objektspeicher (vorher
  direkt im Dateisystem - nach einer S3-Migration wären Logos, Schriften und PDFs verloren
  gewesen); Protokollbilder im PDF ebenso.
- Storage-Migration und `storage_verify` prüfen die Referenzen des Document Studio
  (`document_asset`) statt der entfallenen TeX-Vorlagen-Bauteile.
- Der Backup-Hold sichert auch noch nicht gelöschte Tombstones (Migration
  `0123_backup_hold_tombstones`) - sonst hätte der Purge-Job während eines Backups Inhalte
  gelöscht, die das Backup noch braucht.
- Downloads mit Standortschutz und Exportfassung (Bild-Metadaten) laufen über den
  Objektspeicher; Mandanten-Restore aus Borg prüft importierte Register-Einträge wie der
  ZIP-Import.
- `deploy.sh`: Rollback stoppt bzw. startet die Worker mit Backend-Image passend zum vorherigen
  Release; Smoke-Checks für `document-worker` und `storage-worker`.
- Migration `0118_docmgmt_storage_purge` ist ein No-op (doppelte Einführung desselben Verfahrens,
  die Fassung aus `0118_storage_purge_after_commit` behält die Rollenbindung der Abgabebox).

### Neu und geändert aus main (Audit-Reparatur seit 1.1.13)

- **Bussen:** mitgeführte Bussen mit Pflichtbegründung löschen (Soft-Delete, Anzeige im
  Protokoll, rückgängig solange offen), doppelte Bussen beim Update zusammengeführt und per
  Unique-Index ausgeschlossen, CHECK auf Status und Typ, offene Bussen aus abgeschlossenen
  Protokollen einkassierbar, Bussen-Buchungen und Konten mit Historie geschützt, Statistik je
  Währung.
- **Elemente:** einheitliches Konfigurationsschema, ein Block-Editor für Anlegen und Bearbeiten,
  gemeinsamer Terminfilter, zentraler Bussentarif, fehlende Optionen je Elementtyp.
- **Sicherheit:** Login-Sperre pro Konto und Quell-IP (Traefik als Trusted Proxy), Domain-Wechsel
  erst nach Bestätigung auf der Ziel-Domain, Nonce-CSP statt `unsafe-inline`, OIDC-state an den
  startenden Browser gebunden, Admin-SSO nur mit bestätigter E-Mail, Multipart nur mit
  signierter Session und Grössenlimit, localhost-Origins nur ausserhalb der Produktion,
  Profilbilder validiert und neu kodiert.
- **Betrieb:** Traefik liest Docker nur über einen Socket-Proxy, Lese-/Schreib-Timeouts 1 h,
  Body- und Inflight-Grenzen je IP; Redis mit Passwort; Images per Digest und Actions per SHA
  gepinnt (Dependabot); shellcheck in der CI.
- Zahlreiche Korrekturen in Uploads, Thumbnails, Mandanten-Import/-Klon, Autosave,
  Offline-Outbox, Kollaboration und Oberfläche (siehe Git-Historie).

### Betrieb

- Prod lief bisher mit `HOCX_ENVIRONMENT=prod` und damit für das Backend nicht als
  Produktion (offenes `/docs`/`/openapi.json`, Demo-Daten- und Konfigurationssperren aus).
  `deploy.sh` schreibt jetzt `production`, migriert eine bestehende `.env` beim nächsten
  Deploy automatisch (`prod` → `production`, Sicherung als `.env.bak-*`) und
  `verify_release.sh` prüft den Produktionsmodus. Backend und Frontend akzeptieren `prod`
  weiterhin als Alias.
- Neues `scripts/restore_db.sh` für das Zurückspielen eines Dumps (stoppt die DB-Dienste,
  sichert den aktuellen Stand, legt die DB neu an, spielt mit `ON_ERROR_STOP` in einer
  Transaktion ein). Die bisherige RUNBOOK-Anleitung (`gunzip | psql` in die laufende DB) ist
  ersetzt.
- `backup_db.sh`, `restore_db.sh` und `run_job.sh` verwenden explizit Compose-Projekt und
  -Dateien je Host-Markierung; ohne Markierung gilt `HOCX_COMPOSE_PROJECT` (Default `hocx`,
  für eine über `dev.sh` betriebene Instanz `hocx-dev`). `backup_db.sh` läuft jetzt auch auf
  Hosts ohne Markierung und meldet eine fehlgeschlagene Offsite-Kopie als Fehler.
- `deploy.sh` behält nur die neuesten 10 Pre-Deploy-Dumps (`PRE_DEPLOY_BACKUP_KEEP`) und nimmt
  auf Prod nur noch Release-Tags (`vX.Y.Z`) als `HOCX_VERSION`.
- Der Env-Loader von `deploy.sh` liest unquotierte Werte mit Inline-Kommentar und Escapes in
  doppelt quotierten Werten jetzt wie Compose.
- Redis hängt nur noch im internen Netz `cache` zwischen Backend und Redis.
- `docker-compose.dev.yml` setzt den Projektnamen fest auf `hocx-dev`. Wer den Dev-Stack bisher
  ohne `-p` gestartet hat, bekommt dadurch neue (leere) Dev-Volumes.
- `docker-compose.yml`: `HOCX_ENVIRONMENT` ist per `.env` steuerbar (Default `development`);
  `.env.example` setzt `ABGABEBOX_ENVIRONMENT` nicht mehr. Bestehende `.env`-Dateien einer
  Server-Instanz mit `ABGABEBOX_ENVIRONMENT=development` sollten den Eintrag entfernen.
- Basis-Stack nutzt Traefik v3.6.1 wie der Release-Stack.

## [1.1.13] - 2026-10-13

Feature-Release auf 1.1.12: Offene Protokolle lassen sich nach Änderungen an der Vorlage
neu aufbauen, ohne erfasste Daten zu verlieren; Terminlisten in Matrizen filtern nach
Zyklus und Protokolldatum. Keine Migration, keine neuen Umgebungsvariablen.

### Update von 1.1.12 auf 1.1.13

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.13` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.
Keine weiteren Schritte nötig.

### Neu

- Protokollliste: «Elemente aus Vorlage neu laden» im Drei-Punkte-Menü nicht
  abgeschlossener Protokolle. Übernimmt neue und entfernte Elemente, Titel, Beschreibungen,
  Vorgabetexte, Filter (z. B. Tag-Filter wiederholter Termin-Blöcke), Formularzeilen,
  Matrix-Zeilen/-Spalten und weitere Einstellungen aus der aktuellen Vorlage. Erfasste
  Texte, Todos, Bilder, Formular- und Matrixwerte, Anwesenheiten und ausgeblendete Blöcke
  bleiben erhalten; unveränderte Vorgabetexte folgen der Vorlage. Elemente und Blöcke, die
  nicht mehr in der Vorlage sind, werden nur entfernt, wenn sie leer sind, sonst bleiben
  sie am Ende stehen. Vor dem Anwenden zeigt eine Rückfrage, was sich ändert; offene
  Editoren desselben Protokolls laden danach neu.
- API: `POST /api/protocols/{id}/sync-template` (mit `?dry_run=true` nur Vorschau).
- Matrix-Designer: Terminlisten-Zeilen lassen sich auf einen Zyklus relativ zum
  Protokolldatum (aktueller, vorheriger, … Zyklus) und auf Termine vor dem Protokolldatum
  einschränken. Matrix-Zelle und PDF-Export filtern gleich; bestehende Einstellungen «Nur
  im aktuellen Zyklus» gelten als aktueller Zyklus.

## [1.1.12] - 2026-10-12

Feature- und Bugfix-Release auf 1.1.11 mit neu gestaltetem Matrix-Designer, Zyklus-Filter
für automatische Termin-Spalten, Todos, die nach dem Protokollabschluss bearbeitbar bleiben,
und mehreren Korrekturen am PDF-Export. Enthält die Migration `0112`; sie läuft beim Deploy
automatisch und ist umkehrbar. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.11 auf 1.1.12

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.12` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0112` ergänzt `protocol.todos_snapshot_json` (Todo-Stand beim Abschluss).
  Bereits abgeschlossene Protokolle haben keine Momentaufnahme und zeigen weiterhin den
  aktuellen Stand ihrer Todos, bis sie erneut abgeschlossen werden.
- Optional: `HOCX_APP_URL` (z. B. `https://app.hocx.ch`) bestimmt das Ziel von «Anmelden»
  auf der Website. Leer oder nicht gesetzt gilt weiterhin `https://${TRAEFIK_DOMAIN}`.

### Neu

- Todos bleiben nach dem Abschluss ihres Protokolls bearbeitbar: ändern, erledigen,
  löschen und neu anlegen (ohne Änderungsverfolgung). Beim Abschliessen wird der Stand
  aller Todos, inklusive offener Todos aus früheren Protokollen, als Momentaufnahme
  eingefroren; Ansicht und PDF-Export des abgeschlossenen Protokolls zeigen diesen Stand.
  Zurücksetzen verwirft die Momentaufnahme nach einer Warnung.
- Matrix-Designer: Automatische Termin-Spalten lassen sich auf einen Zyklus einschränken
  (aktueller, vorheriger, … Zyklus relativ zum Protokolldatum). Der Tag-Filter
  automatischer Termin-Spalten akzeptiert mehrere Tags.
- Website: Sprachumschalter im Header; «Anmelden» zeigt auf `HOCX_APP_URL`.

### Geändert

- Matrix-Designer neu gestaltet: Einstellungsleiste für Spaltenquelle, Raster mit
  nummerierten Zeilen und Spaltenköpfen, Inspektor für Zeile oder Spalte, Abbrechen
  verwirft alle Änderungen seit dem Öffnen.
- Abgeschlossene Protokolle öffnen im selben Dokument-Layout wie der Protokolleditor
  (schreibgeschützt); die alte Einzelabschnitt-Ansicht entfällt.
- Stammlisten: Einzel-Teilnehmer erscheinen als Chip mit Initialen wie bei
  Mehrfach-Teilnehmern.
- Abgabe-Detail: Termin bzw. Listeneintrag als Titel, verantwortliche Person in der
  Metazeile.
- Todo-Dialog: Verantwortliche als Mehrfachauswahl; die Herkunft aus einem Aufgabenpaket
  steht im Dialog statt als Badge in der Todo-Liste.
- Aufgabenpakete: Button «Aus Liste» statt «Ämtli aus Liste».
- Website: Hinweis «Hosting in der Schweiz» aus dem Hero entfernt.

### Behoben

- Todo bearbeiten ersetzte mehrere Verantwortliche (z. B. aus einem Aufgabenpaket) durch
  eine einzige Person.
- PDF-Export zeigte andere Termine als der Protokolleditor: Der Editor lud nur die
  neuesten 100 Termine, der Export enthielt «Nächster Hock»-Platzhalter, und
  Terminlisten-Zeilen in Matrizen filterten anders als im Editor.
- Termine «Nur im aktuellen Zyklus» funktionierten nicht, weil die Zyklus-Zuordnungen in
  der Termin-Antwort fehlten.
- PDF-Export: Kleine Bilder wurden auf Textbreite hochskaliert und unscharf;
  Bildunterschriften erschienen als «Figure 1: *».
- Protokollsuche: Treffer im Titel stehen vor Treffern im Inhalt.
- Termine: Tag-Zeilen in der Seitenleiste waren zu hoch, der Stern ragte über den Rand.
- Sidebar: Eine lange Copyright-Zeile schnitt Identitätskarte und Footer ab.
- Website: Ein leeres `HOCX_APP_URL` führte nicht auf `TRAEFIK_DOMAIN` zurück.

## [1.1.11] - 2026-10-12

Feature-Release auf 1.1.10 mit Aufgabenpaketen für wiederkehrende Todos, mehreren
Verantwortlichen pro Todo, einem überarbeiteten Dashboard, einem neu gestalteten
Stammlisten-Block im Protokoll und einem Redesign der Abgabebox. Enthält die Migrationen
`0110` und `0111`; sie laufen beim Deploy automatisch und sind umkehrbar. Keine neuen
Pflicht-Umgebungsvariablen.

### Update von 1.1.10 auf 1.1.11

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.11` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0110` legt `user_protocol_template_preference` an (zuletzt gewählte
  Protokollvorlage pro Benutzer und Mandant).
- Migration `0111` legt die Tabellen für Aufgabenpakete (`task_package`,
  `task_package_cycle`, `task_package_item`) und mehrere Verantwortliche pro Todo
  (`protocol_todo_assignee`) an. Bestehende Todos behalten ihren Verantwortlichen.
- Neuer täglicher Job `task_package_rollover`, erscheint automatisch unter `/admin/jobs`.
- Ist `TRAEFIK_WEBSITE_DOMAIN` gesetzt, prüft `verify_release.sh` nach dem Deploy, dass die
  Website-Domain die Landing Page ausliefert. Optional einen zweiten Uptime-Kuma-Monitor für
  die Website-Domain anlegen (RUNBOOK).

### Neu

- **Aufgabenpakete** (Vorlagen → Aufgabenpakete): Pakete wie «Sommerlager» oder
  «Scharleitung» bündeln wiederkehrende Aufgaben und werden einem oder mehreren Zyklen
  zugewiesen. Für den laufenden Zyklus entstehen daraus automatisch Todos – einmal pro
  Zyklus, monatlich, wöchentlich oder pro Termin mit einem bestimmten Tag, mit fester oder
  relativer Fälligkeit. Verantwortliche kommen wie im Protokoll aus Listenzeilen (z. B. der
  Ämtliliste): alle Personen eines Ämtlis werden gemeinsam einer Aufgabe zugewiesen. Ändert
  sich die Liste oder das Paket, werden offene Aufgaben des laufenden Zyklus angepasst;
  vergangene Zyklen, erledigte Aufgaben und von Hand geänderte Felder bleiben unverändert.
  Beim Löschen eines Pakets oder einer Zyklus-Zuweisung wird gefragt, ob alle, nur künftige
  oder keine Aufgaben gelöscht werden. Neuer täglicher Job `task_package_rollover`
  (`/admin/jobs`) legt beim Zykluswechsel die Aufgaben des neuen Zyklus an.
- Todos können mehrere Verantwortliche haben; «Meine Todos», Kalender-Abo, Export und
  Mandanten-Export/-Import berücksichtigen alle. Migration `0111_task_packages`.
- Termine: Tags lassen sich mit einem Stern als wichtig markieren. Sie stehen in der
  Seitenleiste direkt unter «Alle Termine», mobil zuvorderst in der Tag-Leiste.
- Neue Protokolle merken sich die zuletzt gewählte Vorlage pro Benutzer; die
  Namensvorschau zeigt den tatsächlich entstehenden Protokollnamen (Migration `0110`).
- Dashboard: Kontostände (Kassier/Admin) und Abgaben mit Frist (Schreiber/Admin mit
  Abgabebox) als neue Kacheln.
- Preiskatalog: Ungenutzte Speicherpakete lassen sich löschen.

### Geändert

- Dashboard: Desktop und Mobile nutzen dieselben Daten und rollenbasierten Kacheln. Am
  Desktop neu mit Begrüssung, «Meine Todos» (eigene und überfällige), kommenden Terminen
  und Statistik. Offene Bussen erscheinen nur mit gebuchtem Finanzmodul, Leser sehen ihre
  eigenen offenen Bussen.
- Stammlisten-Tabellenblock im Protokoll neu gestaltet: Personen als Chips mit Initialen,
  Besetzungsgrad, Filter Alle/Offen/Geändert, Änderungsfarben nur bei aktiver
  Änderungsverfolgung. «Leere Zeilen hervorheben» ist pro Block im Template einstellbar;
  Gruppieren/Sortieren kommt aus dem Template statt aus dem Protokolleditor.
- Abgabebox neu gestaltet (Desktop und Mobile): Seitenleiste bzw. Kopfzeile mit
  Schrittanzeige, Abgaben als Karten, Upload mit Dropzone und Sicherheitsprüfung als
  Statuskarte, Erfolgsansicht mit Quittung.
- Aufgabenpaket-Dialog vereinfacht: Verantwortliche als ein Feld mit Chips, Wiederholung
  und Fälligkeit als Segment-Auswahl.
- Teilnehmerfilter: «Aktiv» steht zuerst und ist standardmässig ausgewählt.
- Platform-Admin: Kontoeinstellungen sind ins Profilmenü umgezogen.
- Footer: Versionsanzeige kompakter, Test- und Entwicklungsumgebungen mit Badge.

### Behoben

- Beim Tippen im Protokolltext erschien eine falsche Konflikt-Meldung, und der getippte
  Text wurde durch den Serverstand ersetzt, obwohl niemand sonst bearbeitete.
- Mobile: iOS zoomte beim Fokus ins Login-Formular, Doppeltipp zoomte ungewollt.
- Word-Import: Nach mehreren Importen scheiterte ein gültiges Dokument gelegentlich mit
  «Datei konnte nicht gelesen werden: XMLSyntaxError». Ein solcher Fehler wird jetzt
  einmal in einem frischen Parser-Prozess wiederholt.
- Dashboard: Summe und Personenzahl offener Bussen brachen nach 50 Einträgen ab.
- `deploy.sh` brach mit «Nicht erlaubte Variable TRAEFIK_WEBSITE_DOMAIN» ab, sobald die mit
  1.1.10 eingeführten Variablen `TRAEFIK_WEBSITE_DOMAIN` oder `WEBSITE_CONTACT_EMAIL` (oder
  `ABGABEBOX_ENVIRONMENT`) in der `.env` gesetzt waren. Ein Test stellt jetzt sicher, dass
  jede Variable aus `.env.example` von den Deploy-Skripten akzeptiert wird.

## [1.1.10] - 2026-10-11

Feature-Release auf 1.1.9 mit einer vollständigen Mobile-Oberfläche, Kalender-Abos für
Termine und Todos, einer öffentlichen Landing Page mit Preisen aus dem Katalog,
Systemstatus, Job-Übersicht und ntfy-Benachrichtigungen im Platform-Admin, einer
gemeinsamen Identität für Teilnehmer und Benutzer sowie einem vollständigen
Mandanten-Backup per Export/Import. Enthält die Migrationen `0102` bis `0109`; sie laufen
beim Deploy automatisch. **Migration `0108` ist nicht umkehrbar** (siehe unten). Keine
neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.9 auf 1.1.10

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.10` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- **Backup vor dem Update:** Migration `0108` führt Teilnehmer und Benutzerkonten zu einer
  Identität zusammen und entfernt die Tabelle `participant`. Ein Downgrade ist nicht
  möglich; zurück geht es nur mit dem Datenbank-Backup von vor dem Update. `deploy.sh`
  legt dieses Backup automatisch unter `backups/*-pre-v1.1.10.sql.gz` an – vor dem
  Weitermachen prüfen, dass die Datei existiert und nicht leer ist.
- Migration `0108` übernimmt alle Teilnehmer-Verweise (Vorlagen, Todos, Bussen,
  Termin-Rollen, Anwesenheit, Listen, Verantwortliche, Word-Import-Entwürfe) auf die
  bestehende Benutzer-ID. Unverknüpfte Teilnehmer erhalten ein Konto ohne Login,
  Schattenkonten verlieren ihre Platzhalter-E-Mail und ihr Passwort. Login-E-Mails werden
  kleingeschrieben und müssen danach eindeutig sein: Gibt es zwei Konten, deren E-Mail sich
  nur in Gross-/Kleinschreibung unterscheidet, bricht die Migration ab – vorher prüfen mit
  `SELECT lower(trim(email)), count(*) FROM app_user GROUP BY 1 HAVING count(*) > 1;`
- Migration `0109` gibt dem Abgabebox-Dienst Lesezugriff auf die Namensspalten von
  `app_user` (ohne E-Mail und Kontodaten), damit Abgaben mit Teilnehmer-Elementen nach
  `0108` weiter funktionieren.
- Migrationen `0105` und `0107` legen die Tabellen für Job-Übersicht, Systemstatus und
  Benachrichtigungen an, `0106` ergänzt `storage_package.is_bookable` (bestehende Pakete
  bleiben buchbar).
- Migration `0102` legt die Tabelle `calendar_feed` an (Kalender-Abos). Tokens werden
  nur als SHA-256-Hash und Fernet-verschlüsselt mit `ADMIN_AUTH_SECRET` gespeichert.
- Migration `0103` ergänzt `plan.is_featured` und markiert den Plan `standard` als
  «Beliebteste Wahl». Fehlt dieser Plan, bleibt keiner markiert.
- Migration `0104` ergänzt `tenant.show_on_website`. Standard ist «nicht gelistet»;
  kein Verein erscheint ohne Freigabe im Adminportal auf der Website.
- Neue optionale Variablen `TRAEFIK_WEBSITE_DOMAIN` (Domain der Landing Page, z. B. die
  Hauptdomain) und `WEBSITE_CONTACT_EMAIL` (mailto-Ziel der Demo-/Kontakt-Buttons).
  Leer bleibt die Website deaktiviert, und Traefik fordert kein Zertifikat für sie an.
  Für eine eigene Website-Domain muss deren DNS auf den Server zeigen, damit Traefik ein
  Zertifikat beziehen kann.
- Neuer Container `docker-socket-proxy` (nur lesender Zugriff auf die Docker-API, im
  internen Netz `docker-api`, nur für das Backend erreichbar). Er bindet
  `/var/run/docker.sock` read-only ein; `deploy.sh` startet ihn automatisch mit.
- Der Virenscanner sucht jetzt alle zwei Stunden nach neuen Signaturen
  (`FRESHCLAM_CHECKS=12` in den Compose-Dateien), keine Aktion nötig.
- Optional nach dem Update: ntfy unter `/admin/notifications` einrichten, Host-Cronjobs
  (Backup, Speicher-Aufräumen) über `scripts/run_job.sh` starten und den Statusendpunkt in
  Uptime Kuma eintragen (RUNBOOK Abschnitt 10 und 12).
- Exportformat 4: Alte Archive (Format 2/3) bleiben importierbar. Archive ab 1.1.10
  enthalten Zugangsdaten und sind wie ein Datenbank-Dump aufzubewahren.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Mobile-Oberfläche: Bis 900 px zeigen dieselben URLs eine eigene Mobile-Ansicht mit
  Tableiste (Übersicht, Termine, Todos, Mehr). Unter «Mehr» hat jeder Bereich der
  Desktop-Navigation eine eigene Ansicht, rollenabhängig gelistet. Der mobile
  Protokoll-Editor bearbeitet Text, Anwesenheit, Todos, Fotos, Notizen und Status mit
  Live-Abgleich und erzeugt PDFs. Dialoge erscheinen als Bottom-Sheet. Element-Editor,
  Dokument-Layouts und Import verweisen auf den Computer.
- Verknüpfungen (Benutzermenü): Termine (Schreiber/Admins) und Todos (alle Rollen, eigene
  oder alle sichtbaren) als abonnierbarer Kalender für Apple und Google. Optionen für
  erledigte Todos und «nur Titel und Datum»; URL neu erzeugen oder entfernen. Ein
  deaktivierter Benutzer, eine Rollenänderung oder «überall abmelden» wirkt sofort auf
  den Feed.
- Öffentliche Landing Page unter `TRAEFIK_WEBSITE_DOMAIN` mit Preiskarten direkt aus dem
  Preiskatalog (Monat/Jahr-Umschalter, Ersparnis). Im Admin-Preiskatalog lässt sich ein
  Plan als «Beliebteste Wahl» markieren, im Mandanten-Dialog ein Verein als Kunde unter
  «Im Einsatz bei» freigeben. Indexierung per `robots.txt` nur auf der Website-Domain.
- Toasts können eine Aktion tragen (z. B. «Rückgängig»).
- Platform-Admin: neue Seite „Jobs“ (`/admin/jobs`) mit allen periodischen Hintergrundjobs –
  Virenprüfung, Bildanalyse, Uploads, Aufräum- und Wartungsjobs – samt letztem Lauf, Dauer,
  Status (OK, läuft, fehlgeschlagen, überfällig, nie gelaufen), letzter Fehlermeldung und
  Verlauf. Der Bildanalyse-Worker wird über ein Lebenszeichen überwacht. Jobs, die sich melden,
  aber nicht registriert sind (z. B. künftige Host-Cronjobs), erscheinen unter „Weitere“.
- Platform-Admin: neue Seite „Systemstatus“ (`/admin/system`) mit allen Containern (Status,
  Healthcheck, Neustarts, CPU/RAM, Version) und den Diensten, von denen hocX abhängt (Datenbank,
  Redis, Virenscanner inkl. Alter der Signaturen, Speicherplatz, Fehlerrate, Rückstand der
  Virenprüfung, Bildanalyse-Warteschlange), offenen Problemen und Ereignisverlauf. Container-Daten
  kommen über einen neuen, nur lesenden `docker-socket-proxy` in einem internen Netz.
- Platform-Admin: Benachrichtigungen per ntfy (`/admin/notifications`), konfigurierbar mit
  Server, Topic, Token, Erinnerungsintervall und Testnachricht. Gemeldet werden neue (nach 90 s
  Karenzzeit), verschärfte, weiterhin offene und behobene Probleme sowie Container-Neustarts.
- Statusendpunkt `/api/system-status/summary` (per Token) für externe Überwachung, z. B. mit
  Uptime Kuma: HTTP 503 bei kritischen Problemen oder veraltetem Systemstatus.
- `scripts/run_job.sh`: Wrapper für Host-Cronjobs, meldet Läufe an die Job-Übersicht
  (Backup und Speicher-Aufräumen sind dort bereits registriert, siehe RUNBOOK Abschnitt 10/12).
- Todos: Fälligkeit per Schnellauswahl „Ende der Woche“, „Ende des Monats“ und „In zwei
  Wochen“ sowie mit frei wählbarem Datum – im Fälligkeitsmenü am Desktop und in der
  Mobile-Ansicht.

### Geändert

- Mandant-Einstellungen (Allgemein, Domains, Abo & Nutzung) haben eigene
  Mobile-Ansichten statt eingebetteter Desktop-Karten.
- Profil-Dialog: Sprachauswahl mit Chevron, «Protokollpunkte automatisch einklappen» als
  Karte mit Schalter.
- Abgabebox mobil: kein iOS-Zoom bei der Sprachauswahl, grössere Touch-Ziele, «Datei
  auswählen» statt Drag-and-drop-Hinweis auf Touch-Geräten, lange Titel brechen um.
- Teilnehmer und Benutzer verwenden einen gemeinsamen Datensatz. Die Oberfläche unterscheidet
  „Teilnehmer“ und „Teilnehmer mit Login“. E-Mail und Passwort sind nur für einen Login nötig;
  Kontaktadressen ohne Login dürfen mehrfach vorkommen. Nur Administratoren schalten Logins frei.
  Schattenkonten und Merge-Funktionen entfallen; Authentifizierungs-IDs bleiben erhalten.
- Exportformat 4 referenziert Teilnehmer über UUIDs statt E-Mail-Adressen. Alte Archive
  (Format 2/3) bleiben importierbar. Geklonte Teilnehmer erhalten keinen aktiven Login.
- Der Mandanten-Export ist jetzt ein vollständiges, mandantenspezifisches Backup: Er enthält
  zusätzlich Abgabebox-Links (mit Abgabe-Zuordnung), öffentliche Freigabe-Links,
  Kalender-Abos, gebuchte Features und Speicherpakete, Vertrauensbeziehungen und
  Album-Freigaben mit Partner-Mandanten. Tokens bleiben beim Import erhalten, damit verteilte
  URLs nach einem Restore weiter funktionieren; ist ein Token auf der Zielinstanz bereits
  vergeben, wird mit Warnung ein neuer erzeugt. Beziehungen zu anderen Mandanten werden nur
  wiederhergestellt, wenn der Partner auf der Zielinstanz existiert.
- **Sicherheit:** Export-Archive enthalten damit Zugangsdaten (Passwort-Hashes, MFA-Secrets,
  Link- und Abo-Tokens) und sind wie ein Datenbank-Dump aufzubewahren. Der Export-Dialog
  weist darauf hin.
- Adminportal: Katalog-Import-Dialog ist vor dem Laden einer Datei schmal und wird erst für
  die Vorschau breit; Badges der Plankarten im Preiskatalog brechen sauber um.

### Behoben

- Freigabeseite: «Alle herunterladen» schlug bei Alben ab etwa 20 Fotos mit einer
  fehlerhaften `download.json` fehl, weil die Vorschaubilder das gemeinsame Rate-Limit
  verbrauchten. Jede Endpunkt-Art hat jetzt einen eigenen Zähler; das
  Vorschaubild-Limit liegt bei 3000/min.
- Todos ohne Protokoll liessen sich nicht abhaken, bearbeiten oder löschen.
- Abgabebox: fehlende Gestaltung des Offline-Hinweises ergänzt.
- Der Quarantäne-Aufräumjob der Abgabebox und das Aufräumen alter Exporte im Backend teilten
  sich denselben Datenbank-Lock und haben sich dadurch gegenseitig Durchläufe weggenommen.
- Ein Hintergrund-Loop konnte dauerhaft und ohne jede Spur stehen bleiben, wenn schon das
  Holen seiner Datenbankverbindung fehlschlug (z. B. Pool-Timeout). Solche Fehler beenden jetzt
  nur den einzelnen Durchlauf. Ausserdem starten die Loops zeitversetzt, statt beim Hochfahren
  alle gleichzeitig um den Connection-Pool zu konkurrieren.
- Der Virenscanner konnte nach einem Neustart bis zu einem Tag mit veralteten Signaturen
  arbeiten, wenn das Signatur-Update genau beim Hochfahren lief. Er sucht jetzt alle zwei
  Stunden statt einmal täglich nach neuen Signaturen.
- Mandanten-Export/-Import als vollständiges Backup: Fotoalben (inkl. Best-of-Auswahl)
  und die Zyklus-Snapshots der Listen werden jetzt mitexportiert und wiederhergestellt.
- Import übernimmt die öffentlichen IDs (`public_id`), solange sie auf der Zielinstanz frei
  sind. URLs, Lesezeichen und per `public_id` gespeicherte Bezüge (Abgabe-Element von
  Galerie-Fotos, Upload-Protokoll und Todos, Album-Einträge, Entwürfe offener Word-Importe)
  bleiben so gültig; bei einer Kollision werden sie konsistent umgeschrieben.
- Import verknüpfte einige Daten weiterhin mit dem Quell-Mandanten bzw. brach auf einer
  frischen Instanz ab: Zyklus-Filter von Abgaben, Verantwortliche eines Protokolls,
  „Wiederholen aus Termin/Todo“-Blöcke sowie die gelernten Zuordnungen und Analysen des
  Word-Imports werden jetzt umgemappt. Verantwortliche und Wiederhol-Blöcke waren auch
  beim Mandanten-Klon betroffen.
- Ein auf der Zielinstanz unbekannter Preisplan bricht den Import nicht mehr ab, sondern
  wird mit Warnung weggelassen.
- Mandanten-Klon: Abgabe-Bezüge (`element_ref`) in Upload-Protokoll und Todos zeigen jetzt
  auf die geklonten Termine/Listeneinträge statt auf die des Quell-Mandanten.

## [1.1.9] - 2026-10-05

Feature- und Fix-Release auf 1.1.8 mit einem Zyklus-Filter in der Terminübersicht,
durchgehend automatischer Fotoanalyse, wiederhergestellten Kategorien in der
Blocktyp-Auswahl und einer Korrektur des PDF-Exports. Keine Migration, keine neuen
Pflicht-Umgebungsvariablen.

### Update von 1.1.8 auf 1.1.9

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.9` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Neue Standardwerte: `PHOTO_ANALYSIS_AUTO_QUEUE_START_HOUR=0`/`END_HOUR=24` (rund um
  die Uhr statt 01–06 Uhr UTC), `PHOTO_ANALYSIS_AUTO_QUEUE_INTERVAL_MINUTES`,
  `DOMAIN_HEALTH_CHECK_INTERVAL_MINUTES` und
  `ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES` je 5 statt 30 Minuten. Wer diese
  Variablen in `.env` explizit gesetzt hat, behält seine Werte; für das neue Verhalten
  die Einträge entfernen.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Terminübersicht: Zyklus-Filter. Standardmässig zeigt sie die aktuelle Periode aller
  Zyklen; im Ansicht-Menü lässt sich ein einzelner Zyklus wählen. Zur Periode gehören
  Termine, die zeitlich hineinfallen oder mit ihr verknüpft sind. Tags ohne Termine in
  der Auswahl verschwinden aus der Seitenleiste.

### Geändert

- Fotoanalyse läuft automatisch rund um die Uhr (Prüfung alle 5 Minuten); die
  Last-Bremse (`PHOTO_ANALYSIS_AUTO_QUEUE_MAX_LOAD_FACTOR`) bleibt. Der Button
  «Analyse starten» entfällt. Duplikate und Ähnliche sind wieder eigene Tabs.
- Domain-Health-Check und Quarantäne-Aufräumen der Abgabebox laufen alle 5 statt 30
  Minuten.
- Blocktyp-Auswahl wieder mit den Gruppen Basics, Finanzen und Organisation und einer
  Mini-Vorschau pro Karte; Sitzungsnotizen (#17) hat eine eigene Vorschau. Die
  #ID-Badges bleiben.
- Die Terminliste scrollt bei jedem Tag-, Zeit- oder Zykluswechsel zur «Heute»-Linie.
- Block-Konfiguration aufgeräumt; die Zyklusauswahl in Diagramm-Blöcken ist eine
  kompakte Pill-Gruppe.

### Behoben

- PDF-Export brach mit «invalid literal for int()» ab, wenn ein Block im Editor
  gewählte Teilnehmer oder Termine (öffentliche UUID) neben aus der Vorlage
  vorbefüllten (interne ID) enthielt. Export, Anwesenheit-Speichern sowie Mandant
  klonen/importieren lösen beide Formen jetzt auf; beim Klonen und Importieren gehen
  UUID-Referenzen in Block-Snapshots nicht mehr verloren.

## [1.1.8] - 2026-10-05

Feature-Release auf 1.1.7 mit einem neuen Blocktyp «Sitzungsnotizen», mehrtägigen
Terminen als Balken im Kalender, Datumsauswahl über die Terminübersicht und einer
Korrektur der Anwesenheitsauswahl. Enthält die Migration `0101`; sie läuft beim Deploy
automatisch. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.7 auf 1.1.8

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.8` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0101` legt den Blocktyp `session_notes` mit der festen id 17 an. Bestehende
  Vorlagen und Protokolle bleiben unverändert. Ist die id 17 oder der Code bereits
  anders belegt, bricht sie mit einer Meldung ab, statt zu raten.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Neuer Blocktyp «Sitzungsnotizen»: zeigt die freien Notizen aus dem Sitzungspanel als
  eigenen Block im Protokoll und im PDF-Export, ohne die Sitzungs-Todos. Der Block ist
  nur drin, wenn er in einer Vorlage hinzugefügt wird; bestehende Vorlagen und
  Protokolle bleiben unverändert. Im Protokoll ist er schreibgeschützt, geschrieben wird
  weiterhin im Sitzungspanel. Migration `0101` legt den Typ (id 17) an.
- Der Kalender-Button beim Sitzungsdatum öffnet die Terminübersicht; ein Klick auf einen
  Tag übernimmt das Datum («Nächster Hock»). In der Elementvorlage Sitzungsdatum legt
  ein Tag-Filter fest, welche Termine im Kalender erscheinen (leer = alle).

### Geändert

- Monatskalender in Wochenzeilen: mehrtägige Termine laufen als durchgehender Balken
  über ihre Tage, überlappende Termine bekommen eigene Zeilen, ab der vierten Zeile
  «+N weitere».
- Die Terminübersicht startet bei der «Heute»-Linie; vergangene Termine per
  Hochscrollen. Auf dem Desktop scrollt nur die Terminliste, Kopfzeile, Toolbar und
  Tag-Leiste bleiben stehen. Beginnt ein Monat mit dem ersten kommenden Termin, steht
  die «Heute»-Linie vor dessen Monatsüberschrift.
- Beim Öffnen eines Protokolls springt die Ansicht direkt zum zuletzt aktiven bzw.
  ersten Punkt, statt auf dem Leerraum über dem ersten Punkt stehenzubleiben.
- Fotogalerie: Kacheln wieder in der Grösse vor dem Umbau (automatische Spaltenzahl,
  ca. 180px breit, schmalerer Abstand) statt fester 4/3/2 Spalten; das
  Vergrössern-Icon auf den Kacheln entfällt.
- Dateityp-Icons in der Dateiliste sind kleiner.

### Behoben

- Die Anwesenheitsauswahl im Protokoll verschwand nach dem Klick sofort wieder, weil
  die Serverantwort die interne statt der öffentlichen Teilnehmer-ID enthielt. Dieselbe
  Ursache setzte die Anwesenheit beim Neuladen eines Protokolls auf «Unentschuldigt»
  zurück.

## [1.1.7] - 2026-10-05

Feature-Release auf 1.1.6 mit zyklusbasierter Protokoll-Gruppierung, automatischem
Abgabe-Abschluss und einer neu gestalteten, metadatensensiblen Freigabeseite. Enthält
die Migration `0100`; sie läuft beim Deploy automatisch. Keine neuen Pflicht-
Umgebungsvariablen.

### Update von 1.1.6 auf 1.1.7

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.7` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0100` ergänzt `share_link.share_location`/`share_capture_date`/
  `share_camera` und setzt für bestehende Links dieselbe Vorgabe wie für neue: nur das
  Aufnahmedatum geht mit, Standort (GPS) und Kamera/Gerät nicht. Bisher gingen bei
  öffentlichen Freigaben alle Metadaten ungefiltert raus; wer bei bestehenden Links
  bewusst mehr mitgeben möchte, stellt das pro Link in den Freigabe-Einstellungen um.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- Die Protokoll-Liste gruppiert nach Zyklus statt einer einzigen flachen Liste: der
  aktuelle Zyklus und der unmittelbar vorherige stehen offen, ältere Zyklen stehen
  hinter «Ältere Zyklen anzeigen». Vorlagen ohne Zyklus gruppieren nach Kalenderjahr.
  Suchen/Filtern zeigt alle Treffer unabhängig vom Einklapp-Zustand.
- Diagramm-Blöcke im Protokoll können einen Zyklus relativ zum Protokolldatum wählen
  (aktueller, vorheriger, …) statt einen fest einprogrammierten Zyklus-Schlüssel –
  dieselbe Zyklus-Offset-Auswahl wie bei Abgaben.
- Abgaben können Elemente automatisch schliessen: nie, nach der ersten Abgabe oder
  sobald die maximale Dateizahl erreicht ist. «Wieder aufschalten» funktioniert
  unverändert.
- Dateien/Fotos-Tabelle zeigt ein Dateityp-Icon nach Dateiendung statt eines generischen
  Platzhalters.
- Beim Erstellen eines Freigabe-Links wählbar, welche Foto-Metadaten mitgehen: Standort
  (GPS), Aufnahmedatum, Kamera & Gerät – Vorgabe nur das Aufnahmedatum. Enthält Migration
  `0100`, die diese Vorgabe auch auf bestehende Links setzt.
- Die öffentliche Freigabeseite (`/share/<token>`) ist ohne Login erreichbar (der Token
  bleibt die einzige Authentifizierung) und neu gestaltet: Absender-Kopfzeile, Meta-Zeile
  (Anzahl, Grösse, Aufnahmezeitraum, Ablaufdatum), Masonry-Raster, Lightbox mit Blättern.
  «Alle herunterladen» liefert ein ZIP, im Auswahlmodus nur die gewählten Dateien.

### Geändert

- Terminliste, Kalender und der Termin-Dialog im neuen Design: Tag-Sidebar mit Zählern,
  Monatsgruppen mit Datumskachel und Heute-Linie, Zeitfilter Kommend/Alle/Vergangen,
  Ansicht-Menü für die Zeilenfelder (pro Browser gespeichert); Kalender als
  Vollbild-Dialog mit Tagesdetail; neuer Termin zweispaltig mit Zeitraum,
  Personen-Rollen, Tag-Chips und Zyklen.
- Transaktionsformular der Finanzen mit expliziter Einnahme-/Ausgabe-Auswahl statt
  Vorzeichen-Eingabe über den Betrag.
- Fotogalerie mit haftender Auswahlleiste und kompakteren Aktionen.

### Behoben

- Ein zweiter, schnell aufeinanderfolgender Klick in der Anwesenheitskontrolle (eine
  Person schnell durchklickend, oder zwei Personen nehmen gemeinsam Anwesenheit auf)
  überschreibt nicht mehr stillschweigend den gerade gespeicherten Status der anderen
  Person; betraf auch die Entschuldigen-Aktion im Dashboard.
- Weitertippen im Protokolltext, während ein vorheriger Save noch läuft, löst keinen
  Konflikt mehr gegen die eigene vorherige Version aus, der den gerade getippten Text
  sichtbar durch eine veraltete Serverversion ersetzt hat.
- Die Galerie-Gruppierung «Duplikate»/«Ähnliche» verifiziert vor dem Gruppieren den
  tatsächlichen Bildinhalt (Pixelvergleich), statt sich allein auf den groben
  Perceptual-Hash-Kandidatenfilter zu verlassen.
- Die Aufgaben-Tabelle ist breiter und besser lesbar.
- Die Fotogalerie ordnet Kacheln als Masonry-Raster nach dem echten Bildformat statt
  gleich hoher Zeilen; der Ladezustand zeigt einen getönten Platzhalter statt einer
  leeren Fläche.

## [1.1.6] - 2026-10-04

Wartungsrelease auf 1.1.5 mit Korrekturen an Blocktypen, Zyklus-Zuordnung von Terminen
und der Anzeige von Teilnehmernamen im Protokoll-Editor. Enthält die Migration `0098`;
sie läuft beim Deploy automatisch. Keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.5 auf 1.1.6

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.6` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0098` gleicht die Blocktyp-ids 12–16 an die festen ids des Vorlagen-Editors
  an (12 Kontostand, 13 Transaktionen, 14 Bussenliste, 15 Diagramm, 16 Ein-/Austritte).
  Auf Installationen, die aus der 1.0.0-Baseline aufgesetzt wurden, waren diese Typen
  verschoben; die Migration benennt nur die Typ-Codes um, bestehende Blöcke erhalten
  dadurch den Typ, der im Editor gewählt wurde. Auf bereits korrekten Datenbanken ist sie
  ein No-op; bei unerwarteter Belegung bricht sie mit einer Meldung ab, statt zu raten.
- Nach dem Update betroffene, bereits erstellte Protokolle kurz prüfen: Blöcke, die
  vorher als falscher Typ erschienen, zeigen nun den richtigen Typ. Ein-/Austritte-Blöcke,
  die als Diagramm gespeichert wurden, enthalten noch keine Einträge – den Punkt im
  offenen Protokoll bei Bedarf neu anlegen.
- Bestehende Zyklus-Zuordnungen von Terminen werden nicht automatisch geändert. Termine,
  die fälschlich einem späteren Zyklus zugeordnet sind, in der Terminverwaltung
  korrigieren.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Geändert

- Termine werden standardmässig dem Zyklus zugeordnet, in den ihr eigenes Datum fällt –
  beim Erfassen im Protokoll, in der Terminverwaltung sowie beim Word- und CSV-Import.
  Bisher erhielten im Protokoll erfasste oder importierte Termine zusätzlich den Zyklus
  des Protokolls, wodurch z. B. rückblickend erwähnte Anlässe im neuen Zyklus auftauchten.
  Manuell gewählte Zyklen bleiben erhalten; bei einer Datumsänderung wandern nur
  unveränderte Standard-Zuordnungen mit.
- Das Termin-Popup (Terminverwaltung, Terminübersicht und Terminauswahl im Protokoll)
  zeigt die Zyklen des Termins und erlaubt, sie direkt anzupassen.
- Mehrfachauswahlen von Teilnehmern zeigen im Protokoll-Editor alle Namen statt
  „Name + N“; zu lange Listen werden mit Auslassungspunkten gekürzt, der volle Text
  steht im Tooltip.

### Behoben

- Neu angelegte Kontostand-, Transaktions-, Bussenlisten-, Diagramm- und
  Ein-/Austritte-Blöcke werden mit dem richtigen Typ gespeichert (siehe Migration
  `0098`). Zuvor erschienen z. B. Ein-/Austritte unter Finanzen und „Kein Diagramm
  ausgewählt“ statt der Ein-/Austritte. Frische Installationen erhalten die Typen
  direkt mit festen ids.
- Der Protokoll-Editor zeigt Namen auch für Teilnehmer, die nicht der Vorlage
  zugewiesen sind, statt „X ausgewaehlt“ – in Listen, Formularen, Matrix-Zellen,
  eingebetteten Blöcken und verknüpften Ereignissen.
- Nach einer Spalte gruppierte Listen fassen Einträge mit verschiedenen Personen nicht
  mehr in einer einzigen Zeile zusammen; zusammengefasste Zeilen brechen um, statt die
  Tabelle zu sprengen.
- Ein-/Austritte-Blöcke tragen im Protokoll ihre Bezeichnung statt „ENTRY_EXIT“.

## [1.1.5] - 2026-10-04

Wartungsrelease auf 1.1.4 mit Korrekturen rund um Teilnehmer-Mitgliedschaften,
historische Listen und die Protokollnummerierung im Zyklus. Keine Migrationen und
keine neuen Pflicht-Umgebungsvariablen.

### Update von 1.1.4 auf 1.1.5

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.5` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Keine Datenbank-Migrationen, keine manuellen Vorbereitungsschritte.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Geändert

- In aktuellen Listen werden noch verknüpfte, bereits ausgetretene Teilnehmer
  orange markiert. Der Hinweis zeigt das Austrittsdatum; dies gilt für Einzel-
  und Mehrfachverknüpfungen. Historische Ansichten behalten ihre damalige Darstellung.

### Behoben

- `[n_cycle]` zählt über alle Vorlagen, die derselben Zyklus-Definition zugeordnet
  sind (z. B. Hock und Arbeitsweekend im selben Scharjahr); Vorlagen ohne Zyklus
  zählen weiter pro Vorlage. Einschübe nummerieren offene Protokolle anderer Vorlagen
  im selben Zyklus mit um, und bei einer Kollision der Protokollnummer weicht nur die
  Nummer aus – der Titel behält den echten Rang.
- Automatische Ereignis-Blöcke in Protokollen finden ihr verknüpftes Ereignis wieder
  zuverlässig. Titel, Felder und die Auswahl bereits verwendeter Ereignisse werden
  korrekt angezeigt, statt als unbekanntes Ereignis zu erscheinen.
- Offene Protokolle aktualisieren Teilnehmerlisten sowie Ein- und Austritte nach
  Änderungen der Mitgliedschaft anhand des Protokolldatums. Erfasste Anwesenheiten,
  Notizen und ausgeblendete Einträge bleiben erhalten.
- Historische Listen zeigen die damals verknüpften Teilnehmer wieder korrekt an.
  Neue Snapshots speichern zusätzlich ihre Namen und erhalten sie auch nach einer
  späteren Umbenennung oder Löschung. Abgeschlossene Protokolle zeigen den
  eingefrorenen Stand ihrer Anwesenheitslisten.
- Die Teilnehmerauswahl berücksichtigt Ein- und Austrittsdaten: Aktuelle Listen
  verwenden das heutige Datum, Protokolle und ihre zugehörigen Eingaben das
  Protokolldatum. Der Austrittstag bleibt eingeschlossen; danach stehen ausgetretene
  Teilnehmer nicht mehr zur Auswahl. Bestehende Verknüpfungen bleiben sichtbar.

## [1.1.4] - 2026-10-04

Wartungsrelease auf 1.1.3 mit vollständiger Mehrsprachigkeit (Deutsch/Englisch/
Französisch/Italienisch), einem Design- und einem Usability-Audit sowie mehreren
Sicherheits- und Kollaborations-Fixes. Enthält die Migration `0097`; sie läuft beim
Deploy automatisch. Für das Update von 1.1.3 sind keine neuen Pflicht-Umgebungsvariablen
nötig.

### Update von 1.1.3 auf 1.1.4

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.4` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migration `0097` ergänzt `app_user.preferred_language` nachträglich bei bereits
  laufenden, inkrementell migrierten Installationen, auf denen die Spalte trotz
  aktueller `sql/baseline_schema.sql` noch fehlte (Query-Fehler auf praktisch jedem
  authentifizierten Request). Prüft per Inspector, ob die Spalte schon existiert, ist
  also auch auf frisch per `baseline_schema.sql` initialisierten Datenbanken sicher.
  Keine manuellen Vorbereitungsschritte.
- `deploy.sh` erstellt Traefik beim ersten Deploy mit dieser Version einmalig neu (kurze
  Unterbrechung von wenigen Sekunden), weil sich `infra/traefik/traefik.yml` geändert
  hat (siehe unten).
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein
  Release.

### Neu

- **Vollständige Internationalisierung (i18n)** von Hauptapp, Platform-Admin und
  Abgabebox mit next-intl: Deutsch (Default), Englisch, Französisch, Italienisch.
  Zentrale Locale-Konfiguration in `i18n/locales.json` (siehe `CLAUDE.md`, Abschnitt
  „Internationalisierung / i18n"), Sprachauswahl in den Benutzereinstellungen,
  persistente Präferenz (`app_user.preferred_language` + `hocx_locale`-Cookie) und
  automatische CI-Prüfung auf Übersetzungs-Vollständigkeit, hart codierte UI-Texte und
  fehlerhafte Key-Auflösung zur Laufzeit.
- Echter Upload-Fortschritt im Galerie-Upload-Dialog: Fortschrittsbalken pro Datei
  (gesendete/gesamte Bytes), Prozentanzeige am Upload-Button, animierte Anzeige vor dem
  ersten Fortschrittsereignis und während der Server den Upload entgegennimmt.
- Gemeinsames Action-Icon-Set (`components/ui/action-icons.tsx`) für
  Bearbeiten/Löschen/Schliessen/Plus/Kopieren statt roher Unicode-Zeichen und
  duplizierter Inline-SVGs; `mini-menu` als eigenständiger, in `DESIGN.md`
  dokumentierter Baustein.

### Geändert

- Primäre Seitenaktion durchgängig auf `button-primary` vereinheitlicht (betraf
  mehrere Listen-/Manager-Seiten, die bisher `button-secondary` zeigten).
- Lösch-Terminologie vereinheitlicht ("Löschen" statt "Entfernen" bei echten
  Löschvorgängen, Bestätigungstexte auf Standardformel).
- Vorlagen-Detailseite und ihre Feldlabels lokalisiert und an die Struktur der
  Schwesterseite `/templates` angeglichen.
- Finanzen-Seite: fehlender Mobile-Breakpoint behoben (einspaltiges Layout ≤900px,
  scrollende Transaktionstabelle ≤640px statt Viewport-Überlauf).
- Protokoll-erstellen-Dialog: Namensvorschau beschriftet, Platzhalter aufgelöst statt
  rohe `{n}`/`{date:...}`-Syntax zu zeigen; Dashboard-CTA „+ Neues Protokoll" öffnet den
  Dialog jetzt direkt statt nur zur Liste zu navigieren.
- Natives `required` (englische Browser-Validierungsmeldung) durch disabled-
  Speichern-Button ersetzt (Benutzer-erstellen-Formulare, Tenant- und
  Platform-Admin-Variante).
- „ClamAV Online/Offline"-Chip durch Klartext „Virenprüfung aktiv/offline" ersetzt;
  Offline-Hinweistext bei der Protokoll-Kollaboration erklärt jetzt, dass Änderungen
  trotzdem automatisch gespeichert werden.
- Autofokus beim Öffnen eines Protokolls nur noch bei expliziten Sprungaktionen
  (Navigation/Tastatur/Suche), nicht mehr beim passiven Laden/Wiederherstellen der
  Scroll-Position.
- Nav-Label fr/it gekürzt (Organisation/Organizzazione), Sprachauswahl-Dropdown im
  Seitenkopf der Abgabebox nach denselben Tokens gestylt wie das Haupt-App-Select.

### Behoben

- `deploy.sh` erstellt Traefik neu, wenn sich `infra/traefik/traefik.yml` geändert hat.
  Bisher lief Traefik nach einem Update mit der alten statischen Konfiguration weiter
  (u. a. 60-s-`readTimeout`), wodurch grosse Galerie-Uploads mit «Bad Gateway» abbrachen.
- **Protokoll-Kollaboration** war über vier Bugs zusammen unzuverlässig: Der
  Kollaborations-Websocket liess nur die statische Haupt-Domain zu, nie eine
  Mandanten-eigene Custom-Domain (sofort „Offline"); Todo-/Bild-Updates wurden
  serverseitig immer abgelehnt, weil nur der übergeordnete Block sperrbar ist;
  Anwesenheits-Klicks verliessen sich auf ein Fokus-Event, das bei einem Button-Klick
  nicht in jedem Browser (v. a. Safari) auslöst; die „Status & Zusammenarbeit"-Kachel
  zählte auch ausgeblendete oder zum Löschen vorgesehene Anwesenheits-Blöcke.
- Protokoll-Suche: Sprung zum gewählten Kapitel landete nicht mehr korrekt, weil der
  Scroll-Spy den programmatischen Smooth-Scroll abbrach; ein Treffer auf das bereits
  aktive Kapitel scrollt jetzt ebenfalls.
- **Zentrale Fehlererfassung:** mehrere Stellen, an denen unerwartete Backend-Fehler
  nie in `system_error_log` landeten, geschlossen — u. a. ein falscher `source`-Wert in
  den Wartungs-Loops, der an der DB-Constraint scheiterte und sämtliche
  Wartungs-Loop-Fehler lautlos verwarf, sowie fehlendes zentrales Logging in
  WebSocket-Hintergrund-Tasks und weiteren Hintergrund-Diensten.
- `MISSING_MESSAGE`-Laufzeitfehler durch falschen Übersetzungs-Namespace behoben
  (Haupt-App-Breadcrumb, Protokoll-Vorlagen-Platzhaltervorschau); neuer
  `check-i18n-key-resolution.py`-CI-Guard verhindert ein Wiederauftreten.
- Fehlende Migration für `app_user.preferred_language` ergänzt — fehlte real auf
  bereits laufenden, inkrementell migrierten Datenbanken.
- **Sicherheitsaudit vom 30.09.2026:** `require_feature("custom_domain")` gate nur
  das Anlegen/Verifizieren einer Custom-Domain, nicht deren fortlaufenden Betrieb —
  nach Entzug des Features blieb eine bereits aktive Domain unbegrenzt geroutet;
  Regenerate-Aufruf, Health-Check-Loop und Login-Bridge prüfen das Feature jetzt
  zusätzlich laufend. Dependency-Updates: Next.js 16.2.12 → 16.3.6 (Out-of-Band-
  Sicherheitsupdate), `starlette` explizit auf `>=1.0.1` gepinnt (CVE-2026-48710),
  PyJWT 2.10.1 → 2.12.0, transitive `nanoid`-Schwachstelle in beiden Frontends per
  `npm audit fix` behoben.
- Admin-Mandanten-Einstellungen: Hooks-Reihenfolge-Crash im Speicher-Tab behoben
  (`useTranslations` wurde nach einem frühen `return null` aufgerufen).

## [1.1.3] - 2026-09-27

Wartungsrelease auf 1.1.2 mit Feature-Gating und Preiskatalog im Plattform-Admin,
mandantenübergreifendem Fotoalben-Teilen und mehreren Sicherheits-Fixes an der
Abgabebox. Enthält die Migrationen `0084` bis `0096`; sie laufen beim Deploy
automatisch. Für das Update von 1.1.2 sind keine neuen Umgebungsvariablen nötig.

### Update von 1.1.2 auf 1.1.3

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.3` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.

- Migrationen `0084` bis `0096` ergänzen Feature-Gating, Preiskatalog, Speicher-Zusatzpakete,
  Freigabe-Links und mandantenübergreifendes Fotoalben-Teilen. Alle sind additiv oder
  backfillen bestehende Mandanten automatisch (Finanzen, Abgabebox und eigene Domain
  bleiben für alle bisherigen Mandanten freigeschaltet); keine bricht bei bestehenden
  Daten ab, es sind keine manuellen Vorbereitungsschritte nötig.
- Migration `0088` setzt ein manuell erweitertes Speicherkontingent zurück, wenn es über
  der neuen automatischen Berechnung aus Plan und Zusatzpaketen lag; ein manuell
  verringertes Kontingent bleibt unverändert. Das lässt sich nicht rückgängig machen.
- Das Backend-Speicherlimit (`mem_limit`) steigt in den mitgelieferten Compose-Dateien
  von 1024 MB auf 6144 MB (Spielraum für Galerie-Uploads und Bildverarbeitung) und wird
  beim Update automatisch übernommen; der Host braucht entsprechend freien Arbeitsspeicher.
- Der Galerie-Upload-Router in Traefik puffert Anfragen nicht mehr vollständig, sondern
  streamt direkt zum Backend, das die bisherige Obergrenze jetzt selbst durchsetzt.
- Vor dem Update das Datenbankbackup prüfen.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein Release.

### Neu

- **Feature-Gating und Preiskatalog im Plattform-Admin:** Mandanten lassen sich einzelne
  Funktionen (aktuell Finanzen, Abgabebox, eigene Domain) unabhängig von Rollen zu- oder
  abschalten. Neuer Preiskatalog mit Plänen (Monats-/Jahrespreis, Nutzer-/Speicherlimits),
  Rabatt in Prozent und interner Notiz pro Mandant sowie Abo-Zuweisung im Adminportal.
  Bestehende Mandanten wurden beim Umstieg automatisch auf ihren bisherigen Funktionsumfang
  freigeschaltet.
- **Speicher-Zusatzpakete:** zusätzlich zum Plan-Kontingent einzeln zubuchbare
  Speicherpakete pro Mandant; das Gesamtkontingent wird automatisch aus Plan und Paketen
  berechnet.
- **Fotoalben teilen:** Alben lassen sich mit anderen Mandanten teilen (Einladen per
  Mandanten-ID, Annehmen/Ablehnen), auch automatische Zyklus- und Abgabe-Alben. Neu
  hinzukommende Fotos in einem geteilten Album sind erst nach manueller Freigabe für den
  Partner-Mandanten sichtbar; manuell hinzugefügte Fotos sind sofort geteilt. Name,
  Profilbild und Teilnehmerzahl eines anderen Mandanten werden erst nach gegenseitig
  angenommener Freigabe angezeigt, nicht schon bei offener Anfrage.
- **Freigabe-Links:** öffentliche, tokenbasierte Download-Links ohne Login für einzelne
  Dateien oder ein ganzes Album, verwaltet unter «Freigabe-Links» mit eigener öffentlicher
  Download-Seite.
- Neuer Dialog «Fotos hinzufügen» für Alben: Mehrfachauswahl nach Datumsgruppe,
  «Alle auswählen», Filter und Suche über Tags, Termin, Protokoll oder Abgabe.
- Ctrl+F Kapitel- und Volltextsuche im Protokoll-Editor.
- Elemente lassen sich im Protokoll-Editor mit allen Blöcken duplizieren.
- Foto-Viewer: mit den Tasten J/L zwischen Bildern wechseln.

### Geändert

- **Abgabebox und eigene Domain sind jetzt eigene Feature-Gates** statt immer freigeschaltet;
  bestehende Mandanten behalten beim Umstieg automatisch den Zugriff.
- Manuelles Speicherkontingent-Feld im Adminportal wieder entfernt: Das Kontingent ergibt
  sich automatisch aus Plan und Speicher-Zusatzpaketen.
- Überarbeiteter Teilen-Dialog für Fotoalben: Vorschaukarte des gefundenen Mandanten,
  Statusliste «Geteilt mit», Entfernen bzw. Zurückziehen einer Freigabe.
- Mandanten-ID ist in den Mandanten-Einstellungen sichtbar.
- Protokollmenü vereinfacht; PDFs werden beim Öffnen eines Protokolls automatisch neu
  erstellt.
- Element-Anlegen-Popup an die neue Designvorlage angeglichen (Zyklus-Platzhalter-Karte,
  vereinfachtes Blocktyp-Raster, ergänzte Einstellungsabschnitte für Bild, Sitzungsdatum
  und Bussenliste).
- Modal-Schliessen ist durchgängig ein Icon-Button statt eines Text-Buttons; Auswahl-Popups
  (Teilnehmende, Terminverwaltung, strukturierte Listen) speichern jede Änderung sofort
  statt über einen «Auswahl übernehmen»-Button.
- Letztes rohes Datumsfeld (Todo-Export-Filter) durch den einheitlichen `DateInput` ersetzt.
- Admin-Navigation: Das «Neu»-Badge ist komplett entfernt.
- Redundante Inline-Styles am Zeitraum-Filter entfernt.

### Behoben

- **Sicherheitsaudit vom 24.09.2026:** Die Abgabebox prüfte das Speicherkontingent eines
  Uploads nur gegen eine globale Konstante statt gegen das tatsächliche Mandantenkontingent;
  ein Mandant auf einem kleineren Plan konnte sich darüber kostenlosen Zusatzspeicher bis zur
  globalen Obergrenze verschaffen. Geprüft wird jetzt der jeweils kleinere der beiden Werte.
  Ausserdem prüfte die Domain-Aktivierung das Feature-Gate für eigene Domains nicht wie das
  Anlegen, sodass eine bereits angelegte Domain nach Entzug des Features weiterhin aktiviert
  werden konnte.
- **Galerie-Upload blieb dauerhaft auf «queued» hängen:** Periodische Hintergrundschleifen
  (u. a. der Galerie-Upload-Ingest) nutzten Advisory Locks, die mit Connection-Pooling
  unsicher sind; betroffen waren auch Start-Locks und die Quarantäne-Bereinigung der
  Abgabebox.
- Escape-Zuständigkeit für Modals, Popups und Auswahlmenüs vereinheitlicht.
- Die Protokollliste aktualisiert sich beim Zurücknavigieren im Browser.
- Backend-Reload: Parser-Worker werden jetzt sauber heruntergefahren.
- Admin-Mandantenliste: Der `plan`-Filter griff bei direktem Routenaufruf fälschlich als
  Text statt als leerer Filter.

## [1.1.2] - 2026-09-22

Wartungsrelease auf 1.1.1 mit Verbesserungen an Fotos, Word-Import und Elementeditor
sowie automatischen GitHub-Releases. Enthält Migration `0083`; sie läuft beim Deploy
automatisch. Für das Update von 1.1.1 sind keine neuen Umgebungsvariablen nötig.

### Update von 1.1.1 auf 1.1.2

Nach Veröffentlichung der Release-Images `HOCX_VERSION` in `.env` auf `v1.1.2` setzen,
dann `./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` ausführen.
Wer von einer älteren Version kommt, beachtet zusätzlich die Upgrade-Hinweise zu
1.1.0 und 1.1.1 weiter unten.

- Migration `0083_photo_capture_event_link` ergänzt das optionale EXIF-Aufnahmedatum
  samt Index in `stored_file` und das Kennzeichen `event_auto_linked` in `gallery_image`.
  Bestehende Fotos und manuelle Terminzuordnungen bleiben erhalten; vorhandene
  Zuordnungen werden als manuell behandelt.
- EXIF-Aufnahmedaten werden bei neuen Galerie-Uploads gespeichert. Bestehende Fotos
  werden nicht nachträglich ausgelesen; ohne gespeichertes Aufnahmedatum gilt das
  Upload-Datum. Die Migration ordnet alte Fotos nicht automatisch Terminen zu.
  Die Zuordnung erfolgt bei neuen Uploads sowie beim Anlegen oder Ändern von Terminen.
- Vor dem Update das Datenbankbackup prüfen. Ein Image-Rollback nimmt die Migration
  nicht zurück; die zusätzlichen Spalten sind mit 1.1.1 kompatibel. Für eine vollständige
  Wiederherstellung des vorherigen Datenstands gilt der Backup-Ablauf im RUNBOOK.
- Git-Tag und GitHub-Release entstehen erst nach erfolgreicher Promotion aller Images
  durch den Release-Workflow. Der Push dieser Vorbereitung veröffentlicht noch kein Release.

### Neu

- Fotos werden nach Aufnahmedatum gruppiert und beim Upload automatisch passenden
  Terminen zugeordnet, auch innerhalb mehrtägiger Termine. Manuelle Zuordnungen haben Vorrang.
- Die Galerie trennt «Duplikate» und «Ähnliche» mit unterschiedlichen Ähnlichkeitsschwellen;
  ganze Datumsgruppen lassen sich gemeinsam auswählen.
- Im Vorlageneditor können neue Elemente direkt aus der Elementauswahl angelegt werden.
- Nach erfolgreicher Promotion aller Container-Images wird automatisch ein GitHub-Release
  mit dem Changelog der Version und einem Git-Tag auf dem getesteten Commit veröffentlicht.
- Die Versionsnummer auf der Login-Seite öffnet den zugehörigen GitHub-Release mit
  Changelog in einem neuen Tab; Entwicklungs- und Teststände verlinken die Release-Übersicht.

### Geändert

- Die Foto-Qualitätsbewertung gewichtet gute Porträts stärker.
- Galerie-ZIP-Uploads haben grosszügigere Grössenlimits statt der bisherigen 5-GiB-Grenze;
  Speicherkontingente und Schutzgrenzen für Archive bleiben wirksam.
- Der Elementdialog ist zweispaltig und breiter, die Termin-Zeitfenster sind übersichtlicher.
  Ausgewählte Terminfelder erscheinen direkt als Tabellenzeilen; Beschreibungsfelder im
  Elementdialog entfallen.
- Abgaben können Apple-Dateiformate (`.pages`, `.key`, `.numbers`, `.heic`, `.heif`) zulassen.
- Bestätigte Textabschnitt-Zuordnungen werden bei späteren Word-Importen wiederverwendet,
  auch wenn Überschrift und Elementname unterschiedlich lauten.
- Beim Nachladen von Fotos zeigt die Galerie eine dezente, auf den Fotobereich begrenzte
  Ladeanimation. Überflüssige Upload-Hinweise wurden entfernt.

### Behoben

- Die Protokollliste aktualisiert sich beim Zurücknavigieren nach einem Word-Import.
- FriendlyCaptcha-Fehlerantworten werden auch bei HTTP-Fehlerstatus ausgewertet.
- Der Link «Protokoll ansehen» und Datums-Schaltflächen im Word-Import verwenden die
  vorgesehenen Schaltflächen- und Hover-Stile.

## [1.1.1] - 2026-09-21

Wartungsrelease auf 1.1.0 mit iPhone-Foto-Support, manuellen Abgaben, Zyklusfilter für
Abgaben, Duplikaterkennung beim Upload und mehreren Fixes. Enthält die Migrationen `0079`
bis `0082`; sie laufen beim Deploy automatisch. Manuelle Schritte sind nur nötig, wenn
`FRIENDLY_CAPTCHA_VERIFY_URL` von Hand gesetzt wurde (siehe unten). Wer direkt von 1.0.x
kommt, folgt zusätzlich dem Abschnitt «Update von 1.0.x auf 1.1.0».

### Update von 1.1.0 auf 1.1.1

`HOCX_VERSION` in `.env` auf `v1.1.1` setzen, dann `./scripts/update_deploy_code.sh` und
`./scripts/deploy.sh <test|prod>`. Zu beachten:

- Das Backend-Image enthält neu `ffmpeg` und `pillow-heif`; es kommt mit dem Release-Image,
  ein lokaler Build ist nicht nötig.
- Die Abgabebox prüft das CAPTCHA jetzt gegen `https://api.friendlycaptcha.com/api/v1/siteverify`.
  Wer `FRIENDLY_CAPTCHA_VERIFY_URL` in `.env` von Hand auf den alten v2-Endpunkt gesetzt hat,
  muss die Zeile entfernen oder anpassen, sonst schlägt jede Prüfung weiterhin fehl.
- Migration `0079` gibt der eingeschränkten Rolle `hocx_abgabebox` Lesezugriff auf einzelne
  Spalten von `cycle_config` und `event_cycle` (für den Zyklusfilter der öffentlichen
  Abgabebox). Sie ergänzt nur, entzieht nichts.

### Neu

- **iPhone-Fotos (HEIC/HEIF) und Live Photos in der Galerie:** Der Upload nimmt HEIC/HEIF an
  (auch in ZIPs) und speichert sie als JPEG – Aufnahmedatum, Kamera, Ausrichtung und
  Farbprofil bleiben erhalten, das HEIC-Original wird nicht aufbewahrt. Wird zu einem Bild
  ein gleichnamiges `.mov`/`.mp4` mitgeschickt (`IMG_1234.HEIC` + `IMG_1234.MOV`, so liefert
  es der iPhone-Export), gilt es als Live Photo: der Clip wird zu einem kleinen H.264-MP4
  umgerechnet und in der Galerie beim Hovern über dem Bild abgespielt (im Viewer zusätzlich
  per «LIVE»-Knopf). Im Viewer wählt man bei «Herunterladen», ob man das Bild (JPEG), das
  Video (MP4) oder beides (ZIP mit gleichnamigen Dateien) bekommt. Der Clip ist kein eigenes Foto, zählt aber zum Speicher und wird mit dem
  Bild gelöscht (Migration `0081`). Das Backend-Image enthält dafür `ffmpeg` und
  `pillow-heif`. Nicht abgedeckt: die öffentliche Abgabebox, Android-Motion-Photos und
  ProRAW (DNG).
- **Manuelle Abgaben:** Neben «Termine» und «Liste» gibt es die Verknüpfung «Manuell» – ein
  einzelnes Abgabefeld ohne Bezug zu Terminen oder Listen, optional mit Stichtag (Migration
  `0080`). In der Abgabebox erscheint es als einzelnes Element mit dem Titel der Abgabe.
- **Abgabe erstellen/bearbeiten neu gestaltet:** Aufbau wie der Todo-Editor mit Titel im Kopf,
  Verknüpfung als Karten, Dateitypen als Chips und einer Seitenleiste mit öffentlichem Link,
  Erreichbarkeit und einer Zusammenfassung, wie sich die Abgabe verhält.
- **Zyklusfilter für Abgaben nach Terminen:** Eine Abgabe kann auf Termine eines Zyklus
  eingeschränkt werden (Zyklus-Konfiguration plus Versatz: `0` = aktueller, `-1` = voriger
  Zyklus usw., Migration `0079`). Eine Zyklus-Konfiguration, die noch von einer Abgabe
  verwendet wird, lässt sich nicht löschen; Mandanten klonen übernimmt die Zuordnung. Die
  öffentliche Abgabebox wertet den Filter selbst aus (nur lesender Zugriff auf `cycle_config`
  und `event_cycle`).
- **Leerzustände auf allen Listenseiten:** Dashboard, Protokolle, Todos, Bussen, Finanzen,
  Statistiken, Listen, Teilnehmende, Termine, Abgaben, Fotos, Dateien, Benutzer und
  Dokumentvorlagen zeigen ohne Daten eine erklärende Startansicht mit direkter Aktion.
  Neu dabei: «Busse erfassen» (damit «+ Busse» funktioniert), «Rollen erklären» in der
  Benutzerverwaltung und «Standard-Layout verwenden» bei den Dokumentvorlagen. Filter und
  Kopfzeilen-Knöpfe erscheinen erst, wenn Daten vorhanden sind.
- **Duplikaterkennung vor dem Scan** (Migration `0082`): Byteidentische Dateien werden in der
  App (Dokumente, Fotos, Word-Import) vor Virenscan und Verarbeitung als Duplikat gemeldet.
  Bei konvertierten Dateien (z. B. HEIC → JPEG) zählt der Hash des Originals. Die öffentliche
  Abgabebox überspringt Duplikate desselben Abgabe-Elements still und bestätigt den Upload
  normal. Gleichzeitige Uploads werden pro Mandant über PostgreSQL-Sperren serialisiert, so
  dass auch parallel abgeschickte Kopien nur einmal gespeichert werden.

### Geändert

- **Dokumentvorlagen-Seite neu gestaltet:** Layouts und Bausteine-Bibliothek mit Kartenlayout,
  Liste/Editor-Aufteilung, Reitern im Editor und kompakten Auswahlkarten; der Upload-Dialog
  für Bausteine ist zweispaltig mit Slot-Auswahl, Ablagefläche und Bibliotheks-Übersicht.
- Ein hochgeladenes Mandantenlogo wird in der Seitenleiste angezeigt.
- Word-Import-Assistent: Der Feldname, der eine Zeile rot hält, ist rot umrandet und mit
  Hinweistext sowie einer Zusammenfassung offener Felder markiert; nicht zugeordnete Namen
  heissen «– nicht zugeordnet –» statt «Keinen verknüpfen».
- Matrix-Designer: native Auswahlfelder sehen aus wie die übrigen Dropdowns.
- Speicher-Seite: Abstände der Kennzahlenkarten und der Aufschlüsselung korrigiert.

### Behoben

- **Abgabebox-CAPTCHA:** Die Lösung wurde gegen den v2-Endpunkt geprüft, obwohl das Widget
  FriendlyCaptcha v1 ist; jede Prüfung schlug mit 404 fehl, das Widget lud endlos neu und der
  Sicherheitscheck wurde nie abgeschlossen. Der Standard zeigt jetzt auf `/api/v1/siteverify`;
  abgelehnte Prüfungen werden mit Status, Fehlern und URL protokolliert.
- **Automatisch erzeugtes Folgeprotokoll:** Es wurden interne Zahlen-IDs statt öffentlicher
  UUIDs an die Validierung übergeben (Fehler bei `template_id` und `event_id`). Die
  konfigurierte Folgevorlage wird aus ihrer öffentlichen UUID aufgelöst (alte Zahlenwerte
  gehen weiterhin).
- Datei-Uploads, die mit einem Abgabe-Element verknüpft sind, zählen jetzt als Abgabe.
- Fotos: Ähnliche Fotos öffnen im Betrachter, das Album-Cover lässt sich nicht mehr
  versehentlich ziehen, und Albumtitel bleiben in allen Designs lesbar.
- Frontend: Runtime-Konfiguration und Theme-Skript stehen als normale `<script>`-Tags im `<head>`;
  die React-19-Warnung «Encountered a script tag while rendering React component» entfällt.
- Galerie-Upload: Ein Duplikat-Ergebnis geht auch dann genau einmal an die Oberfläche, wenn
  der Job vor der ersten Statusabfrage fertig ist.

## [1.1.0] - 2026-09-19

Zweite stabile Version. Sie enthält alle seit 1.0.0 gemergten Fixes und
Hardening-Massnahmen sowie die unten aufgeführten neuen Funktionen. Vor dem Update bitte die
mit **Achtung beim Update** markierten Punkte lesen (Migrationen `0064` bis `0078`).

### Update von 1.0.x auf 1.1.0

Ablauf auf jedem Host (Test wie Prod): `HOCX_VERSION` in `.env` auf `v1.1.0` setzen, dann
`./scripts/update_deploy_code.sh` und `./scripts/deploy.sh <test|prod>` (oder
`update_deploy_code.sh --deploy`). `deploy.sh` erledigt dabei alles Weitere selbst:

- **`.env` wird migriert** (`scripts/lib/env_migrate.sh`, Sicherung als `.env.bak-<Zeitstempel>`):
  `PHOTO_WORKER_DB_PASSWORD` und `PHOTO_WORKER_DATABASE_URL` werden neu erzeugt (eigene
  DB-Rolle `hocx_photo_worker`, Migration `0067`), die entfernte Variable `TRAEFIK_WEB_DOMAIN`
  wird gelöscht. Vorhandene Werte bleiben unverändert.
- **`storage-local/thumbnails`** wird angelegt und für den Backend-Benutzer (Gruppe 5001)
  freigegeben; der neue Dienst `photo-analysis-worker` wird signaturgeprüft, gestartet und
  in Smoke-Checks und Rollback einbezogen.
- **Migration `0078` (ein Konto = ein Mandant)** bricht ab, wenn Konten mit mehr als einer
  aktiven Mandanten-Mitgliedschaft oder ganz ohne Mandant existieren; die Datenbank bleibt
  dann unverändert und die alte Version läuft weiter. Entweder vorher bereinigen oder
  `HOCX_SINGLE_TENANT_RESOLUTION=auto` in `.env` setzen (behält je Konto die Mitgliedschaft
  des Standard-Mandanten, sonst die höchste Rolle; Konten ohne jeden Mandanten werden
  **gelöscht**). Das Backup vor dem Update liegt in `backups/`.
- Nur **Test**: Nach dem Deploy wird der Demo-Mandant "Jubla Sonnenberg" neu aufgebaut.
  Optional kann `DEMO_TOTP_SEED` in `.env` gesetzt werden.
- Der Rollback startet die vorherigen Images, macht Datenbankmigrationen aber nicht rückgängig;
  ein Zurück auf 1.0.x nach erfolgreicher Migration braucht das Backup (RUNBOOK Abschnitt 5).

### Geändert

- **Ein Konto gehört genau einem Mandanten** (Migration `0078_single_tenant_users`): Die
  Mehr-Mandanten-Mitgliedschaft ist entfernt - inklusive Mandantenwechsel, Standard-Mandant
  und `POST /api/auth/select-tenant`. Mandant und Rolle stehen direkt am Benutzer
  (`app_user.tenant_id`/`role_id`); die Tabellen `user_tenant_role` und `user_role` sowie
  `app_user.default_tenant_id` entfallen. Wer in mehreren Vereinen arbeitet, braucht pro
  Verein ein eigenes Konto. Folgen:
  - Ein Mandanten-Admin hat volle Hoheit über die Konten seines Mandanten und kommt an keine
    Konten anderer Mandanten heran (löschen, Passwort/E-Mail/Rolle ändern). Das schliesst die
    Lücke, dass ein Admin über einen gemeinsam genutzten Account fremde Mandanten treffen konnte.
  - Der letzte aktive Admin eines Mandanten kann weder herabgestuft noch deaktiviert oder
    gelöscht werden (bisher nur Herabstufen/Entfernen).
  - Benutzer zusammenführen geht nur noch innerhalb eines Mandanten. Ein Teilnehmer-Login mit
    einer E-Mail-Adresse, die bereits ein Konto eines anderen Mandanten besitzt, wird mit
    Fehler 409 abgelehnt.
  - Platform-Admin-Panel: Benutzer werden beim Anlegen einem Mandanten zugeordnet, danach ist
    der Mandant fest. In den Mandanten-Einstellungen entfällt "Benutzer hinzufügen"; "Entfernen"
    heisst "Löschen" und löscht das Konto.
  - Mandanten klonen kopiert keine Benutzer mehr (der Klon startet ohne Konten, alle
    Benutzerverweise auf kopierten Zeilen werden zurückgesetzt). Export-Format Version 3
    enthält nur die Benutzer des exportierten Mandanten; der Import liest Version 2 und 3 und
    übernimmt keine E-Mail-Adresse, die auf der Zielinstallation schon in einem anderen
    Mandanten existiert (Warnung statt Verknüpfung).
  - Sitzungs-Cookies aus der Zeit davor bleiben gültig; ihr `tenant_id`-Anspruch wird ignoriert.
  - **Achtung beim Update:** Die Migration bricht ab, solange Konten mit mehr als einer aktiven
    Mandanten-Mitgliedschaft (oder ganz ohne Mandant) existieren, und listet sie auf. Entweder
    vorher bereinigen oder mit `alembic -x single_tenant_resolution=auto upgrade head` je Konto
    die Mitgliedschaft des Standard-Mandanten (sonst die höchste Rolle) behalten und die
    übrigen verwerfen. `-x seed_demo=true` (Dev/E2E/CI) löst automatisch auf.

- **Navigation neu gegliedert**: Die Seitenleiste ist in Dashboard / Arbeiten / Stammdaten /
  Konfiguration / Administration gruppiert, die Einzel-Gruppe "Tools" entfällt (`/tools`
  leitet auf die Import-Warteschlange um). Zusammengehörige Seiten (Dashboard + Statistiken,
  Konten + Bussen, Vorlagen + Elemente + Dokument-Layouts, Dokumente + Fotos) haben eine
  Tab-Leiste. Routen und Rollenprüfungen bleiben unverändert.
- **Einheitliches Design-System**: Gemeinsame Design-Tokens (`design/tokens.css`) für Hauptapp
  und Abgabebox, verbindliche Regeln in `design/DESIGN.md` und ein Prüfskript
  (`scripts/check-design-rules.py`), das in der CI läuft. Überarbeitet wurden unter anderem
  Todo-Editor, Konto-Dialog, Benutzer-Bearbeitung, Listen-Seitenleiste, Abgaben-Zuordnungen
  und alle Tabellen (gemeinsame maximale Breite).
- **Einheitliche Upload-Pipeline**: Protokollbilder, Galerie- und Word-Import-Uploads teilen
  sich Virenprüfung, Prüfsumme und Vorschaubilder sowie eine gemeinsame Nachprüfungsschleife.
  Die Lock-IDs aller Hintergrundschleifen liegen zentral in `app.core.background_loops`.
  Im Platform-Admin-Panel zeigt die neue Seite "Datei-Pipeline" den Prüfstatus je Datei.
- Dateien-, Vorschau- und Tag-URLs verwenden durchgängig die öffentliche UUID statt interner
  Zahlen-IDs.

### Hinzugefügt

- **Fotos-Galerie**: direkter Bild-Upload (einzelne Dateien oder ZIP-Archive) auf der
  "Dateien"-Seite, unabhängig von Protokoll/Word-Import/Abgabebox. Mit Tags,
  Duplikat-Warnung (Perceptual Hash) und Vorschaubildern.
- **Dateien-Upload**: Dokumente (PDF, Word/Excel/PowerPoint, OpenDocument, RTF, Text/CSV,
  ZIP) lassen sich direkt auf der "Dateien"-Seite hochladen - gleicher Upload-Dialog wie bei
  den Fotos (Drag & Drop, Warteschlange, Tags, Virenprüfung). Optionaler Bezug zu einem
  Termin, Abgabe-Element oder Zyklus, der in der Spalte "Bezug" erscheint.
  Bei einem Abgabe-Element gelten für Datei- und Foto-Uploads die Dateiregeln der Abgabe
  (erlaubte Dateitypen, maximale Dateigrösse, maximale Anzahl Dateien pro Element - inklusive
  der bereits über die Abgabebox eingereichten Dateien).
- **Speicherkontingent**: Mandanten-Speichernutzung im Adminportal einsehbar, mit pro
  Mandant konfigurierbarem Limit (Speicherkontingent-Verwaltung, eigene Storage-Seite).
- **Word-Import-Verbesserungen**: Matrix-Spalten-Zuordnung für Tabellen mit variablen
  Spalten, Unterstützung für mehrtägige Termine (Zeiträume statt Einzeldatum), sowie
  eine "zuletzt gewählte Vorlage", die beim nächsten Öffnen des Import-Assistenten
  automatisch vorausgewählt wird.
- **Tenant-Export/Import-Erweiterungen**: verifizierte Custom-Domains,
  Fotos-Galerie-Zuordnungen und die Word-Import-Vorlagen-Fremdschlüssel-Referenz
  werden jetzt mitexportiert/-importiert.
- **Tabellen-Snapshot-Funktion**: Zeilen einer "Zeile aus Liste"-Tabellenzeile können
  auf "Historische Daten verwenden" umgestellt werden - die Zeile zeigt dann die
  eingefrorenen Werte des Zyklus, in den das jeweilige Protokoll fällt, statt immer
  die aktuellen Live-Daten des verknüpften Listeneintrags.
- **Fotos/Dateien-Neugestaltung**: eigenständige "Fotos"-Seite mit nach Datum
  gruppierter Galerie (inkl. Zyklus-/Termin-/Protokoll-Kontext je Datumsgruppe),
  Mehrfachauswahl mit Sammelaktionen (Album, Tags, Best-of, Löschen), ein
  Vollbild-Fotobetrachter mit Analyse-Kennzahlen (Schärfe/Belichtung/
  Gesichtsqualität), ein mandantenweiter Analyse-Fortschrittsbalken, ein
  "Ähnliche"-Tab zur Serien-Bereinigung ("Nur beste behalten") sowie ein
  "Alben"-Tab mit Cover-Collage und Foto-/Best-of-Zahlen pro Album. Die
  "Dateien"-Seite zeigt jetzt Dokumente/Fotos/Speicher-Kennzahlen und eine
  Tabellenansicht statt der bisherigen Kachelliste.
- **Abgabe-Links**: Die öffentliche Abgabebox ist nur noch über einen Link mit zufälligem
  Schlüssel erreichbar (`<abgabebox-domain>/<schlüssel>`), nicht mehr über den
  Mandanten-Slug. Unter *Abgaben → Links* lassen sich beliebig viele Links mit Klarnamen
  anlegen, umbenennen, als Standard festlegen, mit neuem Schlüssel versehen und löschen; im
  Abgabe-Konfigurator wird gewählt, über welche Links eine Abgabe erreichbar ist. Jeder
  Mandant startet mit einem Standard-Link, der bei neuen Abgaben vorausgewählt ist.
  Die restricted DB-Rolle der Abgabebox darf dafür nur `id`, `tenant_id` und `token` der
  Links sowie die Zuordnung Abgabe↔Link lesen (Migration `0075_submission_link`).
  **Achtung beim Update:** Bestehende Mandanten erhalten automatisch einen Standard-Link, an
  dem alle bisherigen Abgaben hängen - die alten Adressen mit Mandanten-Slug funktionieren
  aber nicht mehr und müssen durch die neuen Links ersetzt werden. Die Umgebungsvariable
  `DEFAULT_TENANT_SLUG` entfällt. Beim Klonen/Importieren eines Mandanten entstehen immer
  neue Schlüssel (Tokens werden nie exportiert oder übernommen).

- **Foto-Auswahl und Qualitätsanalyse**: Schärfe und Belichtung werden bei jedem Upload
  berechnet, die Gesichtsqualität übernimmt der neue Dienst `photo-analysis-worker`
  (automatisch ausserhalb der Stosszeiten und nur bei geringer Serverlast). Ähnliche Fotos
  werden per Perceptual Hash zu Serien gruppiert (nach EXIF-Drehung und Randbeschnitt);
  "Nur beste behalten" räumt Serien auf. Migrationen `0066`-`0072`, `0076`, `0077`.
- **Automatische Foto-Alben**: Pro Zyklus, Abgabe und Abgabe-Element entsteht automatisch ein
  Album mit Best-of-Auswahl ("Stern"), die sich von Hand ergänzen oder ausschliessen lässt.
  Uploads aus der Abgabebox werden periodisch einsortiert.
- **Asynchrone Galerie-Uploads**: Bild-Uploads und ZIP-Archive bis 5 GB werden nur noch auf
  die Platte gestreamt und im Hintergrund verarbeitet; der Dialog schliesst sich sofort, ein
  Fortschrittsbalken zeigt den Stand (Migration `0073`). Dafür gibt es einen eigenen
  Traefik-Router ohne Standard-Grössenlimit. **Achtung beim Update:** Traefik-Konfiguration
  und Backend-Speicherlimit (`mem_limit`) aus den mitgelieferten Compose-Dateien übernehmen.
- **Demo-Mandant**: Jedes Test-Deployment (nie Prod) legt einen vollständig befüllten
  Demo-Mandanten "Jubla Sonnenberg" an (Teilnehmende, Termine, Protokolle, Fotos, Abgabe);
  ein fester TOTP-Seed für Demo-Konten ist konfigurierbar.

### Behoben

- Die Audit-Runde über `v1.0.0..1.1` hat 13 kritische und mehrere mittlere/niedrige Befunde
  ergeben, alle sind behoben. Wichtigste Punkte:
  - Drei Hintergrundschleifen der Foto-Funktionen starteten wegen fehlender Lock-IDs nie;
    fehlerhafte Durchläufe beenden eine Schleife nicht mehr dauerhaft und blockieren die
    Event-Loop nicht mehr.
  - Das Speicherkontingent wird jetzt beim Upload verbindlich durchgesetzt (race-frei).
  - Beim Tenant-Import wird `GalleryImage.event_id` korrekt umgeschrieben, sodass importierte
    Fotos nicht mehr fremden Terminen zugeordnet werden.
  - Ein Platform-Admin kann seinen letzten TOTP-Faktor nicht mehr löschen (Aussperr-Schutz).
  - Veraltete Antworten überschreiben in der Serien-Bereinigung und in historischen Listen
    keine neueren mehr.
  - Zyklus-Snapshots holen verpasste Zyklen nach; die Auswahl des "besten Fotos" ist in
    Serien-Bereinigung und Alben identisch.
  - Diverse Performance-Verbesserungen (Album-Sync, Hash-Abgleich, Snapshot-Rekonstruktion).
- Migration `0067`: Downgrade scheiterte, solange die Rolle noch Berechtigungen hielt.

## [1.0.0] - 2026-08-27

Erste stabile Version.

### Geändert

- Die 74 inkrementellen Alembic-Migrationen der Beta-Reihe wurden zu einer
  einzigen Baseline-Migration (`0001_initial_schema`) zusammengefasst. Neue
  Installationen erhalten direkt den aktuellen Schema-Stand; ein Upgrade-Pfad
  von einer bestehenden Beta-Installation auf 1.0.0 ist nicht vorgesehen.
