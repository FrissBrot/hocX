# Dateien importieren

Mit dem Datei-Import übernimmt ein Verein eine bestehende Ablage in einem Durchgang nach hocX -
zum Beispiel den Vereinsordner aus OneDrive, Google Drive oder Dropbox. Zu finden unter
**Dateien › Importieren**.

!!! info "Wer darf importieren?"
    Die Berechtigung **Dateien importieren** hat standardmässig nur die Rolle *Administrator*. Sie lässt
    sich unter *Rollen* auch eigenen Rollen geben. Für Bilder braucht es zusätzlich «Dateien & Fotos
    verwalten». Es läuft immer nur ein Import pro Verein gleichzeitig.

## Quellen

| Quelle | Wann | Hinweise |
|---|---|---|
| **ZIP-Archiv** | Download aus OneDrive/Dropbox, Google Takeout, Archiv vom PC | Mehrere ZIPs pro Import möglich (z. B. Takeout-Teilarchive), je bis 10 GB. Bei Google Takeout wird der Ordner «Takeout» automatisch erkannt. Die Metadaten-Dateien (`.json`) werden nicht importiert, ihr Aufnahmedatum aber übernommen, wenn das Foto selbst keines hat (siehe unten). |
| **Ordner hochladen** | Synchronisierter Ordner auf dem PC (OneDrive, Google Drive, …) | Zuerst wird nur die Dateiliste übertragen. Nach dem Start lädt der Browser genau die Dateien hoch, die importiert werden - das Fenster muss dafür offen bleiben. Wird es geschlossen, denselben Ordner später erneut wählen; der Upload geht weiter. |
| **Microsoft OneDrive / SharePoint** | OneDrive privat, OneDrive for Business, SharePoint-Bibliotheken | Direkte Verbindung, siehe unten. Erscheint nur, wenn der Betreiber die Verbindung eingerichtet hat. |
| **Dropbox** | Persönliche Dropbox, freigegebene Ordner in der eigenen Dropbox | Direkte Verbindung, siehe unten. Erscheint nur, wenn der Betreiber die Verbindung eingerichtet hat. |
| **WebDAV (kDrive, Nextcloud …)** | Infomaniak kDrive, Nextcloud, SwissDisk und andere Speicher mit WebDAV | Verbindung mit Benutzername und **App-Passwort**, siehe unten. |


### Direkt aus Microsoft OneDrive und SharePoint

1. Kachel **Microsoft OneDrive / SharePoint** wählen, Dateitypen und Optionen festlegen, **Weiter**.
2. **Bei Microsoft anmelden** - die Anmeldung läuft direkt bei Microsoft (privates Konto oder Konto
   von Arbeit/Schule). hocX bittet zuerst nur um **Lesezugriff auf die eigenen Dateien**.
3. Im Ordnerbaum die gewünschten Ordner oder Dateien ankreuzen (Pfeiltasten nicht nötig: Tab zu
   «aufklappen» bzw. zur Checkbox, Enter/Leertaste). Ein gewählter Ordner umfasst alle Unterordner.
   - **Mein OneDrive**: die eigenen Dateien.
   - **Für mich freigegeben** und **SharePoint-Websites**: bei Geschäftskonten erst nach einer zweiten
     Zustimmung («Zugriff erlauben»); hocX fragt erst danach, wenn du es brauchst.
4. **Dateien auflisten** - hocX geht die Ordner im Hintergrund durch (die Seite darf geschlossen
   werden). Danach folgen Regeln, Vorschau und Start wie beim ZIP-Import.
5. Während des Imports lädt hocX die Dateien selbst bei Microsoft herunter; der Browser muss nicht
   offen bleiben.

**«Freigabe durch die IT nötig»:** Viele Firmen- und Schulkonten erlauben neue Apps erst, wenn ein
Administrator der Organisation zustimmt. Der Assistent zeigt dann eine Anleitung: Domain der
Organisation (z. B. `verein.onmicrosoft.com`) eingeben, den **Freigabe-Link** kopieren und der IT
schicken. Nach der Freigabe erneut anmelden. Private Konten sind nicht betroffen.

**Neu anmelden:** Verlangt Microsoft mitten im Import eine neue Anmeldung (z. B. nach einem
Passwortwechsel), pausiert der Import und du bekommst eine E-Mail. Mit **Neu anmelden** im Assistenten
geht es dort weiter, wo der Import stand. Ohne Anmeldung wird er nach 7 Tagen beendet.

**Datenschutz:** hocX liest nur die gewählten Ordner, nur lesend. Der Zugang (Token) wird
verschlüsselt gespeichert und gelöscht, sobald der Import beendet ist; **Verbindung trennen** löscht
ihn sofort. Die App-Berechtigung selbst entfernst du bei Microsoft: privat unter
<https://account.live.com/consent/Manage>, geschäftlich unter <https://myapps.microsoft.com>.

