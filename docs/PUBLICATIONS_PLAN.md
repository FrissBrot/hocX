# Umsetzungsplan: Hefte / Vereinszeitungen in hocX

Stand: 14.11.2026 · Grundlage: Code-Stand `frissbrot/hocx` @ `ee0baab`, Referenzprojekt «Gliähwurm 2025» (InDesign)

> **Status:** Plan, noch nicht umgesetzt. Hinweis zur Nummerierung: `0181` ist inzwischen durch den
> persönlichen Abgabe-Link belegt (`0181_submission_owner_access`), die Migrationen der Hefte
> beginnen deshalb frühestens bei `0182` (Wanderplaner beachten).

## 1. Ziel

Mit hocX soll ein Verein ein Heft (Jahresheft, Vereinszeitung, Lagerbericht) aus vorhandenen Daten
zusammenstellen und als druckfertiges PDF ausgeben – ohne InDesign.

Ein Heft besteht aus einer geordneten Liste von **Bausteinen**, z. B.:

| # | Baustein | Inhalt kommt aus |
|---|---|---|
| 1 | Titelseite | Titel, Jahrgang, Titelbild |
| 2 | Editorial / Impressum | Text mit Platzhaltern (Auflage, Datum, Druckerei, Redaktion) |
| 3 | Inhaltsverzeichnis | automatisch |
| 4 | **Termin-Schleife** | alle Termine mit Tag X im Zeitraum → pro Termin Titel, Datum, **Text und Bilder aus der Abgabe zu diesem Termin** |
| 5 | Rätsel / feste Seiten | hochgeladene Assets (PDF/PNG) |
| 6 | Inserate | Inserate-Register, automatisch auf Seiten verteilt |
| 7 | Rückseite | Text, Logo, Website |

**Referenz «Gliähwurm 2025»**: A5 (148 × 210 mm), 52 Seiten, doppelseitig, 3 mm Anschnitt, CMYK,
Schriften Helvetica + Daily Grind, ca. 10 Anlassberichte (Titel, Datum, Text, 1–4 Fotos, oft
ganzseitige Fotoseiten), mehrseitiger Lagerbericht, Rätsel, Gruppeneinteilung, Scharprogramm,
18 Inserate (meist PDF, 1/1 und 1/2 Seite).

**Abnahmekriterium Gesamtprojekt:** Ein Heft im Umfang des Gliähwurms lässt sich aus Terminen,
Abgaben und Assets erzeugen und wird von der Druckerei ohne Nacharbeit angenommen.

## 2. Leitentscheide

1. **Eigenes Objekt «Heft» (`publication`), kein Protokoll.** Protokolle tragen Sitzungslogik
   (Status, Anwesenheit, Bussen, Versionen). Übernommen wird nur das Bedienmuster: sortierbare
   Bausteinliste mit Konfiguration pro Baustein (wie `TemplateElement`).
2. **Abgabebox bleibt unverändert.** Text und Bilder kommen aus den bestehenden Abgaben:
   `SubmissionUpload.event_id` → `SubmissionUploadFile` → `StoredFile`. Texte liefert die
   bestehende Extraktion (`DocumentExtraction.content`, Format `hocx.document-content`), Bilder
   das Best-of des Abgabe-Element-Albums (`PhotoAlbum.kind = "submission_element"`).
3. **Seitenmuster statt freiem Layout.** Ein Muster ist eine fertig gestaltete Seite oder
   Seitenfolge («Bericht + 1 Bild», «Fotoseite 2/4 Bilder», «Inseratseite 2 × 1/2»). hocX füllt
   Muster automatisch, der Benutzer kann pro Termin ein anderes Muster wählen. Kein InDesign-Nachbau.
4. **Gleiche Engine wie das Document Studio.** Das Heft wird zu einem Layout-Baum
   (`documents/layout.py`) kompiliert und mit Typst gerendert. Neue Fähigkeiten (Doppelseiten,
   Anschnitt, Bilder aus Dateien, PDF-Assets) kommen in die Engine und stehen danach auch
   Vorlagen im Studio zur Verfügung.
5. **Druckvorstufe als Nachbearbeitung.** Typst rendert RGB mit vergrösserten Seiten (Anschnitt);
   ein Prepress-Schritt setzt TrimBox/BleedBox und erzeugt bei Bedarf CMYK/PDF/X (Ghostscript).
6. **Inhalte werden aufgelöst, nicht kopiert.** Das Heft speichert nur Konfiguration und
   Überschreibungen (Foto fixiert/ausgeschlossen, anderes Muster). Ändert jemand eine Abgabe, zeigt
   das nächste Rendern den neuen Stand. Erst der Export «final» friert den Stand ein (PDF-Version
   im Dokumentarchiv).

