# Plan: Abgaben abschliessen und persönlicher Link für Verantwortliche

Stand 2026-11-12, noch nicht umgesetzt. Baut auf der Mail «Abgabe eingegangen»
(`todo.submission_done`, Branch `feat/submission-done-mail`) auf.

## Ziel

1. Ein **von Hand geschlossenes Element** zählt als erledigt, im Fortschrittsbalken und für die Aufgabe.
2. Sind **alle Elemente einer Abgabe** abgegeben oder geschlossen, ist die Abgabe **abgeschlossen**
   und steht unter «Abgaben» im zweiten Tab «Abgeschlossen».
3. Die Verantwortlichen eines Elements bekommen in der Mail «Abgabe eingegangen» einen **persönlichen
   Link**. Darüber können sie die eigene Abgabe ansehen und, falls erlaubt, zurückziehen und neu
   abgeben. Was erlaubt ist, steht in der Konfiguration der Abgabe.

Zweck von 3: Macht jemand Fremdes über den gemeinsamen Abgabebox-Link eine falsche Abgabe, ist die
betroffene Person nicht ausgesperrt. Sie erfährt es per Mail und kann die Abgabe selbst korrigieren.

## Heutiger Stand (geprüft im Code)

- Elementstatus: `get_assignment_elements` in `submission_service.py`. Ist die jüngste
  `submission_upload`-Zeile `closed`, gilt `closed`; mit Dateien `submitted`, sonst `open`.
- Fortschritt: `GET /api/submission-assignments/{id}/summary` zählt nur **Elemente mit Dateien**
  (`count_submissions_summary`). Geschlossene Elemente ohne Datei fehlen im Balken.
- Aufgabe: Der Trigger `trg_sync_todo_status` (0164) erledigt sie bei einer Einreichung.
  `close_element` ändert die Aufgabe **nicht**. `reopen_element` schreibt eine `submitted`-Zeile ohne
  `submitted_at`. Das öffnet eine erledigte Aufgabe nicht wieder.
- Ein Archiv gibt es nicht, nur `is_active` (aus = über die Abgabebox nicht erreichbar).
- `submission_upload` ist append-only, die Abgabebox-Rolle darf nur `INSERT`.
- Die Abgabebox kennt keine Identität: Wer den Link hat, kann für jedes Element abgeben.

## Teil 1: Geschlossen = erledigt

**Backend**
- `count_submissions_summary` zählt neu **je Element** und liefert `submitted`, `closed`
  (geschlossen ohne Datei), `quarantine`, `infected`, `open` und `total`. Grundlage ist
  dieselbe Logik wie in `get_assignment_elements`, damit Balken und Detailansicht nie
  auseinanderlaufen.
- `close_element` schliesst die Aufgabe des Elements und ruft `todo_fine_service.sync_todo` auf
  (Entscheid 2026-11-12):
  - mit Datei → **erledigt** (`completed_at` = Zeitpunkt des Schliessens)
  - ohne Datei → **abgebrochen** (keine Verspätungsbusse)
  Im Balken zählen beide als erledigt. Es geht keine Mail «Abgabe eingegangen» raus, weil es keine
  passende Einreichung gibt.
- `reopen_element` öffnet die Aufgabe wieder (`open`, `completed_at = NULL`) und gleicht die
  Pendenzen-Busse ab. Damit ist auch die heutige Lücke geschlossen.

**Frontend** (`submission-assignment-manager.tsx`, `SummaryBar`)
- Neues Segment «geschlossen» (neutraler Ton, Token `--neutral-*`), Beschriftung z. B.
  «4 von 5 erledigt · 1 geschlossen».

## Teil 2: Abgabe abgeschlossen (zweiter Tab)

Kein Archiv: eine Abgabe ist **abgeschlossen**, sobald alle Elemente abgegeben oder geschlossen sind,
und erscheint in der App unter «Abgaben» im zweiten Tab «Abgeschlossen» (wie erledigte Aufgaben).

**Abgabebox:** braucht keine Änderung. Sie zeigt heute schon nur Abgaben mit mindestens einem offenen
Element (`list_assignments` → `element_resolver.resolve_open_elements`); geschlossene Elemente
blendet sie aus. Eine Abgabe, deren Elemente alle geschlossen sind, ist dort also nicht mehr sichtbar.
Ein abgegebenes, aber nicht geschlossenes Element (`auto_close = never`) bleibt dort für weitere
Dateien offen, wie bisher.

