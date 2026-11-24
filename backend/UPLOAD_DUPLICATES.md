# Uploads: Duplikate, Vorab-Abgleich, Bild-Metadaten und Datumsverwaltung

Dieses Dokument beschreibt, wie hocX doppelte Uploads erkennt, Bilder bereits im Browser
analysiert, fehlende Metadaten vorhandener Bilder ohne erneuten Upload ergänzt und die drei
Datumsarten eines Bildes verwaltet.

Code-Einstieg:

| Thema | Datei |
|---|---|
| Serverseitige Bildanalyse, Validierung, Ergänzungsregeln | `app/services/image_metadata_service.py` |
| Datumspriorität (einzige Quelle) | `app/services/capture_date.py` |
| Vorab-Abgleich, Ergänzen vorhandener Bilder | `app/services/upload_precheck_service.py` |
| Export mit geschätztem Datum | `app/services/image_export_service.py` |
| Backfill | `app/services/image_metadata_backfill.py`, `scripts/backfill_image_metadata.py` |
| Abgabebox (eigener Dienst) | `abgabebox-backend/app/image_metadata.py` |
| Browser-Analyse (Parser, Hash, Worker, Pool) | `frontend/lib/image-analysis/` |
| Migration | `alembic/versions/0113_image_capture_metadata.py` |

## 1. Exakte Duplikate (serverseitig, unverändert gültig)

Galerie, Dokumentuploads, Word-Import und Protokollbilder prüfen SHA-256 vor ClamAV innerhalb
des Mandanten (`FileService._filter_exact_duplicates`). Verglichen wird gegen
`checksum_sha256` **und** `source_checksum_sha256` (Hash des Originals konvertierter
HEIC/HEIF-Bilder); infizierte Dateien zählen nicht. Galerie-ZIP-Einträge durchlaufen dieselbe
Prüfung beim Entpacken.

Die Abgabebox prüft innerhalb desselben Abgabe-Elements. Exakte Duplikate werden still
übersprungen; die erfolgreiche Antwort zählt alle empfangenen Dateien. Nur neue Dateien zählen
gegen Dateilimit und Speicherbedarf. Reine Duplikat-Anfragen erreichen weder Bildanalyse noch
ClamAV.

Ähnliche, aber nicht byteidentische Bilder bleiben getrennt (Perceptual-Hash-Hinweis bzw.
Tab „Duplikate“/„Ähnliche“).

Gleichzeitige Uploads werden je Mandant über eine gemeinsame PostgreSQL-Transaktionssperre
koordiniert (vom Hashvergleich bis zum Commit, auch zwischen Haupt-App, Abgabebox und mehreren
Serverprozessen). Nach dem Warten wird erneut geprüft: ein inzwischen gespeichertes Duplikat
wird übersprungen; nach einem fehlgeschlagenen Upload kann die nächste Anfrage übernehmen.

Der Vorab-Abgleich (Abschnitt 3) **ersetzt diese Prüfung nicht**: jede tatsächlich
übertragene Datei wird serverseitig neu gehasht und erneut geprüft.

## 2. Clientseitige Bildanalyse

Sobald im Upload-Popup Dateien gewählt sind, analysiert der Browser jede Bilddatei lokal:

- **SHA-256** über die unveränderten Originalbytes (`crypto.subtle`).
- **Metadaten** mit einem eigenen, abhängigkeitsfreien Parser (`metadata.ts`): Aufnahmedatum
  (EXIF `DateTimeOriginal`, sonst `DateTimeDigitized`, sonst IFD0 `DateTime`; XMP
  `exif:DateTimeOriginal`/`photoshop:DateCreated`/`xmp:CreateDate` als Ausweichquelle),
  Zeitzonen-Offset (`OffsetTimeOriginal`), GPS (Breite, Länge, Höhe, Blickrichtung,
  Genauigkeit `GPSHPositioningError`, GPS-Zeitstempel), Kamerahersteller und -modell,
  Breite/Höhe, Ausrichtung.
- Unterstützte Formate: JPEG, PNG (`eXIf`, unkomprimiertes XMP-`iTXt`), WebP (`EXIF`/`XMP `,
  VP8/VP8L/VP8X), TIFF, HEIC/HEIF (ISOBMFF, Exif-Item über `iinf`/`iloc`, Grösse über `ispe`).
  GIF/BMP gelten als lesbar ohne Datum. ZIP-Dateien und Live-Photo-Clips analysiert nur der
  Server.

Die Datei wird genau **einmal** eingelesen; derselbe Puffer dient Hash und Parser. Die Analyse
läuft in **Web Workern** (`image-analysis.worker.ts`) mit begrenzter Parallelität (2), mit
Fortschrittsanzeige und Abbruch (Popup schliessen, Datei entfernen). Ohne Worker-Unterstützung
läuft dieselbe Logik im Hauptthread. Dateien über 512 MiB werden nicht im Browser gehasht
(Speicher) und gehen ohne Vorab-Abgleich hoch. Ohne `crypto.subtle` (kein sicherer Kontext)
entfällt der Vorab-Abgleich ebenfalls.