## 3. Datenfluss

```
Heft (publication)
 └─ Bausteine (publication_section, sortiert)
     └─ Termin-Schleife: Tag-/Zyklus-Filter + Zeitraum + Abgabe
          │
          ▼  publication_content_service.resolve()
     Termin (event)  ──  SubmissionUpload(assignment, event)  ──  SubmissionUploadFile
          │                                                        ├─ Dokument → DocumentExtraction.content → Textblöcke
          │                                                        └─ Bild     → Album submission_element → Best-of-Reihenfolge
          │  + Überschreibungen (publication_event_override)
          ▼
     PublicationModel (reine Daten: Abschnitte → Einträge → Text, Fotos, Warnungen)
          │
          ├─► API «Inhaltsstatus» (Editor: Text fehlt / in Verarbeitung / 12 Fotos, 3 gewählt)
          ▼
     publication_compiler → Layout-Baum (Seitenmuster instanziert) → LayoutCompiler → Typst
          ▼
     PDF (RGB, Anschnitt) → prepress (TrimBox/BleedBox, optional CMYK/PDF/X) → Dokumentarchiv
```

## 4. Datenmodell (Migrationen ab `0182`, siehe Hinweis oben)

Alle Tabellen mit Mandantendaten: `tenant_id NOT NULL` + RLS-Policy im selben Change
(Untertabellen über die Elterntabelle), siehe `SECURITY-RULES.md`.

### 4.1 `publication`
| Feld | Typ | Bemerkung |
|---|---|---|
| id, public_id, tenant_id | | Standard (`uuidv7()`) |
| title | text | «Gliähwurm» |
| issue_label | text | «2024/2025» |
| period_from, period_to | date | Standardzeitraum für Termin-Schleifen |
| status | text | `draft` · `final` (CHECK) |
| page_setup_json | jsonb | Format, Ausrichtung, `facing`, Ränder innen/aussen, `bleed_mm`, Spalten |
| print_profile_json | jsonb | `output`: `screen`/`print`, `color`: `rgb`/`cmyk`, `pdfx`: `none`/`x3`/`x4`, `min_dpi`, `crop_marks`, `page_multiple` (z. B. 4) |
| brand_id | fk → document_brand, null | Schriften/Farben aus dem Brand-Profil |
| created_by | fk app_user | |
| timestamps | | |

### 4.2 `publication_section`
| Feld | Typ | Bemerkung |
|---|---|---|
| id, public_id, publication_id (cascade) | | RLS über `publication` |
| sort_index | int | unique je Heft |
| kind | text | CHECK: `cover`, `text`, `toc`, `event_loop`, `asset_pages`, `ads`, `page_break` |
| pattern | text | Schlüssel des Seitenmusters (siehe 6.3), null = Standard des Typs |
| title | text, null | Anzeigename im Editor / Inhaltsverzeichnis |
| config_json | jsonb | typabhängig, validiert über Pydantic-Schema je `kind` |
| is_visible | bool | |

`config_json` der **Termin-Schleife** (`EventLoopConfig`):
```jsonc
{
  // gemeinsames Terminfilter-Format aus services/event_filter.py (wie Protokoll-Wiederholungen):
  "event_filter": {
    "tags": ["glühwurm"],             // Tag enthält einen der Werte
    "range": null,                    // null = Zeitraum des Hefts (period_from..period_to)
    "cycle": null                     // optional {config_id, offset}
  },
  "include_cancelled": false,
  "submission_assignment_ids": ["…"], // Abgaben, aus denen Text/Bilder kommen (1..n)
  "photo_sources": ["submission"],    // optional zusätzlich "gallery" (GalleryImage.event_id)
  "photo_order": "best_of",           // best_of | upload_order | capture_time
  "max_photos": 4,
  "photo_page": "auto",               // none | auto | always  (Fotoseite nach dem Bericht)
  "on_missing": "skip",               // skip | placeholder  (Termin ohne Abgabe)
  "heading": "{title}", "subheading": "{date:weekday_long}"
}
```

`text`: Rich-Text (Markdown-Untermenge wie `rich_text`) mit Bindungen (`publication.*`,
`organization.*`), z. B. Impressum.
`asset_pages`: Liste von Asset-IDs (Bild oder PDF), je Asset `fit` und Seitenbereich.
`ads`: Filter auf das Inserate-Register (Phase 5).

