# Benachrichtigungen

Zentraler, einheitlicher Weg, um Personen zu benachrichtigen. Heute nur per E-Mail (SMTP), später
weitere Kanäle. Code: `backend/app/notifications/`, Migration `0170_notifications`.

## Entscheidungen (2026-11-11)

| Frage | Entscheidung |
|---|---|
| Versand | SMTP, konfiguriert in `/admin/notifications` (Passwort verschlüsselt per `secret_crypto`, kein Env-Secret) |
| Absender | eine hocX-Adresse; der Vereinsname steht im Betreff und im Text |
| Personen ohne Login | nur, wenn ein Admin es bei der Person einschaltet (`app_user.notify_without_login`) |
| Menge | bewusst wenig: Sammelnachrichten, jede Erinnerung je Aufgabe nur einmal |
| Aufgaben aus Protokollen | erst beim Abschluss des Protokolls, alle offenen auf einmal |
| Aufgaben ohne Protokoll | beim Erstellen bzw. neu Verantwortlichen (10 Minuten Bündelungsfenster) |
| Erinnerungen | täglich ab 07:00: «fällig in 3 Tagen» und «seit gestern überfällig», je einmal |

## Ablauf

1. **Veröffentlichen:** Fachcode ruft `notifications.publish(db, kind=..., tenant_id=..., recipient_ids=..., subject_id=..., dedupe=...)`
   in seiner eigenen Transaktion auf. Bei einem Rollback wird nichts verschickt. `dedupe` macht eine
   Benachrichtigung je Empfänger einmalig (Unique-Index `uq_notification_dedupe_key`).
2. **Warteschlange:** Tabelle `notification` (eine Zeile je Empfänger, `deliver_after`, Status
   `pending/sent/skipped/failed`). Sie ist zugleich Versandprotokoll (90 Tage, dann gelöscht) und
   steht im Datenschutz-Export der Person.
3. **Versand:** Loop `notification_dispatch` im job-worker (jede Minute). Je Empfänger und Gruppe
   eine Mail. Vor dem Versand wird neu geprüft:
   - Konto aktiv, gleicher Mandant, E-Mail vorhanden, Login oder `notify_without_login`
   - Kategorie in den Einstellungen der Person nicht abgeschaltet (`notification_preference`)
   - Eintrag noch aktuell (Aufgabe offen, Person noch verantwortlich, Fälligkeit unverändert)
   Übersprungenes bekommt einen `skip_reason`. SMTP-Fehler: Wiederholung nach 5, 15, 60, 240 Minuten,
   danach `failed`. Ist der Versand aus, verfallen Einträge nach 7 Tagen (`email_disabled`).
4. **Zeitgesteuert:** Loop `todo_reminders` (alle 30 Minuten, wirkt ab 07:00 Ortszeit) legt die
   Erinnerungen idempotent an.

## Katalog

`backend/app/notifications/catalog.py` ist die einzige Stelle für Arten und Kategorien:

| Art | Kategorie | Gruppe (eine Mail) | Verzögerung |
|---|---|---|---|
| `todo.assigned` | `todo_new` | `todo.new` | 10 Minuten |
| `todo.due_soon` | `todo_reminders` | `todo.reminder` | – |
| `todo.overdue` | `todo_reminders` | `todo.reminder` | – |

Kategorien schalten Personen im Profil (Reiter «Benachrichtigungen») ein oder aus; Standard ist ein.

## Neue Benachrichtigung hinzufügen

1. Art (und bei Bedarf Kategorie) im Katalog ergänzen.
2. An der fachlichen Stelle `publish(...)` aufrufen, mit `dedupe`, wenn sie einmalig sein soll.
3. Für eine neue Gruppe: Lader der aktuellen Daten in `dispatch.ITEM_LOADERS` und Texte in
   `render.py`. Die Texte stehen in `frontend/messages/<locale>/documentPdf.json` unter `email.*`
   (`python3 scripts/sync-document-i18n.py` kopiert sie ins Backend).
4. Für eine neue Kategorie: Übersetzungen `settings.profileModal.notifications.category.<key>`.
5. Tests in `backend/tests/test_notifications.py` (Versand über `email_transport.override_transport`).

## Sicherheit und Datenschutz

- Mails enthalten nur das Nötige: Aufgabe, Fälligkeit, Herkunft. Links nur auf feste Pfade der App
  (`/todos`, `/settings`), an Personen ohne Login gar keine.
