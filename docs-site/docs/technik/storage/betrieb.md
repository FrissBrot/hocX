# Installation, Konfiguration, Monitoring, Troubleshooting

## Installation

`scripts/deploy.sh <test|prod>` erledigt alles Nötige:

1. `.env` wird um fehlende Werte ergänzt (`scripts/lib/env_migrate.sh`, einmalig zufällig erzeugt,
   bestehende Werte werden nie überschrieben): `STORAGE_CREDENTIALS_KEY`, `GARAGE_RPC_SECRET`,
   `GARAGE_ADMIN_TOKEN`, `LOCAL_S3_ACCESS_KEY`/`LOCAL_S3_SECRET_KEY`,
   `LOCAL_S3_ABGABEBOX_ACCESS_KEY`/`LOCAL_S3_ABGABEBOX_SECRET_KEY`.
2. Geheimnisse landen als Compose-Secret-Dateien in `.secrets/` (0600).
3. `local-s3` startet, `storage-init` richtet Layout, Schlüssel und Buckets idempotent ein,
   das Backend legt das Profil «Lokales S3 (Garage)» an bzw. hält es aktuell.
4. `storage-worker` startet (gleiches Image wie das Backend).
5. Die Smoke-Checks führen `storage-init` erneut aus; schlägt die Einrichtung fehl, rollt der
   Deploy zurück.
6. Am Ende bringt `scripts/storage_controller.sh` das lokale S3 in den Sollzustand, und der
   Cron-Eintrag dafür wird eingerichtet bzw. aktualisiert (siehe [Lokales S3](lokales-s3.md)).

!!! warning "STORAGE_CREDENTIALS_KEY sichern"
    Ohne diesen Schlüssel lassen sich gespeicherte S3-Zugangsdaten nicht mehr entschlüsseln.
    Er gehört in das gleiche Secret-Backup wie `.env`.

Bis zur Erstmigration bleibt das Dateisystem aktiv – das Update allein verschiebt keine Datei.

## Konfiguration

| Variable | Bedeutung | Default |
|---|---|---|
| `STORAGE_CREDENTIALS_KEY` | Schlüssel für die Profil-Zugangsdaten (Backend, Abgabebox, Worker) | – (Pflicht, ≥ 32 Zeichen) |
| `LOCAL_S3_*` | Zugang zum lokalen Garage-S3 (siehe oben) | von `deploy.sh` erzeugt |
| `GARAGE_RPC_SECRET`, `GARAGE_ADMIN_TOKEN` | Garage intern | von `deploy.sh` erzeugt |
| `GARAGE_CAPACITY` | Kapazität des lokalen Knotens im Layout | `100G` |
| `STORAGE_FALLBACK_DAYS` | Rückfallfrist abgelöster Generationen | `14` |
| `STORAGE_WORK_ROOT` | lokaler Arbeitsbereich (Kopien, Caches) | `/app/storage-local/work` |
| `MAINTENANCE_CACHE_SECONDS` | wie lange Prozesse den Wartungszustand cachen | `2` |
| `ESTIMATOR_*` | vorsichtige Annahmen des Schätzers (Raten, Reserven) | siehe `config.py` |

## Externe Anbieter

Im Adminportal unter **System → Storage → Profil anlegen**:

| Anbieter | Endpoint | Region | Adressierung |
|---|---|---|---|
| Hetzner Object Storage | leer lassen (wird `https://<region>.your-objectstorage.com`) | `fsn1`, `nbg1`, `hel1` | Virtual-Host |
| AWS S3 | leer lassen | z. B. `eu-central-2` | Auto/Virtual |
| andere (Ceph RGW, Wasabi, …) | `https://…` | laut Anbieter | meist Path |

Regeln: externe Endpoints nur per HTTPS; Bucket-Namen nach S3-Konvention; Präfixe dürfen sich mit
keinem anderen Profil im selben Bucket überschneiden. Empfohlen ist ein zweiter Bucket für die
Abgabebox mit eigenen, auf diesen Bucket beschränkten Zugangsdaten. Danach **Verbindung testen**:
der Test schreibt, liest, prüft (Grösse + SHA-256), listet und löscht ein isoliertes Testobjekt in
beiden Buckets. Nur getestete Profile können Ziel einer Migration sein; jede Änderung an Ort oder
Zugangsdaten verlangt einen neuen Test.

Profile, die aktiv sind, von einer offenen Migration verwendet werden oder noch eine
Generation in der Rückfallfrist halten, lassen sich weder löschen noch in ihrem Ort ändern.

## Monitoring

- **/admin/jobs**: `storage_migration_worker` (Heartbeat, Alarm nach 5 min Stille),
  `maintenance_supervisor`, `storage_journal_cleanup`, `storage_purge` (entfernt gelöschte
  Objekte nach dem Commit, pausiert bei Wartung/Fence), `storage_controller` (Host-Cron).
- **/admin/system** und ntfy: `object_storage` (aktiver Speicher erreichbar, kritisch bei Ausfall),
  `storage_migration` (Warnung bei hängendem Worker, Retries oder dauerhaft fehlgeschlagenen
  Objekten, kritisch bei `rollback_required`), `storage` (lokaler Plattenplatz).
- **Integritätsprüfung**: `docker compose exec backend python -m app.workers.storage_verify --full`
  (Exit 0 = konsistent, 2 = Abweichungen, Bericht mit `--json`).

## Troubleshooting

| Symptom | Ursache / Abhilfe |
|---|---|
| Uploads liefern 503 «Speichern ist gerade kurz gesperrt» | Schreib-Fence aktiv (Cutover/Wartung). Status unter System → Storage; ein liegengebliebenes Fence löst der Worker beim nächsten Durchlauf bzw. beim Abbruch. |
| 503 «Dateispeicher vorübergehend nicht erreichbar» | aktives S3 weg (z. B. `local-s3` gestoppt). `docker compose ps local-s3`, `scripts/storage_controller.sh`; Fehler stehen im Fehlerprotokoll. |
| Migration steht in `retrying` | `last_error` im Adminportal; nach Behebung läuft sie mit Backoff weiter (max. 10 Versuche, danach `failed`, Quelle bleibt aktiv). |
| Objekte `dead` | dauerhaft fehlgeschlagen; «Fehlgeschlagene erneut versuchen». Fehlen sie schon in der Quelle (`source_missing`), mit «Fehlende bestätigen» bewusst ausweisen. |
| Worker-Heartbeat veraltet | `docker compose logs storage-worker`; nach Neustart übernimmt er die Migration (Lease läuft nach 60 s ab). |
| Profil lässt sich nicht ändern | aktiv oder in Migration/Rückfallfrist – neues Profil anlegen und migrieren. |
| Login zeigt Wartung, obwohl Arbeiten fertig sind | Wartung endet nur über die Freigabe (System → Wartung); offene Bedingungen werden dort angezeigt. |
