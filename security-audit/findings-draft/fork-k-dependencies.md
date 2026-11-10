# Fork K — Dependencies (Audit-Abschnitt 25)

Scope: Python-/JS-Dependency-Inventar + gezielte CVE-Recherche für sicherheitskritische
Kern-Bibliotheken. Keine Codeänderungen, keine Commits. Alle Versionen exakt gepinnt
(`==` in `requirements.txt`, exakte Versionen in `package.json` — kein `^`/`~` bei den
Kern-Runtime-Deps ausser den Tiptap-Paketen und wenigen Dev-Tools).

## Paket-Inventar

### `backend/requirements.txt`
fastapi==0.140.0, uvicorn[standard]==0.34.0, sqlalchemy==2.0.40, alembic==1.15.2,
psycopg[binary]==3.2.6, pydantic==2.11.3, pydantic-settings==2.8.1,
python-multipart==0.0.32, pyclamd==0.4.0, redis==5.2.1, matplotlib==3.10.1,
dnspython==2.7.0, PyYAML==6.0.3, PyJWT[crypto]==2.10.1, cryptography==50.0.0,
python-docx==1.1.2, pdfplumber==0.11.10, scipy==1.18.0, Pillow==12.3.0,
pillow-heif==1.7.0, ImageHash==4.3.2

### `backend/requirements-dev.txt` (zusätzlich, nie in Produktion installiert)
pytest==8.3.4, pytest-cov==6.0.0, httpx2>=2.0.0,<3 (Test-Client), reportlab==5.0.0
(nur Test-Fixtures)

### `abgabebox-backend/requirements.txt`
Erbt `backend/requirements.txt` (`-r requirements.txt`) + eigene Pins: fastapi==0.140.0,
uvicorn[standard]==0.34.0, sqlalchemy==2.0.40, psycopg[binary]==3.2.6, pydantic==2.11.3,
pydantic-settings==2.8.1, python-multipart==0.0.32, httpx==0.28.1, pyclamd==0.4.0,
scipy==1.18.0, Pillow==12.3.0, ImageHash==4.3.2 (identische Versionen wie Hauptbackend,
kein Versions-Drift zwischen den Services).

### `photo-analysis-worker/requirements.txt`
opencv-python-headless==5.0.0.93, numpy==2.5.3, SQLAlchemy==2.0.40, psycopg[binary]==3.2.6.
Kein separates `onnxruntime`-Paket — die ONNX-Inferenz läuft über OpenCVs eigenes DNN-Modul
(`cv2.dnn`/`FaceDetectorYN`), nicht über eine zusätzliche Python-Onnxruntime-Dependency.

### `frontend/package.json`
next=16.2.12, react=19.2.8, react-dom=19.2.8, @tiptap/pm=^2.11.5, @tiptap/react=^2.11.5,
@tiptap/starter-kit=^2.11.5, tiptap-markdown=^0.8.10, qrcode=^1.5.4, recharts=^2.15.4
(+ Dev-Tools: playwright, vitest, testing-library, typescript — keine Laufzeit-Relevanz)

### `abgabebox-frontend/package.json`
next=16.2.12, react=19.2.8, react-dom=19.2.8, friendly-challenge=^0.9.20 (FriendlyCaptcha-
Client-Widget)

## Bestätigte/relevante Findings

### [DEP-01] [MEDIUM] Next.js 16.2.12 liegt im betroffenen Versionsbereich einer kritischen RCE (CVE/GHSA-vcvr-r3jv-pc5j, Next.js-Advisory 2026-09-22), verwundbares Feature aber nicht genutzt

Status: CONFIRMED (Versions-Match), Impact aktuell NICHT ausnutzbar (Feature ungenutzt)
CWE: CWE-1104 (Use of Unmaintained Third-Party Components) / betroffene CVE selbst ist eine
Remote-Code-Execution über `next/og`/`ImageResponse` (Node.js-Runtime, Satori-SVG-Escaping)

Betroffene Dateien: `frontend/package.json`, `abgabebox-frontend/package.json` (beide
`next=16.2.12`)