**Regel «abgeschlossen»** (eine Funktion `assignment_completion(db, assignment)`, im Service getestet)
- Alle bekannten Elemente sind `submitted` (mit sauberer Datei) oder `closed`; Quarantäne zählt nicht.
- Und es kann nichts mehr dazukommen:
  - `manual`: sofort.
  - `events`/Zyklus: kein Fenster eines Elements endet in der Zukunft, kein künftiger Termin mit dem Tag.
  - `list`: der Stichtag (`deadline`) ist vorbei; ohne Stichtag zählt der aktuelle Stand der Liste.
- Kommt später ein neues offenes Element dazu (neuer Termin, neuer Listeneintrag), ist die Abgabe
  automatisch wieder «offen».

**Speicherung:** `submission_assignment.completed_at timestamptz NULL` (neue Migration, frühestens
0176). Der Job `submission_todo_sync` hält das Feld aktuell, zusätzlich direkt nach Schliessen,
Wiederöffnen und Einreichungen über das Backend. So filtert die Liste ohne teure Berechnung je Abgabe.

**Oberfläche:** `FilterTabs` «Offen» / «Abgeschlossen» über der Tabelle (Standard «Offen»),
abgeschlossene mit Badge «Abgeschlossen». Abgeschlossene bleiben voll bearbeitbar (Elemente wieder
öffnen, Dateien ansehen).

## Teil 3: Persönlicher Link für Verantwortliche

### Konfiguration je Abgabe (Formular, Abschnitt «Verantwortliche»)

| Feld | Werte | Standard |
|---|---|---|
| `owner_access` | `off` · `view` · `manage` (ansehen, zurückziehen, neu abgeben) | `off` |
| `owner_resubmit_only_personal` | nach dem Zurückziehen nur noch über den persönlichen Link abgeben | aus |
| `owner_access_days` | Gültigkeit des Links in Tagen nach dem Versand (1–90) | 30 |

Die Felder gibt es nur, wenn die Abgabe Verantwortliche hat (`responsible_participant_source`).
Gespeichert wird in `submission_assignment` (gleiche Migration wie Teil 2), mit `CHECK` auf die Werte.

### Wer bekommt den Link

- Alle Verantwortlichen des Elements, die die Mail «Abgabe eingegangen» bekommen. Jede Person
  erhält einen **eigenen** Link, gebunden an Mandant, Abgabe, Element und Person.
- Auch Personen ohne Login, wenn bei ihnen «auch ohne Login benachrichtigen» gesetzt ist
  (Entscheid 2026-11-12); es ist ihr einziger Weg ohne Konto.
- Nur, wenn `owner_access <> off` beim Versand gilt. Der Link wird **erst beim Versand** erzeugt
  (wie `account.link_items_for`), nie im Payload der Benachrichtigung gespeichert.

### Token

- Neue Tabelle `submission_access_token`: `id`, `tenant_id NOT NULL` (RLS), `assignment_id`,
  `element_ref`, `participant_id`, `token_hash` (SHA-256, unique), `created_at`, `expires_at`,
  `revoked_at`, `last_used_at`. Den Klartext gibt es nur in der Mail.
- 32 Byte aus `secrets.token_urlsafe`. Der Link steht im **URL-Fragment**:
  `https://<app>/abgabe/verwalten#<token>`. Er landet so nicht in Server-Logs, im Verlauf mit Query
  oder im Referer.
- Je (Element, Person) gilt nur der **neueste** Link. Ein neuer Versand widerruft die älteren.
- Ungültig wird ein Link bei jedem Zugriff, wenn eine der Bedingungen nicht mehr stimmt:
  abgelaufen, widerrufen, Person nicht mehr verantwortlich, Option jetzt `off`, Abgabe gelöscht,
  Konto des Mandanten gesperrt oder Feature `submissions` nicht mehr gebucht.
- Aufräumen: abgelaufene Tokens nach 30 Tagen löschen, im bestehenden Loop `notification_dispatch`.

### Endpunkte (Haupt-Backend, öffentlich, Router `public_submission_access`)

Das Haupt-Backend statt der Abgabebox, weil es Aufgaben, Bussen, Dateien und Benachrichtigungen
schon verwaltet. Die eingeschränkte Rolle `hocx_abgabebox` bekommt **keine** neuen Rechte.

