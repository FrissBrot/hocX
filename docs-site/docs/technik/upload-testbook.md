# Testbook: Upload-Duplikate, Vorab-Abgleich und Bild-Metadaten

Dieses Testbook prüft, dass byteidentische Dateien vor ClamAV und weiterer Verarbeitung
abgefangen werden. In der Haupt-App erscheint ein Duplikathinweis; die öffentliche
Abgabebox überspringt Duplikate desselben Abgabe-Elements still und bestätigt den Upload.

Seit Migration `0113` kommen hinzu: Browser-Analyse und SHA-256-Vorab-Abgleich vor der
Übertragung, Ergänzen fehlender Metadaten ohne erneuten Upload, die drei Datumsarten
(echt/geschätzt/Upload) samt Priorität, GPS, Export mit geschätztem Datum und der
Metadaten-Backfill. Fachliche Beschreibung: `backend/UPLOAD_DUPLICATES.md`.

## Vorbereitung und Ausführung

Die Testdatenbank muss bis einschließlich `0113_image_capture_metadata` migriert sein (im Release
1.2.0: `alembic upgrade head`). Seit 1.2.0 lesen alle Downloads aus dem Objektspeicher; die
automatisierten Tests laufen gegen die Dateisystem-Generation, S3 prüfen STO-M1/STO-M2.
Die regulären Testskripte bereiten die Testumgebung vor:

```bash
./scripts/test.sh backend
./scripts/test.sh abgabebox-backend
./scripts/test.sh frontend
```

Für manuelle Prüfungen einen Testmandanten, einen zweiten Mandanten und zwei offene
Abgabe-Elemente vorbereiten. Eine gültige PDF, ein Bild und jeweils eine byteidentische
Kopie unter anderem Namen bereithalten. Zusätzlich eine PDF mit geändertem Inhalt und
bei Bedarf eine HEIC-Datei verwenden. Für die Metadaten-Fälle: ein Handyfoto mit
Aufnahmedatum und GPS (idealerweise Süd-/Westhalbkugel, z. B. per `exiftool` gesetzt), ein
Bild ohne EXIF (Screenshot), eine HEIC-Datei mit GPS, ein Ordner mit über 50 Bildern und ein
ZIP mit Bildern mit und ohne Aufnahmedatum. Dateiname, Dateigrösse und Bildähnlichkeit allein
sind kein Nachweis für ein exaktes Duplikat.

Bei manuellen Prüfungen Ergebnis, Datum und verwendete Version festhalten. Die folgenden
manuellen Fälle sind Prüfanweisungen, keine bereits ausgeführten Testnachweise.

## Automatisierte Prüfungen

Die Dateinamen in der letzten Spalte beziehen sich auf die angegebenen Testverzeichnisse.

