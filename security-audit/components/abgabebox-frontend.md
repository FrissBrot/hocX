# Component: abgabebox-frontend

Status: REVIEWED (Inventar, keine Tiefenprüfung)
Files reviewed:
- abgabebox-frontend/app/page.tsx
- abgabebox-frontend/app/layout.tsx
- abgabebox-frontend/app/[linkToken]/page.tsx
- abgabebox-frontend/app/[linkToken]/[assignmentSlug]/page.tsx
- abgabebox-frontend/app/[linkToken]/[assignmentSlug]/[elementRef]/page.tsx
- abgabebox-frontend/components/upload-form.tsx
- abgabebox-frontend/components/captcha-widget.tsx (nur überflogen)
- abgabebox-frontend/lib/api.ts
- abgabebox-frontend/lib/validate-upload.ts (+ validate-upload.test.ts)

## 1. Struktur-Überblick

Eigenständige Next.js-App (eigenes `package.json`/Dockerfile, kein Shared-Package mit
`frontend/`). Routing rein über den Link-Token in der URL, keine Auth/Session/Cookies:

```
/                                              -> Hinweis "Link verwenden" (kein Redirect, keine Enumeration möglich)
/[linkToken]                                   -> Liste offener Assignments
/[linkToken]/[assignmentSlug]                  -> Liste Elemente
/[linkToken]/[assignmentSlug]/[elementRef]     -> Upload-Formular für genau ein Element
```

Jede Ebene löst serverseitig (SSR, `fetchLinkResolution`/`fetchJson` in `lib/api.ts`) direkt
gegen `abgabebox-backend` über das interne Docker-Netzwerk auf (`INTERNAL_ABGABEBOX_API_URL`,
Default `http://abgabebox-backend:8000`). Der Token selbst ist laut
`backend/app/models/entities.py:1335` (`SubmissionLink.token`) "ein zufaelliger, nicht
erratbarer Wert, der selbst die Authentifizierung ist" — die eigentliche Tenant-/Ownership-
Prüfung liegt vollständig im Backend (`abgabebox-backend/app/repository.py::get_link_by_token`
als einziger Einstiegspunkt). Dieses Frontend selbst trifft keine Autorisierungsentscheidung,
reicht nur weiter — Tiefenprüfung der eigentlichen Trust-Boundary gehört in den
`abgabebox-backend`-Component-Checkpoint (Token-Entropie, Rate-Limiting, Enumeration).

Unterscheidung 404 vs. 403: `LinkResolution` in `lib/api.ts` trennt bewusst "Link existiert
nicht" von "Feature (Abgabebox) für Mandant nicht gebucht" (403) — auf Ebene `[linkToken]`
sauber gehandhabt; auf tieferen Ebenen (`getAssignmentDetail`/`getElement`) läuft alles über
das einfache `fetchJson`, das jeden Non-OK-Status (401/403/404/...) gleich auf `null` →
`notFound()` abbildet. Dadurch ist von aussen ein abgelaufener/falscher Assignment-Slug nicht
von einem Feature-Gating unterscheidbar (kein Leak), aber auch ein evtl. anderer Fehlerstatus
(z.B. 500) würde stumm als 404 erscheinen — für Vertiefung im Backend-Checkpoint vermerken,
kein eigenständiges Frontend-Finding.

## 2. Trust-Modell / Informationspreisgabe

Diese App ist per Definition öffentlich erreichbar für jeden, der den Link kennt. Angezeigte
Daten pro Ebene:
- Assignment-Liste: `title`, `description` (vom Tenant gepflegte Zwecktexte, kein PII anderer
  Nutzer)
- Element-Liste: `label`, Zeitfenster (`window_start`/`window_end`), `uploaded_count`
  (Anzahl bereits hochgeladener Dateien — reine Zahl, keine Dateinamen/Inhalte anderer
  Einreichenden)
- Upload-Seite: `allowed_file_types`, `max_files_per_element`, `max_file_size_mb`

Kein sichtbares Leak von Tenant-internen Daten (keine Nutzerlisten, keine anderen Abgaben,
keine Kontaktdaten) auf dieser Ebene. Ob `uploaded_count` o.ä. tenant-übergreifend korrekt
gescoped aus dem Backend kommt, ist Backend-Scope.

## 3. Upload-Flow (Frontend-Seite)

- Kein Chunking: ein `FormData`-POST mit allen ausgewählten Dateien gleichzeitig,
  `AbortSignal.timeout(3 * 60 * 60 * 1000)` (3h Timeout) an
  `/api/public/{linkToken}/assignments/{assignmentSlug}/elements/{elementRef}/upload`
  (Next.js Rewrite/same-origin, `publicApiUrl()` ist Identität — Browser spricht die jeweilige
  Domain direkt an, kein separater API-Origin).
- Kein "echter Fortschrittsbalken" in dieser App (anders als das im Git-Log erwähnte
  Fortschritts-Feature der Haupt-App/Galerie-Upload) — nur Auswahl-Anzeige und
  Submitting-Spinner-Text.