| Methode | Pfad | Wirkung |
|---|---|---|
| `POST` | `/api/public/submission-access/view` | Abgabetitel, Element, Fenster, Status, Dateien (Name, Grösse, Zeit, Scanstatus), erlaubte Aktionen |
| `POST` | `/api/public/submission-access/files/{file_public_id}` | Datei herunterladen, nur `clean` und nur Dateien **dieses** Elements |
| `POST` | `/api/public/submission-access/withdraw` | Abgabe zurückziehen (nur `manage`, Bestätigung im Body) |
| `POST` | `/api/public/submission-access/upload` | neu abgeben, nur wenn `owner_resubmit_only_personal` gilt (sonst über die normale Abgabebox) |

- Der Token steht immer im Body (`{"token": …}`), auch beim Lesen. So kommt er nie in einen Pfad
  oder Query, und alles läuft über `POST` mit Origin-Prüfung.
- Ein Rate-Limit `enforce_rate_limit` gilt je IP (z. B. 30 pro 15 Minuten) und je Token-Hash
  (z. B. 60 pro Stunde), für Upload und Zurückziehen strenger.
- Jede Antwort für einen ungültigen Link ist dieselbe 404-Antwort «Link ungültig oder abgelaufen»,
  ohne Hinweis, ob es den Token, die Abgabe oder die Person gibt.
- Der Mandant kommt **nur** aus der Token-Zeile. Alle Abfragen danach laufen mit
  `tenant_id=token.tenant_id` und im RLS-Kontext des Mandanten. Datei-IDs werden zusätzlich gegen
  Abgabe und Element des Tokens geprüft.
