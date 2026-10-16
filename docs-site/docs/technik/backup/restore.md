# Wiederherstellung

Drei Wege, alle lesen ausschliesslich aus dem Borg-Repository – der S3-Anbieter zum Zeitpunkt
des Backups muss nicht mehr erreichbar sein:

| Situation | Weg |
|---|---|
| Ein Mandant hat Daten verloren/verändert, die Installation läuft | [Mandant als Kopie](#mandant-als-kopie) (Admin-Portal) |
| Installation läuft, Gesamtzustand muss zurück (Fehlbedienung, Ransomware im Datenbestand) | [Voll-Restore im Admin-Portal](#voll-restore-im-admin-portal) |
| Server weg, Datenbank weg, Backend startet nicht | [Recovery-CLI](#recovery-cli-neuer-server-oder-ohne-backend) |

Ein Mandant wird **nie** in-place überschrieben – dafür gibt es bewusst keine Funktion.

## Mandant als Kopie

System → Backups → Wiederherstellung → «Mandant als Kopie»:

1. Sicherungspunkt wählen (Liste aus der Historie, inkl. Prüfstatus).
2. Mandant aus diesem Punkt wählen (Name, Benutzerzahl und Datenmenge zum Zeitpunkt des Backups).
3. Namen des neuen Mandanten eingeben.
4. «Vorschau erstellen»: Schema-Kompatibilität, Datenmenge, Ablauf, Risiken.
5. Bestätigungsphrase (`KOPIE <id>`) und aktuellen TOTP-Code eingeben, starten.
6. Fortschritt und Ergebnis (inkl. Import-Hinweisen) bleiben auch nach einem Reload sichtbar.

Technisch: der Dump des Punkts wird in eine isolierte Temp-Datenbank `hocx_tsrc_<id>`
eingespielt (ggf. per Alembic auf den aktuellen Stand gebracht), die bestehende Export-Logik
sammelt den Mandanten **aus dieser historischen Datenbank**, die Dateien kommen direkt aus Borg
in einen Restore-Bereich des aktiven Speichers und werden beim Import serverseitig an ihren
endgültigen Ort kopiert. Kein ZIP, keine 2-GiB-Grenze – der normale ZIP-Import bleibt begrenzt.

Regeln für Identitäten und Berechtigungen:

| Daten | Verhalten |
|---|---|
| Mandant | neue interne ID, neuer Name; öffentliche IDs werden übernommen, wenn frei, sonst neu vergeben und alle Verweise umgeschrieben |
| Benutzer | E-Mail existiert bereits (z. B. im Original) → **nicht** übernommen, Hinweis; sonst neues Konto inkl. Rolle und Passwort-Hash |
| MFA | TOTP-Faktoren werden mit dem Schlüssel dieser Installation neu verschlüsselt (gleiches `ADMIN_AUTH_SECRET` nötig) |
| Freigabe-/Abgabelinks, Kalender-Feeds | Token bleibt, wenn frei; sonst neues Token (der alte Link bleibt beim Original) |
| Vertrauensbeziehungen, Album-Freigaben an andere Mandanten, Domains | **nie** übernommen – eine Kopie bekäme sonst Rechte, die Partner nur dem Original gegeben haben |
| Dateien | neu unter `tenant_imports/tenant-<neue id>/…`, jede Datei läuft durch die Virenprüfung |

Fehlerfall: Ein abgebrochener Import entfernt den halb angelegten Mandanten samt Dateien. Stürzt
der Worker mitten im Import ab, merkt sich der Auftrag die neue Mandanten-ID und räumt beim
nächsten Versuch auf. Temp-Datenbank und Restore-Bereich werden immer gelöscht.

## Voll-Restore im Admin-Portal

System → Backups → Wiederherstellung → «Vollständige Wiederherstellung». Ablauf, den der Worker
ausführt:

1. **Rettungspunkt**: geschütztes Backup des aktuellen Zustands (nur mit Begründung abwählbar).
2. **Vorbereitung**: Repository, Metadaten, Schema-Kompatibilität (neuer als der Code → Abbruch),
   keine laufende Storage-Migration, neue Generation `g<n>` im Zielprofil reservieren und prüfen,
   dass sie leer ist.
3. **Datenbank** in eine neue Datenbank `hocx_restore_<id>` (die Live-Datenbank wird nicht berührt).
4. **Objekte** aus Borg in die neue Generation – SHA-256 beim Lesen und beim Schreiben geprüft,
   ohne lokale Zwischenkopie.
5. **Prüfung**: ggf. Alembic-Upgrade (erst jetzt), Speicher der wiederhergestellten DB auf die neue
   Generation setzen (das alte Profil wird nicht blind aktiviert), Referenzprüfung
   (Register ↔ wiederhergestellte Objekte, DB-Verweise), Anwendungstest (alle ORM-Tabellen).
6. **Umschaltung**: volle Wartung, Schreib-Fence, Backup-Historie in die neue DB übernehmen,
   Verbindungen beenden, `hocx` → `hocx_pre_restore_<zeit>`, `hocx_restore_<id>` → `hocx`.
7. **Smoke-Test** gegen die neue Live-DB und den Speicher; bei Fehlern automatischer Rücktausch
   (Status «Zurückgerollt»), sonst Freigabe der Wartung.

Danach: Anmeldung prüfen, Stichproben in Mandanten, System → Backups → «Backup jetzt starten».
Die bisherige Datenbank bleibt als `hocx_pre_restore_<zeit>` erhalten (gesperrt für Verbindungen,
damit niemand versehentlich in den alten Stand schreibt; zum Einsehen
`ALTER DATABASE "…" WITH ALLOW_CONNECTIONS true`), die bisherige Storage-Generation bleibt
unberührt; beide erst nach einer bewussten Entscheidung entfernen:

```bash
docker compose -p hocx exec db psql -U hocx -d postgres -c 'DROP DATABASE "hocx_pre_restore_20261015120000"'
```

Rückweg nach einem erfolgreichen Restore (z. B. falscher Punkt gewählt): Wartung starten,
`swap-database --live hocx --restored hocx_pre_restore_<zeit>` (siehe CLI), Wartung freigeben.

Ein Absturz während des Tauschs ist abgesichert: jeder Schritt (auch der automatische
Rücktausch) steht *vor* der Umbenennung im Journal `backups/borg-work/restore-journal/<auftrag>.json`.
Beim Start des Workers und bei der Fortsetzung des Auftrags wird es gegen die tatsächlich
vorhandenen Datenbanken abgeglichen:

- Fehlt die Live-Datenbank, wird `hocx_pre_restore_<zeit>` (der bisherige Stand) zurückbenannt;
  der Tausch beginnt danach neu.
- Existieren Live- und `hocx_pre_restore_<zeit>`, die Restore-Datenbank aber nicht mehr, war der
  Tausch vollzogen; der Auftrag setzt mit Smoke-Test und Freigabe fort, ohne erneut zu tauschen.
- Lässt sich der Zustand nicht eindeutig zuordnen, wird nichts umbenannt oder gelöscht: das
  Journal erhält den Schritt `inconsistent`, der Auftrag endet mit `cutover_inconsistent`. Dann
  die Datenbanken (`\l` in psql) manuell prüfen, die richtige als `hocx` setzen
  (`swap-database`) und erst danach die Journal-Datei entfernen. Solange sie existiert, löscht
  auch die automatische Bereinigung keine Restore-Datenbank und keine Generation.

## Recovery-CLI (neuer Server oder ohne Backend)

Braucht weder laufendes Backend noch Redis noch eine hocX-Datenbank – nur Docker, den
Repository-Zugang und die Notfallmappe (Passphrase, Borg-Schlüssel-Export, `.env` mit
`STORAGE_CREDENTIALS_KEY`, `ADMIN_AUTH_SECRET`, `AUTH_SECRET`).

### Server verloren

1. Server nach RUNBOOK Abschnitt 8 aufsetzen, Repo-Checkout, `.env` aus der Notfallmappe,
   `BACKUP_SSH_KEY_PATH`/`BACKUP_KNOWN_HOSTS_PATH` neu anlegen (neuer Schlüssel auf der Box
   hinterlegen), `HOCX_VERSION` = Version des Backups (siehe `show`).
2. Nur Datenbank starten: `docker compose -p hocx up -d db`.
3. Repository prüfen und Punkte auflisten:

   ```bash
   CLI="docker compose -p hocx run --rm --no-deps --entrypoint python backup-worker -m app.backup.cli"
   $CLI info
   $CLI list --details
   $CLI show hocx-rp-20261015T061500Z-<id>
   ```

   Ist der Borg-Schlüssel im Repository beschädigt, zuerst `borg key import` mit dem
   Papier-Export (siehe Borg-Doku).
4. Wiederherstellen in eine **neue** Datenbank und einen Objektspeicher nach Wahl:

   ```bash
   # Ziel: neues S3 (z. B. anderer Anbieter) - Zugangsdaten als Dateien, nie als Argument
   $CLI restore-full --archive hocx-rp-… --target-db hocx_restored --storage s3 \
     --s3-provider hetzner --s3-endpoint https://fsn1.your-objectstorage.com --s3-region fsn1 \
     --s3-bucket hocx-prod --s3-prefix hocx --s3-addressing virtual \
     --s3-access-key-file /run/s3-ak --s3-secret-key-file /run/s3-sk
   # oder: lokales Dateisystem (leere Verzeichnisse)
   $CLI restore-full --archive hocx-rp-… --target-db hocx_restored --storage filesystem \
     --filesystem-root /app/storage --filesystem-abgabebox-root /app/abgabebox-storage
   ```

   Die CLI legt Profil, Generation und Speicherzustand in der wiederhergestellten DB neu an,
   aktiviert dort eine Wartung (`--no-maintenance` zum Abschalten) und prüft alle Verweise.
   `--resume` setzt einen abgebrochenen Objekt-Restore fort: eine vorhandene Zieldatenbank wird
   übernommen, wenn sie als vollständig aus genau diesem Punkt wiederhergestellt markiert ist
   (Datenbank-Kommentar, gesetzt nach erfolgreichem `pg_restore`); sonst bricht die CLI ab, ohne
   etwas zu verändern – dann die unvollständige Datenbank löschen und ohne `--resume` neu
   starten. `--allow-schema-upgrade` migriert
   ein älteres Schema kontrolliert. Auf einem fremden PostgreSQL ohne hocX-Rollen: `--no-owner`.
   Die eingeschränkten Rollen (`hocx_app`, `hocx_abgabebox`, `hocx_photo_worker`) sind
   clusterweit und nicht im Dump: `restore-full` legt fehlende an und setzt ihre Passwörter, wenn
   sie dem Aufruf mitgegeben werden (Variablen ohne Wert = aus der Shell, nicht im Argument):

   ```bash
   set -a; . ./.env; set +a
   CLI="docker compose -p hocx run --rm --no-deps -e APP_DB_PASSWORD -e ABGABEBOX_DB_PASSWORD \
        -e PHOTO_WORKER_DB_PASSWORD --entrypoint python backup-worker -m app.backup.cli"
   ```
5. Datenbank an ihren Platz: `$CLI swap-database --live hocx --restored hocx_restored`
   (existiert `hocx` noch nicht, wird nur umbenannt).

   Der Datenbankzugang kommt aus `DATABASE_URL`/`DATABASE_URL_FILE` des Containers. Für einen
   anderen Server die URL als Datei übergeben (`--database-url-file /run/db-url`), nicht als
   `--database-url postgresql://user:passwort@…` – ein Passwort im Argument steht in der
   Prozessliste und der Shell-History (die CLI warnt dann).
6. `./scripts/deploy.sh prod`, im Admin-Portal prüfen, Wartung unter System → Wartung freigeben.

### Datenbankzustand verloren, Dateispeicher intakt

Ein Restore schreibt Objekte immer in eine neue Generation; ein intakter Speicher wird dadurch
nicht überschrieben. Vorgehen wie oben mit `--storage s3` auf denselben Bucket – die CLI wählt
eine neue Generation. Den Platz der alten Generation gibt danach die Generationen-Bereinigung
unter System → Storage frei (bewusst, mit Bestätigung).

### Wechsel des S3-Anbieters

Backups sind anbieterunabhängig: das Manifest kennt nur `(namespace, key)` und SHA-256. Ein
Restore nach einem Anbieterwechsel schreibt in das gewählte Zielprofil (Admin-Portal:
Zielprofil-Auswahl, Standard = aktives Profil; CLI: `--storage s3 …`). Der alte Anbieter muss nicht
erreichbar sein. Nach einer normalen Storage-Migration arbeitet der Backup-Worker automatisch
mit der neuen Generation weiter.

## Nach der Wiederherstellung

- Sammel-/ZIP-Uploads, die zum Backup-Zeitpunkt noch verarbeitet wurden, sind nicht enthalten
  (nur ihr Auftrag). Sie schlagen beim nächsten Lauf von `gallery_upload_ingest` mit fehlender
  Datei fehl und müssen neu hochgeladen werden.
- Thumbnails und materialisierte Vorlagen entstehen beim ersten Zugriff neu.

## Beschädigte Backups

| Befund | Vorgehen |
|---|---|
| Integritätsprüfung meldet fehlende/beschädigte Inhalte | `cli verify <archiv>` für den betroffenen und den nächstälteren Punkt; sofort ein neues Backup («Backup jetzt starten») – fehlende Inhalte werden dabei neu übertragen, weil der Index gegen das Repository abgeglichen wird |
| `borg check` meldet Repository-Fehler | keine Retention/compact mehr ausführen; mit dem Wartungsschlüssel `borg check --repair` nur nach Rücksprache/Kopie; Storage-Box-Snapshot als Rückfall |
| Punkt als `*.invalid` markiert | entsteht, wenn die Nachprüfung direkt nach dem Schreiben scheitert; nicht verwenden, die Retention entfernt ihn nach 7 Tagen |
| Teilweises Backup (`partial`) | Liste der fehlenden Dateien im Detaildialog; die Dateien fehlten bereits im Speicher – Ursache im Objektspeicher suchen |

## Versionskompatibilität

Jeder Punkt speichert hocX-Version und Alembic-Revision. Restore-Pfade vergleichen sie mit dem
laufenden Code: gleiche Revision → direkt; ältere → nach der Wiederherstellung kontrolliertes
`alembic upgrade head` in der isolierten Datenbank; neuere/unbekannte → Abbruch, zuerst die
passende hocX-Version einspielen. Automatische Migrationen laufen nie vor dieser Prüfung.
