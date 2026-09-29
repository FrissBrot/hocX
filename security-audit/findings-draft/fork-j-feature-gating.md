# Fork J — Feature-Gating (Audit-Abschnitt 10)

Scope: alle Feature-Codes im System, Gating-Matrix, gezielte Bypass-Prüfung (Tenant-Import/-Clone,
Domain-Aktivierung vs. -Anlage, Feature-Downgrade, Storage-Pakete/Tenant-Trust). Keine
Codeänderungen, keine Commits.

## Feature-Katalog (vollständig, per grep verifiziert)

Nur **3** Feature-Codes existieren im gesamten System (`feature`-Tabelle, Migrationen
`0084_tenant_feature`, `0085_plan_pricing`, `0086_custom_domain_enforcement`):

| Feature | Eingeführt | Zweck |
|---|---|---|
| `finance` | 0084 | Kassenbuch, Beiträge, Bussen |
| `abgabebox` | 0085 | Öffentliche Upload-Box |
| `custom_domain` | 0086 | Eigene Domain statt hocX-Standarddomain |

`Feature`/`Plan`/`PlanFeature`/`TenantFeature` (siehe `entities.py:129-187`): `tenant_feature` ist
laut explizitem Code-Kommentar "die alleinige Quelle der Wahrheit fürs Enforcement" —
`Tenant.plan_code` ist nur der Vertrag/die Baseline, kein Laufzeit-Gate.

## Feature-Gating-Matrix

| Feature | UI-Gate | API-Gate | Service-Gate | Alternative Pfade geprüft | Fail-Default |
|---|---|---|---|---|---|
| `finance` | Tenant-Settings/Abo-Seite blendet Menüpunkte aus (nicht als Security-Grenze gewertet) | `require_feature(user, "finance")` in `fines.py` (3×) | `require_finance_read/write`/`require_all_fines_read` in `security.py:235-260` rufen intern `require_feature(..., "finance")` | Kein Endpoint gefunden, der Finance-Daten ohne diese Guards zurückgibt (Fork G hat `finance.py`/`fines.py` vollständig gelesen) | **deny-by-default** (`code in user.current_tenant_features`, leeres Set = alles verboten) |
| `abgabebox` | dito | `require_abgabebox_read/write` (`security.py:252-260`), `submission_assignments.py` durchgehend | dito | Abgabebox-Backend selbst prüft KEIN Feature-Flag (separater Service, vertraut dem Haupt-Backend, dass nur gebuchte Tenants einen Link erzeugen — verifiziert: `submission_link_service.create_default_link` wird bei Tenant-Erstellung IMMER aufgerufen, unabhängig vom Feature-Status, siehe unten FEAT-02) | deny-by-default, ABER siehe FEAT-02 |
| `custom_domain` | `tenant-domains-manager.tsx` | `require_feature(actor, "custom_domain")` in `tenant_service.py::create_domain` (Z. 222) UND `verify_domain` (Z. 270) | — | **Laufender Betrieb einer bereits aktiven Domain prüft das Feature NICHT erneut** — siehe FEAT-01 | deny-by-default nur bei Erst-Anlage/Verifizierung, NICHT bei fortlaufendem Gebrauch |

## [FEAT-01] [MEDIUM] Aktive Custom-Domains bleiben nach Feature-Entzug unbegrenzt funktional

Status: **CONFIRMED**
CWE: CWE-862 (Missing Authorization) / Business-Logic-Bypass eines Paid-Features

Betroffene Dateien/Funktionen:
- `backend/app/services/admin_tenant_service.py::update_tenant_features` (Zeilen 423-440)
- `backend/app/services/traefik_config_service.py::regenerate` (Zeile 104-111)
- `backend/app/services/domain_health_check_service.py::run_health_check` (Zeile 12-18)

### Security Invariant
Abschnitt 10: "Ein deaktiviertes Feature darf nicht durch direkten API-Zugriff nutzbar sein" —
hier erweitert auf "nicht durch fortlaufenden, bereits provisionierten Zugriff weiter nutzbar
bleiben".

### Beschreibung
`require_feature(actor, "custom_domain")` wird ausschliesslich beim **Anlegen**
(`create_domain`) und **Verifizieren** (`verify_domain`) einer Domain geprüft. Sobald eine Domain
den Status `active` erreicht hat, prüft **keiner** der beiden Code-Pfade, die eine aktive Domain
tatsächlich am Leben halten, das Feature erneut:
- `traefik_config_service.regenerate()` selektiert `TenantDomain` ausschliesslich über
  `WHERE status = 'active'` — kein Join/Check gegen `tenant_feature`.