| ID | Prüfung | Erwartung | Testdatei |
|---|---|---|---|
| DUP-01 | Gespeicherte Datei erneut unter anderem Namen als Dokument oder Galerie-Datei übergeben | Kein Scanner-Aufruf, kein neues Ergebnisobjekt, Duplikathinweis | `backend/tests/test_exact_upload_duplicates.py` |
| DUP-02 | Identische Bytes zweimal und geänderte Bytes einmal im Batch prüfen; Original existiert nur in einem anderen Mandanten | Erste Datei und geänderte Datei bleiben erhalten; nur die Wiederholung wird übersprungen; fremder Mandant blockiert nicht | `backend/tests/test_exact_upload_duplicates.py` |
| DUP-03 | Originalhash einer konvertierten Datei hinterlegen und Original erneut prüfen | Duplikat trotz unterschiedlichem Hash der gespeicherten Konvertierung erkannt | `backend/tests/test_exact_upload_duplicates.py` |
| DUP-04 | Gespeichertes Dokument erneut an den Word-Import übergeben | Duplikatantwort mit Status 409 vor dem Scanner | `backend/tests/test_exact_upload_duplicates.py` |
| DUP-05 | In der Abgabebox ausschliesslich vorhandene Duplikate einreichen | Erfolg und unveränderte Empfangszahl; keine Duplikatwarnung, Bildanalyse, Kontingentprüfung oder Scanner-Aufrufe | `abgabebox-backend/tests/test_exact_upload_duplicates.py` |
| DUP-06 | In der Abgabebox vorhandene Datei und zweimal dieselbe neue Datei einreichen | Nur eine neue Datei wird gescannt und gespeichert; alle drei empfangenen Dateien werden ohne Duplikathinweis bestätigt | `abgabebox-backend/tests/test_exact_upload_duplicates.py` |
| PAR-01 | Zwei Dokument- beziehungsweise Galerie-Uploads mit identischen Bytes gleichzeitig in unabhängigen DB-Sitzungen starten | Genau ein Scanner-Aufruf, ein gespeicherter Datensatz und ein Duplikathinweis | `backend/tests/test_concurrent_uploads.py` |
| PAR-02 | Gleichen Mandanten sperren, zweite Anfrage warten lassen, anderen Mandanten prüfen und erste Transaktion zurückrollen | Zweite Anfrage wartet ohne Blockade des Event-Loops; anderer Mandant bleibt unabhängig; Rollback gibt die Sperre frei; synchroner Import verwendet dieselbe Sperre | `backend/tests/test_concurrent_uploads.py` |
| PAR-03 | Zwei identische öffentliche Uploads gleichzeitig starten | Beide Antworten erfolgreich und ohne Duplikatwarnung; nur ein Scan und eine Speicherung | `abgabebox-backend/tests/test_exact_upload_duplicates.py` |
| PAR-04 | Laufende Abgabebox-Verarbeitung abbrechen und Sperre erneut anfordern | Sperre wird nach Abbruch freigegeben | `abgabebox-backend/tests/test_exact_upload_duplicates.py` |
| UI-01 | Galerie-Job mit Duplikat bereits vor der ersten Statusabfrage abschliessen lassen | Ergebnis wird trotzdem genau einmal an die Oberfläche gemeldet | `frontend/components/photos/gallery-upload-progress.test.tsx` |

### Vorab-Abgleich und Metadaten-Ergänzung (Haupt-Backend)

Testdatei `backend/tests/test_upload_precheck.py`, sofern nicht anders angegeben. Die Spalte
„Auftrag“ verweist auf die nummerierte Anforderungsliste der Funktion.

| ID | Prüfung | Erwartung | Auftrag |
|---|---|---|---|
| PRE-01 | Bekannten und unbekannten Hash in einem Request prüfen | `already_exists` mit `file_id` bzw. `upload_required` ohne `file_id` | 1, 2 |
| PRE-02 | Vorhandenes Bild ohne Datum mit Schätzdatum prüfen, danach erneut, danach mit anderem Datum | Erst `metadata_updated` (`applied=[estimated_taken_on]`), Datei auf dem Server byte-gleich; dann `already_exists`; abweichendes Datum nur als Konflikt, nie überschrieben | 3, 4, 5, 10 |
| PRE-03 | Byte-identische Datei mit falschen Client-Angaben prüfen | Server liest seine eigene Datei (Herkunft `server`); Client-Behauptungen werden nie direkt gespeichert | 4, 16 |
| PRE-04 | Bild ohne Metadaten mit behauptetem Datum prüfen | `already_exists`, nichts gespeichert | 16, 56 |
| PRE-05 | Konvertiertes HEIC über `source_checksum_sha256` mit GPS prüfen | GPS mit Herkunft `client` ergänzt, Ausrichtung des Originals nicht übernommen | 12, 32 |
| PRE-06 | Konvertiertes Bild mit vorhandenem GPS und abweichendem Client-GPS | Konflikt `gps`, vorhandene Werte bleiben | 33 |
| PRE-07 | Hash eines Bildes aus einem anderen Mandanten prüfen | `upload_required` ohne `file_id`, fremde Datei unverändert | 7 |
| PRE-08 | Endpunkt als Leser aufrufen | 403 | 7 |
| PRE-09 | Kontext `document` mit Schätzdatum | Nur Hash-Abgleich, keine Metadaten-Änderung | 15 |
| PRE-10 | Treffer ist als infiziert markiert | `upload_required` | 16 |
| PRE-11 | Ungültiger Hash im Request | Schema lehnt ab (422) | 16 |
| PRE-12 | Ergänzen wirft eine unerwartete Ausnahme | Rollback, `fallback_required`, Fehler in `system_error_log` | 9, 10 |