- HTML-Teil: alle Werte escaped. Header `Auto-Submitted: auto-generated`.
- SMTP-Passwort nur verschlüsselt gespeichert, nie in Antworten; Fehlermeldungen ohne Zugangsdaten.
- `notification` und `notification_preference` haben `tenant_id` und RLS.
- Mandanten-Export und -Klon übernehmen `notify_without_login` (Spalte an `app_user`), nicht aber
  Warteschlange und Einstellungen der Personen (Standard gilt wieder).

## Audit: wo Benachrichtigungen sinnvoll sind

Stand 2026-11-11. Prio P0 = vor der Vermarktung nötig, P3 = nice to have.

| Bereich | Ereignis | Empfänger | Prio | Status |
|---|---|---|---|---|
| Konto/Sicherheit (Pflicht, nicht abbestellbar) | Passwort zurücksetzen (Einmal-Link) | Person | P0 | offen |
| | Konto-Einladung statt vom Admin gesetztem Passwort | neue Person | P0 | offen |
| | Passwort geändert, MFA geändert/zurückgesetzt, Sitzungen beendet | Person | P1 | offen |
| | Vereins-Datenexport fertig | Besteller | P1 | offen |
| Aufgaben | neue Aufgabe (Sammelmail) | Verantwortliche | P1 | **umgesetzt** |
| | fällig in 3 Tagen / seit gestern überfällig | Verantwortliche | P1 | **umgesetzt** |
| Sitzungen | Einladung mit Traktandenliste (von Hand, Versandprotokoll) | Teilnehmende | P1 | offen |
| | Protokoll abgeschlossen (PDF-Link) | Teilnehmende | P1 | offen |
| | Sitzung in X Tagen, später mit Abmeldelink | Teilnehmende | P2 | offen |
| | neues/vertagtes Anliegen | Verantwortliche/Ersteller | P3 | offen |
| Bussen | neue Anwesenheitsbussen, Pendenzen-Busse läuft/fixiert | betroffene Person | P2 | offen |
| | Konflikte bei Pendenzen-Bussen (Sammelmail) | Kasse | P2 | offen |
| | Busse einkassiert/erlassen | betroffene Person | P3 | offen |
| Abgabebox | neue Abgabe (einzeln oder Tageszusammenfassung) | Verantwortliche | P2 | offen |
| | Upload in Quarantäne | Mandantenadmin | P3 | offen |
| Fotos | Einladung zu geteiltem Album, angenommen/abgelehnt | Admins Partnerverein / Einladender | P2/P3 | offen |
| Verwaltung | neue Löschvorschläge (Aufbewahrung) | `settings.manage` | P2 | offen |
| | Speicher-/Benutzerlimit fast erreicht, Domain-Prüfung fehlgeschlagen | Admins | P2 | offen |
| | geplante Wartung | alle aktiven Konten | P2 | offen |
| Plattform | Systemalarme, Backups, Jobs | Plattform-Admin | – | bleibt ntfy |

## Phasen

1. **Fundament** – ✅ Katalog, Warteschlange, SMTP, Versand-Loop, Admin-Seite, Einstellungen im Profil.
   Offen: Mailpit im Dev-/E2E-Stack, Prüfung «E-Mail» in `/admin/system` mit ntfy-Alarm.
2. **Aufgaben** – ✅ neue Aufgaben, Erinnerungen, Personen ohne Login per Admin.
3. **Konto und Sicherheit** – Passwort zurücksetzen und Einladung (öffentliche Endpunkte mit
   Rate-Limit, Einmal-Token gehasht, Link per URL-Fragment), Sicherheitshinweise, Export fertig.
4. **Sitzungen** – Einladung/Protokoll versenden mit Versandprotokoll, Erinnerung vor Sitzungen,
   später An-/Abmeldung per Link.
5. **Rest** – Bussen, Abgabebox, Aufbewahrung, Limits, Wartung, geteilte Alben; dazu Abmelden mit
   einem Klick (`List-Unsubscribe`) ohne Login.
6. **Weitere Kanäle** – Web-Push für die PWA (Service Worker), Posteingang in der App.

## Ausblick

Weitere Benachrichtigungen aus dem Audit (Passwort zurücksetzen, Einladung, Sicherheitshinweise,
Versand von Einladung/Protokoll, Bussen, Abgabebox, Aufbewahrung, Wartung) nutzen denselben Weg.
Weitere Kanäle (Web-Push für die PWA, Posteingang in der App) werden als zusätzlicher Versand je
Zeile ergänzt, ohne den Fachcode zu ändern. Für Mails mit Einmal-Links (Passwort) und echtes
Abmelden ohne Login braucht es noch öffentliche Endpunkte mit Rate-Limit.