- Header: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`;
  Downloads mit `Content-Disposition: attachment` und `X-Content-Type-Options: nosniff`.
- Fehler laufen über `raise HTTPException(...) from exc` ins Fehlerprotokoll. Den Token selbst
  loggen wir nie, höchstens die ersten 6 Zeichen des Hashes.

### Zurückziehen

- Append-only bleibt erhalten: neue `submission_upload`-Zeile mit Status `withdrawn`. Die
  Migration erweitert dafür `ck_submission_upload_status`, und eine neue Version der
  Trigger-Funktion öffnet die Aufgabe bei `withdrawn` wieder.
- Die Dateien des Elements sind danach für die Abgabe nicht mehr sichtbar, werden aber **nicht
  sofort gelöscht**. Sie bleiben 30 Tage für Verwalter wiederherstellbar (Upload-Protokoll:
  «Zurückgezogen über persönlichen Link von Anna A.» und Aktion «Wiederherstellen»), danach
  löscht sie der bestehende Speicher-Purge. Schutz gegen einen geleakten Link: Ein Fremder mit
  der Mail kann nichts endgültig zerstören.
- Ist das Element danach `open`, darf wieder abgegeben werden, auch wenn `auto_close` es vorher
  geschlossen hatte. Ist das Fenster vorbei und `keep_open_after_end` aus, nur über den
  persönlichen Link, sonst wäre die Person ausgesperrt.
- Mit `owner_resubmit_only_personal` ist das Element für den gemeinsamen Abgabebox-Link gesperrt
  (die Abgabebox zeigt «wird von der verantwortlichen Person abgegeben»). Genau das verhindert,
  dass der Fremde gleich wieder etwas Falsches abgibt.
- Verwalter (`submissions.manage`) bekommen eine Benachrichtigung «Abgabe zurückgezogen» (neue
  Art in `catalog.py`, Kategorie `todo_submissions`).

### Neu abgeben über den persönlichen Link

- Upload über die **bestehende Pipeline des Backends** für direkte Abgabe-Dateien
  (`files.py`, Grössenlimit, Magic-Byte-Prüfung, ClamAV, Dateitypen und `max_files_per_element`
  der Abgabe). Kein zweiter Upload-Weg mit eigenen Regeln.
- Captcha wie in der Abgabebox (Friendly Captcha), zusätzlich zum Rate-Limit.
- Danach dieselbe Logik wie eine normale Einreichung: Aufgabe erledigt, Mail «Abgabe eingegangen»
  mit neuem persönlichem Link.

### Oberfläche

- Eigene schlanke Seite `/abgabe/verwalten` im Haupt-Frontend, öffentlich, ohne App-Navigation
  und ohne Session. Gleiches Muster wie `/auth/set-password`.
- Die Seite liest das Fragment, entfernt es sofort mit `history.replaceState` und hält den Token
  nur im Speicher des Tabs (`sessionStorage`). Nach dem Neuladen funktioniert sie weiter, in einem
  neuen Tab nicht.
- Inhalt: Titel der Abgabe, Element und Fenster, Status (`Badge`), Dateiliste mit Download, je
  nach Option «Abgabe zurückziehen» (`useConfirm`, `tone: "danger"`) und «Neu abgeben».
- Kein Zugriff auf andere Elemente, andere Personen, Teilnehmerlisten, die App oder den
  gemeinsamen Abgabebox-Link.
- Texte in allen Sprachen, Design-Regeln, Light/Dark, 390 px.

## Sicherheit: Bedrohungen und Gegenmassnahmen

| Bedrohung | Gegenmassnahme |
|---|---|
| Token erraten | 256 Bit Zufall, nur Hash gespeichert, Rate-Limit je IP |
| Token aus Logs, Referer oder Verlauf | Fragment statt Pfad oder Query, Token nur im POST-Body, `no-referrer`, Fragment wird sofort entfernt |
| Weitergeleitete oder geleakte Mail | kurze Gültigkeit, nur der neueste Link gilt, Zurückziehen ist 30 Tage umkehrbar, Verwalter werden benachrichtigt |
| Zugriff auf fremde Elemente oder Mandanten | Token bindet Mandant, Abgabe, Element und Person; jede Datei wird gegen das Element geprüft; RLS-Kontext aus dem Token; Test mit fremder Datei-ID |
| Person nicht mehr verantwortlich | wird bei jedem Zugriff neu geprüft |
| Fremder gibt nach dem Zurückziehen wieder ab | Option «nur noch über persönlichen Link» |
| Schadhafte Uploads | gleiche Pipeline wie bisher (ClamAV, Magic Bytes, Limits), Captcha |
| Existenz-Orakel | einheitliche 404-Antwort |
| CSRF | nur `POST`, Origin-Prüfung, keine Cookies für diese Seite |
| Ausweitung der Abgabebox-Rechte | keine: alles läuft im Haupt-Backend |

Vor dem Commit: Security-Review des Diffs (öffentliche Endpunkte, Uploads, Migration, Tokens).

## Tests

- Service: Erledigt-Regel je Quelle (manual, events, list), Quarantäne zählt nicht, `close_element`
  und `reopen_element` mit Aufgabe und Busse.
- Abgeschlossen: Regel je Quelle, wird wieder offen bei neuem Element, Tab-Filter.
- Token: Hash statt Klartext, nur der neueste gilt, Ablauf, Widerruf, Option `off` sperrt sofort,
  Person entfernt sperrt, fremder Mandant, fremde Datei-ID, fremdes Element: immer dieselbe 404.
- Rate-Limit und Header (`no-store`, `no-referrer`).
- Zurückziehen: Aufgabe wieder offen, Busse abgeglichen, Dateien weg, aber wiederherstellbar;
  Sperre für den gemeinsamen Link.
- RLS: `tests/test_tenant_rls.py` deckt `submission_access_token` ab.
- Playwright: Portal mit Light/Dark bei 1440 und 390 px; Ablauf Mail → Link → Ansehen →
  Zurückziehen → neu abgeben.

## Umsetzung in Schritten

1. **Teil 1** (klein): Zählung je Element, Balken, Aufgabe bei Schliessen/Wiederöffnen.
2. **Teil 2**: Migration (`completed_at` und die Optionen aus Teil 3), Regel «abgeschlossen», Job, Tabs.
3. **Teil 3a**: Token-Tabelle, Link in der Mail, Portal nur zum Ansehen.
4. **Teil 3b**: Zurückziehen mit Wiederherstellen, Benachrichtigung der Verwalter, Sperre des
   gemeinsamen Links.
5. **Teil 3c**: Neu abgeben über das Portal.

Jeder Schritt ist einzeln lauffähig und kann einzeln ausgeliefert werden.

## Entscheide (2026-11-12)

1. Von Hand geschlossen ohne Datei → Aufgabe «abgebrochen» (keine Busse), mit Datei → «erledigt».
2. Kein Archiv: abgeschlossene Abgaben stehen in der App im zweiten Tab «Abgeschlossen». Die
   Abgabebox zeigt sie schon heute nicht mehr, sobald alle Elemente geschlossen sind.
3. Zurückgezogene Dateien bleiben 30 Tage für Verwalter wiederherstellbar.
4. Personen ohne Login bekommen den Link, wenn «auch ohne Login benachrichtigen» gesetzt ist.