- `domain_health_check_service.run_health_check()` (periodischer Background-Loop) ebenso nur
  `WHERE status = 'active'`.
- `admin_tenant_service.update_tenant_features()` (der Endpunkt, über den ein Platform-Admin
  einem Tenant das Feature `custom_domain` entzieht) löscht ausschliesslich die
  `TenantFeature`-Zeile — es gibt **keinen** Code, der bei Feature-Entzug zugehörige
  `TenantDomain`-Zeilen deaktiviert, löscht oder auch nur markiert, und `regenerate()`/der
  Health-Check-Loop werden dabei nicht einmal aufgerufen.

Ergebnis: Ein Tenant, dem `custom_domain` entzogen wird (Downgrade, Zahlungsausfall, manuelle
Admin-Aktion), behält seine bereits aktive(n) Domain(s) **unbegrenzt weiter funktionsfähig** —
Traefik routet weiterhin Traffic dorthin, der Health-Check hält sie sogar aktiv "gesund". Erst ein
expliziter `DELETE .../domains/{id}` (der laut Fork B bewusst OHNE Feature-Gate implementiert ist,
damit eine Domain nach Downgrade überhaupt entfernbar bleibt) beendet die Nutzung — dieser Schritt
ist aber nirgends automatisch an den Feature-Entzug gekoppelt.

### Root Cause
Feature-Gating wurde als "Gate bei Erstellung" implementiert, nicht als "Invariante über die
gesamte Lebensdauer der Ressource". Die drei o. g. Stellen wurden nach der Feature-Einführung
(0085/0086) nicht um einen Feature-Check erweitert, vermutlich weil sie historisch vor dem
Feature-System entstanden (Traefik-Regenerierung/Health-Check existieren unabhängig vom
Billing-Modell).

### Preconditions
Keine Angreifer-Rechte nötig — der Effekt tritt automatisch bei jeder normalen Admin-Aktion ein
(Feature-Entzug via Platform-Admin-Panel). Kein Exploit im klassischen Sinn, sondern ein
Business-Logic-Bypass, der sich von selbst manifestiert.

### Attack Path (bzw. Ablauf, der den Bypass auslöst)
1. Tenant hat `custom_domain` gebucht, legt eine Domain an, verifiziert sie (`status='active'`).
2. Tenant wechselt auf einen Plan ohne `custom_domain` ODER ein Platform-Admin entzieht das
   Feature manuell über `PATCH .../tenants/{id}/features`.
3. `update_tenant_features` löscht die `TenantFeature`-Zeile — die `TenantDomain`-Zeile bleibt
   unverändert `status='active'`.
4. Die Domain wird weiterhin von `regenerate()`/dem Health-Check-Loop bedient — Endnutzer
   erreichen den Tenant weiterhin über die eigene Domain, unbegrenzt, ohne dass das Feature
   bezahlt/gebucht ist.

### Proof of Concept
Kein aktiver Exploit nötig — Nachweis durch Code-Lektüre der drei Funktionen (kein Feature-Check
in keiner der drei). Praktischer Nachweis wäre trivial: Domain anlegen+verifizieren, Feature per
Admin-API entziehen, `curl` gegen die Domain zeigt weiterhin die Tenant-Anwendung.

### Impact
MEDIUM (Business-Logic/Payment-Bypass, kein Datenzugriffsverstoss über Tenant-Grenzen hinweg —
der Tenant sieht weiterhin nur seine eigenen Daten, nur über eine Domain, für die er nicht mehr
zahlt). Finanzieller Schaden proportional zur Anzahl betroffener Tenants/Dauer.

### Existing Mitigations
`delete_domain` erlaubt manuelles Aufräumen (bewusst ohne Feature-Gate). Kein automatischer
Mechanismus.

### Why Existing Mitigations Are Insufficient
Nichts erinnert einen Platform-Admin daran, nach Feature-Entzug auch die Domain zu löschen — die
beiden Aktionen sind im UI/API vollständig entkoppelt.

### Recommended Fix
`update_tenant_features` (bzw. eine gemeinsame Stelle, die Feature-Änderungen verarbeitet) sollte
bei Entzug von `custom_domain`: entweder (a) alle aktiven `TenantDomain`-Zeilen des Tenants mit
`purpose='app'`/`'abgabebox'` auf einen neuen Status (z. B. `'suspended'`) setzen und
`traefik_config_service.regenerate()` aufrufen, sodass sie aus dem Router-Config verschwinden,
aber (anders als bei echtem Löschen) beim erneuten Zubuchen ohne erneute DNS-Verifikation
reaktivierbar bleiben, oder (b) zumindest `regenerate()`/den Health-Check so erweitern, dass sie
zusätzlich gegen `tenant_feature` joinen und inaktive-Feature-Domains auslassen. Variante (b) ist
der kleinere Eingriff (ein zusätzlicher JOIN in zwei Funktionen).

