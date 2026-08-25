# Deployment

Es gibt drei Umgebungen; die vollständigen Befehle stehen in `RUNBOOK.md` im
Repository-Root. Diese Seite fasst die Grundzüge zusammen.

| | Dev | Test | Prod |
|---|---|---|---|
| Wo | dieser Server | dieser Server (separates Compose-Projekt) | eigener Server |
| Domain | hocx.example.com | test.hocx.example.com | hocx.ch |
| Code-Quelle | lokal, `build:` aus Source | Docker-Image von GHCR | Docker-Image von GHCR |

## Ablauf für ein Release

1. Änderungen werden auf `main` gemerged.
2. Auf GitHub ein Release mit Semver-Tag erstellen (z. B. `v1.2.0`).
3. `.github/workflows/release.yml` baut automatisch die Images
   (`hocx-backend`, `hocx-frontend`, `hocx-abgabebox-backend`,
   `hocx-abgabebox-frontend`) und pusht sie nach GHCR.
4. In `hocX-test/.env` `HOCX_VERSION` setzen, `./scripts/deploy.sh test` ausführen.
   Das Skript macht automatisch: DB-Backup → Images pullen → Neustart (Alembic migriert
   automatisch) → Smoke-Checks für Backend, Frontend, Abgabebox, Docs und ClamAV.
5. Nach erfolgreicher Verifikation auf Test dieselben Schritte auf dem Prod-Server
   wiederholen.

## Wichtige Betriebsregeln

!!! warning "DNS vor Stack-Start setzen"
    Traefik holt beim ersten Start sofort ein Let's-Encrypt-Zertifikat. Zeigt die
    Domain noch nicht auf den Server, zählt ein Fehlversuch gegen Let's Encrypts
    Rate-Limit (5 Fehlversuche/Domain/Stunde). Bei einer neuen Domain daher immer erst
    den DNS-Eintrag setzen, dann den Stack starten.

!!! warning "Riskante Schema-Änderungen über zwei Releases"
    Spalten umbenennen/löschen oder Typen ändern immer in zwei Schritten ausrollen
    (Release A: neue Spalte hinzufügen + befüllen, Release B: alte Spalte entfernen).
    So bleibt jeder Schritt rückwärtskompatibel und ein Rollback ohne Backup-Restore
    möglich.

!!! info "Lokales Entwickeln nutzt jetzt einen eigenen Overlay"
    Für echtes lokales Dev mit Hot-Reload:
    `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`

    Optional:
    `--profile scan` für ClamAV,
    `--profile docs` für die Doku auf `localhost:3002`,
    `--profile edge` für lokalen Traefik.

## Rollback

`HOCX_VERSION` in `.env` auf die vorherige Version setzen und erneut deployen. Bei
**destruktiven** Schema-Änderungen (Spalte gelöscht/Typ geändert) reicht ein
Code-Rollback nicht – zusätzlich muss das vor dem Update gezogene Backup eingespielt
werden.