Ergebnis je Bild: Aufnahmedatum **vorhanden**, **fehlt** (Datei geprüft, kein Datum) oder
**nicht prüfbar** (unbekanntes Format, Parserfehler). Ein nicht prüfbares Bild wird nie als
„ohne Aufnahmedatum“ gezählt – der Server analysiert es beim Upload selbst, und ein dort
gefundenes echtes Datum hat Vorrang.

Konventionen wie im Backend: Datum = lokale Kamerazeit ohne Zeitzone, Offset separat,
Süd/West negativ, `(0, 0)` gilt als „kein GPS-Fix“, unplausible Werte (vor 1826, Zukunft,
Bereichsfehler) werden verworfen.

## 3. SHA-256-Vorab-Abgleich

### Endpunkt

`POST /api/files/upload-precheck` (Rolle Schreiber/Admin, aktueller Mandant)

```json
{
  "context": "gallery",
  "estimated_taken_on": "1998-08-01",
  "files": [
    {
      "client_id": "0",
      "sha256": "…64 Hex-Zeichen…",
      "name": "IMG_0001.HEIC",
      "size": 2345678,
      "mime_type": "image/heic",
      "analysis": "ok",
      "metadata": {
        "taken_at": "2024-06-01T18:45:00",
        "taken_offset": "+02:00",
        "gps": { "latitude": 46.2, "longitude": -6.1, "altitude_m": 540, "direction_deg": 123.4 },
        "camera_make": "Apple", "camera_model": "iPhone 15",
        "width": 4032, "height": 3024, "orientation": 6
      }
    }
  ]
}
```

Antwort je Datei (`client_id` unverändert zurück):

| `status` | Bedeutung | Client |
|---|---|---|
| `upload_required` | Unbekannt im Mandanten | normal hochladen |
| `already_exists` | Byte-identisch vorhanden, nichts zu ergänzen | nicht übertragen → „Übersprungen“ |
| `metadata_updated` | Vorhanden, fehlende Metadaten wurden **gespeichert**; `applied` nennt die Feldgruppen | nicht übertragen → „Übersprungen · Metadaten ergänzt“ |
| `fallback_required` | Kein sicherer Abgleich (interner Fehler, zweite Kopie derselben Datei im Batch) | normal hochladen |

Weitere Felder: `file_id` (nur bei vorhandenen Dateien, immer aus dem eigenen Mandanten),
`applied` und `conflicts` mit Werten aus `taken_at`, `gps`, `camera`, `dimensions`,
`orientation`, `estimated_taken_on`.

`context`: `gallery` (Hash + Metadaten), `document` und `protocol_image` (nur Hash – keine
Metadaten-Ergänzung). Höchstens 500 Dateien je Request; der Client sendet in Blöcken zu 200.

### Regeln

- Gleiche Trefferregel wie die serverseitige Duplikaterkennung (Mandant, nicht infiziert,
  `checksum_sha256` oder `source_checksum_sha256`), damit Vorab-Ergebnis und Upload nie
  auseinanderlaufen.
- **Mandantensicherheit:** Gesucht wird ausschliesslich im aktuellen Mandanten. Ein Hash aus
  einem anderen Mandanten liefert exakt dieselbe Antwort wie ein unbekannter Hash
  (`upload_required`, keine `file_id`). Leser haben keinen Zugriff.
- **Race Conditions:** Die gefundenen Zeilen werden für die Dauer der Transaktion gesperrt
  (`SELECT … FOR UPDATE`); Ergänzungen setzen nur leere Felder. Zwei gleichzeitige Abgleiche
  füllen ein Feld deshalb höchstens einmal, der zweite sieht den Wert und meldet nichts bzw.
  einen Konflikt. Zwei parallele Uploads derselben neuen Datei erhalten beide
  `upload_required`; die serverseitige Duplikaterkennung unter der Mandantensperre speichert
  sie genau einmal, die zweite wird im Upload-Ergebnis als „Übersprungen“ gemeldet.
- **Fehler:** Schlägt das Ergänzen unerwartet fehl, wird der ganze Batch zurückgerollt und
  jede vorhandene Datei als `fallback_required` gemeldet – nie wird eine Änderung behauptet,
  die nicht gespeichert wurde. Ist der Endpunkt nicht erreichbar, lädt der Client alles normal
  hoch (`precheckUploads` liefert dann `null`). Der Fehler landet in `system_error_log`.
- Eine Datei, die erst nach dem Vorab-Abgleich gelöscht wird, gilt für diesen Vorgang als
  übersprungen (kein erneuter Upload). Das ist bewusst so; erneutes Auswählen lädt sie hoch.

### Abgabebox: bewusst kein Vorab-Abgleich