### Galerie-Upload, Datumsarten und Bearbeitung (Haupt-Backend)

| ID | Prüfung | Erwartung | Testdatei | Auftrag |
|---|---|---|---|---|
| DAT-01 | Bilder mit und ohne EXIF-Datum mit Schätzdatum hochladen | Echtes Datum gespeichert, Schätzung nur beim Bild ohne Datum, Uploaddatum separat; `date_source` `exif` bzw. `estimated` | `test_upload_precheck.py` | 13–16, 24–26 |
| DAT-02 | Dasselbe Bild dreimal hochladen (ohne, mit Schätzdatum, ohne) | `uploaded`, `metadata_updated`, `skipped`; nur ein Datensatz | `test_upload_precheck.py` | 3, 4, 10, 53–57 |
| DAT-03 | Zwei Aufträge mit derselben Datei hintereinander verarbeiten | Ein Datensatz, Ergebnisse `uploaded` und `skipped` | `test_upload_precheck.py` | 6 |
| DAT-04 | `file_metadata` mit fremdem und ungültigem Hash mitschicken | Hinweise werden nicht angewendet | `test_upload_precheck.py` | 16 |
| DAT-05 | Unplausibles Schätzdatum (1700) beim Upload | 422 | `test_upload_precheck.py` | 9 (Datum) |
| DAT-06 | Kein Bildformat hochladen | Ergebnis `failed` mit Meldung | `test_upload_precheck.py` | 11 |
| DAT-07 | Gemischter Auftrag: neu, Duplikat mit Schätzdatum, defekt | Je Datei genau ein Status, Summe = Dateizahl | `test_upload_precheck.py` | 26, 57 |
| DAT-08 | Schätzdatum setzen, ändern, entfernen | Echtes Datum und Uploaddatum unverändert | `test_upload_precheck.py` | 17, 18 |
| DAT-09 | Bearbeitung als Leser bzw. aus fremdem Mandanten | 403 bzw. 404 | `test_upload_precheck.py` | 7, 9 |
| DAT-10 | Metadaten als Schreiber, Kassier, Leser, fremder Mandant abrufen | Drei Datumsarten und GPS nur im eigenen Mandanten; Bearbeitbarkeit nur für Schreiber; Leser 403 | `test_upload_precheck.py` | 34 |
| DAT-11 | Zwei Bilder mit Schätzdatum sortieren, einem später ein echtes Datum geben | Reihenfolge ändert sich; Schätzung verknüpft nie automatisch mit einem Termin, das echte Datum schon | `test_upload_precheck.py` | 19–21, 38, 39 |
| DAT-12 | HEIC mit Datum, Offset und GPS hochladen, danach erneut vorab prüfen | Werte aus dem Original gespeichert, Schätzung ignoriert, Ausrichtung nicht übernommen; Vorab-Abgleich erkennt das HEIC | `test_upload_precheck.py` | 12 |
| DAT-13 | Protokollbild mit EXIF und GPS hochladen | Datum und GPS gespeichert | `test_upload_precheck.py` | 15 |
| MET-01 | EXIF/GPS aus JPEG, PNG, WebP lesen; Süd/West; Höhe unter Meeresspiegel | Korrekte Vorzeichen und Werte | `test_image_metadata_service.py` | 30, 31 |
| MET-02 | EXIF-Datum ohne Zeitzone, ungültige Daten, Zukunft, 0/0-GPS | Lokale Kamerazeit, Offset separat; Unplausibles verworfen | `test_image_metadata_service.py` | 22 |
| MET-03 | Ergänzungs- und Konfliktregeln, Schätzdatum nie über echtem Datum | Nur fehlende Werte gefüllt, Konflikte gemeldet | `test_image_metadata_service.py` | 4, 25, 33 |
| MET-04 | Datumspriorität und Termin-Zuordnung | `exif` > `estimated` > `upload`; Schätzung ohne Auto-Zuordnung; reines Kalenderdatum ohne Uhrzeit | `test_image_metadata_service.py` | 19, 20, 23 |
| MET-05 | Abgabebox liest Datum, Offset, Süd/West-GPS, unterscheidet „keine Metadaten“/„unlesbar“, verwirft 0/0 | Werte im INSERT, kein Vorab-Endpunkt | `abgabebox-backend/tests/test_image_metadata.py` | 8 |