### 4.3 `publication_event_override`
Pro Heft und Termin, nur wenn der Benutzer etwas ändert.
| Feld | Bemerkung |
|---|---|
| publication_id, section_id, event_id | unique (section, event) |
| included | bool, Termin trotz Treffer ausblenden |
| title_override, subheading_override | |
| pattern_override | anderes Seitenmuster |
| excluded_document_file_ids | jsonb, einzelne Text-Dateien weglassen |
| photo_picks_json | jsonb: `[{file_id, state: pinned/excluded, order, focus_x, focus_y}]` |
| text_override | text, optional: von Hand korrigierter Text (überschreibt die Extraktion) |

`text_override` ist bewusst eingeplant: Extraktionen aus Word sind nie perfekt (Silbentrennung,
Tippfehler). Wer korrigiert, korrigiert im Heft, die Abgabe bleibt unverändert.

### 4.4 Inserate (Phase 5)
- `advertiser`: tenant_id, name, contact_person, address, email, phone, notes, is_active.
- `publication_ad`: publication_id, advertiser_id, size (`full`/`half`/`quarter`/`custom` + w/h mm),
  asset_id (Bild oder PDF), amount, currency, paid_at, placement (`auto`/`section_id`/`cover_inner`
  /`back`), sort_index.
- Optional später: Verknüpfung mit Finanzen (Rechnung/Zahlungseingang) und Brief an Inserenten
  als Dokumenttyp.

### 4.5 Exporte
Kein neues Archiv: der Druck-Export wird als verwaltetes Dokument (`document`, `source_kind =
"publication_export"`, `export_kind = "print" | "web"`) mit Versionen abgelegt, analog
`protocol_export_document_service.py`. `document.publication_id` (fk, null) ergänzen.

## 5. Backend

### 5.1 Neue Module
| Datei | Inhalt |
|---|---|
| `models/publication_entities.py` | Modelle aus Abschnitt 4 |
| `schemas/publications.py` | Pydantic: Heft, Bausteine, `EventLoopConfig` usw., strikt (`_Strict`) |
| `repositories/publication_repository.py` | Mandanten-gescopte Lese-/Schreibzugriffe |
| `services/publication_service.py` | CRUD, Sortierung, Duplizieren («Heft 2026 aus 2025»), Status |
| `services/publication_content_service.py` | **Inhaltsauflösung** (5.2) |
| `documents/publication_compiler.py` | PublicationModel → Layout-Baum (5.4) |
| `documents/publication_patterns.py` | Seitenmuster als Builder-Funktionen (6.3) |
| `documents/prepress.py` | TrimBox/BleedBox, Schnittmarken, Ghostscript-Konvertierung (7) |
| `api/routes/publications.py` | Routen (5.5) |

### 5.2 Inhaltsauflösung (`publication_content_service.resolve`)
Rein lesend, ein Aufruf liefert das ganze `PublicationModel`. Wird vom Editor (Status) und vom
Compiler genutzt.

Für jede Termin-Schleife:
1. **Termine wählen**: über den gemeinsamen Terminfilter (`services/event_filter.py`, schon von
   Protokollen und Word-Import genutzt) mit festem Zeitraum (`period_from..period_to`; prüfen, ob
   `range` einen absoluten Zeitraum kann, sonst ergänzen), sortiert nach `event_date`, abgesagte weg.
2. **Abgabe-Dateien je Termin**: alle `SubmissionUpload`-Zeilen mit
   `assignment_id ∈ submission_assignment_ids` und `event_id = termin` (Uploads sind kumulativ),
   deren `SubmissionUploadFile` mit `delete_comment IS NULL`, `scan_status = 'clean'`, sortiert nach
   Upload und `sort_index`. Eine Abfrage für alle Termine (kein N+1, `tests/query_budget.json`).
   (Seit `0181` zusätzlich `withdrawn_at IS NULL`: über den persönlichen Link zurückgezogene
   Dateien gehören nicht mehr zur Abgabe.)
3. **Text**: für Dokument-Dateien die aktuelle Version (`document.current_version_id`) →
   `DocumentExtraction`. Status je Datei: `ok` / `pending` (Job läuft) / `failed` / `unsupported`.
   `content.blocks` (heading, paragraph, list) → Rich-Text-Markdown (`documents/richtext.py`);
   `table` und eingebettete `media` vorerst weglassen (Warnung). Mehrere Dokumente werden
   aneinandergehängt. `text_override` hat Vorrang.