Die Abgabebox ist öffentlich und anonym (Link genügt). Ein Hash-Endpunkt wäre dort ein
Orakel („liegt diese Datei schon in dieser Abgabe?“), und die bestehende Antwort verrät
absichtlich nicht einmal, ob eine Datei ein Duplikat war. Die Abgabebox behält deshalb ihre
engeren Regeln (Duplikate je Abgabe-Element, still) und liest Aufnahmedatum, Offset, GPS,
Kamera und Ausrichtung **serverseitig** beim Speichern (`abgabebox-backend/app/image_metadata.py`).

## 4. Fehlende Metadaten vorhandener Bilder ergänzen

Erkennt der Server ein Bild am Hash wieder (Vorab-Abgleich oder Duplikat beim Upload), ergänzt
er fehlende Werte (`upload_precheck_service.enrich_existing`):

1. Vorhandene gültige Werte werden **nie still überschrieben**.
2. Fehlende Werte werden gezielt ergänzt (echtes Aufnahmedatum, GPS inkl. Höhe/Richtung,
   Kamera, Abmessungen, Ausrichtung, geschätztes Datum).
3. Abweichende Werte werden als `conflicts` gemeldet und verworfen.
4. Ungültige/unplausible Werte werden verworfen (Validierung in `image_metadata_service`).
5. Herkunft wird gespeichert: `exif_taken_source`/`gps_source` = `server` | `client` |
   `backfill`, `estimated_taken_set_at/_by` für Schätzungen, `metadata_scanned_at/_status`.

**Vertrauen:** Client-Angaben sind nicht vertrauenswürdig.

- Passt `checksum_sha256` (byte-identisches Original liegt auf dem Server), analysiert der
  Server **seine eigene Datei** - höchstens einmal (solange `metadata_scanned_at` leer ist);
  Client-Angaben lösen keine erneute Analyse aus und werden nie übernommen. Behauptet ein
  Client z. B. ein Datum, das die Datei nicht enthält, wird nichts gespeichert.
- Passt nur `source_checksum_sha256` (HEIC/HEIF wurde nach JPEG konvertiert, das Original
  existiert nicht mehr), werden validierte Client-Werte mit Herkunft `client` übernommen –
  ohne Abmessungen und Ausrichtung, die für das bereits gedrehte JPEG nicht gelten.
- Ein Hash identifiziert genau eine Aufnahme; Metadaten können so nie einem anderen Bild
  zugeordnet werden. Beim Galerie-Upload mitgeschickte Client-Metadaten (`file_metadata`)
  werden nur angewendet, wenn der **serverseitig neu berechnete** Hash passt.

Später nachgelieferte echte Aufnahmedaten, GPS-Daten und geschätzte Daten sind jederzeit
möglich (über Vorab-Abgleich, erneuten Upload, Backfill oder – für Schätzungen – die
Bearbeitung). Ändert sich dabei das Datum, wird die automatische Termin-Zuordnung des Fotos
neu bewertet.

## 5. Drei Datumsarten

| Feld | Inhalt | Quelle |
|---|---|---|
| `exif_taken_at` | tatsächliches Aufnahmedatum | Bildmetadaten (Server, Backfill, bei Konvertierung ggf. Client) |
| `estimated_taken_on` | geschätztes Aufnahmedatum, **reines Kalenderdatum** (`DATE`, keine Uhrzeit/Zeitzone) | Benutzereingabe |
| `created_at` | Uploaddatum | Speicherzeitpunkt, unverändert |

`exif_taken_at` speichert wie seit Migration 0083 die **lokale Kamerazeit**, „schwebend“ als
UTC – damit liefert `cast(... AS date)` immer den Kalendertag des Fotografen. Ein EXIF-Offset
steht separat in `exif_taken_offset` und wird nie eingerechnet. Ohne Offset bleibt die
Zeitzone unbekannt. Die Oberfläche formatiert diese Zeit deshalb in UTC
(`formatCaptureDateTime`), damit die App-Zeitzone sie nicht verschiebt.

Das Uploaddatum wird nie als Aufnahmedatum gespeichert. Ein fehlendes Aufnahmedatum bleibt
`NULL`.

## 6. Datumspriorität

Zentral in `capture_date.py` (Python- und SQL-Variante):

1. `exif_taken_at` → `date_source = "exif"`
2. `estimated_taken_on` → `"estimated"`
3. `created_at` → `"upload"`

Gilt für Galerie-Sortierung (`sort_by=group_date`, innerhalb eines Tages nach Aufnahmezeit,
sonst Uploadzeit), Gruppierung und Überschriften (`group_date`), Bilddetails
(`effective_date`), Zyklus-Zuordnung beim Upload und Abgabebox-Bilder. Protokoll- und
Word-Import-Bilder gruppieren weiterhin primär nach dem Protokolldatum
(`date_source = "context"`), danach nach derselben Priorität.

Wird später ein echtes Datum ergänzt, gewinnt es automatisch; das geschätzte bleibt zur
Nachvollziehbarkeit gespeichert (Detailansicht: „Das echte Aufnahmedatum hat Vorrang.“).