### Export und Backfill (Haupt-Backend)

| ID | Prüfung | Erwartung | Testdatei | Auftrag |
|---|---|---|---|---|
| EXP-01 | Nur geschätztes Datum exportieren | EXIF `JJJJ:MM:TT 12:00:00` ohne Offset, XMP-Datum ohne Uhrzeit und hocX-Markierung; GPS bleibt; Re-Import erkennt Schätzung | `test_image_export.py` | 42, 44 |
| EXP-02 | Echtes Datum in Datenbank oder Datei | Datei unverändert | `test_image_export.py` | 41 |
| EXP-03 | Weder echtes noch geschätztes Datum | Kein Datum erfunden | `test_image_export.py` | 43 |
| EXP-04 | PNG, einfaches und erweitertes WebP | Datum geschrieben, Bild bleibt gültig | `test_image_export.py` | 42 |
| EXP-05 | GPS nur in der Datenbank | In die Kopie geschrieben (inkl. Höhe unter Meeresspiegel) | `test_image_export.py` | 44 |
| EXP-06 | GIF, TIFF, defektes JPEG | Unverändert exportierbar | `test_image_export.py` | 47 |
| EXP-07 | Einzeldownload mit/ohne Schätzdatum | Exportfassung als eigene Antwort (nie das gespeicherte Objekt) bzw. Original per `object_response`; gespeicherte Datei byte-gleich | `test_image_export.py` | 45 |
| EXP-08 | Freigabe-ZIP mit/ohne geteiltes Aufnahmedatum | Datumslogik je Datei; ohne Freigabe kein Datum und keine Markierung | `test_image_export.py` | 46 |
| EXP-09 | Freigabe ohne Standort, GPS nur in der Datenbank | Kein GPS in Datei und API | `test_image_export.py` | 34 |
| LOC-01 | Album-Freigabe an Partner mit/ohne Standort, Partner-Fotos beim Besitzer | Inhalts- und Download-Route liefern GPS nur mit Freigabe, sonst bereinigte Bytes; Kamera/Datum bleiben | `test_album_share_location.py` | IMGMETA-007 |
| LOC-02 | GPS nur in der Datenbank, Partner ohne Standortfreigabe | Exportfassung schreibt kein GPS in die Kopie | `test_album_share_location.py::test_database_only_gps_is_not_written_into_the_partner_copy` | IMGMETA-007 |
| LOC-03 | Live-Photo-Clip für Partner ohne Standort | Clip aus dem Objektspeicher per ffmpeg ohne Container-Metadaten | `test_album_share_location.py::test_live_photo_video_loses_its_location_for_partners_without_the_location` (braucht ffmpeg) | IMGMETA-007 |
| BFL-01 | Backfill mit vollständigem, leerem, fehlendem und defektem Original sowie fremdem Mandanten | Datum/GPS rekonstruiert; Status `no_metadata`/`missing_file`/`unreadable`; Auswertung stimmt; zweiter Lauf ohne Änderungen; `--rescan` nur ergänzend | `test_image_metadata_backfill.py` | 48–51 |
| BFL-02 | Lauf nach zwei Bildern abbrechen, neu starten | Setzt fort, kein Bild doppelt | `test_image_metadata_backfill.py` | 52 |
| BFL-03 | Dry-Run | Auswertung ohne Schreiben | `test_image_metadata_backfill.py` | 51 |

### Frontend (Vitest)