### Regression Test
Test: Tenant mit aktiver, verifizierter Custom-Domain; Feature `custom_domain` per
`update_tenant_features` entziehen; `traefik_config_service.regenerate()` bzw. eine
äquivalente "wird diese Domain noch bedient?"-Prüfung aufrufen; erwarten, dass die Domain NICHT
mehr im generierten Router-Config auftaucht.

### Evidence
`admin_tenant_service.py:423-440`; `traefik_config_service.py:104-111`;
`domain_health_check_service.py:12-18`.

---

## [FEAT-02] [MEDIUM] Tenant-Import stellt aktive Custom-Domains wieder her, ohne dass der neue Tenant das Feature je gebucht hat

Status: **CONFIRMED** (Spezialfall/Verschärfung von FEAT-01, gleicher Root Cause, zusätzlicher
eigenständiger Auslöser)
CWE: CWE-862

Betroffene Datei/Funktion: `backend/app/services/tenant_import_service.py::_import_tenant_domains`
(Zeilen 419-451), aufgerufen aus `_run()` (Zeile 193) **vor** jeder Plan-/Feature-Zuweisung.

### Beschreibung
`TenantImportService._run()` importiert eine vollständige Tenant-Sicherung (ZIP mit
`manifest.json`, Platform-Admin-only über `admin.py:604`). `_import_tenant_domains()` übernimmt
`TenantDomain`-Zeilen der Quelle 1:1 inkl. `status`/`verification_token`/`verified_at` — laut
eigenem Docstring bewusst, damit eine bereits DNS-verifizierte Domain nicht erneut verifiziert
werden muss. Ist `status == 'active'`, wird sofort `traefik_config_service.regenerate()`
aufgerufen. Der gesamte Import-Code (`tenant_import_service.py`) enthält **keine einzige**
Referenz auf `TenantFeature`/`feature` — der neu erzeugte Tenant hat nach dem Import **keine**
`tenant_feature`-Zeilen (leeres Set, deny-by-default für `require_feature`-Checks bei künftigen
API-Aufrufen), besitzt aber bereits eine voll funktionsfähige, aktiv gerouteten Custom-Domain.
`TenantCloneService` (`tenant_clone_service.py`, komplett gelesen) referenziert dagegen an keiner
Stelle `TenantDomain` — Klonen kopiert keine Domains, ist also von diesem Fund nicht betroffen.

### Preconditions
Platform-Admin-Rechte, um einen Tenant-Export zu importieren (kein Fremdzugriff nötig – `admin.py`
ist laut Fork B vollständig `require_admin_write`-gated). Kein böswilliger externer Angreifer,
aber ein interner Vorgang (Migration/Restore/Support-Fall), der ungewollt einen kompletten
Feature-Freischein für Custom-Domains erzeugt.

### Attack Path
1. Platform-Admin exportiert Tenant A (hat `custom_domain` gebucht, aktive Domain).
2. Platform-Admin importiert den Export als neuen Tenant B (z. B. Testsystem, Kundenmigration,
   Wiederherstellung nach Vertragswechsel ohne `custom_domain`).
3. Tenant B hat sofort eine aktive, geroutete Custom-Domain — ohne dass irgendwo `custom_domain`
   für Tenant B gebucht wurde.