**Automatische Termin-Zuordnung** (`photo_event_link_service`) ist bewusst vorsichtiger: Ein
nur geschätztes Datum ist zu unsicher, um ein Foto ohne Zutun einem Termin zuzuordnen. Liegt
eine Schätzung vor, wird weder nach ihr noch nach dem (dann erwiesenermassen falschen)
Uploaddatum automatisch verknüpft; eine frühere automatische Verknüpfung über das Uploaddatum
wird gelöst. Manuelle Verknüpfungen bleiben immer unberührt.

## 7. Geschätztes Aufnahmedatum

### Beim Upload (Galerie-Popup)

Nach der Analyse zeigt das Popup – nur wenn nötig – einen Hinweis („Für 12 Bilder wurde kein
Aufnahmedatum gefunden. Du kannst ein geschätztes Datum angeben.“), Hinweise zu nicht
prüfbaren Bildern und ZIP-Dateien sowie das optionale Feld „Geschätztes Aufnahmedatum für
Bilder ohne Aufnahmedatum“. Das Datum

- geht mit Hash und Metadaten an den Vorab-Abgleich (Duplikate erhalten es ohne Upload),
- geht als Formularfeld `estimated_taken_on` mit jedem Upload-Auftrag mit und wird vom Server
  nur für Bilder gesetzt, für die er **selbst** kein echtes Aufnahmedatum findet (auch
  ZIP-Einträge und nicht prüfbare Bilder),
- überschreibt nie echte Aufnahmedaten oder vorhandene Schätzungen.

Ordner lassen sich per Drag & Drop oder „Ordner auswählen“ hochladen (nur Bilder, HEIC,
Live-Clips, ZIPs werden übernommen). Grosse Auswahlen (bis 2000 Dateien / 50 GiB) werden
automatisch in Aufträge zu höchstens 50 Dateien bzw. 10 GiB geteilt; Live-Photo-Paare bleiben
zusammen.

### Nachträglich

`PATCH /api/stored-files/{id}/capture-date` mit `{"estimated_taken_on": "1998-08-01"}` setzt
oder ändert, `{"estimated_taken_on": null}` entfernt die Schätzung. Nur Schreiber/Admins des
eigenen Mandanten, nur Bilder; Datum zwischen 1826 und heute. Echtes Datum und Uploaddatum
bleiben unverändert. In der Bilddetailansicht stehen die drei Datumsarten getrennt; die
Galerie sortiert/gruppiert nach dem Schliessen der Detailansicht neu.

Der automatische Hash-Abgleich überschreibt eine vorhandene Schätzung nie (Konflikt); bewusste
Änderungen laufen nur über diesen Endpunkt.

## 8. Dezente Kennzeichnung in der Galerie

In den Datumsüberschriften der Galerie:

- echtes Aufnahmedatum: keine Kennzeichnung,
- geschätztes Datum: kleines Kalendersymbol mit Hinweis „Geschätztes Aufnahmedatum“,
- Uploaddatum-Fallback: kleines Info-Symbol mit Hinweis „Aufnahmedatum unbekannt –
  Uploaddatum wird verwendet.“

Bei gemischten Tagen nennt der Hinweis den Anteil („(3 von 10 Bildern)“). Die Symbole sind
Buttons (Tastatur, Screenreader-Label, Tippen öffnet den Hinweis auf Mobilgeräten); Kacheln
erhalten keine zusätzlichen Textzeilen. Die Bildbetrachter-Kopfzeile zeigt dieselbe
Kennzeichnung.

## 9. Upload-Ergebnisse

Jede Datei erhält genau einen Status: **Hochgeladen**, **Übersprungen**, **Übersprungen ·
Metadaten ergänzt** oder **Fehlgeschlagen**. „Metadaten ergänzt“ zählt nie zusätzlich als
übersprungen und wird nur angezeigt, wenn der Server tatsächlich gespeicherte Felder meldet.

- Galerie: Vorab-Ergebnisse und die Ergebnisse aller Aufträge eines Vorgangs
  (`GalleryUploadJobDetail.file_results`, gespeichert in `gallery_upload_job.file_results`)
  werden zusammengeführt. Sobald alle Aufträge fertig sind, erscheint eine Zusammenfassung
  („24 Bilder verarbeitet: 12 hochgeladen, 8 übersprungen, 4 übersprungen und Metadaten
  ergänzt.“) mit „Details“ für die Liste je Datei. Im Popup selbst zeigt jede Datei ihren
  Status (übersprungen, wartet, wird hochgeladen, hochgeladen).
- Dokumente: `DocumentUploadResult.file_results`; bereits vorhandene Dokumente werden nach
  dem Vorab-Abgleich gar nicht erst übertragen.
- Protokollbilder: Ein im Mandanten bereits vorhandenes Bild wird vorab erkannt und nicht
  übertragen (der Server würde es ohnehin mit 409 ablehnen).

