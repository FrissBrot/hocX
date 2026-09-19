# Testbook: Abgabe-Links

Dieses Testbook beschreibt die Prüfungen für den Zugang zur öffentlichen Abgabebox per
Link. Der Zugang ist ein zufälliger Schlüssel in der URL (`<abgabebox-domain>/<schlüssel>`),
der Mandanten-Slug ist keine Zugangsberechtigung mehr. Geschützt werden vor allem drei
Dinge: **kein Zugriff ohne gültigen Link**, **ein Link erreicht nur die ihm zugeordneten
Abgaben** und **die Trennung der Abgabebox bleibt so strikt wie zuvor** (eingeschränkte
DB-Rolle, kein geteilter Code).

## Ausführung

| Ebene | Befehl | Datei |
|---|---|---|
| E2E (echter Stack, Chromium) | `./scripts/e2e.sh all` | `frontend/e2e/abgabe-links.spec.ts` |
| Haupt-Backend (echte DB, DB-Rechte) | `./scripts/test.sh backend` | `backend/tests/test_submission_links.py` |
| Abgabebox-Backend (ohne DB) | `./scripts/test.sh abgabebox-backend` | `abgabebox-backend/tests/test_link_token_access.py` |
| Haupt-Frontend (Vitest) | `./scripts/test.sh frontend` | `frontend/components/submission-assignments/submission-link-manager.test.tsx` |

Nur die E2E-Datei, bei bereits gestartetem E2E-Stack (`./scripts/e2e.sh up`):

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:13000 E2E_ABGABEBOX_BASE_URL=http://127.0.0.1:13001 \
  npx playwright test e2e/abgabe-links.spec.ts --workers=1
