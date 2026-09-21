# Exakte Upload-Duplikate

Galerie, Dokumentuploads, Word-Import und Protokollbilder prüfen SHA-256 vor ClamAV innerhalb des Mandanten. Die vorhandenen Upload-Rückmeldungen zeigen übersprungene Dateien als Duplikate an. Galerie-ZIP-Einträge durchlaufen dieselbe Prüfung beim Entpacken.

Die Abgabebox prüft innerhalb desselben Abgabe-Elements. Exakte Duplikate werden still übersprungen; die erfolgreiche Antwort zählt alle empfangenen Dateien. Nur neue Dateien zählen gegen das Dateilimit und den Speicherbedarf. Reine Duplikat-Anfragen erreichen weder Bildanalyse noch ClamAV.

Der Vergleich benötigt die Dateibytes und einen SHA-256-Durchlauf. Er findet serverseitig nach der Übertragung statt; es gibt keine Browser-Vorabprüfung. Ähnliche, aber nicht byteidentische Bilder bleiben von dieser Prüfung getrennt.

Migration `0082_upload_exact_duplicates` ergänzt Indizes für den Hashvergleich und einen Originaldatei-Hash für konvertierte Bilder. Dieser Originalhash wird bei neuen Galerie-Uploads gespeichert. Bei früher konvertierten Dateien lässt sich der Originalhash nicht aus dem JPEG rekonstruieren.

Gleichzeitige Uploads werden je Mandant über eine gemeinsame PostgreSQL-Transaktionssperre koordiniert. Die Sperre gilt vom Hashvergleich bis zum Datenbank-Commit, auch zwischen Haupt-App und Abgabebox sowie verschiedenen Serverprozessen. Wartende asynchrone Anfragen geben den Event-Loop frei. Nach dem Warten wird erneut geprüft: Ein erfolgreich gespeichertes Duplikat wird übersprungen; nach einem fehlgeschlagenen Upload kann die nächste Anfrage übernehmen. Andere Mandanten bleiben unabhängig. Die Abgabebox hält ihre Sperre auf einer separaten Verbindung, damit Zwischen-Commits der Upload-Protokollierung sie nicht vorzeitig freigeben.