#### Beschreibung
Next.js hat am 22.09.2026 einen kritischen Out-of-Band-Security-Release (16.3.6 / 15.5.26)
veröffentlicht: Next.js-Versionen `>=16.2.0 <16.3.6` sind durch eine RCE-Schwachstelle in der
Node.js-`ImageResponse`-Implementierung (`next/og`, fehlerhaftes SVG-Escaping über die
Satori-Abhängigkeit) betroffen. Beide Frontends dieses Repos pinnen exakt `16.2.12` — liegt
eindeutig im betroffenen Bereich.

#### Verifikation (False-Positive-Check, Abschnitt 28)
`grep -rn "next/og\|ImageResponse" frontend/ abgabebox-frontend/` (ausserhalb `node_modules`)
ergibt **keinen Treffer** — keines der beiden Frontends nutzt `next/og`/`ImageResponse`
überhaupt. Der konkrete RCE-Pfad ist daher aktuell nicht erreichbar.

#### Impact
Aktuell kein bekannter ausnutzbarer Pfad in diesem Repo (Feature ungenutzt). Dennoch:
Next.js 16.2.x ist laut denselben Suchergebnissen zusätzlich von mehreren im Mai 2026 gefixten
Middleware-/Bypass-CVEs betroffen gewesen (`CVE-2026-44574` u. a., gefixt in 16.2.5/16.2.6) —
`16.2.12` liegt NACH diesen Fixes (nicht betroffen), aber das Gesamtbild (mehrere kritische
Advisories innerhalb weniger Monate für den 16.2.x-Zweig) spricht dafür, zeitnah auf den
gepatchten Stand zu aktualisieren, statt einzelne CVEs isoliert zu bewerten.

#### Recommended Fix
`next` in beiden `package.json` auf `>=16.3.6` (bzw. aktuelle 16.3.x-Patch-Version) anheben,
Regressionstests (Playwright-E2E-Suiten) danach laufen lassen. Kostengünstiger Fix (reiner
Patch-Versionssprung innerhalb derselben Minor-Linie laut Next.js-Advisory).

#### Evidence
`frontend/package.json`, `abgabebox-frontend/package.json`; Next.js-Advisory
"Next.js Security Update for a Critical Upstream Issue" (22.09.2026, GHSA-vcvr-r3jv-pc5j).

---

### [DEP-02] [NEEDS_VERSION_VERIFICATION] FastAPI/Starlette: kein expliziter Starlette-Pin gegen CVE-2026-48710 ("BadHost", CISA-KEV)

Status: NEEDS_VERSION_VERIFICATION — tatsächlich installierte Starlette-Version im
produktiven Image aus dem Repo-Code allein nicht bestimmbar (kein Lockfile, kein
`pip freeze`-Artefakt im Repo; Backend-Container zum Zeitpunkt des Audits nicht laufend,
kann daher auch nicht live inspiziert werden — siehe unten).
CWE: CWE-1395 (Dependency on Vulnerable Third-Party Component) — konkrete CVE:
CVE-2026-48710, CVSS 6.5 (Medium), seit 02.09.2026 in der CISA KEV-Liste (aktiv ausgenutzt).

Betroffene Datei: `backend/requirements.txt` (`fastapi==0.140.0`, kein separates
`starlette==`-Pin)

#### Beschreibung
CVE-2026-48710 ("BadHost") ist eine Host-Header-Authentication-Bypass-Schwachstelle in
Starlette (betrifft Starlette `0.8.3` bis `1.0.0`, gefixt in `1.0.1`, veröffentlicht
21.05.2026): ein einzelnes fehlerhaftes Zeichen im `Host`-Header lässt `request.url`/
pfadbasierte Security-Middleware fehlinterpretieren. FastAPI `0.140.0` verlangt laut
offiziellem Changelog nur `starlette>=0.46.0` **ohne Obergrenze** — die tatsächlich beim
Docker-Image-Build von `pip` aufgelöste Version hängt vom Build-Zeitpunkt ab, nicht von einer
im Repo fixierten Version. Ein lokaler `uv`-Cache-Fund auf diesem Host zeigt zwar
`starlette-1.6.0` (deutlich über der gepatchten Version) als einmal aufgelöste Version — das
belegt aber nur, dass IRGENDWANN ein Environment mit einer gepatchten Version gebaut wurde,
nicht zwingend das aktuell produktiv laufende Image (dessen exakte Digest-gepinnte Version
laut `deploy.sh`/Cosign-Mechanismus zum jeweiligen Build-Zeitpunkt in CI eingefroren wurde).

