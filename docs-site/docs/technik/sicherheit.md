# Sicherheit

## Grundprinzipien

- **Tenant-Scoping**: Jeder schreibende Endpoint muss den Tenant der referenzierten
  Ressource laden und gegen `user.current_tenant_id` prüfen. Das ist das zentrale
  Muster, an dem sich alle neuen Endpoints orientieren müssen.
- **Getrennte Isolationsgrenzen**: Die Abgabebox ist über eine eigene, stark
  eingeschränkte Datenbankrolle isoliert (siehe [Architektur](architektur.md#abgabebox)),
  nicht nur über Applikationslogik.
- **Zwei unabhängige Login-Systeme**: Kunden-Login und Platform-Admin-Login sind
  vollständig getrennt (eigene Tabellen, eigene Session-Secrets).

## Betriebsmassnahmen

- Rate-Limiting auf Login-Endpoints (Kunde und Admin) via Traefik.
- Postgres nur an `127.0.0.1` gebunden, nicht öffentlich erreichbar.
- Datei-Uploads: Grössenlimit, MIME-Whitelist, Magic-Byte-Prüfung (nicht nur
  Client-Content-Type), Pfad-Traversal-Schutz.
- ClamAV-Scan für Abgabebox-Uploads.
- CI: automatischer Dependency-Audit (`pip-audit`/`npm audit`) und Secret-Scan
  (`gitleaks`) als hartes Gate.
- Security-Header (CSP, HSTS, X-Frame-Options, nosniff) in beiden Next.js-Anwendungen.
- Anwendungsseitiges Audit-Log (`audit_log`-Tabelle, `AuditService`): protokolliert Login,
  Protokoll-Status-Wechsel, User-Rollenänderungen, Finanz-Transaktionen, Bussen,
  Todo-Statuswechsel/-Löschungen, Exporte und die wichtigsten Admin-Panel-Aktionen. Noch
  nicht vollständig, siehe [Bekannte offene Punkte](offene-punkte.md).

## Audit-Historie

Am 2026-07-26 wurde ein vollständiger Sicherheitsaudit durchgeführt (Backend, Frontend,
Abgabebox, Admin-Panel, Infra, CI, DB). Alle kritischen Funde (Cross-Tenant-IDOR,
Account-Takeover via Teilnehmer-Merge, OIDC-Lücken, offener Postgres-Port, Stored XSS
via Content-Type-Confusion, fehlendes Rate-Limit auf Admin-Login) wurden am selben Tag
gefixt. Die verbleibenden mittleren/niedrigen Funde wurden im Anschluss ebenfalls
abgearbeitet.

Details zu offenen, bewusst zurückgestellten Punkten siehe
[Bekannte offene Punkte](offene-punkte.md).