4. **Bilder**: Bild-Dateien derselben Uploads; Reihenfolge nach `photo_order`:
   `best_of` = `PhotoAlbumItem.is_best` im Album `submission_element` (`element_ref =
   "event-<public_id>"`), dann Qualitäts-Score (Schärfe/Belichtung/Gesicht), dann Upload-Reihenfolge.
   Optional `GalleryImage.event_id` als zweite Quelle. Danach `photo_picks_json` anwenden
   (fixiert vorne, ausgeschlossen weg), auf `max_photos` + Fotoseiten-Kontingent kürzen.
   Je Bild Breite/Höhe (Hoch-/Querformat für die Musterwahl) und Auflösung.
5. **Warnungen** je Eintrag: kein Text, Text in Verarbeitung, Text unlesbar, keine Fotos,
   Fotoauflösung zu tief für die Rahmengrösse (nach Musterwahl), sehr langer Text.
6. **Rechte**: aufgelöst mit den Rechten des Benutzers. Ohne `submissions.read` bzw. ohne
   Abo-Feature `abgabebox` keine Abgabe-Inhalte, sondern Warnung (nie still leer).

Das Ergebnis enthält nur IDs und Texte, keine Bilddaten. Bilder lädt erst der Compiler.

### 5.3 Erweiterungen der Dokument-Engine (`backend/app/documents`)
| # | Änderung | Dateien |
|---|---|---|
| E1 | **Doppelseiten**: `PageSetup.facing: bool`, Ränder `inside/outside` statt `left/right` wenn `facing`; Typst `page(binding: left, margin: (inside:, outside:))`; Master für gerade/ungerade Seiten (`PageMaster` `odd`/`even` oder `masters_by_parity`) | `layout.py`, `typst/layout.typ`, `compiler.py` |
| E2 | **Anschnitt**: `PageSetup.bleed_mm` (0–5). Seite wird um 2 × Anschnitt grösser gesetzt, Ränder entsprechend verschoben; neuer Anker `absolute_layer.anchor = "bleed"` für randabfallende Bilder/Hintergründe. Seitengeometrie (Trim-Rechteck) als Metadaten an den Prepress-Schritt | `layout.py`, `typst/layout.typ`, `renderer.py` |
| E3 | **Bilder aus Dateien**: neue Bildquelle `FileImageSource{kind:"file", file_id}` und Bindung `item.photo` / Wiederholung über `item.photos`. Laden über denselben Weg wie `image_gallery` (Mandant + Leserecht prüfen) | `layout.py`, `bindings.py`, `context.py`, `compiler.py` |
| E4 | **Bildausschnitt**: `ImageNode.focus_x/focus_y` (0–1) für `fit: cover` → Typst `box(clip: true)` mit Versatz | `layout.py`, `typst/layout.typ` |
| E5 | **Bildauflösung je Profil**: `IMAGE_MAX_PIXELS` (heute fest 2400, `context.py:31`) wird Parameter des Build-Kontexts. Druck: Zielauflösung = Rahmengrösse × `min_dpi` (Standard 300), höchstens Original; JPEG-Qualität 92. Cache der normalisierten Bilder je (Checksumme, Zielgrösse) im Arbeitsordner, damit wiederholtes Rendern nicht neu kodiert | `context.py` |
| E6 | **PDF als Asset**: `assets.py` akzeptiert `application/pdf` (`kind = "pdf"`, nur `scan_status = clean`, Seitenanzahl merken); Typst bettet per `image("x.pdf", page: n)` ein (Typst ≥ 0.14, **im Spike prüfen**). Für Inserate und Rätsel | `assets.py`, `layout.py`, `compiler.py` |
| E7 | **Langtext mit eingestreuten Bildern**: Muster «Langbericht» fliesst über mehrere Seiten in 1–2 Spalten; Bilder werden nach jedem n-ten Absatz als Spaltenbild eingesetzt (kein Textrahmen-Verketten nötig) | `publication_patterns.py` |
| E8 | **PDF-Profil**: `renderer.py` wählt `pdf_standards` je Profil: Studio weiterhin `a-2b`, Heft-Druck ohne PDF/A (PDF/X folgt im Prepress) | `renderer.py` |
| E9 | **Absatzformate light**: benannte Textstile im Brand-Profil (`body`, `lead`, `heading_1/2`, `caption`, `byline`) statt Einzelformatierung; die Muster verwenden nur diese Rollen | `brand.py`, `layout.py` |

Grenzen prüfen und für Hefte anheben: `MAX_NODES` (2000), Body-Knoten (500), `MAX_REPEAT_TOTAL`.
Statt globaler Erhöhung: eigenes Limit-Profil `publication` im `CompileInput`.

