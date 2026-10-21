# hocX – Lasttests und Reproduktionen

Begleitmaterial zu `ROBUSTNESS_CONCURRENCY_AUDIT.md` (Abschnitt 7). Alles hier ist **nicht
destruktiv gegenüber Bestandsdaten**, erzeugt aber Last und eigene Testdaten.

## Sicherheitsregeln (verbindlich)

1. Nur gegen einen **ausdrücklich freigegebenen, isolierten** Stack: eigenes Compose-Projekt
   (z. B. `hocx-loadtest`), eigene Volumes, eigene Datenbank, eigener Host oder zumindest nicht
   der Host der Dev-/Produktivinstanz. Nie gegen Produktion, nie gegen `hocx-dev`.
2. Jedes k6-Skript verlangt `-e HOCX_LOADTEST_TARGET_CONFIRMED=isolated`; mit
   `-e FORBIDDEN_HOSTS=hocx.ch,…` brechen Skripte ab, falls die URL einen gesperrten Host enthält.
3. Der Seeder verweigert `HOCX_ENVIRONMENT=production`, verlangt `HOCX_LOADTEST=1` und einen
   Datenbanknamen mit `loadtest`/`e2e`/`test`.
4. Vor Szenario C/D freien Speicher prüfen: Galerie-ZIPs werden auf dem Upload-Datenträger
   gepuffert (bis 10 GiB je Upload, entpackt bis 20 GiB), Vereinsexporte und öffentliche
   ZIP-Downloads legen vollständige Kopien an. Auf dem aktuellen Dev-Host (95 % belegt) **nicht**
   ausführen.

## Zielumgebung

Messwerte sind nur aussagekräftig mit der **Release-Konfiguration** (`docker-compose.release.yml`:
2 uvicorn-Worker, Ressourcenlimits, Traefik-Middlewares). Der E2E-Stack (`scripts/e2e.sh`) nutzt
die Dev-Compose-Dateien und andere Limits – für Funktionsproben ok, für Kapazitätsaussagen nicht.

Empfohlen: eigener Host mit denselben Eckdaten wie Produktion (laut Compose-Kommentar 8 Kerne,
16 GB), Release-Images des zu prüfenden Commits, `docker-compose.release.yml` +
`docker-compose.clamav.yml` + `docker-compose.traefik.yml` mit eigener `.env`, `COMPOSE_PROJECT_NAME=hocx-loadtest`,
`POSTGRES_DB=hocx_loadtest`, ohne Captcha-Schlüssel (dev/test überspringt das Captcha) und mit
`HOCX_ENVIRONMENT=test`. Lastgenerator auf einem **zweiten** Rechner (sonst konkurriert k6 um
dieselbe CPU) – oder mindestens mit `--cpus` begrenzt.

Hinweis Traefik: `/api/auth/login` ist auf 10/min je IP begrenzt, `inflightreq` auf 100 je IP.
Der Lastgenerator hat eine IP – deshalb Sessions per Seeder statt Login, und für Profile ab
u250 entweder mehrere Lastgeneratoren/IPs oder `BASE_URL` direkt auf den Backend-Port
(dann **ohne** Traefik-Limits – im Ergebnis vermerken).

## Ablauf mit `loadtest/stack/` (empfohlen)

```bash
loadtest/stack/up.sh                      # baut Images dieses Commits, .env/Secrets unter /docker/loadtest-stack
/docker/loadtest-stack/dc.sh run --rm --no-deps -T -e HOCX_LOADTEST=1 \
  -v "$PWD/loadtest:/loadtest:ro" -v /docker/loadtest-stack/seed-out:/out \
  backend python /loadtest/seed/seed_loadtest.py --tenants 20 --writers 25 --out /out/tokens.json
loadtest/stack/k6.sh interactive.js u100 -e PROFILE=u100     # Ergebnis: /docker/loadtest-stack/results/u100
python3 loadtest/stack/summarize.py /docker/loadtest-stack/results u10 u50 u100
loadtest/stack/down.sh                    # Stack, Volumes, Images entfernen (results/ bleibt)
```

k6 läuft als Container im Netz des Stacks gegen `backend:8000` (ohne Traefik-Limits), Tokens und
Messdaten bleiben ausserhalb des Repos. `loadtest/k6/session_consistency.js` prüft CONC-022.

## Ablauf (manuell, eigener Host)

```bash
# 1. Daten (im Backend-Container des Lasttest-Stacks)
docker cp loadtest hocx-loadtest-backend-1:/loadtest
docker exec -e HOCX_LOADTEST=1 -e DEMO_TOTP_SEED=JBSWY3DPEHPK3PXP hocx-loadtest-backend-1 \
  python /loadtest/seed/seed_loadtest.py --tenants 20 --writers 25 --out /loadtest/tokens.json
docker cp hocx-loadtest-backend-1:/loadtest/tokens.json loadtest/tokens.json   # in .gitignore

# 2. Testdateien
docker run --rm -v "$PWD/loadtest/fixtures:/out" hocx-tests-backend-test:latest python /out/make_fixtures.py --out /out

# 3. Messung starten (parallel zum Lasttest, eigenes Terminal)
LT_PROJECT=hocx-loadtest INTERVAL=5 OUT=results/u100 loadtest/monitor/sample.sh
docker exec hocx-loadtest-db-1 psql -U hocx -d hocx_loadtest -c "SELECT pg_stat_statements_reset();"

# 4. Lastprofile (je Lauf neu messen, Stack zwischen den Stufen nicht neu starten)
cd loadtest/k6
for p in u10 u50 u100 u250 u500 u1000; do
  k6 run -e PROFILE=$p -e BASE_URL=https://lt.example.test -e HOCX_LOADTEST_TARGET_CONFIRMED=isolated \
         -e TOKENS_FILE=../tokens.json --summary-export=../../results/$p.json interactive.js
done
k6 run -e PROFILE=burst ... interactive.js
k6 run -e PROFILE=soak -e SOAK_DURATION=4h ... interactive.js

# 5. Schwere Aufgaben: Mandant 0 schwer, Mandanten 1-5 interaktiv – Vergleich mit Baseline (Schritt 4, u100)
k6 run -e HEAVY_TENANTS=0 -e INTERACTIVE_TENANTS=1,2,3,4,5 -e INTERACTIVE_VUS=100 \
       -e FIXTURE_ZIP=../fixtures/gallery-200.zip ... heavy.js

# 6. Kollaboration und Upload-Sturm
k6 run -e COLLAB_USERS=50 -e TENANT_FILTER=0 ... collab.js
k6 run -e STORM_VUS=50 -e ABGABEBOX_URL=https://abgabe.lt.example.test ... abgabebox_storm.js

# 7. Am Ende jedes Laufs
docker exec -i hocx-loadtest-db-1 psql -U hocx -d hocx_loadtest < loadtest/monitor/queries.sql > results/<lauf>-db.txt
```

