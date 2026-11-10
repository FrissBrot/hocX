# Lokales S3 (Garage)

## Warum Garage

MinIO Community wurde 2025/2026 eingestellt (keine Images mehr, Repository archiviert). hocX nutzt
darum [Garage](https://garagehq.deuxfleurs.fr/) (aktiv gepflegt, S3-kompatibel, klein). Getestet
mit boto3: Metadaten, Byte-Ranges, Multipart inkl. Abbruch, serverseitige Kopie, Listing.
Nicht unterstützt: Objektversionierung und bedingte Schreibzugriffe (`If-None-Match`) – hocX ist
auf beides nicht angewiesen (Generationen, SHA-256-Prüfung, Journal).

## Dienste

| Dienst | Aufgabe |
|---|---|
| `local-s3` | `dxflrs/garage:v2.3.0` per Digest gepinnt, Volume `local_s3_data`, Healthcheck `garage status`, `restart: unless-stopped`, 512 MB / 1 CPU, `read_only`, keine Ports, nur Netz `storage` |
| `storage-init` | einmaliger Init-Container (`infra/garage/bootstrap.py`): Layout, Schlüssel, Buckets `hocx-main` und `hocx-abgabebox`, Rechte; idempotent |

Konfiguration: `infra/garage/garage.toml` (Einzelknoten, `replication_factor = 1`, fsync an).
Geheimnisse kommen nur aus Secret-Dateien bzw. der Umgebung.

## Host-Controller

`scripts/storage_controller.sh` läuft auf dem Host (Cron alle 5 min über `run_job.sh`, zusätzlich
am Ende von `deploy.sh`) und entscheidet über die DB-Funktion `storage_local_s3_decision()`:

| Grund | lokales S3 |
|---|---|
| aktiver Speicher | läuft |
| Ziel der Erstmigration (Dateisystem noch aktiv) | läuft |
| Quelle/Ziel einer offenen Migration | läuft |
| Generation in der Rückfallfrist, offene Bereinigung | läuft |
| nicht verifizierte Objekte einer abgeschlossenen Migration | läuft |
| von einem Admin angefordert (2 h, «Lokales S3 bereitstellen») | läuft |
| nichts davon | darf gestoppt werden |

Gestoppt wird ausschliesslich mit `docker compose stop` – Container und Volume bleiben, es wird
nichts gelöscht. Unbekannte Gründe oder eine nicht erreichbare Datenbank führen nie zum Stopp.
Wird das lokale S3 wieder gebraucht (z. B. vor einer Migration zurück), startet der Controller es,
wartet auf den Healthcheck und führt `storage-init` erneut aus.

Den Cron-Eintrag richtet `deploy.sh` selbst in der crontab des Deploy-Benutzers ein und hält
ihn aktuell (Projekt, Compose-Dateien inkl. `docker-compose.local.yml`, Pfade). Erkennbar am
Kommentar `# hocx-managed:<projekt>:storage_controller`; andere Zeilen bleiben unverändert, ein
von Hand eingetragener Job wird nicht verdoppelt. `HOCX_MANAGE_CRON=false` in `.env` schaltet das
ab. Auf Prod sieht der Eintrag so aus:

```cron
*/5 * * * * /docker/hocX/scripts/run_job.sh storage_controller env HOCX_COMPOSE_PROJECT=hocx HOCX_COMPOSE_FILES="/docker/hocX/docker-compose.release.yml /docker/hocX/docker-compose.clamav.yml /docker/hocX/docker-compose.traefik.yml" HOCX_ENV_FILE=/docker/hocX/.env /docker/hocX/scripts/storage_controller.sh >> /docker/hocX/backups/storage_controller.log 2>&1 # hocx-managed:hocx:storage_controller
```