## 10. GPS

Spalten `gps_latitude`, `gps_longitude` (WGS84-Dezimalgrad, `DOUBLE PRECISION`),
`gps_altitude_m`, `gps_direction_deg` (0 ≤ x < 360), `gps_accuracy_m`, `gps_timestamp` (UTC),
`gps_source`. CHECK-Constraints erzwingen Bereich und dass Breite/Länge nur gemeinsam
vorkommen; ein Teilindex (`idx_stored_file_tenant_gps`) bereitet die spätere Kartenansicht vor
(diese ist nicht Teil dieser Änderung).
Ortsnamen und Umkreissuche aus diesen Spalten: Abschnitt 16.

Als Wert lesbar nur über `GET /api/stored-files/{id}/metadata` (`gps`), d. h. für Benutzer mit
Zugriff auf die Datei im eigenen Mandanten. Partner-Mandanten geteilter Alben erhalten über
`/metadata` keine Metadaten; Leser haben auf Galeriebilder keinen Zugriff. Öffentliche
Freigabe-Links geben GPS nie über die API aus und entfernen es aus Dateien, wenn der Link den
Standort nicht teilt.

**Dateikopien:** Der Export (§11) schreibt nur in der DB vorhandenes GPS (Client-GPS bzw.
konvertierte HEIC) und das Schätzdatum in die heruntergeladene Kopie. Das gilt für den
Einzeldownload - auch für Partner-Mandanten geteilter Alben, die das Bild herunterladen dürfen
- und für öffentliche Freigaben, deren Link den Standort teilt.

**Standort für Partner-Mandanten (IMGMETA-007):** Jede Album-Freigabe hat einen Schalter
„Standort teilen“ (`photo_album_tenant_share.share_location`, Standard **an** – zwei Mandanten,
die ein Album teilen, vertrauen sich). Der Besitzer setzt ihn beim Einladen und kann ihn später
ändern (`PATCH /api/files/albums/{id}/shares/{tenant}`). Ist er aus, bekommt der Partner
Originale (`/content`), Downloads (`/download`, inkl. Live-Photo-Video) ohne Standort: das
GPS-IFD fällt weg (nach dem Export, damit auch DB-GPS nicht hineinkommt), Videos werden ohne
Container-Metadaten umverpackt; fehlt ffmpeg, wird das Video nicht ausgeliefert. Massgeblich
ist `photo_album_share_service.location_shared_with`: es braucht ein Album mit dem Foto, in dem
Betrachter **und** Mandant des Fotos (Besitzer oder Partner mit Schalter an) den Standort
teilen. Öffentliche Freigabe-Links haben ihren eigenen Schalter (`share_location`, Standard
**aus**). Thumbnails tragen nie Metadaten.
Der Mandantenexport (Backup) enthält die Spalten unverändert.

Browser-Hinweise (`file_metadata` des Galerie-Uploads, ggf. mit GPS) schickt das Upload-Popup
nur für HEIC/HEIF - nur dort übernimmt der Server Client-Werte. Der Auftrag
(`gallery_upload_job.file_hints`) hält sie nur bis zum Jobende (`done`/`failed`) und leert
sie dann; ein abgebrochener Auftrag behält sie bis zur Wiederaufnahme.

## 11. Export

`image_export_service.export_bytes` erzeugt eine **temporäre Kopie**; gespeicherte Originale
werden nie verändert.

- **Echtes Aufnahmedatum vorhanden** (Datenbank oder `DateTimeOriginal` in der Datei): Datei
  unverändert.
- **Nur geschätztes Datum:**
  - XMP `photoshop:DateCreated="JJJJ-MM-TT"` – reines Datum, keine Uhrzeit,
  - XMP `hocx:CaptureDateEstimated="True"` und `hocx:EstimatedCaptureDate` (Namespace
    `https://hocx.ch/ns/capture/1.0/`),
  - EXIF `DateTimeOriginal`/`DateTimeDigitized` = `JJJJ:MM:TT 12:00:00` ohne `OffsetTime`.
    **Konvention:** EXIF verlangt eine Uhrzeit; 12:00 (Mittag) verhindert, dass Programme das
    Datum durch Zeitzonenumrechnung auf einen Nachbartag schieben. Zusätzlich steht der
    geschätzte Charakter im EXIF-`UserComment` (falls leer).
  - Wird ein so exportiertes Bild wieder in hocX hochgeladen, erkennt der Server (und der
    Browser) die Markierung und übernimmt das Datum als **geschätztes**, nicht als echtes.
- **Weder noch:** kein Datum, insbesondere nie das Uploaddatum.
- GPS: vorhandenes GPS bleibt erhalten; liegt GPS nur in der Datenbank vor (z. B. vom Browser
  nachgeliefert), wird es in die Kopie geschrieben. Stammt das DB-GPS aus der Datei selbst
  (`gps_source` `server`/`backfill`, keine HEIC-Konvertierung), wird die Datei dafür gar nicht
  erst eingelesen - Download und Freigabe liefern dann direkt das Original (sofern weder
  Schätzdatum noch Metadatenfilter des Links greifen).
