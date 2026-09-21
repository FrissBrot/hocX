# Testbook: Upload-Duplikate und parallele Uploads

Dieses Testbook prüft, dass byteidentische Dateien vor ClamAV und weiterer Verarbeitung
abgefangen werden. In der Haupt-App erscheint ein Duplikathinweis; die öffentliche
Abgabebox überspringt Duplikate desselben Abgabe-Elements still und bestätigt den Upload.

## Vorbereitung und Ausführung

Die Testdatenbank muss bis einschließlich `0082_upload_exact_duplicates` migriert sein.
Die regulären Testskripte bereiten die Testumgebung vor:

```bash
./scripts/test.sh backend
./scripts/test.sh abgabebox-backend
./scripts/test.sh frontend
```

Für manuelle Prüfungen einen Testmandanten, einen zweiten Mandanten und zwei offene
Abgabe-Elemente vorbereiten. Eine gültige PDF, ein Bild und jeweils eine byteidentische
Kopie unter anderem Namen bereithalten. Zusätzlich eine PDF mit geändertem Inhalt und
bei Bedarf eine HEIC-Datei verwenden. Dateiname, Dateigrösse und Bildähnlichkeit allein
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

## Grenzen und Nachweise

- Die Prüfung findet nach der Übertragung auf dem Server statt. Eine Browser-Vorabprüfung
  und das Einsparen der Netzwerkübertragung sind nicht Bestandteil dieser Tests.
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