| ID | Prüfung | Erwartung | Testdatei | Auftrag |
|---|---|---|---|---|
| FE-01 | Parser gegen echte Pillow-Testbilder (JPEG, PNG, WebP, TIFF, HEIC, hocX-Export) | Datum, Offset, Kamera, Ausrichtung, Süd/West-GPS, Höhe, Richtung korrekt; Export-Schätzung kein echtes Datum | `frontend/lib/image-analysis/metadata.test.ts` | 30, 31 |
| FE-02 | SHA-256, „vorhanden“/„fehlt“/„nicht prüfbar“, ZIP/Clips, defekte Metadaten | Hash entspricht Original; nicht prüfbar nie als „fehlt“ | `metadata.test.ts` | 27 |
| FE-03 | Popup mit Bildern mit/ohne Datum | Hinweis „Für 2 Bilder …“ und Datumsfeld nur bei Bedarf | `frontend/components/photos/gallery-upload-modal.test.tsx` | 24 |
| FE-04 | Nicht prüfbares Bild, ZIP | Eigener Hinweis, nicht als „ohne Datum“ gezählt | `gallery-upload-modal.test.tsx` | 27 |
| FE-05 | Vorab-Abgleich mit Schätzdatum | Vorhandenes Bild nicht übertragen, Datum und Metadaten mitgesendet, Ergebnis an Seite gemeldet | `gallery-upload-modal.test.tsx` | 2, 3, 10 |
| FE-06 | Alle vorhanden / Abgleich fehlgeschlagen | Kein Upload bzw. normaler Upload aller Dateien | `gallery-upload-modal.test.tsx` | 9, 10 |
| FE-07 | 120 Bilder auswählen | Drei Aufträge (50/50/20) | `gallery-upload-modal.test.tsx` | 28, 29 |
| FE-08 | Dokumente: vorhanden / Abgleich fehlgeschlagen | Nicht übertragen, als übersprungen gemeldet bzw. normaler Upload | `frontend/components/files/document-upload-modal.test.tsx` | 15 |
| FE-09 | Batches, Live-Photo-Paare, Zählung, keine behauptete Ergänzung ohne Felder | Jede Datei genau einmal | `frontend/lib/utils/upload-results.test.ts` | 56, 57 |
| FE-10 | Kennzeichnung in Datumsüberschriften | Echtes Datum ohne Symbol; geschätzt/Upload mit zugänglichem Button, Tippen öffnet Hinweis; keine Textzeilen in Kacheln | `frontend/components/photos/photo-capture-date.test.tsx` | 35–37, 40 |
| FE-11 | Detailansicht | Kamerazeit ohne Zeitzonenverschiebung, drei Datumsarten, GPS; Schätzdatum setzen/entfernen nur mit Schreibrecht | `photo-capture-date.test.tsx` | 17, 18, 39 |
| FE-12 | Ergebnisanzeige | Zusammenfassung „24 Bilder verarbeitet: 12 hochgeladen, 8 übersprungen, 4 übersprungen und Metadaten ergänzt.“; vier Status je Datei | `photo-capture-date.test.tsx` | 53–55 |
| FE-13 | Mehrfachdownload | Nutzt Export-Endpunkt statt Original | `frontend/components/photos/photo-bulk-bar.test.tsx` | 46 |

## Manuelle Browser- und Integrationsprüfungen