- **Max. 2 MiB entpacktes PNG-XMP:** Komprimiertes `iTXt`-XMP wird nur bis zu dieser Grenze
  entpackt; grösseres XMP bricht den Export ab, geliefert wird das Original.

Exportwege: Einzeldownload `GET /api/stored-files/{id}/download?part=image|both` (auch der
Live-Photo-ZIP), Mehrfachdownload der Galerie-Auswahl (nutzt denselben Endpunkt), öffentliche
Freigaben (Einzeldatei, Ansicht, ZIP „Alle herunterladen“ – zuerst Export, danach entfernt
`photo_metadata_privacy` die Kategorien, die der Link nicht teilt). „Original öffnen“
(`/content`) liefert bewusst die unveränderte Originaldatei.

Formate: JPEG, PNG, WebP verlustfrei auf Segment-/Chunk-Ebene (kein Re-Encode, alle übrigen
Segmente bleiben byte-gleich). TIFF, GIF, BMP und Live-Clips werden unverändert exportiert.
Schlägt das Umschreiben fehl, geht das Original raus.

## 12. Backfill

Für Bilder, die vor dieser Funktion hochgeladen wurden. Kein Hintergrundjob, nichts beim
Serverstart – manuell ausführen:

```bash
docker compose exec backend python -m scripts.backfill_image_metadata --dry-run
docker compose exec backend python -m scripts.backfill_image_metadata
docker compose exec backend python -m scripts.backfill_image_metadata --tenant-id 3 --limit 500
docker compose exec backend python -m scripts.backfill_image_metadata --rescan   # bereits analysierte erneut (nur ergänzend)
```

Kandidaten: saubere Bilder mit `metadata_scanned_at IS NULL`, denen Aufnahmedatum, GPS,
Kameramodell oder Abmessungen fehlen. Je Bild: Original suchen (Abgabebox-Uploads im
Abgabebox-Speicher) → nur wenn vorhanden analysieren → fehlende Werte ergänzen (Herkunft
`backfill`) → `metadata_scanned_at`/`metadata_scan_status` (`ok`, `no_metadata`,
`unreadable`, `missing_file`) setzen. Chargen werden einzeln committet (`SKIP LOCKED`), ein
abgebrochener Lauf setzt beim nächsten Aufruf fort, ein wiederholter Lauf ändert nichts.

Auswertung (JSON): `checked`, `taken_at_added`, `gps_added`, `other_added`,
`not_reconstructable` (= `no_metadata` + lesbar ohne Ergänzung), `no_metadata` („keine
Metadaten vorhanden“), `failed` („Analyse nicht möglich“), `missing_files`, `conflicts`,
`converted_sources`.

HEIC/HEIF-Konvertierungen: Das Original existiert nicht mehr; der Backfill analysiert das
gespeicherte JPEG, das EXIF und GPS aus der Konvertierung übernommen hat. Was dort fehlt, kann
nur ein erneuter Upload des Originals (Vorab-Abgleich über `source_checksum_sha256`) ergänzen.

## 13. Upload-Wege im Überblick

| Weg | Browser-Analyse/Vorab-Abgleich | Serverseitig |
|---|---|---|
| Galerie (Einzelbilder, Ordner) | ja (Hash + Metadaten + Schätzdatum) | Duplikate, Analyse, Schätzdatum, Ergebnis je Datei |
| Galerie-ZIP | nein (Inhalt unbekannt) | Duplikate je Eintrag, Analyse, Schätzdatum |
| Dokumente | ja (nur Hash) | Duplikate, Ergebnis je Datei |
| Protokollbilder (Desktop, Mobil) | ja (nur Hash) | Duplikate (409), Analyse |
| Word-Import | nein | Duplikate (409) |
| Abgabebox | nein (bewusst, siehe 3.) | Duplikate je Element, Analyse |

Virenscan, Speicherquoten, Fortschrittsanzeige, HEIC-Konvertierung, Vorschaubilder,
Qualitätsanalyse, Ähnlichkeitserkennung und Berechtigungen laufen unverändert.

## 14. Migration

`0113_image_capture_metadata` (rein additiv, umkehrbar): neue nullable Spalten an
`stored_file` (siehe oben), CHECK-Constraints, zwei Teilindizes; an `gallery_upload_job`
`estimated_taken_on`, `file_hints` (JSONB), `file_results` (JSONB). Bestehende Datensätze
bleiben unverändert gültig; fehlende Werte liefert der Backfill.

## 15. Bekannte Einschränkungen

- Komprimiertes PNG-XMP (`iTXt` mit Kompression) wird im Browser nicht gelesen (selten); der
  Server liest es.
- AVIF wird im Browser nicht analysiert (gilt als „nicht prüfbar“) – hocX nimmt AVIF
  ohnehin nicht an.
