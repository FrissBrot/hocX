---
name: testhost-abnahme
description: Abnahme eines hocX-Candidates auf dem Test-Host ausführen und selbst auswerten - Traefik-Komprimierung, Migration 0166, Postgres-Parameter, Bereichs-CSS inklusive Dialoge und Detailseiten, Übersetzungen, Ladezeiten, Tippen in Pendenzen. Einsetzen, wenn auf dem Test-Host (01-test-hocx) nach einem Update getestet werden soll, oder bei "Abnahme", "teste auf dem Testsystem", "Tests auf dem Test-Host".
---

# Abnahme auf dem Test-Host

Prüft, was weder CI noch Dev-Host können: echtes Traefik, Release-Images, die Test-Datenbank und
die Performance-Änderungen aus 1.2.1 unter echten Bedingungen. Du führst die Prüfungen aus,
wertest sie selbst aus und meldest dem Nutzer ein Urteil.

**Regeln**

- Nur auf dem Test-Host. Prod ist tabu, das Skript bricht dort ab.
- Keine Commits und keine Dateiänderungen im Checkout: `update_deploy_code.sh` verlangt einen
  sauberen Worktree. Fehler werden gemeldet, nicht hier gepatcht; der Fix gehört auf den Dev-Host.
- Nicht promoten, nicht taggen. Deploy, Rollback und `.env`-Änderungen nur auf Zuruf des Nutzers.
- Passwörter und TOTP-Secrets nie ausgeben, nicht in den Bericht und nicht in Befehle schreiben.

## 1. Vorbedingungen

```bash
cat /etc/hocx/environment        # muss "test" sein
git log -1 --oneline             # enthält der Checkout die zu prüfende Änderung?
grep '^HOCX_VERSION=' .env       # Candidate-Tag
free -h && df -h /               # mindestens 3 GB RAM verfügbar, sonst dem Nutzer melden
```

Steht der Host noch nicht auf dem gewünschten Stand, frage den Nutzer, ob du aktualisieren sollst
(RUNBOOK Abschnitte 2 und 9: `HOCX_VERSION` in `.env`, `./scripts/update_deploy_code.sh --deploy`,
danach `./scripts/verify_release.sh test`). Die Abnahme auf einem alten Stand ist wertlos.

## 2. Zugangsdaten

Datei `~/.hocx-testhost.env` mit Rechten 600, ausserhalb des Repositories. Fehlt sie, bitte den
Nutzer, sie selbst anzulegen (lass dir die Werte nicht in den Chat schreiben):

```bash
TH_WRITER_EMAIL=...              # Konto mit Rolle writer, möglichst ohne MFA
TH_WRITER_PASSWORD=...
TH_TENANT_ADMIN_EMAIL=...        # Mandanten-Admin
TH_TENANT_ADMIN_PASSWORD=...
TH_TENANT_ADMIN_TOTP=...         # Base32-Secret, wenn das Konto TOTP hat
TH_PLATFORM_ADMIN_EMAIL=...
TH_PLATFORM_ADMIN_PASSWORD=...
TH_PLATFORM_ADMIN_TOTP=...
```

Das Skript richtet nie MFA ein. Fehlt ein Konto, werden nur dessen Prüfungen `SKIP`. Melde das im
Bericht als Lücke, nicht als bestanden.

## 3. Ausführen

Laufzeit etwa 20 bis 40 Minuten, im Hintergrund starten und nichts Speicherhungriges parallel:

```bash
TH_WRITE=1 TH_ADMIN_BASE="https://<admin-domain>:<port>" scripts/testhost/abnahme.sh all
```