| ID | Durchführung | Erwartung |
|---|---|---|
| DUP-M1 | PDF unter „Dateien“ hochladen, danach byteidentische Kopie mit anderem Namen hochladen | Sichtbarer Duplikathinweis; keine zweite Datei |
| DUP-M2 | Bild unter „Fotos“ hochladen, Verarbeitung abwarten, Kopie erneut hochladen; zusätzlich ein ZIP mit wiederholtem Bild testen | Duplikathinweis auch bei sehr schneller Verarbeitung; nur ein Bild gespeichert |
| DUP-M3 | Ein Protokollbild erneut im selben Block und danach in einem anderen Block desselben Mandanten hochladen | Sichtbare Rückmeldung zum vorhandenen Bild; keine zweite gespeicherte Datei |
| DUP-M4 | Dasselbe Dokument zweimal in die Word-Import-Warteschlange hochladen | Zweiter Upload zeigt Duplikathinweis; kein zweiter Warteschlangeneintrag |
| DUP-M5 | Neue HEIC-Datei hochladen, JPEG-Verarbeitung abwarten und dieselbe HEIC-Datei erneut hochladen | Original wird als Duplikat erkannt; kein zweites Galerie-Bild |
| DUP-M6 | In der Abgabebox dasselbe Dokument erneut und anschliessend zusammen mit einem neuen Dokument einreichen | Gewohnte Erfolgsanzeige ohne Duplikattext; intern nur die neue Datei zusätzlich gespeichert |
| DUP-M7 | Dateilimit eines Abgabe-Elements erreichen, dann einen ausschliesslich identischen Upload über den Upload-Endpunkt wiederholen | Erfolgreiche Antwort ohne Duplikatwarnung; Dateizahl und Speicherverbrauch bleiben gleich. Eine mögliche Sperre der Dateiauswahl im Browser separat erfassen |
| DUP-M8 | Identische Datei für zwei unterschiedliche Abgabe-Elemente einreichen und in einem anderen Mandanten hochladen | Jede fachlich getrennte Abgabe beziehungsweise jeder Mandant kann die Datei erhalten |
| PAR-M1 | Dieselbe Datei in zwei Browserfenstern möglichst gleichzeitig hochladen | Eine Speicherung; Haupt-App zeigt Duplikathinweis, Abgabebox bestätigt beide Uploads still. Scanner-Aufrufzahl zusätzlich über Testinstrumentierung prüfen |
| PAR-M2 | Im Testbetrieb mit mehreren Backend-Prozessen denselben Upload über Haupt-App und Abgabebox überlappen lassen | Verarbeitung wird je Mandant koordiniert; Duplikatentscheidung nach Abschluss des ersten Uploads. Abgabebox bleibt auf ihr Abgabe-Element begrenzt |
| PAR-M3 | Im Testbetrieb ersten Upload während der Verarbeitung serverseitig abbrechen, zweiten Upload warten lassen | Zweiter Upload kann nach Freigabe übernehmen; keine dauerhaft gehaltene Sperre. Blosses Schliessen des Browserfensters garantiert keinen serverseitigen Abbruch |
| PRE-M1 | Bild hochladen, danach dasselbe Bild erneut wählen; im Browser-Netzwerkprotokoll prüfen | Popup zeigt „Übersprungen – bereits vorhanden“; kein Request an `gallery-uploads` mit dieser Datei; Zusammenfassung „… 1 übersprungen“ |
| PRE-M2 | Screenshot hochladen, danach erneut mit Schätzdatum hochladen | „Übersprungen · Metadaten ergänzt“, Details nennen „geschätztes Aufnahmedatum“; Galerie ordnet das Bild unter dem geschätzten Tag mit Kalendersymbol ein |
| PRE-M3 | Mischung aus Handyfotos und Screenshots wählen, Schätzdatum setzen | Hinweis nennt nur die Screenshots; Handyfotos behalten ihr echtes Datum |
| PRE-M4 | Ordner mit über 50 Bildern per Drag & Drop und per „Ordner auswählen“ hochladen | Nur Bilddateien übernommen; Analysefortschritt sichtbar, Popup bleibt bedienbar; Upload in mehreren Teilen („Teil 2 von 3“); Abbrechen stoppt weitere Teile |
| PRE-M5 | Backend kurz stoppen bzw. Precheck-Request im Browser blockieren, dann hochladen | Normaler Upload; serverseitige Duplikaterkennung greift weiterhin |
| PRE-M6 | Seite über HTTP ohne sicheren Kontext öffnen (nur Testbetrieb) | Upload funktioniert ohne Vorab-Abgleich |
| DAT-M1 | Bild in der Detailansicht öffnen, Schätzdatum setzen, ändern, entfernen, Ansicht schliessen | Drei Datumsarten getrennt; Galerie sortiert/gruppiert danach neu; echtes Datum und Uploaddatum unverändert |
| DAT-M2 | Datumssymbole in Light/Dark, 1440 px und 390 px prüfen; per Tastatur und Tippen öffnen | Dezent, kein Layoutsprung, Hinweistext lesbar und zugänglich |
| DAT-M3 | Foto mit GPS (Süd-/Westhalbkugel) öffnen | Standort mit korrekten Vorzeichen; als Partner eines geteilten Albums kein Standort |
| EXP-M1 | Bild mit Schätzdatum einzeln, als Mehrfachauswahl und über einen Freigabe-Link herunterladen; in einem Fotoprogramm (z. B. Apple Fotos, Lightroom, `exiftool`) öffnen | Programm sortiert unter dem geschätzten Tag; `exiftool` zeigt `CaptureDateEstimated=True`; Original auf dem Server unverändert (Hash vergleichen) |
| EXP-M2 | Exportiertes Bild wieder hochladen | Wird als vorhanden bzw. mit geschätztem (nicht echtem) Datum übernommen |
| BFL-M1 | Auf einer Kopie der Testdaten `python -m scripts.backfill_image_metadata --dry-run`, dann ohne `--dry-run`, dann erneut ausführen | Plausible Auswertung; zweiter Lauf `checked: 0`; Abbruch mit Ctrl+C und Neustart setzt fort |
| STO-M1 | Nach einer Storage-Migration auf S3 (Testumgebung): Foto mit Schätzdatum einzeln, als Live-Photo-ZIP und als Partner ohne Standort herunterladen | Exportfassung bzw. bereinigte Datei wie auf dem Dateisystem; Videos im Browser spulbar (Range/206) |
| STO-M2 | Nach der Migration den Metadaten-Backfill und den Vorab-Abgleich ausführen | Backfill liest aus S3 (`missing_file` nur bei wirklich fehlenden Objekten); vorhandene Bilder werden weiter erkannt |
| ABX-M1 | Handyfoto mit GPS über die Abgabebox einreichen | Aufnahmedatum und Standort in der Detailansicht; Abgabebox-Antwort unverändert (kein Duplikat- oder Metadatenhinweis) |