### Impact
MEDIUM — wie FEAT-01, zusätzlich potenziell überraschend für Admins ("Import hat versehentlich
ein Paid-Feature freigeschaltet").

### Recommended Fix
Gleiche Fix-Richtung wie FEAT-01 (b): `_import_tenant_domains` sollte importierte Domains
grundsätzlich auf einen nicht-aktiven Status setzen (z. B. `'pending'`, DNS-Token beibehalten für
schnelle Re-Verifizierung) UND/ODER die zentrale Fix-Lösung aus FEAT-01 (Feature-Join in
`regenerate()`/Health-Check) würde dieses Szenario automatisch mit abdecken, ohne Import-Code
separat anfassen zu müssen — **Empfehlung: FEAT-01 Variante (b) zuerst umsetzen, dann prüfen ob
FEAT-02 dadurch bereits geschlossen ist** (voraussichtlich ja, da beide über dieselbe
`regenerate()`/Health-Check-Logik laufen).

### Regression Test
Tenant-Export mit aktiver Custom-Domain erzeugen, in eine frische Installation ohne
`custom_domain`-Feature-Zuweisung importieren, verifizieren dass die importierte Domain NICHT im
generierten Traefik-Config auftaucht (bzw. nach dem gewählten Fix: Status `pending` statt
`active`).

### Evidence
`tenant_import_service.py:419-451,187-193`; Gegenprobe `tenant_clone_service.py`
(kein `TenantDomain`-Bezug, `grep -in domain` liefert 0 Treffer).

---

## Geprüft, kein Fund

- **`finance`/`abgabebox` Feature-Bypass über Alternativpfade**: kein Endpoint gefunden, der
  Finance-/Abgabebox-Funktionalität ohne den jeweiligen `require_feature`-Aufruf bereitstellt
  (Cross-Reference Fork G für Finance; `submission_assignments.py`/`public_share.py` für Abgabebox
  via Fork F — durchgehend `require_abgabebox_*`).
- **`abgabebox-backend` selbst prüft kein Feature-Flag**: architektonisch bewusst (separater
  Service kennt keine Tenant-Features) — Kontrolle liegt vollständig im Haupt-Backend, das nur bei
  gebuchtem Feature überhaupt einen funktionierenden `SubmissionLink` für die UI erreichbar macht.
  Kein Bypass gefunden: `submission_link_service.create_default_link` wird zwar bei JEDER
  Tenant-Erstellung aufgerufen (auch ohne Feature), aber der Link ist ohne gebuchtes Feature aus
  dem Haupt-Frontend nicht erreichbar/verwaltbar (`submission_assignments.py` requires
  `require_abgabebox_read/write`, die intern `require_feature(..., "abgabebox")` prüfen) — ein
  bereits existierender, aber nie beworbener Link-Token ohne Feature ist zwar theoretisch über die
  Abgabebox-URL direkt aufrufbar (Token ist ja in der DB), ABER: **das ist dieselbe Klasse wie
  FEAT-01/FEAT-02** (bereits provisionierte Ressource bleibt nutzbar) — hier jedoch praktisch
  irrelevant, da OHNE gebuchtes Feature kein Tenant-User jemals einen Assignment/Element für diesen
  Link erzeugen kann (Assignments werden nur über die gated `submission_assignments.py`-Routen
  angelegt) — der Default-Link existiert, aber zeigt ohne Assignments nur eine leere Liste. Kein
  eigenständiges Finding, aber verwandt zu FEAT-01/02 — falls in Zukunft `abgabebox` einem Tenant
  entzogen wird, der BEREITS Assignments hat, bleiben diese über den alten Link-Token
  abrufbar (dieselbe fehlende "Revoke-on-Downgrade"-Logik). **Empfehlung**: bei der Umsetzung von
  FEAT-01 auch prüfen, ob ein analoger Fall für `abgabebox`-Assignments existiert (nicht
  abschliessend verifiziert in diesem Fork, da der primäre Fokus auf `custom_domain` lag — für
  einen kurzen Nachfolge-Check vormerken).
- **Storage-Pakete**: `update_storage_packages` (`admin_tenant_service.py`, gelesen im Rahmen
  dieses Forks) ist Platform-Admin-only, kein Self-Service-Endpoint für Tenants gefunden, der
  Storage-Pakete ohne Admin-Freigabe hinzufügt. `recompute_effective_storage_quota` wird konsistent
  nach jeder Änderung aufgerufen. Kein Bypass gefunden.
- **`tenant_trust`-Migration (0095)**: betrifft Cross-Tenant-Foto-Album-Sharing
  (`photo_album_share_service.py`), NICHT Plan-/Storage-Features — thematisch verwandt aber
  ausserhalb des Feature-Gating-Scopes, bereits von Fork A/C im Rahmen von
  `ensure_can_read_stored_file` als korrekt verifiziert.
- **Domain-Anlage/-Verifizierung selbst**: beide korrekt mit `require_feature(actor,
  "custom_domain")` gated (siehe Matrix oben) — der 2026-09-24-Fix (Domain-Aktivierung prüfte
  Feature nicht wie Anlegen) ist vollständig und hält weiterhin (keine Regression gefunden).

## Fazit

2 CONFIRMED MEDIUM-Findings (FEAT-01, FEAT-02), beide derselbe Root Cause (Feature-Gating ist
"Gate bei Provisionierung", nicht "Invariante über die Ressourcen-Lebensdauer"), beide mit
identischem empfohlenem Fix. Kein Fund bei `finance`/`abgabebox` API-Ebene selbst. Ein verwandter,
nicht abschliessend verifizierter Verdacht zu `abgabebox`-Assignments nach Feature-Entzug für
Nachfolge-Check vorgemerkt.

Status-Update für `security-audit/components/backend.md`: Abschnitt "Phase 4 Fork J" ergänzt,
Status bleibt `REVIEWED_WITH_FINDINGS`.