Grenzen: höchstens 50 000 Dateien und 100 GB pro Import; Dokumente bis 20 MB, Bilder bis 100 MB
(wie beim normalen Hochladen). Grössere oder nicht unterstützte Dateien erscheinen im Bericht.

### Direkt aus Dropbox

1. Kachel **Dropbox** wählen, Optionen festlegen, **Weiter**.
2. **Bei Dropbox anmelden** - die Anmeldung läuft direkt bei Dropbox. hocX bittet nur um
   **Lesezugriff** (Dateien und Ordnerangaben); Dropbox zeigt die Berechtigungen vor der Zustimmung.
3. Im Ordnerbaum unter **Dropbox** die Ordner oder Dateien ankreuzen. Grosse Ordner werden
   seitenweise geladen (**Weitere laden**). Paper-Dokumente lassen sich nicht als Datei laden und
   erscheinen nicht.
4. **Dateien auflisten**, danach Regeln, Vorschau und Start wie oben. Bremst Dropbox (zu viele
   Anfragen), wartet hocX und macht automatisch weiter.

**Datenschutz:** Der Zugang wird verschlüsselt gespeichert und nach dem Import bei Dropbox
widerrufen und gelöscht (**Verbindung trennen** sofort). Unter
<https://www.dropbox.com/account/connected_apps> siehst und entfernst du verbundene Apps.

### Aus kDrive, Nextcloud oder einem anderen WebDAV-Speicher {#webdav}

WebDAV ist ein offenes Verfahren, mit dem viele Schweizer und europäische Speicher Dateien
bereitstellen. hocX meldet sich dort mit **Benutzername und App-Passwort** an.

1. Kachel **WebDAV (kDrive, Nextcloud …)** wählen, Optionen festlegen, **Weiter**.
2. **Anbieter** wählen:
   - **Infomaniak kDrive:** nur Benutzername (die E-Mail-Adresse des Infomaniak-Kontos) und
     App-Passwort. Wer mehrere kDrives hat, gibt zusätzlich die **kDrive-ID** an (die Zahl in der
     Adresse, wenn kDrive im Browser offen ist).
   - **Nextcloud:** zusätzlich die **Serveradresse** des Vereins, z. B. `cloud.verein.ch` (ohne
     `https://`). Den Pfad ergänzt hocX selbst.
   - **Andere WebDAV-Adresse** (z. B. SwissDisk): die vollständige WebDAV-Adresse mit `https://`,
     wie sie der Anbieter angibt.
3. **Verbinden** - hocX prüft Adresse und Zugangsdaten sofort. Danach wie oben Ordner wählen,
   **Dateien auflisten**, Regeln, Vorschau, Start.

Erlaubt sind nur verschlüsselte Adressen (`https://`) auf den Ports 443 oder 8443. Adressen im
eigenen Netz (z. B. ein NAS zu Hause oder `192.168.…`) sind aus Sicherheitsgründen gesperrt - hocX
kann sie ohnehin nicht erreichen.

**Passwort abgelehnt:** Wird das App-Passwort während des Imports ungültig (gelöscht, geändert),
pausiert der Import, du bekommst eine E-Mail und gibst mit **Neu anmelden** ein neues App-Passwort
ein. Der Import geht dort weiter, wo er stand. Adresse und Benutzer müssen dieselben bleiben.

**Datenschutz:** Das App-Passwort wird verschlüsselt gespeichert, nie angezeigt und gelöscht,
sobald der Import beendet ist (**Verbindung trennen** sofort). Lösche das App-Passwort nach dem
Import am besten auch beim Anbieter.

#### App-Passwort erstellen {#app-passwort}

Ein App-Passwort ist ein eigenes Passwort nur für hocX. Es funktioniert auch mit
Zwei-Faktor-Anmeldung und lässt sich jederzeit einzeln löschen, ohne dein normales Passwort zu
ändern. Die Menüs der Anbieter können sich ändern; im Zweifel in deren Hilfe nach «App-Passwort»
bzw. «Anwendungspasswort» suchen.

**Infomaniak kDrive**

1. Im Infomaniak Manager anmelden, oben rechts auf das **Profilbild** → **Mein Profil**.
2. **Sicherheit** → **Anwendungspasswörter** → **Ein Anwendungspasswort erstellen**.
3. Name `hocX Import` eingeben, bestätigen und das angezeigte Passwort kopieren (es wird nur
   einmal gezeigt).
4. In hocX: Anbieter **Infomaniak kDrive**, Benutzername = E-Mail-Adresse des Infomaniak-Kontos,
   App-Passwort einfügen.
5. Nach dem Import: dort das Anwendungspasswort wieder löschen.

**Nextcloud**

1. In Nextcloud anmelden, oben rechts auf das **Profilbild** → **Persönliche Einstellungen**.
2. **Sicherheit** → Abschnitt **Geräte & Sitzungen** → App-Name `hocX Import` eingeben →
   **Neues App-Passwort erstellen**.