## Grenzen und Nachweise

- Die serverseitige Prüfung nach der Übertragung bleibt die verbindliche Duplikaterkennung.
  Der Browser-Vorababgleich spart nur Übertragungen; ob tatsächlich keine Bytes gesendet
  werden, belegen die Vitest-Fälle über gemockte Requests, im echten Browser PRE-M1.
- Die Abgabebox hat bewusst keinen Vorab-Abgleich (öffentlich, anonym); MET-05 und ABX-M1
  prüfen nur die serverseitige Metadatenextraktion.
- Web Worker laufen in Vitest nicht (jsdom); die Tests nutzen den Hauptthread-Fallback mit
  derselben Analyse. Die Worker-Bündelung ist nur durch den Produktionsbuild belegt, die
  Bedienbarkeit bei grossen Mengen durch PRE-M4.
- Die Export-Konvention (12:00 Uhr) ist automatisiert geprüft; wie Fremdprogramme sie
  darstellen, nur über EXP-M1.
- ClamAV ist in den gezielten Regressionstests ersetzt; geprüft wird die Zahl der
  Scanner-Aufrufe. Das belegt nicht die Erkennungsleistung eines echten Virenscanners.
- Die parallelen Haupt-Backend-Tests verwenden echte DB-Sitzungen und gespeicherte Dateien.
  Die Abgabebox-Tests verwenden die echte PostgreSQL-Sperre, ersetzen aber Repository und
  Dateispeicherung. Vollständige HTTP-, Captcha- und Browserabläufe bleiben manuelle Fälle.
- Der Frontend-Test prüft die Weitergabe des Job-Ergebnisses; die tatsächliche sichtbare
  Rückmeldung gehört zusätzlich zu DUP-M2.
- Der Originalhash-Test prüft den Hashvergleich, nicht die HEIC-Konvertierung. Vor der
  Einführung des Originalhashs konvertierte Dateien können nicht rückwirkend anhand der
  ursprünglichen HEIC-Bytes erkannt werden.
- Gleichzeitige Uploads innerhalb desselben Mandanten warten aufeinander, auch wenn ihre
  Dateien verschieden sind. Andere Mandanten verwenden unabhängige Sperren.
- Das Zusammenspiel mehrerer Prozesse und beider Dienste wird durch PAR-M2 geprüft;
  die automatisierten Paralleltests allein ersetzen diesen Integrationstest nicht.
