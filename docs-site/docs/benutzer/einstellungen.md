# Einstellungen und Domains

Unter **Mandant-Einstellungen** verwaltest du die Grunddaten eures Vereins: Name und Logo, eigene
Domains, das Abo, die Echtheitsprüfung, den Datenschutz, Aufbewahrungsfristen und den Verlauf.

!!! info "Berechtigungen"
    Die Mandant-Einstellungen sehen nur Konten mit «Einstellungen verwalten» (Standardrolle:
    Admin). Siehe [Rollen & Berechtigungen](rollen.md).

## Stammdaten {#stammdaten}

Im Tab **Allgemein** stehen Name, Profilbild (Logo), Kurzname und die Vereins-ID.

- **Name**: erscheint in der App, in E-Mails und auf PDFs. Ist euer Verein durch hocX
  [verifiziert](echtheit.md#verifizierung), hebt eine Namensänderung diese Verifizierung auf:
  neue PDFs werden dann nicht mehr als «verifiziert» ausgewiesen. hocX fragt deshalb vor dem
  Speichern nach. Die Verifizierung kannst du danach unter **Echtheitsprüfung** neu beantragen.
- **Kurzname**: kurzer, eindeutiger Name aus Kleinbuchstaben, Ziffern und Bindestrichen (z. B.
  `turnverein-seedorf`). Andere Organisationen finden euch darüber, etwa wenn sie euch ein
  Fotoalbum freigeben. Links zur [Abgabebox](abgabebox.md) hängen nicht davon ab und bleiben bei
  einer Änderung gültig.
- **Vereins-ID**: technische Kennung zum Kopieren, z. B. für eine Album-Freigabe.

## Finanzen {#finanzen}

Ebenfalls im Tab **Allgemein**: die **Währung** des Vereins (z. B. «CHF», «EUR» oder «Fr.»). Sie
gilt für alle [Konten und Bussen](finanzen.md). hocX rechnet nicht um: eine Änderung ändert nur
die Bezeichnung bei allen Konten, Bussen und Exporten, die Beträge bleiben gleich.

## Eigene Domains {#domains}

Mit einer eigenen Domain ist hocX unter eurer Adresse erreichbar. Es gibt drei Zwecke:

| Zweck | Wofür | Abo-Modul |
|---|---|---|
| **hocX-App** | Die normale Oberfläche, z. B. `app.verein.ch` | Eigene Domain |
| **Abgabebox** | Die öffentliche Abgabebox, z. B. `abgabe.verein.ch` | Eigene Domain |
| **Prüfseite** | Die Echtheitsprüfung eurer PDFs, z. B. `verify.verein.ch` | Eigene Prüf-Domain |

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
    Eine Domain ohne Vorsatz wie `verein.ch` (Apex- oder Hauptdomain) kann bei vielen Anbietern
    keinen CNAME-Eintrag haben. Nimm dann eine Subdomain wie `app.verein.ch` oder setze einen
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
**Vereinsexport** mit allen Daten des Vereins.

## Aufbewahrung {#aufbewahrung}

Im Tab **Aufbewahrung** legst du Fristen fest, z. B. wann Einreichungen der Abgabebox nach dem
Abgabeschluss gelöscht oder ehemalige Mitglieder deaktiviert werden. Alle Regeln sind aus, bis du
sie einschaltest. hocX schlägt passende Einträge täglich vor; du bestätigst oder verwirfst sie.
Ehemalige Mitglieder werden nur deaktiviert, nie gelöscht.

## Verlauf {#aktivitaet}

Der Tab **Verlauf** zeigt Änderungen, Anmeldungen und Zugriffe der hocX-Plattform auf Daten eures
Vereins, filterbar nach Bereich und Ergebnis. IP- und E-Mail-Adressen werden dort nicht
angezeigt.