```

Für einen frischen Lauf den E2E-Stack zurücksetzen (`./scripts/e2e.sh down`, dann `up`):
die MFA-Einrichtung gehört zur jeweiligen Testdatenbank. Die Spec räumt ihre Links,
Abgaben und Termine selbst auf und stellt den ursprünglichen Standard-Link wieder her.

## Automatisierte Testfälle (E2E)

| ID | Durchführung | Erwartung |
|---|---|---|
| LNK-01 | Links des Mandanten abrufen | Genau ein Standard-Link; Schlüssel ≥ 32 Zeichen, nur URL-sichere Zeichen, alle Schlüssel verschieden; URL endet auf den Schlüssel |
| LNK-02 | Link anlegen, doppelten Namen (andere Schreibweise) anlegen, umbenennen, zum Standard machen | Doppelter Name abgelehnt (400); Umbenennen ändert den Schlüssel nicht; danach genau ein Standard-Link |
| LNK-03 | Abgabe ohne, mit expliziter und mit leerer Link-Auswahl anlegen | Ohne Angabe: Standard-Link; explizit: genau die gewählten Links; leer: kein Link |
| LNK-04 | Öffentlichen Abruf über passenden Link, über fremden gültigen Link, über unbekannten/zu kurzen Schlüssel und über den Mandanten-Slug | Nur der zugeordnete Link liefert 200; alle anderen Fälle 404 (nicht unterscheidbar); der Slug öffnet nichts mehr |
| LNK-05 | Abgabe über zwei Links erreichbar machen, danach einen Link abwählen | Beide Links funktionieren; nach dem Abwählen 404 nur über den abgewählten Link |
| LNK-06 | Neuen Schlüssel erzeugen, danach Link löschen | Alte URL sofort 404, neue URL 200; nach dem Löschen 404 und die Abgabe hat den Link nicht mehr |
| LNK-07 | Link-Endpunkte mit der Sitzung eines Lesers eines anderen Arbeitsbereichs aufrufen | Auflisten (würde Schlüssel preisgeben), Anlegen, Ändern, Erneuern und Löschen: 403; Link unverändert |
| LNK-08 | Im Browser Links-Dialog öffnen, öffentliche Seite mit Schlüssel, mit falschem Schlüssel und Startseite laden | Dialog zeigt Namen und volle URL; Abgabe erscheint über den Schlüssel; falscher Schlüssel 404 „Nicht gefunden“; Startseite ohne Mandanten-/Abgabeinfo; `Referrer-Policy: no-referrer` und `noindex` |

## Automatisierte Testfälle (Backend)

`backend/tests/test_submission_links.py` (echte, migrierte Datenbank):

| Bereich | Prüfung |
|---|---|
| Tokens | Zufällig, mindestens 32 Zeichen, URL-sicher, eindeutig |
| Link-Verwaltung | Name je Mandant eindeutig (ohne Beachtung der Schreibweise), anderer Mandant darf denselben Namen nutzen; höchstens ein Standard-Link; Neu-Erzeugen ändert den Schlüssel; Links sind mandantengebunden |
| Neuer Mandant | Anlage über das Admin-Panel erzeugt genau einen Standard-Link „Standard“ |
| Zuordnung | Neue Abgabe nutzt den Standard-Link; mehrere Links oder keiner möglich; fremder Link wird abgelehnt (Anlegen und Ändern); Ändern ersetzt die Links, `None` lässt sie unverändert; Löschen eines Links entfernt nur die Zuordnung, Löschen einer Abgabe lässt den Link bestehen |
| Todos | Referenz-Link enthält den Link-Schlüssel; nach Neu-Erzeugen des Schlüssels aktualisiert; ohne Link kein Sync und Referenz geleert |
| Klonen/Export/Import | Klon erhält gleiche Link-Struktur mit **neuen** Schlüsseln (bzw. einen Standard-Link, falls die Quelle keinen hatte); Export enthält keine Schlüssel, Import erzeugt einen neuen Standard-Link mit allen importierten Abgaben |
| Isolation | Rolle `hocx_abgabebox` darf `id, tenant_id, token` und `assignment_id, link_id` lesen, aber weder Name, Standard-Flag noch `SELECT *`, und weder einfügen, ändern noch löschen |
| Migration | Jeder bereits vorhandene Mandant hat nach `0075` einen Standard-Link |

`abgabebox-backend/tests/test_link_token_access.py` (ohne Datenbank):

- Ungültig geformte Schlüssel ergeben 404, **ohne** die Datenbank abzufragen.
- Unbekannter Schlüssel: 404 mit derselben Meldung wie bei jeder anderen fehlenden Ressource.
- Jede Abfrage unterhalb des Links ist auf Mandant **und** Link beschränkt.
- Die Tabellendefinitionen entsprechen exakt den freigegebenen Spalten; es gibt keine
  Mandanten-Tabelle und keine Slug-Abfrage mehr.
- Die Captcha-Sitzung ist an den Link gebunden (anderer Link, andere Abgabe, andere IP: abgelehnt).

`submission-link-manager.test.tsx`: Anzeige mit Namen, Standard-Markierung und voller URL;
Anlegen nur mit Namen; Löschen nur nach Bestätigung samt Hinweis auf betroffene Abgaben;
nach „Als Standard festlegen“ genau ein Standard-Link.

## Manuelle Prüfungen

Diese Punkte sind bewusst nicht automatisiert (Infrastruktur oder Betriebsablauf):

| ID | Durchführung | Erwartung |
|---|---|---|
| LNK-M1 | Update einer bestehenden Installation (`alembic upgrade head`) | Jeder Mandant hat einen Standard-Link, alle bisherigen Abgaben sind daran gehängt; alte URLs mit Mandanten-Slug liefern 404 |
| LNK-M2 | Mandant mit eigener, verifizierter Abgabebox-Domain | Die Link-URL im Links-Dialog verwendet diese Domain |
| LNK-M3 | Abgabe im Konfigurator anlegen und bearbeiten | Standard-Link ist bei „Erreichbar über“ vorausgewählt; ohne Auswahl erscheint der Hinweis „nicht erreichbar“; nach Löschen eines Links verschwindet er auch aus dem geöffneten Formular |
| LNK-M4 | Echter Upload über die Abgabebox mit einem Link (mit FriendlyCaptcha oder im Dev-Stack) | Upload gelingt; Datei erscheint in der Abgabe; Upload über einen inzwischen gelöschten Link wird abgewiesen |
| LNK-M5 | Verantwortliche Person zuweisen, Todos synchronisieren, danach Schlüssel erneuern | Todo-Verweis zeigt auf die neue Adresse und öffnet die Abgabe |

## Grenzen

- Der vollständige Upload über die Abgabebox im Browser ist im Dev-/E2E-Stack durch das
  bekannte Hydration-Problem der Captcha-Anbindung blockiert (siehe Kopfkommentar von
  `frontend/e2e/abgabebox-photo-album-sync.spec.ts`). LNK-08 prüft deshalb serverseitig
  gerenderte Inhalte und Statuscodes; der Upload selbst bleibt LNK-M4.
- LNK-07 kann die Mandantentrennung der Link-IDs nicht über die API zeigen, weil der zweite
  Arbeitsbereich der E2E-Sitzung nur Leserechte hat; diese Trennung prüft
  `test_submission_links.py` auf Service-Ebene.
- Die Prüfung der Datenbankrechte läuft über `SET ROLE` in der Test-Datenbank und ersetzt
  keine Prüfung der Rechte in einer produktiven Installation.