- FriendlyCaptcha: Lösung wird gegen ein serverseitig ausgestelltes `session_token`
  eingetauscht (`captcha-verify`-Endpoint), das dann für nachfolgende Uploads mitgeschickt
  wird (`captcha_session_token` im FormData). Ohne konfigurierten Sitekey (Dev/Test) wird der
  Austausch mit der festen Zeichenkette `"no-friendly-captcha-configured"` als "Lösung"
  ausgelöst — laut Kommentar spiegelbildlich zu einem Backend-Fallback (`captcha_enabled()`),
  der das nur akzeptiert, wenn dort ebenfalls kein echter Key gesetzt ist. Ob diese
  Fallback-Bedingung im Backend tatsächlich wasserdicht an "kein Sitekey konfiguriert" (statt
  z.B. an einen erratbaren/festen Wert) gebunden ist, ist ein Kandidat für den
  `abgabebox-backend`-Checkpoint (Captcha-Bypass-Frage).
- Client-seitige Validierung (`validate-upload.ts`): Dateianzahl ≤ 50, Gesamtgrösse ≤ 150 MiB,
  erlaubte Extensions, `maxFiles`/`maxFileSizeMb` aus Assignment-Konfiguration,
  `alreadyUploaded`-kumulatives Limit. Explizit im Code als "erste Rückmeldung, serverseitige
  Validierung ist massgeblich" dokumentiert (Kommentar in `validate-upload.ts`) — hier nur als
  UX vermerkt, keine Security-Grenze. Reale Durchsetzung (MIME-Sniffing, echte Grössen-/
  Typ-Prüfung, Rate-Limiting hinter 429) liegt im `abgabebox-backend`.

## 4. XSS-relevante Stellen

Ein `dangerouslySetInnerHTML` im gesamten Frontend: `app/layout.tsx:24` — ein rein statischer,
fest im Quellcode stehender Theme-Bootstrap-Script-String ohne jede Interpolation von
User-/Server-Daten. Kein Injection-Risiko.

Keine weiteren `innerHTML`-Verwendungen (Treffer nur in `node_modules`-Typdefinitionen).
Nutzerdaten (Titel/Beschreibung/Label/Dateinamen) werden überall als reiner JSX-Text
gerendert (React escaped automatisch) — keine Stelle gefunden, die Tenant-gepflegte Texte
(`assignment.title`, `.description`, `element.label`) oder Dateinamen als rohes HTML
ausgibt. Für abschliessende Bewertung wäre zu prüfen, ob `assignment.title`/`description`
irgendwo serverseitig (z.B. E-Mail-Templates, PDF-Export) nochmal ausserhalb von React
gerendert werden — das liegt aber ausserhalb dieser Frontend-Komponente.

## 5. Tests

Nur `lib/validate-upload.test.ts` (Unit-Tests für die Client-Validierungsfunktion, u.a.
Grössen-/Typ-Grenzfälle, Case-Insensitivity bei Extensions). Keine Komponenten-/E2E-Tests
innerhalb von `abgabebox-frontend/` selbst gefunden; E2E-Abdeckung für den Abgabebox-Flow
liegt vermutlich in `frontend/e2e/` (dort z.B. `feature-gating.spec.ts` gesehen) oder im
Backend — für Test-Inventar noch zu verifizieren.

## 6. Auffälligkeiten für Vertiefung (Backend-/Cross-Component-Scope, keine eigenen Findings hier)

- **Hinweis auf existierenden Vorgänger-Audit**: Kommentare im Code referenzieren explizit
  frühere Audit-Findings, z. B. `lib/api.ts:26` ("audit finding E-Niedrig-4") und
  `lib/validate-upload.ts:3` ("audit A5, 2026-08-16"). Es könnte einen älteren
  Security-Audit-Bericht (ausserhalb von `security-audit/`, evtl. nicht mehr im Repo oder in
  `CHANGELOG.md`/an anderer Stelle) geben. Empfehlung: kurz repo-weit nach weiteren
  `audit [A-Z]?\d+`/"audit finding"-Kommentaren suchen, um zu klären, ob frühere Findings
  bereits behoben wurden oder ob deren Nummerierung mit diesem neuen Audit kollidiert.
- Captcha-Bypass-Bedingung bei fehlendem Sitekey (`captcha_enabled()` im Backend) — prüfen,
  ob das an Produktionskonfiguration gebunden ist oder von aussen beeinflussbar sein könnte.
- 403-vs-404-Kollaps auf Assignment-/Element-Ebene (`fetchJson` mappt jeden Fehlerstatus auf
  `null`) — für sich harmlos, aber verhindert, dass diese Ebene selbst zwischen
  Feature-Gating und "existiert nicht" unterscheidet; falls das für UX relevant werden soll,
  wäre `fetchLinkResolution` konsistent auch hier zu verwenden. Kein Security-Finding, nur
  Konsistenz-Notiz.
- Rate-Limiting/Token-Entropie/Enumeration-Schutz für `linkToken` selbst: vollständig
  Backend-Scope (`abgabebox-backend`), hier nicht geprüft.