### 5.4 `publication_compiler`
- Eingabe: `PublicationModel` + `page_setup` + Brand. Ausgabe: `TemplateContent` (bestehender
  Layout-Baum), der durch den normalen `LayoutCompiler` geht.
- Je Baustein: Muster-Builder aufrufen (`cover`, `text`, `toc`, Termin-Einträge, Asset-Seiten,
  Inserate). Termin-Einträge erhalten ein Scope-Objekt (`item.title`, `item.date`, `item.text`,
  `item.photos[]`), damit Muster dieselben Bindungen wie das Studio nutzen.
- **Musterwahl `auto`** pro Termin: anhand Textlänge (Zeichen), Anzahl und Ausrichtung der
  Fotos: kurz + 1 Bild → «Bericht kompakt», mittel + 2–4 Bilder → «Bericht + Bildleiste»,
  lang → «Langbericht», viele Fotos → zusätzlich «Fotoseite».
- **Seitenzahl auffüllen**: `page_multiple` (Rückstichheftung: Vielfaches von 4). Fehlende Seiten
  zuerst mit Fotoseiten/Inseraten, sonst Leer- bzw. Notizseiten am Schluss. Warnung im Editor.
- Inhaltsverzeichnis: jede Termin-Überschrift als `outlined` Heading (bestehendes `toc`).

### 5.5 API (`api/routes/publications.py`)
Jede Route: `require_permission` + `require_feature(F.PUBLICATIONS, write=…)`, mandantengescoped,
danach `scripts/sync-route-permissions.py`.

| Methode | Pfad | Zweck |
|---|---|---|
| GET/POST | `/publications` | Liste, anlegen (optional als Kopie eines Hefts) |
| GET/PATCH/DELETE | `/publications/{id}` | Heft lesen/ändern/löschen |
| POST | `/publications/{id}/sections`, PATCH/DELETE `/sections/{sid}`, POST `/sections/reorder` | Bausteine |
| GET | `/publications/{id}/content` | aufgelöster Inhalt + Warnungen (Editor-Status) |
| GET | `/publications/{id}/events/{event_id}/candidates` | alle Foto-/Textkandidaten eines Termins für die Auswahl |
| PUT | `/publications/{id}/sections/{sid}/overrides/{event_id}` | Überschreibungen speichern (optimistische Sperre wie `config_version`) |
| POST | `/publications/{id}/preview` | Vorschau-PNG (ganzes Heft niedrig aufgelöst oder ein Baustein) |
| POST | `/publications/{id}/render` | Export-Auftrag (`print` / `web`), 202 + Job-ID |
| GET | `/publications/{id}/exports` | Export-Historie (Dokumentversionen) |

Fehlerbehandlung nach `CLAUDE.md`: `raise HTTPException(...) from exc`, erwartete Fehler als `ValueError`.

### 5.6 Render-Job
- Bestehenden Auftragsweg (`services/document_render_jobs.py`, Migration 0150) um Ziel
  `publication` erweitern statt neuen Worker zu bauen: Fairness, Wiederholung und Polling sind dort gelöst.
- Eigene Limits: `publication_render_timeout_seconds` (z. B. 600), `publication_render_memory_limit_mb`
  (z. B. 6144), Concurrency 1. Fortschritt in Phasen (Inhalte auflösen → Bilder aufbereiten →
  setzen → Prepress → speichern).
- Ablauf: resolve → Bilder in den Arbeitsordner (Cache) → compile → prepress → als
  Dokumentversion speichern → Benachrichtigung «Heft-PDF bereit».
- Kein neuer periodischer Job nötig; falls doch (z. B. Bild-Cache aufräumen): Eintrag in
  `job_registry.py` + Übersetzungen (`CLAUDE.md`, Abschnitt Hintergrundjobs).

## 6. Layout

### 6.1 Seitenformat
Vorgaben im Editor: A5 hoch doppelseitig (Standard), A4 hoch doppelseitig, eigenes Format.
Standardränder A5: innen 15, aussen 12, oben 15, unten 15 mm; Anschnitt 3 mm.

### 6.2 Master
- `standard_odd` / `standard_even`: Logo/Heftname in der Kopfzeile aussen, Seitenzahl unten aussen.
- `clean`: ohne Kopf/Fuss (Titel, Fotoseiten, Inserate).