| Variable | Bedeutung |
|---|---|
| `TH_BASE` | Standard `https://$TRAEFIK_DOMAIN` aus `.env` |
| `TH_ADMIN_BASE` | Admin-Einstieg (`TRAEFIK_ADMIN_DOMAIN`, Host-Port meist nur an 127.0.0.1 gebunden). Ohne: `TH-20d` wird `SKIP` |
| `TH_WRITE=1` | erlaubt `TH-25`: legt ein Wegwerf-Protokoll an und löscht es wieder. Vorher sagen, falls Dritte gerade testen |
| `TH_ADD_HOSTS` | ohne DNS: `"test.example:127.0.0.1 admin.test.example:127.0.0.1"` |
| `TH_PROTOCOL_ID` | Protokoll für die Messungen; Standard ist das grösste der letzten zwölf |
| `TH_ONLY` | nur diese Browser-Prüfungen wiederholen, z. B. `"TH-23 TH-25"` (mit Modus `browser`) |
| `TH_OUT` | Standard `~/hocx-testhost-results/<Zeitstempel>` |

Ergebnisse: `$TH_OUT/results.jsonl` (`id`, `status`, `summary`, `details`) und `$TH_OUT/shots/`.
Exit 1 heisst: mindestens ein `FAIL`.

## 4. Auswerten

Lies `results.jsonl` vollständig, auch `details`, nicht nur die Zusammenfassung. Eine Prüfung gilt
erst als bestanden, wenn sie wirklich etwas geprüft hat: `visited` muss die erwarteten Routen
enthalten und darf nicht auf Login-Seiten enden, `dialogs` muss grösser 0 sein.

| ID | Prüft | Bei `FAIL`/`WARN` |
|---|---|---|
| TH-01 | Container gesund, Backend-Image = `HOCX_VERSION` | Deploy unvollständig. Erst beheben lassen, sonst ist alles Weitere wertlos |
| TH-02 | `alembic_version` = Kopf des Checkouts | Deploy-Code und Image passen nicht zusammen |
| TH-03 | Migration 0166: vier Indizes weg, `record_job_run` mit `max(id)` | Migration nicht gelaufen. Blocker |
| TH-04 | Jobs melden ihre Läufe weiter | `FAIL`: Jobmeldung kaputt, Blocker. `WARN`: fehlgeschlagene Jobs in `/admin/jobs` ansehen, Ursache muss nichts mit dem Release zu tun haben |
| TH-05 | `random_page_cost`, `effective_io_concurrency`, `max_wal_size`, `pg_stat_statements.track` | Deploy hat die DB nicht neu erstellt (`docker-compose.release.yml`) |
| TH-06 | Neustarts, OOM, Tracebacks | Tracebacks lesen (`docker logs`, `/admin/error-logs`). OOM ist ein Blocker |
| TH-07 | Speicher der Frontends (nur Info) | Über 1,5 GB im Leerlauf dem Nutzer melden |
| TH-20a–e | Crawler: Anon, Writer, Mandanten-Admin, Plattform-Admin, Mobil | siehe unten |
| TH-21 | Alle Sprachen: keine rohen Schlüssel, kein `MISSING_MESSAGE` | Namespace fehlt in `lib/i18n/message-scopes.ts` für diese Route. Blocker |
| TH-22 | Ladezeiten bei 4-fach gedrosselter CPU | Grenzen siehe unten |
| TH-23 | HTML, CSS, JS, API-JSON komprimiert, Icon nicht | Traefik wurde nicht neu erstellt (`sync_traefik_static_config`) oder `compress@file` fehlt. Blocker, denn Next komprimiert nicht mehr selbst |
| TH-24 | Sammelrouten = Einzelrouten; 401 ohne Login, 404 bei unbekannter ID | Abweichung ist ein Blocker, Rechte-Abweichung sofort melden. `WARN`: nichts verglichen, Protokoll mit Pendenzen per `TH_PROTOCOL_ID` angeben |
| TH-25 | Tippen in Pendenz bleibt nach Neuladen erhalten, Verzögerung | Nicht gespeichert ist ein Blocker (Datenverlust). `TH-25c`: Wegwerf-Protokoll von Hand löschen |
| TH-29 | Browser-Skript abgebrochen | Ausgabe lesen, Ursache beheben (Netz, RAM, Image), Prüfung wiederholen |