#### Warum hier relevant über das Übliche hinaus
Diese Anwendung hat ein **Custom-Domain-Feature** (Host-Header-basiertes Tenant-/Domain-
Routing, `traefik_config_service.py`, `TRAEFIK_ADMIN_DOMAIN`-Unterscheidung in `proxy.ts`).
Falls irgendein Code-Pfad im Backend `request.url`/`request.base_url` (von Starlette aus dem
`Host`-Header rekonstruiert) für eine Security-Entscheidung nutzt (z. B. Ableitung des
Tenants oder Unterscheidung Admin-Domain vs. normale Domain), wäre ein Host-Header-Bypass
potenziell wirkungsvoller als im Durchschnittsfall. Diese spezifische Code-Pfad-Frage wurde
in diesem Fork NICHT verifiziert (ausserhalb des Scopes "Dependencies") — Empfehlung: an
Fork B/Backend-Team weitergeben, ob `request.url`/`request.base_url`/`request.headers["host"]`
irgendwo für eine Auth-/Tenant-Entscheidung statt für reines Logging/Link-Generierung genutzt
wird.

#### Preconditions
Nur relevant, falls die tatsächlich deployte Starlette-Version im Bereich `0.8.3`–`1.0.0`
liegt UND ein Code-Pfad existiert, der sich auf den (durch Starlette ungeprüft
rekonstruierten) `Host`-Wert für eine Security-Entscheidung verlässt.

#### Recommended Fix
1. `starlette>=1.0.1` explizit in `backend/requirements.txt`/`abgabebox-backend/requirements.txt`
   pinnen (unabhängig vom tatsächlichen Risiko — kostenloser Fix, schliesst die
   Unsicherheit über zukünftige Builds strukturell).
2. Tatsächlich laufendes Produktions-Image inspizieren (`pip show starlette` im Container,
   oder Image-SBOM falls vorhanden) — ausserhalb der Möglichkeiten dieses Code-Audits, da der
   Backend-Container zum Zeitpunkt der Prüfung nicht lief (nur `test-db`/`test-redis` aktiv,
   vermutlich von einem parallel laufenden E2E-Lauf einer anderen Session — bewusst nicht
   angefasst, um diesen Lauf nicht zu stören).

#### Regression Test
Kein klassischer Unit-Test sinnvoll (Dependency-Pinning-Policy); stattdessen ein CI-Schritt,
der `pip list`/`pip-audit` gegen eine bekannte CVE-Datenbank prüft (siehe generelle Empfehlung
unten).

#### Evidence
`backend/requirements.txt:1`; FastAPI-Changelog-Aussage "runtime requirement for Starlette
has been a bare floor, starlette>=0.46.0, since 0.136.3 ... with no upper bound"; CVE-2026-48710
(IONIX/CISA-KEV, Fix in Starlette 1.0.1, 21.05.2026); lokaler Fund
`/root/.cache/uv/archive-v0/HKa3U4muEvOs4DZ1/starlette-1.6.0.dist-info` (Beleg für IRGENDEINE
gepatchte Auflösung, kein Beleg für das Produktions-Image).

## Geprüft, nicht betroffen (Version ist bereits Fix-Version oder deutlich danach)

- **cryptography==50.0.0**: exakt die Fix-Version für CVE-2026-69247 (Bleichenbacher-Oracle
  in `pkcs7_decrypt_*`, betrifft `44.0.0`–`<50.0.0`). Zusätzlich: Code nutzt laut Phase-1/2-
  Funden kein PKCS7/S-MIME-Decrypt (eigenes HMAC-Session-Token-Schema, kein
  `pkcs7_decrypt_der/pem/smime`-Aufruf gefunden) — selbst bei einer älteren Version wäre der
  konkrete Angriffspfad hier nicht vorhanden. Kein Fund.
- **Pillow==12.3.0**: exakt die Fix-Version für die McIdas-AREA-mmap-Out-of-Bounds-Lese-
  Schwachstelle und den `FontFile.compile()`-Decompression-Bomb-Gap; FITS-Decompression-Bomb
  (betraf `10.3.0`–`12.1.1`) ebenfalls bereits gefixt. Kein Fund.