### 6.3 Seitenmuster (Phase 2, als Code in `publication_patterns.py`)
| Schlüssel | Beschreibung |
|---|---|
| `cover_photo` | Vollflächiges Titelbild (Anschnitt), Titel, Untertitel, Jahrgang |
| `text_page` | Überschrift + Rich-Text (Editorial, Impressum, Wort des Präses) |
| `toc` | Inhaltsverzeichnis |
| `report_compact` | Titel, Datum, Text, 1 Bild unten (Höhe abhängig von Restplatz) |
| `report_strip` | Titel, Datum, Text, Bildleiste 2–3 Bilder |
| `report_long` | Mehrseitig fliessend, Bilder eingestreut (E7) |
| `photo_page_1` / `_2` / `_4` | Fotoseite randabfallend, Auswahl je nach Hoch-/Querformat |
| `asset_page` | Asset (PDF-Seite/Bild) ganzseitig, `contain` innerhalb Satzspiegel oder randabfallend |
| `ads_page` | Inserate 1 × 1/1, 2 × 1/2, 4 × 1/4 oder gemischt |
| `back_cover` | Rückseite |

Phase 6: Muster als `DocumentComponent` im Designer bearbeitbar machen (Mandanten-Muster).

## 7. Druckvorstufe (`documents/prepress.py`)

1. **Boxen**: mit `pikepdf` je Seite `MediaBox` = Seite inkl. Anschnitt (+ Platz für Marken),
   `BleedBox` = Endformat + Anschnitt, `TrimBox` = Endformat.
2. **Schnittmarken** (optional, viele Druckereien wollen keine): als Vektorlinien ausserhalb der
   BleedBox.
3. **CMYK / PDF/X** (nur wenn Profil verlangt): Ghostscript im Sandbox-Prozess
   (`services/documents/sandbox.py`-Muster, `-dSAFER`, Zeit-/Speicherlimit):
   `-sColorConversionStrategy=CMYK`, Ausgabeprofil (z. B. PSO Coated v3 / ISO Coated v2 der ECI,
   Lizenz prüfen), PDF/X-3 oder X-4 mit `OutputIntent`. Schriften bleiben eingebettet.
4. **Prüfung**: Seitenzahl Vielfaches von `page_multiple`, alle Boxen gesetzt, Bildauflösung
   (aus E5) ≥ `min_dpi`, keine RGB-Objekte bei `cmyk`. Ergebnis als Prüfbericht zum Export.
5. **Web-PDF**: zweiter Export ohne Anschnitt, Bilder 150 dpi, RGB, PDF/A-2b wie bisher.

Docker: `ghostscript` und ICC-Profil ins Backend-/Job-Worker-Image, `pikepdf` in
`requirements.txt`. Ad-PDFs sind fremde Dateien: nur `scan_status = clean`, Verarbeitung nur im
Sandbox-Prozess.

## 8. Frontend (`frontend/app/publications`)

Vor jeder UI-Arbeit `design/DESIGN.md` lesen; Standardbausteine (`Modal`, `DataTable`, `Badge`,
`SearchableSelect`, `DateInput`, `ActionMenu`, `useConfirm`, `useToast`) und Tokens; Styles in
`frontend/app/styles/publications.css`.

| Ansicht | Inhalt |
|---|---|
| **Liste** `/publications` | Hefte mit Jahrgang, Status, Seitenzahl, letzter Export; «Neues Heft», «Kopie für nächstes Jahr» |
| **Aufbau** `/publications/[id]` | Bausteinliste mit Drag & Drop (Muster aus den Protokoll-Vorlagen), Konfiguration im Seitenpanel, Heft-Einstellungen (Format, Zeitraum, Druckprofil) |
| **Inhalte** | Tabelle pro Termin-Schleife: Termin, Datum, Text-Status (`Badge`: ok/in Verarbeitung/fehlt/unlesbar), Fotos (gewählt/verfügbar), Muster, Warnungen; Link zur Abgabe und zum Termin |
| **Termin-Detail** (Modal) | Textvorschau mit «Text korrigieren» (`text_override`), Dateien ein/aus, Fotoauswahl im Raster mit Best-of-Sternen, fixieren/ausschliessen/sortieren, Fokuspunkt setzen, Muster wählen |
| **Vorschau** | Doppelseitenansicht der Vorschau-PNGs, Klick auf Seite → zugehöriger Baustein/Termin |
| **Export** | «Druck-PDF», «Web-PDF», Prüfbericht, Historie (Dokumentversionen), Download |
| **Inserate** (Phase 5) | Register (`DataTable`), Inserat je Heft mit Grösse, Datei, Betrag, bezahlt |

Navigation: Eintrag in `nav.json`, sichtbar mit `publications.read` und Feature `publications`.
i18n: neue Datei `frontend/messages/<locale>/publications.json` in **allen** Locales; die drei
i18n-Prüfskripte vor jedem Commit.

## 9. Rechte, Abo, i18n, Sicherheit