Event-Loop- und Threadpool-Zustand zusätzlich mit py-spy (eigener Container, nur Lesezugriff
auf den Prozessbaum des Backends):

```bash
docker run --rm --pid=container:hocx-loadtest-backend-1 --cap-add SYS_PTRACE python:3.13-slim \
  sh -c "pip install -q py-spy && py-spy dump --pid \$(pgrep -f 'uvicorn' | tail -1)"
```

## Skripte

| Datei | Zweck |
|---|---|
| `seed/seed_loadtest.py` | N Mandanten (Muster `seed_test_tenant.py`) + W Schreibkonten je Mandant, Session-Tokens → `tokens.json` |
| `fixtures/make_fixtures.py` | Rausch-JPEGs (1/8/25 MB) und ZIP mit 200 Bildern |
| `k6/interactive.js` | Szenario A: Lesen/Navigieren/Autosave/Anwesenheit + Event-Loop-Sonde (OPTIONS-Preflight) und Threadpool-Sonde (`/api/health`) |
| `k6/collab.js` | Szenario B: 20–50 WebSockets auf demselben Protokoll, Locks, Broadcast-Latenz, Abbrüche |
| `k6/heavy.js` | Szenario C: PDF-Render/Vorschau, Galerie-Uploads, Ähnlichkeitsgruppen, Vereinsexport in Mandant A, interaktive Last in Mandant B |
| `k6/abgabebox_storm.js` | Szenario D: öffentlicher Upload-Sturm (zählt 503 "Upload-Kapazität belegt", Scan-Fehler) |
| `monitor/sample.sh` | CSV: `docker stats`, `pg_stat_activity` je Rolle/Zustand, Lock-Wartende, Redis INFO |
| `monitor/queries.sql` | Lock-Graph, Advisory Locks, `storage_state`-Sperren, pg_stat_statements, Warteschlangen, Joblaufzeiten |
| `repro/attendance_lost_update.py` | CONC-005: parallele Anwesenheits-Klicks → zählt verlorene Updates (braucht einen Anwesenheitsblock in einem offenen Protokoll; der Demo-Seed legt keinen an – einmal per UI hinzufügen) |
| `repro/loop_block_probe.py` | CONC-001 (Muster): synchroner Pool-Checkout in ASGI-Middleware friert DB-freie Requests ein |
| `repro/stream_dep_probe.py` | CONC-002: yield-Dependency hält Pool-Verbindung bis zum Ende einer StreamingResponse |
| `repro/pg_lock_probes.sh` | CONC-006/-023: Advisory-Lock nach Idle-Timeout frei; FOR SHARE hinter wartendem UPDATE |

`repro/loop_block_probe.py` und `stream_dep_probe.py` laufen gegen einen Wegwerf-Postgres
(`docker run -d --name hocx-audit-pgprobe -e POSTGRES_PASSWORD=probe --tmpfs /var/lib/postgresql/data postgres:16`)
im Backend-Test-Image: `docker run --rm --network container:hocx-audit-pgprobe -v "$PWD/loadtest/repro:/probe:ro" hocx-tests-backend-test:latest python /probe/<datei>`.

## Erfolgskriterien (Startwerte, nach der ersten Baseline festschreiben)

| Kriterium | Grenze |
|---|---|
| Interaktiv p95 / p99 (`hocx_interactive_ms`) bei Zielnutzerzahl | < 800 ms / < 2 s |
| Fehlerrate interaktiv | < 1 %, keine `QueuePool limit … timed out` im Backend-Log |
| Event-Loop-Sonde p99 (`hocx_loop_probe_ms`) | < 250 ms (Werte nahe 30 s = Pool-Timeout im Event-Loop, CONC-001) |
| Threadpool-Sonde p99 (`hocx_threadpool_probe_ms`) | < 500 ms |
| Mandant B interaktiv p95 während Heavy-Last in Mandant A | ≤ 1,5 × Baseline |
| WebSocket | 0 unerwartete Abbrüche, Broadcast p95 < 500 ms |
| Abgabebox-Sturm | 0 × 503 "Upload-Kapazität belegt" bei der erwarteten Spitzenzahl |
| Lost Updates (`attendance_lost_update.py`) | 0 Runden |
| `idle in transaction` > 60 s ausserhalb von Hintergrundjobs | 0 |
| Soak (4 h) | kein RSS-Wachstum > 10 %, keine Worker-Neustarts, keine wachsende Joblaufzeit |