- Sehr grosse Dateien (> 512 MiB) und Browser ohne `crypto.subtle` (kein HTTPS) laden ohne
  Vorab-Abgleich hoch.
- Der Export schreibt bei JPEG/PNG/WebP; TIFF, GIF und BMP bleiben unverändert. Ist in einer
  Datei bereits XMP mit `photoshop:DateCreated` vorhanden, wird kein zweites XMP-Datum
  eingetragen (EXIF wird trotzdem gesetzt).
- Exportiertes EXIF-Datum trägt die Konvention 12:00 Uhr (siehe 11.).
- Konvertierte HEIC-Originale existieren nicht mehr; für sie sind Client-Angaben (Herkunft
  `client`) die einzige nachträgliche Quelle.
- Eine Kartenansicht ist vorbereitet (Spalten, Index), aber nicht umgesetzt (auch mit den
  Foto-Standorten aus Abschnitt 16 bewusst nicht).
- Manuell gesetzte Orte sind nicht Teil des Mandanten-Exports (ZIP); GPS-Orte entstehen beim
  Import aus den Koordinaten neu.

## 16. Foto-Standorte (Ortsnamen, Umkreissuche, Ort von Hand)

Code: `app/services/geo_places.py` (Ortsdaten laden), `app/services/photo_places.py` (Suche,
Umkreis, Ort von Hand, Nachtragen), `app/api/routes/photo_places.py`, Migration
`0260_photo_places.py`, Frontend `lib/photos/places.ts`, `components/photos/photo-place-*.tsx`.

**Ortsdaten (global, kein Mandantendatum).** `geo_place` enthält Orte aus GeoNames (CC BY 4.0:
`cities500` weltweit plus Länderdateien aus `GEO_PLACES_COUNTRIES`, Standard CH, LI, AT, DE, FR, IT
– für CH nur Ortschaften mit Kantonskürzel, für die Nachbarländer auch Weiler, Gipfel, Pässe, Hütten,
Seen, Gletscher) und swisstopo swissNAMES3D (Gipfel, Hütten, Pässe, Seen, Gletscher, Flurnamen,
Quartiere, Weiler < 100 Einwohner, Stationen, Aussichtspunkte; LV95 → WGS84 nach den
Näherungsformeln von swisstopo, ~1 m). Keine Tabelle mit `tenant_id`, darum keine RLS; die
Laufzeitrolle `hocx_app` darf `geo_place` und `geo_dataset` nur lesen und hat keinen Zugriff auf die
Zwischenablage. Schreiben darf nur die eigene Rolle `hocx_geo` (`GEO_DB_PASSWORD`, im job-worker
`GEO_DATABASE_URL`, `geo_places.geo_session`): Zwischenablage `geo_place_import` und
`hocx_geo_import_apply`, Lesen der Ortsdaten, kein Zugriff auf Mandantentabellen (Tests in
`test_tenant_rls.py` und `test_photo_places.py`). Der Job `geo_places_update` (job-worker,
täglich geprüft, lädt nur bei neuer Ausgabe bzw. GeoNames nach 30 Tagen) lädt über HTTPS nur von
`download.geonames.org` und `data.geo.admin.ch` (keine Weiterleitungen, Grössen- und Zeitlimit),
importiert mit der Rolle `hocx_geo`, prüft swissNAMES3D gegen die SHA-256 aus der STAC-API, GeoNames gegen `Content-Length` und ZIP-CRC,
schreibt per `COPY` in die Zwischenablage `geo_place_import` und übernimmt sie mit
`hocx_geo_import_apply` (SECURITY DEFINER: bekannte Quelle, Schlüsselpräfix `gn:`/`sn:`,
Mindestmenge, höchstens 50 % Schwund, Upsert je Schlüssel). Ohne Netz:
`python -m scripts.import_geo_places` mit lokalen Dateien; `--fixture` lädt den kleinen
Testdatensatz (`tests/fixtures/geo_places`) für Tests und E2E. Kein PostGIS: das offizielle
`postgres:18`-Image bringt es nicht mit. `cube`/`earthdistance` wären vorhanden, gebraucht werden
aber nur Kern-Typen: Teil-GiST-Indizes über `point(longitude, latitude)` (präzise Orte,
Ortschaften) für die Bounding-Box beim Reverse-Geocoding und eine eigene Haversine-Funktion
(`hocx_geo_distance_m`).

Umfang (gemessen 2026-11-24, Standardländer): Download ~70 MB (cities500 14 MB, Länderdateien
24 MB, swissNAMES3D 33 MB), 848 000 Orte (GeoNames 511 000, swissNAMES3D 337 000; davon
280 000 Flurnamen), `geo_place` 296 MB inkl. Indizes (Tabelle 141 MB). Reverse-Geocoding ~3 ms je
Foto, Ortssuche 40–100 ms, Umkreis-Kandidaten auf 100 000 Fotos eines Mandanten 3–13 ms
(2–20 km, Bitmap-Index-Scan auf `idx_photo_location_coords`).