- **Berechtigungen** (`permissions/catalog.json` → `sync-permission-catalog.py`):
  `publications.read` (lesen, Vorschau, Export herunterladen), `publications.manage` (anlegen,
  bearbeiten, exportieren). Migration fügt sie den Standardrollen hinzu (`admin` alle, `writer`
  beide, `reader` read) inkl. `hocx_seed_tenant_roles`; Übersetzungen
  `roles.permissions.publications.*` in allen Locales.
- **Abo-Feature** (`permissions/features.json` → `sync-feature-catalog.py`): `publications`,
  Modul `documents`, `downgrade: read_only`, `read_permissions: ["publications.read"]`.
  Abgabe-Inhalte zusätzlich nur mit Feature `abgabebox` (sonst Warnung im Editor).
  Migration: Tabelle `feature`, `plan_feature`, Bestandsschutz-Backfill; Übersetzung
  `common.features.publications`.
- **Sicherheit**: RLS auf allen neuen Tabellen, alle Zugriffe über `public_id` + `tenant_id`,
  Inhalte immer mit den Rechten des exportierenden Benutzers, fremde PDFs nur sandboxed.
  `check-security-rules.py`, Security-Review des Diffs (Uploads/Migrationen betroffen).
- **Datenschutz**: Fotos von Kindern. Vor Phase 2 klären, ob es eine Einwilligung «Fotos
  veröffentlichen» gibt (Teilnehmende/`privacy_settings`); falls ja, in der Fotoauswahl
  berücksichtigen bzw. kennzeichnen.
- **Testdaten**: keine echten Namen/Fotos/Inserate aus dem Gliähwurm ins Repo (gitleaks-Regeln);
  synthetische Fixtures verwenden.

## 10. Tests

| Ebene | Was |
|---|---|
| Unit (Backend) | `EventLoopConfig`-Validierung (inkl. `event_filter`); Extraktion → Rich-Text; Fotoreihenfolge (Best-of, Overrides, Kontingent); Musterwahl `auto`; Seiten-Auffüllung auf Vielfaches von 4 |
| Service | `publication_content_service` mit Fixtures: Termine mit Tag, Abgaben mit .docx + Bildern, gelöschte Datei, Extraktion pending/failed, zweite Abgabe, fremder Mandant (darf nie erscheinen) |
| Query-Budget | Inhaltsauflösung für 30 Termine mit fester Anzahl Queries (`query_budget.json`) |
| RLS / RBAC | neue Tabellen in den RLS-Tests; `test_route_permission_inventory.py`; reader darf nicht ändern |
| Engine | Golden-Tests (`scripts/update-document-goldens.sh`) für Doppelseiten, Anschnitt, Datei-Bilder, PDF-Asset, jedes Seitenmuster |
| Prepress | Boxen gesetzt und korrekt (pikepdf), Seitenzahl, CMYK-Konvertierung ohne RGB-Reste, Ghostscript-Timeout |
| Last | synthetisches Heft 56 Seiten / 150 Fotos à 12 MP: Renderzeit und Speicher unter den Job-Limits |
| E2E | Heft anlegen → Termin-Schleife mit Abgabe → Inhalte-Status → Foto fixieren → Druck-PDF herunterladen |

## 11. Phasen

Grössen: S ≈ 1–3 Tage, M ≈ 1 Woche, L ≈ 2+ Wochen (eine Person, grob).

### Phase 0 – Technik-Spike (S)
Ausserhalb der App, mit Typst 0.15 wie im Backend:
- PDF-Inserat per `image(…pdf)` einbetten (Vektor bleibt Vektor, Schriften ok).
- A5 doppelseitig mit 3 mm Anschnitt, randabfallendes Bild, TrimBox/BleedBox mit pikepdf.
- Ghostscript → CMYK + PDF/X-4, Ergebnis in Acrobat-Preflight bzw. bei der Druckerei prüfen.
- 56 Seiten / 150 Fotos: Zeit und Speicher messen.
**Ergebnis:** Go/No-Go je Punkt, Parameter für Limits. Bei No-Go für PDF-Einbettung:
Fallback Rasterisierung der Inserate mit 600 dpi (`pypdfium2`, bereits für Vorschauen im Einsatz).

### Phase 1 – Datenmodell und Inhaltsauflösung (M)
Migrationen + RLS, Modelle, Rechte, Feature, `publication_service`, `publication_content_service`,
Routen ohne Render (CRUD, `content`, `candidates`, Overrides), Tests.
**Abnahme:** Über die API lässt sich ein Heft mit Termin-Schleife anlegen; `GET content` liefert pro
Termin den extrahierten Text, die Fotoliste in Best-of-Reihenfolge und korrekte Warnungen.