3. Nextcloud zeigt **Benutzername** und **Passwort** - beide so übernehmen (der Benutzername kann
   von deinem Anmeldenamen abweichen).
4. In hocX: Anbieter **Nextcloud**, Serveradresse (wie in der Adresszeile, ohne `https://` und
   Pfad), Benutzername und App-Passwort.
5. Nach dem Import: in derselben Liste das App-Passwort mit **Widerrufen** löschen.

**SwissDisk und andere:** In den Kontoeinstellungen des Anbieters nach «WebDAV» suchen; dort
stehen die Adresse und, falls angeboten, ein App- oder Gerätepasswort.

## Regeln

Regeln werden der Reihe nach auf jede Datei angewendet. Eine Regel hat Bedingungen (alle müssen
passen) und eine Aktion.

**Bedingungen**

- **Im Ordner** - die Datei liegt in diesem Ordner oder einem Unterordner.
- **Pfad-Muster** - `*` steht für beliebige Zeichen innerhalb eines Ordners, `**` für beliebig
  viele Ordner, `?` für ein Zeichen. Ein Muster ohne `/` prüft nur den Dateinamen (`*.pdf`).
  Beispiele: `Fotos/20??/*`, `**/Lager/**`.
- **Dateiname (regulärer Ausdruck)** - z. B. `^IMG_\d+` oder `(?i)protokoll`. Rückverweise und
  Lookarounds werden aus Sicherheitsgründen nicht unterstützt.
- **Dateityp** - Bilder, Dokumente oder beide.

**Aktionen**

| Aktion | Wirkung |
|---|---|
| Tags hinzufügen | Tags aller passenden Regeln werden zusammengeführt. |
| Aufnahmedatum setzen, wenn es fehlt | Nur Bilder. Gilt nur, wenn die Datei selbst kein Aufnahmedatum hat, und erscheint als «geschätzt». Passen mehrere Regeln, gilt die erste (andere werden als Konflikt angezeigt). |
| Nicht importieren | Gewinnt immer. Die Datei wird weder übertragen noch importiert. |
| In Album einordnen | Nur Bilder, nur mit eingeschalteter Option «Bilder per Regel in Alben einordnen»: in ein bestehendes oder ein neues Album. |
| Album nach Ordnernamen | Nur Bilder, nur mit eingeschalteter Option: ein Album je Ordner (direkter oder oberster Ordner). |

**Alben sind standardmässig aus.** Ohne die Option kommen Bilder einfach in die Galerie; sie lassen
sich später über die Mehrfachauswahl einem Album zuordnen. Gibt es im Verein schon ein Album mit
genau diesem Namen, wird es ergänzt statt ein zweites anzulegen (bei mehreren gleichnamigen das
älteste; der Bericht nennt das). Alben anderer Vereine (geteilte Alben) werden nie verändert.

**Aufnahmedatum:** Es gilt immer das Datum aus der Datei (EXIF). Fehlt es, übernimmt hocX bei Google
Takeout das Datum aus der Metadaten-Datei (`photoTakenTime`), sonst das Datum einer Datumsregel. Beide
erscheinen als «geschätzt». Bekannte Einschränkung: Das Takeout-Datum wird nur aus ZIP-Archiven
gelesen und nur, wenn die Metadaten-Datei im selben Teilarchiv liegt wie das Foto - nicht beim
Hochladen eines entpackten Takeout-Ordners.

Zusätzlich lassen sich die **Ordnernamen als Tags** übernehmen (nichtssagende Namen wie «Neuer
Ordner» oder «Desktop» werden ausgelassen). hocX kennt keine Ordner in der Ablage: die
Ordnerstruktur bleibt über Tags und Alben erhalten.

## Vorschau, Start, Bericht

Die Vorschau zeigt für jede Datei, ob sie importiert wird, mit welchen Tags, welchem Datum und in
welchen Alben, und welche Regeln getroffen haben. Reicht das Speicherkontingent nicht, lässt sich
der Import nicht starten.

Nach dem Start lassen sich die Regeln nicht mehr ändern. Jede Datei durchläuft die gleichen
Prüfungen wie ein normaler Upload (Virenprüfung, Inhaltstyp, Duplikate, Kontingent). Bereits
vorhandene Dateien werden nicht doppelt gespeichert; sie bekommen aber die Tags und Alben aus den
Regeln dazu (nur ergänzt, nie entfernt) und erscheinen im Bericht als «Duplikat, ergänzt». Ein Import lässt sich jederzeit abbrechen;
bereits importierte Dateien bleiben. Ein unterbrochener Import (z. B. Kontingent voll) lässt sich
fortsetzen.

Der **Bericht** listet jede Datei mit Ergebnis und Grund. Er bleibt erhalten, solange mindestens
eine importierte Datei existiert.
