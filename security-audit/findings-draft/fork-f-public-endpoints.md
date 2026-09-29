# Fork F — Public Endpoints (`share_links.py`, `public_share.py`, `submission_assignments.py`)

Scope: Audit-Abschnitt 21. Dateien vollständig gelesen: `backend/app/api/routes/share_links.py`,
`backend/app/api/routes/public_share.py`, `backend/app/services/share_link_service.py`,
`backend/app/api/routes/submission_assignments.py`, Auszüge `backend/app/services/
submission_service.py` (`get_stored_file_for_upload`, `get_assignment`), `backend/app/services/
submission_link_service.py` (Tenant-Scoping), `backend/app/models/entities.py`
(`SubmissionUpload`, `SubmissionLink`). Keine Codeänderungen, keine Commits.

## Wichtige Einordnung

`submission_assignments.py` ist **nicht öffentlich** — jede Route verlangt `get_current_user` +
`require_abgabebox_read`/`require_abgabebox_write`. Es ist die authentifizierte Tenant-seitige
Verwaltung der Abgabebox-Integration (Links/Assignments/Uploads-Ansicht), nicht die öffentliche
Grenzfläche selbst (die liegt vollständig in `abgabebox-backend`, bereits in Fork D/Phase 1
geprüft). Echte unauthentifizierte Endpoints in diesem Scope sind ausschliesslich die 4 Routen
in `public_share.py`.

## Geprüft, kein Fund

- **Token-Entropie** (`share_link_service.generate_token`): `secrets.token_urlsafe(24)` = 192 Bit,
  identisch zum bereits geprüften Abgabebox-Link-Token. Nicht praktisch erratbar.
- **Expiry/Revocation serverseitig durchgesetzt**: `resolve_active()` prüft `revoked_at` UND
  `expires_at` bei JEDEM Aufruf (nicht nur beim Erstellen), alle 4 `public_share.py`-Routen rufen
  ausschliesslich `_resolve_link_or_404` → `resolve_active`. Kein Cache/Bypass gefunden.
- **404 statt 403/410 bei abgelaufen/widerrufen/unbekannt**: bewusst ununterscheidbar (Kommentar
  im Code), verhindert Enumeration-Oracle. Konsistent mit dem Abgabebox-Muster.
- **IDOR über `file_id`**: `_resolve_file_or_404` iteriert ausschliesslich über
  `_clean_stored_files_for_link(db, link)` (Dateien, die tatsächlich zu DIESEM Link/Album
  gehören, UND `scan_status == "clean"`) — ein `file_id` aus einem anderen Link/Tenant matcht
  nie, unabhängig davon ob die UUID real existiert. Kein Cross-Link/Cross-Tenant-Zugriff möglich.
- **Rate-Limiting/Enumeration-Schutz**: alle 4 `public_share.py`-Routen rufen
  `enforce_rate_limit(f"public-share:{ip}", ...)` (60/min Übersicht+Download, 300/min Thumbnail,
  20/min ZIP-Download) — App-seitig vorhanden, unabhängig von Traefik-Labels (die laut
  `components/deployment.md` für DIESE Route nicht separat gelistet waren — App-Level-Limit ist
  hier also die primäre Verteidigung, nicht nur Traefik). Kein Finding, aber Empfehlung: prüfen
  (ausserhalb dieses Forks), ob `public-share` auch ein Traefik-Label bekommen sollte als
  zusätzliche Schicht analog zu Abgabebox — Defense-in-Depth-Vorschlag, kein Fund.
- **Erzeugung von Share-Links auf fremde Tenant-Ressourcen**: `create_share_link` prüft
  `payload.album_id` über `photo_album_share_service.get_accessible_album(db, album_id,
  user.current_tenant_id)` (404 falls nicht zugreifbar) bzw. `payload.file_ids` über
  `service.list_tenant_files(db, user.current_tenant_id, file_ids=ids, ...)` + Mengen-Vergleich
  (404 falls eine ID nicht im eigenen Tenant liegt) — kein Weg, einen Link auf eine fremde
  Ressource zu erzeugen. `revoke_share_link` prüft `link.tenant_id != user.current_tenant_id`.