**Crawler (TH-20).** Er lädt jede Seite hart, klickt Schaltflächen und Reiter an und folgt Links;
alle schreibenden Anfragen sind blockiert. `missingCss` listet Klassen, die im DOM stehen, deren
Bereichs-CSS auf dieser Route aber nicht geladen ist, also ungestylte Elemente. Jeder solche Fund
ist ein echter Fehler: Bundle im Layout der Route importieren oder Regel nach `globals.css`
verschieben, und `scripts/check-css-scopes.py` um den Fall ergänzen, den es übersehen hat.
`serverErrors` sind 5xx-Antworten beim Lesen, Blocker. `jsErrors` ergibt nur `WARN`, weil der
Schreibschutz selbst Fehler auslösen kann: Einträge mit `Failed to fetch` oder `Crawler:` sind
meist harmlos, alles andere prüfen.

**Grenzen TH-22** (Referenz: Messung auf dem Dev-Host mit 23 Traktanden, 2026-11-09):

| Wert | Referenz nachher (vorher) | `WARN` | `FAIL` |
|---|---|---|---|
| Protokollseite TTFB | 412 ms (1048 ms) | > 800 ms | > 1500 ms |
| Andere Seiten TTFB | 120–220 ms | > 400 ms | > 800 ms |
| CSS je Seite | 251–341 KB (579 KB) | | > 400 KB |
| Längste Blockade Protokoll | 652 ms (1018 ms) | > 1000 ms | |
| Pendenz tippen, p50 (TH-25) | 60 ms (488 ms) | > 150 ms | > 250 ms |

Die Referenz lief ohne TLS und Traefik auf anderer Hardware. Vergleiche Grössenordnungen, keine
Millisekunden. Bleibt ein Wert knapp über der Grenze, einmal wiederholen, bevor du ihn meldest.

**Screenshots ansehen.** Öffne mit dem Read-Tool etwa 15 Bilder aus `shots/`: alle `*-dialog-*`
der Bereiche Dokumente, Vorlagen, Mandanten-Einstellungen, Admin, dazu Protokollseite und zwei
Mobilseiten. Worauf achten: Text ohne Abstand, Schaltflächen ohne Rahmen, Modals ohne Hintergrund,
übereinanderliegende Elemente. Das fängt, was die Klassenprüfung nicht sieht, etwa eine falsche
Kaskade. Nichts davon ist mit dem Stand vor dem Update vergleichbar, also nur klare Fehler melden.

## 5. Vom Nutzer zu prüfen

Das kannst du nicht selbst beurteilen. Nenne es im Bericht als offene Punkte:

- Scrollen und Tippen auf einem echten, eher schwachen Rechner im Protokoll mit vielen Traktanden.
- Zwei Personen gleichzeitig im selben Protokoll: Bearbeitungssperren, Pendenzen sichtbar beim
  anderen, kein Textverlust. Pendenzen werden jetzt verzögert gespeichert, darum auch: tippen und
  den Tab sofort schliessen.
- Matrix-Karten: Liste ändern, im Protokoll «Daten aktualisieren» (neu, umbenannt, entfernt,
  erfasste Karte bleibt mit Hinweis).
- Erfasstes in Matrix-Blöcken: die Tipp-Verzögerung dort wurde bisher nie gemessen.

## 6. Bericht

Schreibe `$TH_OUT/REPORT.md` und antworte dem Nutzer knapp mit:

1. **Urteil**: `FREIGABE` (kein `FAIL`, keine ungeprüfte Pflichtprüfung), `FREIGABE MIT VORBEHALT`
   (nur `WARN`, oder `SKIP` bei TH-20c/d/TH-25 mit Begründung) oder `NICHT FREIGEBEN` (`FAIL`,
   oder TH-01 bis TH-03, TH-20b oder TH-23 nicht geprüft).
2. **Getestet**: Commit, `HOCX_VERSION`, Datum, welche Konten.
3. **Funde** nach Schwere, je mit Prüf-ID, Route, Beleg und vermuteter Ursache mit Datei.
4. **Nicht geprüft** (`SKIP`, Abschnitt 5), jeweils mit Grund.
5. **Messwerte** aus TH-22 und TH-25 gegen die Referenz.

Kommt das Urteil `FREIGABE`, ist der nächste Schritt laut RUNBOOK Abschnitt 3 die Promotion. Die
macht der Nutzer selbst.