### Phase 2 – Layout und erstes PDF (L)
Engine E1, E3, E4, E5, E8, E9; `publication_patterns` (alle Muster ausser Inserate);
`publication_compiler` inkl. Musterwahl und Inhaltsverzeichnis; Render-Job mit eigenen Limits;
Export ins Dokumentarchiv (Web-PDF).
**Abnahme:** Ein A5-Heft mit Titel, Editorial, Inhaltsverzeichnis, 10 Termin-Berichten aus Abgaben,
Fotoseiten, Rätsel als Bild und Impressum wird als PDF erzeugt.

### Phase 3 – Editor (L)
Frontend: Liste, Aufbau, Inhalte, Termin-Detail mit Fotoauswahl/Fokus/Textkorrektur, Vorschau
(Doppelseiten), Export-Dialog, i18n alle Locales, Light/Dark, 1440/390 px.
**Abnahme:** Ein Redaktionsmitglied ohne technische Kenntnisse erstellt das Heft komplett im Browser.

### Phase 4 – Druckvorstufe (M)
Engine E2 (Anschnitt), E6 (PDF-Assets), `prepress.py`, Druckprofil im Editor, Prüfbericht,
Docker-Images (Ghostscript, ICC-Profil), Seiten-Auffüllung auf Vielfaches von 4.
**Abnahme:** Druckerei akzeptiert das Druck-PDF (Anschnitt, Boxen, Farbraum gemäss ihren Vorgaben).

### Phase 5 – Inserate (M)
`advertiser`, `publication_ad`, Register-UI, Muster `ads_page` mit automatischer Verteilung
(gleiche Grössen gruppieren, ganze Seiten bevorzugt, Platzierungswünsche), Inserate in der
Seiten-Auffüllung; optional Briefe an Inserenten als Dokumenttyp und Verknüpfung mit Finanzen.
**Abnahme:** Die 18 Inserate des Referenzhefts (synthetisch nachgebildet) werden korrekt platziert.

### Phase 6 – Komfort (fortlaufend)
- Muster im Designer bearbeitbar (Mandanten-Muster als `DocumentComponent`).
- Weitere Bausteine: Gruppeneinteilung (aus Gruppen/Leitern), Scharprogramm (aus kommenden
  Terminen, Bindung `events.upcoming` existiert), Austritte (aus Ein-/Austritten).
- Rätsel-Generatoren (Sudoku, Wortsuche; Kreuzworträtsel deutlich aufwändiger).
- «Heft 2026 aus 2025 kopieren» mit verschobenem Zeitraum.
- Wiederverwendung für den geplanten «Jahresbericht» (`meetings.reports` in der Roadmap).

## 12. Risiken

| Risiko | Gegenmassnahme |
|---|---|
| Layoutqualität bei schwankenden Inhalten (200 vs. 2000 Wörter, 1 vs. 40 Fotos) | Musterwahl `auto` + Override pro Termin; Warnungen; Vorschau pro Baustein |
| Extraktion aus Word unsauber (Formatierung, Trennstriche, eingebettete Bilder) | `text_override`; eingebettete Bilder später als Fotoquelle |
| Render-Zeit/Speicher bei vielen Fotos | Bild-Cache, eigene Job-Limits, Bausteinvorschau statt Gesamtvorschau |
| PDF/X/CMYK-Anforderungen der Druckerei | Phase 0 mit echter Druckerei-Vorgabe; RGB + Anschnitt als Minimalprofil |
| Fremde PDF-Inserate (Schriften fehlen, kaputt, RGB) | nur geprüfte Dateien, Sandbox, Prüfbericht; Fallback Rasterisierung |
| Engine-Änderungen brechen Studio-Vorlagen | neue Felder optional mit Default = bisheriges Verhalten; Goldens |

## 13. Offene Fragen

1. Welche Druckerei und welche PDF-Vorgaben (PDF/X-Version, Farbprofil, Schnittmarken ja/nein)?
2. Bindung: Rückstichheftung (Seitenzahl Vielfaches von 4) – immer?
3. Gibt es eine Foto-Einwilligung, die berücksichtigt werden muss?
4. Sollen die Seitenmuster pro Mandant gestaltbar sein (Phase 6) oder reichen 2–3 Stilvarianten?
5. Schriften: Helvetica/Daily Grind sind lizenzpflichtig – Mandanten-Upload genügt (`assets.py`
   kann TTF/OTF), Lizenz liegt beim Verein.
