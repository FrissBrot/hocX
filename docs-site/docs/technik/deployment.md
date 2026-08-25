# Deployment

Es gibt drei Umgebungen; die vollständigen Befehle stehen in `RUNBOOK.md` im
Repository-Root. Diese Seite fasst die Grundzüge zusammen.

| | Dev | Test | Prod |
|---|---|---|---|
| Wo | dieser Server | eigener Test-Server | eigener Prod-Server |
| Domain | hocx.example.com | test.hocx.ch | hocx.ch |
| Code-Quelle | lokal, `build:` aus Source | Docker-Image von GHCR | Docker-Image von GHCR |

## Ablauf für ein Release

1. Änderungen werden auf `main` gemerged.
2. Auf GitHub den manuellen Workflow `Build test candidate images` starten und dabei in
   der Actions-UI den gewuenschten Branch/Tag waehlen (typischerweise `main`).
   Der Workflow baut automatisch den neuesten Commit dieses Refs und erzeugt selbst einen
   eindeutigen Candidate-Tag wie `test-20260825-abc1234-r42`.
3. Auf dem Test-Host in `.env` `HOCX_VERSION` auf genau diesen Candidate-Tag setzen und
   `./scripts/deploy.sh test` ausfuehren. Das Skript macht automatisch:
   DB-Backup → Images pullen → Neustart (Alembic migriert automatisch) → Smoke-Checks
   fuer Backend, Frontend, Abgabebox, Docs und ClamAV.
4. Direkt danach `./scripts/verify_release.sh test` ausfuehren. Das prueft die lokalen
   Services, Alembic-Head und die externen Traefik-Domains.
5. Wenn Test gruen ist, auf GitHub den manuellen Workflow
   `Promote tested release images` starten: `source_tag=<candidate>`,
   `release_tag=vX.Y.Z`. Dieser Schritt baut **nicht** neu, sondern setzt den finalen
   Release-Tag auf dasselbe bereits getestete Image.
6. Auf dem Prod-Server in `.env` `HOCX_VERSION=vX.Y.Z` setzen, `./scripts/deploy.sh prod`
   und danach `./scripts/verify_release.sh prod` ausfuehren.
7. Optional danach ein GitHub-Release fuer Changelog/Release Notes erstellen. Das ist ab
   jetzt rein dokumentarisch und triggert keinen zweiten Image-Build mehr.

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

    Alternativ als Wrapper:
    `./scripts/dev.sh`
    `./scripts/dev.sh stop`
    `./scripts/dev.sh down`
    `./scripts/dev.sh up --profile docs --profile scan`

    Optional:
    `--profile scan` für ClamAV,
    `--profile docs` für die Doku auf `localhost:3002`,
    `--profile edge` für lokalen Traefik.

!!! info "Test und Prod nutzen denselben Release-Stack"
    Der dedizierte Test-Host laeuft bewusst mit denselben Release-Compose-Dateien wie
    Prod (`docker-compose.release.yml` + ClamAV + Traefik). Unterschiede kommen nur aus
    `.env`, `PROJECT_NAME` (`hocx-test` vs. `hocx`) und dem jeweils gepinnten
    `HOCX_VERSION`-Tag.

## Rollback

`HOCX_VERSION` in `.env` auf die vorherige Version setzen und erneut deployen. Bei
**destruktiven** Schema-Änderungen (Spalte gelöscht/Typ geändert) reicht ein
Code-Rollback nicht – zusätzlich muss das vor dem Update gezogene Backup eingespielt
werden.