- **python-docx==1.1.2**: CVE-2016-5851 (XXE) betraf Versionen vor `0.8.6` — `1.1.2` liegt
  weit danach, XXE-Schutz seit langem Standard in der Bibliothek. Kein Fund (Cross-Reference:
  Fork C hat den `.docx`-Parsing-Pfad selbst bereits separat als isoliert/prozess-gesandboxt
  verifiziert).
- **FastAPI==0.140.0**: die einzige direkt FastAPI-spezifische kritische CVE in den
  Suchergebnissen (CVE-2026-2978, RCE) betrifft Versionen **vor** `0.115.8` — `0.140.0` liegt
  weit danach. `fastapi-sso`-CVE (`CVE-2025-14546`) betrifft ein anderes, hier nicht
  verwendetes Paket. Kein Fund (die relevante Restfrage ist die transitive Starlette-Version,
  siehe DEP-02).

## Nicht tief recherchiert (niedrigere Priorität, aus Zeitgründen nur Versions-Notiz)

PyYAML==6.0.3, dnspython==2.7.0, redis==5.2.1 (Python-Client, kein bekanntes aktives
Advisory in den durchgeführten Suchen, geringe Angriffsfläche da nur intern gegen die eigene
Redis-Instanz verwendet), scipy==1.18.0, ImageHash==4.3.2, matplotlib==3.10.1,
pillow-heif==1.7.0, pdfplumber==0.11.10, pyclamd==0.4.0, uvicorn==0.34.0, alembic==1.15.2,
sqlalchemy==2.0.40, psycopg==3.2.6, pydantic(-settings), python-multipart==0.0.32,
opencv-python-headless==5.0.0.93, numpy==2.5.3, qrcode/recharts/@tiptap-Pakete,
friendly-challenge. **Empfehlung statt Einzelrecherche**: `pip-audit`/`npm audit`
(bzw. GitHub Dependabot, falls nicht bereits aktiv) in die CI aufnehmen — das deckt diese
Breite systematisch ab, statt sie manuell im Audit nachzuziehen.

## PyJWT — geprüft, geringes Risiko trotz Versionslücke

`PyJWT==2.10.1` (< `2.12.0`, betroffen von CVE-2026-32597: `crit`-Header-Parameter aus
RFC 7515 §4.1.11 wird nicht validiert, unbekannte Extensions werden fälschlich akzeptiert
statt abgelehnt). Tatsächliche Nutzung im Code: **ausschliesslich**
`backend/app/services/platform_oidc_service.py` (Platform-Admin-SSO/OIDC-Login,
`jwt.decode(...)` auf ID-Tokens vom konfigurierten Identity-Provider). Der eigentliche
Session-Token-Mechanismus (`core/security.py`) nutzt PyJWT NICHT (eigenes HMAC-Schema).
Risiko ist damit auf den optionalen Platform-Admin-OIDC-Login begrenzt (kleine Angriffsfläche,
erfordert Kontrolle über den IdP/ID-Token-Inhalt) — kein CONFIRMED-Finding, aber als
**POTENTIAL** vermerkt: Update auf `PyJWT>=2.12.0` ist ein risikoarmer, empfehlenswerter
Hygiene-Fix, da OIDC-Login-Code-Pfade generell hochsensibel sind. Ein alternativ genannter
Fund (`CVE-2025-45768`, "weak encryption") ist laut Hersteller **disputed** (Schlüssellänge
liegt in der Hand der aufrufenden Anwendung, kein Bibliotheksfehler) — kein Fund.

## Fazit

2 Findings mit Handlungsbedarf: **DEP-01** (MEDIUM, Next.js-Patch-Upgrade empfohlen, aktuell
nicht ausnutzbar da Feature ungenutzt) und **DEP-02** (NEEDS_VERSION_VERIFICATION, Starlette-
Pin fehlt, tatsächliche Produktions-Version nicht aus dem Repo bestimmbar — Kandidat für
FINAL_REPORT "Residual Risk", da Runtime-Verifikation nötig). 1 POTENTIAL (PyJWT-Update,
geringes Risiko, begrenzt auf OIDC-Login). Alle anderen geprüften Kern-Bibliotheken sind
bereits auf oder nach der jeweiligen Fix-Version gepinnt. Generelle Empfehlung: automatisiertes
`pip-audit`/`npm audit`/Dependabot in CI aufnehmen, um diese Klasse von Findings künftig
kontinuierlich statt punktuell im Audit abzudecken.