**Ort je Foto (`photo_location`, Mandantendaten mit RLS).** Ein Statement-Trigger auf
`stored_file` ruft bei neuem bzw. geändertem GPS `hocx_photo_location_refresh` (SECURITY
DEFINER) – damit gilt das für jeden Upload-Weg (Galerie, ZIP, Datei-Import, Abgabebox,
Protokollbilder, Mandanten-Import), sobald der Metadaten-Scan GPS gesetzt hat. Rangfolge
(`hocx_geo_reverse`): präziser Ort innerhalb seiner Reichweite (Hütte 800 m, Gipfel 1 km, Pass
800 m, See/Gletscher 1,5 km, Weiler 700 m, Flurname/Aussichtspunkt 400 m, Station 300 m; Hütten
und Gipfel vor Flurnamen), Flurnamen und Weiler nicht innerhalb eines Dorfs, Quartiere nur in
Städten; dazu immer die Ortschaft (nächste, nach Grösse gewichtet, bis 30 km) mit Kanton bzw.
Land. Ohne Treffer bleiben nur die Koordinaten (Umkreissuche geht trotzdem). Gespeichert:
wirksame Koordinate, präziser Ort, Ortschaft, Kanton/Land, `search_text` (alle Schreibweisen) und
`geo_generation`. Das Suchdokument der Fotosuche (0204/0217) nimmt die Ortsnamen in die starken
Wörter auf.

**Sichtbarkeit.** Den Ortsnamen sehen alle, die das Foto im eigenen Mandanten sehen
(`GET /files` als `place`, `GET /stored-files/{id}/metadata` als `place`); Koordinaten weiter nur
mit `files.manage`/`meetings.edit` (`gps`). Die Distanz in der Umkreissuche (`place.distance_m`)
nur mit demselben Recht; ohne dieses Recht ist der Umkreis nie enger als der Standard der Ortsart
(mind. 2 km) und die Liste nicht nach Distanz sortiert – sonst liesse sich der Aufnahmeort mit
vielen kleinen Kreisen eingrenzen (Security-Review). Partner geteilter Alben bekommen keinen Ort (wie keine Metadaten),
öffentliche Freigabe-Links nie (eigenes Schema `PublicShareFile` ohne Ort, Dateien ohne Ortsnamen).

**Ortssuche und Umkreis.** `GET /places/search?q=` (ab 3 Zeichen, `photos.read` oder `files.read`):
unscharf über alle Schreibweisen (`hocx_geo_fold`: klein, ohne Akzente, ä = ae = a; Trigramm-Index,
Wortähnlichkeit für Tippfehler), gerankt nach Treffer (Name gleich, beginnt mit, enthält, ähnlich)
und Bedeutung (Art, Einwohner, Schweiz und Nachbarländer zuerst), Dubletten (gleicher Name, < 3 km)
zusammengefasst, ohne Koordinaten. `GET /files?near=<schlüssel>&near_km=<km>` (auch
`/files/timeline`) filtert auf den Umkreis – Standard je Ortsart (Gipfel/Hütte/Punkt 2 km, See 3 km,
Dorf 5 km, Kleinstadt 10 km, Stadt/Region 20 km), höchstens 200 km – und sortiert mit
`sort_by=relevance` nach Distanz (mit Suchtext: zuerst Anzahl getroffener Wörter, dann Distanz).
Der Filter ist eine Bounding-Box im Index `idx_photo_location_coords (tenant_id, latitude,
longitude)`, die Haversine-Distanz läuft nur für die Kandidaten.

**Ort von Hand.** `POST /photo-places/assign` (`photos.manage`, auditiert `photo.place_set` /
`photo.place_cleared`): Ort setzen oder entfernen für bis zu 500 Fotos je Aufruf (der Browser
stückelt grössere Auswahlen mit derselben `batch_id`), optional mit Bezug zum Upload-Vorgang.
Nur Fotos ohne GPS (`skipped_gps`); echtes GPS ersetzt später einen manuellen Ort. Rückgängig:
`POST /place-changes/{id}/undo` (nur, wo seither nichts geändert wurde), Liste je Vorgang:
`GET /place-changes?upload_job_id=`. Fremde, unbekannte und nicht lesbare IDs kommen einheitlich
als `not_found` zurück.

**Altbestand und Updates.** Die Migration legt für jedes vorhandene GPS-Foto eine Zeile ohne Namen
an; der Job `photo_places_resolve` (job-worker, alle 10 min, höchstens 5000 Fotos je Lauf) beschriftet
je Mandant in Stücken zu 500 mit eigenem Commit alles, dessen `geo_generation` älter ist als die
Ortsdaten – wiederaufnehmbar, auch nach jedem Datenupdate. Manuelle Orte behalten ihren Ort und
bekommen nur die Beschriftung neu.
