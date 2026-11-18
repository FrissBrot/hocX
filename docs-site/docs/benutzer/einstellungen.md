# Einstellungen und Domains

Unter **Organisation** in der Seitenleiste verwaltest du die Grunddaten eurer Organisation: Name und Logo, eigene
Domains, das Abo, die Echtheitsprüfung, den Datenschutz, die Zugangslinks, Aufbewahrungsfristen und den Verlauf.

!!! info "Berechtigungen"
    Den Bereich «Organisation» und die Einstellung «Domains & Echtheit» sehen nur Konten mit «Einstellungen verwalten» (Standardrolle:
    Admin). Siehe [Rollen & Berechtigungen](rollen.md).

## Profil {#stammdaten}

Unter **Organisation › Profil** stehen Name, Profilbild (Logo), Kurzname und die Organisations-ID.

- **Name**: erscheint in der App, in E-Mails und auf PDFs. Ist eure Organisation durch hocX
  [verifiziert](echtheit.md#verifizierung), hebt eine Namensänderung diese Verifizierung auf:
  neue PDFs werden dann nicht mehr als «verifiziert» ausgewiesen. hocX fragt deshalb vor dem
  Speichern nach. Die Verifizierung kannst du danach unter **Echtheitsprüfung** neu beantragen.
- **Kurzname**: kurzer, eindeutiger Name aus Kleinbuchstaben, Ziffern und Bindestrichen (z. B.
  `muster-organisation`). Andere Organisationen finden euch darüber, etwa wenn sie euch ein
  Fotoalbum freigeben. Links zur [Abgabebox](abgabebox.md) hängen nicht davon ab und bleiben bei
  einer Änderung gültig.
- **Organisations-ID**: technische Kennung zum Kopieren, z. B. für eine Album-Freigabe.

## Finanzen {#finanzen}

Ebenfalls im Tab **Allgemein**: die **Währung** der Organisation (z. B. «CHF», «EUR» oder «Fr.»). Sie
gilt für alle [Konten und Bussen](finanzen.md). hocX rechnet nicht um: eine Änderung ändert nur
die Bezeichnung bei allen Konten, Bussen und Exporten, die Beträge bleiben gleich.

## Eigene Domains {#domains}

Mit einer eigenen Domain ist hocX unter eurer Adresse erreichbar. Es gibt drei Zwecke:

| Zweck | Wofür | Abo-Modul |
|---|---|---|
| **hocX-App** | Die normale Oberfläche, z. B. `app.example.ch` | Eigene Domain |
| **Abgabebox** | Die öffentliche Abgabebox, z. B. `abgabe.example.ch` | Eigene Domain |
| **Prüfseite** | Die Echtheitsprüfung eurer PDFs, z. B. `verify.example.ch` | Eigene Prüf-Domain |

Die Standard-Adressen von hocX bleiben immer zusätzlich erreichbar.

### Domain einrichten

1. Im Tab **Domains** auf **Domain hinzufügen** klicken, den Zweck wählen und die Domain ohne
   `https://` eintragen.
2. hocX zeigt zwei DNS-Einträge. Trage sie bei deinem Domain-Anbieter ein (dort, wo die Domain
   registriert ist):
    - **TXT-Eintrag (Besitznachweis)**: beweist, dass euch die Domain gehört. Name und Wert genau
      so übernehmen, wie hocX sie anzeigt.
    - **CNAME-Eintrag (Weiterleitung)**: leitet die Adresse auf hocX um. Ziel ist der angezeigte
      Ziel-Host.
3. Auf **Jetzt verifizieren** klicken. Klappt es, ist die Domain aktiv. hocX holt das
   HTTPS-Zertifikat automatisch; das kann nach der Aktivierung noch ein bis zwei Minuten dauern.

!!! tip "Hauptdomain ohne Vorsatz"
    Eine Domain ohne Vorsatz wie `example.ch` (Apex- oder Hauptdomain) kann bei vielen Anbietern
    keinen CNAME-Eintrag haben. Nimm dann eine Subdomain wie `app.example.ch` oder setze einen
    A-Eintrag auf dieselbe IP-Adresse wie der Ziel-Host.

### Wartezeit und Prüfungen

Neue DNS-Einträge brauchen oft einige Minuten, manchmal bis zu einigen Stunden, bis sie überall
sichtbar sind. Klicke erst auf **Jetzt verifizieren**, wenn beide Einträge gesetzt sind. Pro
Stunde sind 20 Prüfungen möglich; danach meldet hocX, dass du kurz warten sollst. Mit **Später
fertigstellen** schliesst du den Assistenten, die Domain bleibt als «Ausstehend» in der Liste und
lässt sich über **Einrichten** jederzeit fortsetzen.

Die Fehlermeldungen sagen, was fehlt:

- *TXT-Eintrag nicht gefunden*: Name oder Wert stimmen nicht, oder die Änderung ist noch nicht
  verbreitet.
- *Domain zeigt noch nicht auf hocX*: Der CNAME- bzw. A-Eintrag fehlt oder zeigt woanders hin.

### Domain ersetzen

Pro Zweck gibt es genau eine aktive Domain. Trägst du für denselben Zweck eine neue Domain ein,
bleibt die bisherige **unverändert aktiv**, bis die neue erfolgreich geprüft ist. Erst dann
ersetzt hocX die alte Domain. Ein Tippfehler legt so nie eure laufende Adresse lahm: Die neue
Domain steht bis dahin als «Ausstehend – ersetzt …» in der Liste und lässt sich einfach wieder
löschen.

### Status «Nicht erreichbar»

hocX prüft aktive Domains regelmässig. Zeigt eine Domain nicht mehr auf hocX (z. B. weil der
DNS-Eintrag geändert wurde) oder ist das Modul nicht mehr im Abo, erscheint sie als **Nicht
erreichbar**. Über **Erneut prüfen** öffnest du die DNS-Ansicht mit den nötigen Einträgen und
prüfst nach der Korrektur erneut.

### Domain löschen

Über das Menü einer Domain lässt sie sich löschen. Bei einer aktiven Domain endet der Zugriff über
diese Adresse sofort; die Standard-Adressen bleiben erreichbar.

## Abo & Nutzung {#abo}

Der Tab **Abo & Nutzung** zeigt euren Plan, die Abrechnung, Benutzer und Speicher.

- **Plan und Kosten**: Plan, Abrechnungsintervall und die geschätzten Kosten inklusive Rabatt.
  Plan ändern oder Module dazubuchen könnt ihr nicht selbst: Wendet euch an den Betreiber eurer
  hocX-Instanz.
- **Module**: «Aktiv» heisst voll nutzbar. **Nur lesen** heisst: Das Modul ist nach einem
  Planwechsel nicht mehr im Abo, eure Daten bleiben aber erhalten und lesbar; ändern ist
  gesperrt, bis das Modul wieder gebucht ist. Eigene Domains fallen bei einem Downgrade weg.
- **Benutzer**: Zahl der aktiven Konten mit Login im Verhältnis zum Limit des Plans.
- **Speicher**: belegter Speicher und Kontingent (Plan plus zugebuchte Speicherpakete). Ist das
  Kontingent voll, lehnen Uploads und die Abgabebox weitere Dateien mit einem Hinweis ab.
- **Abrechnung**: Forderungen je Abrechnungsperiode mit Status (offen, überfällig, bezahlt,
  erlassen). Zahlbar innert 30 Tagen ab Periodenbeginn.

## Echtheitsprüfung {#echtheit}

Wie PDFs geprüft werden, wie ihr Name und Logo auf der Prüfseite zeigt und wie die Verifizierung
durch hocX funktioniert, steht unter [Echtheit prüfen](echtheit.md).

## Datenschutz {#datenschutz}

Im Tab **Datenschutz** legst du fest, wer welche Personendaten sieht (z. B. ob Bussen und
Anwesenheit je Person in der Statistik für alle sichtbar sind), und erstellst den
**Gesamtexport** mit allen Daten der Organisation.

## Zugangslinks {#zugangslinks}

Der Tab **Zugangslinks** zeigt alles, worüber jemand **ohne Anmeldung** an Daten eurer Organisation kommt:

| Art | Was der Link erlaubt | Läuft ab |
|---|---|---|
| Dateien, Album | Freigabelink: Dateien oder ein Album ansehen und herunterladen | am gewählten Datum oder nie |
| Album · Partner-Link | ein Partner-Organisation hat auf euer geteiltes Album einen öffentlichen Link erstellt | wie beim Partner eingestellt |
| Abgabebox | Dateien für die verknüpften Abgaben hochladen | solange die Abgaben offen sind |
| Kalender | Kalender-Abo (Termine oder Aufgaben) einer Person in ihrer Kalender-App | nie (die Person kann den Link neu erzeugen) |
| Einladung, Passwort | Einmal-Link aus einer E-Mail, um ein Konto einzurichten oder das Passwort neu zu setzen | nach Gebrauch oder nach 7 Tagen bzw. 60 Minuten |
| Partner-Organisation | ein Album ist mit einer anderen Organisation geteilt | bis die Freigabe aufgehoben wird |

Abgelaufene, widerrufene und benutzte Links erscheinen nicht. Über **Verwalten** gelangst du zur
Seite, auf der du den Link änderst oder widerrufst. Links, die nie ablaufen, sind orange markiert:
prüfe ab und zu, ob sie noch gebraucht werden. Kommt in hocX eine neue Art von Link dazu, erscheint
sie hier automatisch. Den Tab sehen nur Personen mit dem Recht, die Einstellungen der Organisation zu verwalten.

## Aufbewahrung {#aufbewahrung}

Im Tab **Aufbewahrung** legst du Fristen fest, z. B. wann Einreichungen der Abgabebox nach dem
Abgabeschluss gelöscht oder ehemalige Mitglieder deaktiviert werden. Alle Regeln sind aus, bis du
sie einschaltest. hocX schlägt passende Einträge täglich vor; du bestätigst oder verwirfst sie.
Ehemalige Mitglieder werden nur deaktiviert, nie gelöscht.

## Verlauf {#aktivitaet}

Der Tab **Verlauf** zeigt Änderungen, Anmeldungen und Zugriffe der hocX-Plattform auf Daten eurer
Organisation, filterbar nach Bereich und Ergebnis. IP- und E-Mail-Adressen werden dort nicht
angezeigt.