- **`submission_assignments.py` Tenant-Scoping der Upload-Datei-Endpoints** (Content/Thumbnail/
  Tags/Metadata): `upload_id`/`file_id` werden ungescoped aufgelöst (`SubmissionUpload` hat kein
  eigenes `tenant_id` — nur transitiv über `assignment_id`), ABER `get_stored_file_for_upload`
  verifiziert zusätzlich, dass `file_id` tatsächlich zu GENAU diesem `upload_id` gehört
  (`list_upload_files(db, upload_id=...)`-Iteration, kein freies Cross-Matching), UND danach wird
  `assignment.tenant_id != user.current_tenant_id` geprüft, bevor irgendetwas zurückgegeben wird.
  Ein Tenant-A-User mit erratener/geleakter Tenant-B-`upload_id` + `file_id` bekommt spätestens am
  finalen Tenant-Check ein 404. Kein IDOR gefunden — korrekt nach demselben Muster, das Fork A
  bereits repo-weit als konsistent verifiziert hat.
- **`download_all_files_zip`**: `upload_id`/`file_id` stammen hier NICHT aus Client-Input,
  sondern aus `service.get_assignment_elements(db, assignment)` (bereits tenant-verifiziertes
  `assignment`) — keine Client-kontrollierten IDs im Spiel, kein Bypass möglich. Zip-Slip
  ausgeschlossen (`arcname` wird aus `stored_file.original_name` gebaut, keine Pfadanteile aus
  Client-Input).
- **`submission_link_service`**: `SubmissionLink` hat eigene `tenant_id`-Spalte, `get_link()`
  ruft `get_by_public_id(..., tenant_id=tenant_id)` korrekt mit Tenant-Filter auf.
- **Datenpreisgabe in `PublicShareRead`/`PublicShareFile`**: nur `name`, Dateiname, MIME-Typ,
  Grösse, generierte Thumbnail/Download-URLs (die selbst wieder denselben Token brauchen) —
  keine internen DB-IDs, keine Tenant-Metadaten, keine Angaben zu anderen Freigaben.

## [PUB-01] [INFO] `/api/clamav/status` gibt Scanner-Version an jeden authentifizierten Abgabebox-Reader zurück, unabhängig vom Tenant

Status: CONFIRMED (Informationsfund, keine Sicherheitsgrenze verletzt)

Betroffene Datei: `backend/app/api/routes/submission_assignments.py:375-386`

### Beschreibung
`GET /api/clamav/status` verlangt nur `require_abgabebox_read(user)` (keine Tenant-spezifische
Prüfung, da ClamAV eine geteilte Infrastruktur-Komponente ist, keine Tenant-Ressource) und gibt
`{"status": ..., "version": ...}` zurück — die ClamAV-Version ist für jeden Tenant mit gebuchtem
Abgabebox-Feature sichtbar, auch für andere Tenants als den, der die Info "gehört". Da es sich um
eine geteilte Infrastrukturkomponente handelt (dieselbe ClamAV-Instanz für alle Tenants), ist das
kein Cross-Tenant-Datenleck im eigentlichen Sinn, aber technisch eine globale Info, die keine
tenant-spezifische Berechtigungsprüfung durchläuft.

### Impact
Sehr gering: Versionsnummer eines bekannten Open-Source-Scanners, kein Secret, keine
Tenant-Daten. Potenziell nützlich für einen Angreifer, der gezielt nach einer CVE für eine
bestimmte ClamAV-Version sucht — aber jeder Tenant-User mit Abgabebox-Feature (nicht nur
Angreifer) sieht das ohnehin schon für seinen eigenen Zweck.

### Recommended Fix
Kein Handlungsbedarf zwingend. Falls gewünscht: Versionsstring aus der Response entfernen oder
nur `status` (online/offline) an Tenants ausgeben, volle Version nur im Platform-Admin-Panel.

### Evidence
`submission_assignments.py:375-386`.

## Fazit

Keine CONFIRMED/NEEDS_VERIFICATION-Findings mit Sicherheitsimpact in diesem Scope. Ein Info-Fund
(PUB-01, kein Handlungsbedarf). Die öffentliche Freigabe-Grenzfläche (`public_share.py`) ist
solide implementiert: gleiche Entropie/Rate-Limiting/404-Unschärfe wie das bereits geprüfte
Abgabebox-Muster, keine IDOR-Lücke gefunden.

Status: REVIEWED_WITH_FINDINGS (1x INFO)
