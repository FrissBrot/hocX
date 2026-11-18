# Echtheit prüfen

Jedes PDF, das hocX erzeugt, wird registriert: hocX merkt sich den digitalen Fingerabdruck
(SHA-256) genau dieser Datei. Wer ein PDF erhält, kann ohne Konto prüfen, ob es unverändert aus
hocX stammt.

## Echtheit eines Dokuments prüfen

1. Den QR-Code auf der letzten Seite scannen oder die Adresse aus der Fusszeile öffnen
   (`…/verify`).
2. Die PDF-Datei auf der Prüfseite ablegen oder auswählen.
3. Das Ergebnis erscheint sofort.

**Die Datei wird nicht hochgeladen.** Der Browser berechnet den Fingerabdruck selbst und schickt
nur diesen zur Prüfung. Ist die Datei kein Original, schickt er zusätzlich die Dokument-ID und je
Seite einen Fingerabdruck des Texts (siehe unten), nie den Text selbst. hocX speichert weder
Fingerabdrücke noch IP-Adresse der Prüfung.

| Ergebnis | Bedeutung |
|---|---|
| **Original** | Die Datei ist eine unveränderte Kopie eines Dokuments aus hocX. Angezeigt werden Dokumenttyp, Titel, Status (z. B. Entwurf, Abgeschlossen), Version, Dokument-ID und Erstellungsdatum. |
| **Neuere Version vorhanden** | Nur bei Protokollen: Es gibt eine neuere Version (z. B. v1.3). Der Inhalt wird nicht gezeigt. |
| **Gehört zu einem anderen Dokument** | Die Datei ist echt, passt aber nicht zum gescannten QR-Code. |
| **Neu gespeichert – Text unverändert** | Kein Original, aber die Datei gehört zu einem hocX-Dokument, und der Text aller Seiten stimmt überein. Typisch nach «Drucken als PDF» oder Speichern auf dem Handy. |
| **Verändert** | Die Datei gehört zu einem hocX-Dokument, aber die genannten Seiten (oder die Seitenzahl) weichen vom Original ab. |
| **Nicht gefunden** | Die Datei stammt nicht aus hocX oder enthält keine lesbare Dokument-ID. |

!!! warning "Nur die Originaldatei ist «Original»"
    Erneutes Speichern, «Drucken als PDF», Komprimieren oder das Ausfüllen von Formularfeldern
    verändert die Datei, auch wenn der Inhalt gleich aussieht. Die Prüfseite ordnet solche Dateien
    über die Dokument-ID zu und vergleicht Seite für Seite den Text. Gleicher Text bestätigt die
    Echtheit aber nicht: Das Aussehen kann trotzdem verändert sein. Als Original gilt nur die
    unveränderte Datei.

## Seitenvergleich bei veränderten Dateien {#seitenvergleich}

- Beim Erstellen eines PDFs speichert hocX je Seite einen Fingerabdruck des Texts: einen kurzen,
  mit der Dokument-ID gesalzenen Hash. Text und PDF werden dafür nicht gespeichert.
- Auf der Prüfseite liest der Browser die Dokument-ID (aus den Metadaten oder dem Link des
  QR-Codes) und berechnet dieselben Fingerabdrücke. Der Server antwortet nur mit «stimmt» oder
  «stimmt nicht» je Seite.
- Verglichen werden Buchstaben und Ziffern in ihrer Reihenfolge. Leerzeichen, Zeilenumbrüche und
  Satzzeichen zählen nicht, weil Programme sie beim Neuspeichern unterschiedlich setzen.
- Ohne Freigabe von Name und Logo zeigt die Prüfseite bei veränderten Dateien keinen Titel.
- PDFs, die vor Version 1.4.0 erstellt wurden, haben keine Seiten-Fingerabdrücke. Für sie zeigt die
  Prüfseite nur, zu welchem Dokument die Datei gehört und dass sie verändert wurde.

Die Prüfseite funktioniert auch auf der eigenen Abgabebox-Adresse einer Organisation und auf seiner
eigenen Prüf-Domain (siehe unten).

## Name und Logo auf der Prüfseite anzeigen

Unter **Mandanten-Einstellungen → Echtheitsprüfung** (nur Administratorinnen und Administratoren):

- **Name und Logo auf der Prüfseite anzeigen** (Standard: aus). Ausgeschaltet zeigt die Prüfseite
  nur, dass das Dokument unverändert aus hocX stammt – nicht, von welcher Organisation.
- **Auf neuere Versionen hinweisen** (Standard: an). Gilt für Protokolle.
- Eine **Vorschau** zeigt, wie das Ergebnis aussieht, und **Prüfseite öffnen** führt direkt hin.

Welche Angaben im PDF selbst stehen (Prüfadresse, Dokument-ID, QR-Code), legt das Corporate Design fest:
**Dokument-Studio → Corporate Design**, Abschnitt «Echtheitsprüfung».

## Verifizierte Organisation {#verifizierung}

hocX kann bestätigen, dass ein Konto wirklich zu einer Organisation gehört. Auf der Prüfseite
erscheint dann das Abzeichen **«Verifizierte Organisation»** – aber nur, wenn Name und Logo
angezeigt werden. Ohne Verifizierung steht dort «Erstellt im hocX-Konto von …».

1. Unter **Mandanten-Einstellungen → Echtheitsprüfung** auf **Verifizierung beantragen** klicken, optional mit
   einer Nachricht (z. B. Eintrag im Handelsregister, Website, Statuten).
2. hocX prüft den Antrag und bestätigt oder lehnt ihn mit Begründung ab. Der Stand ist auf
   derselben Seite sichtbar; ein offener Antrag lässt sich zurückziehen.

Bestätigt wird der Name zum Zeitpunkt des Antrags. **Ändert sich der Name der Organisation, wird die
Verifizierung automatisch aufgehoben** und kann neu beantragt werden. Ein neues Logo ändert nichts.

## Eigene Prüf-Domain {#pruef-domain}

Mit der Zusatzfunktion **«Eigene Prüf-Domain»** prüfen Empfänger Dokumente einer Organisation unter
dessen eigener Adresse, zum Beispiel `verify.muster-organisation.ch`. So sieht jede Person, dass ein
bestätigtes Dokument mit dieser Domain in Verbindung steht. Die Funktion wird von hocX separat
freigeschaltet, unabhängig von eigenen Domains für die App oder die Abgabebox.

**Einrichten** (Administratorinnen und Administratoren):

1. Unter **[Mandanten-Einstellungen → Domains](einstellungen.md#domains)** auf **Domain hinzufügen** klicken, den Zweck
   **Prüfseite** wählen und die Domain eingeben. Der Name ist frei wählbar, `verify.` ist üblich.
2. Die beiden angezeigten DNS-Einträge beim Domain-Anbieter setzen (TXT-Eintrag als
   Besitznachweis, CNAME auf die Abgabebox-Adresse von hocX) und **Jetzt prüfen** klicken.
3. Unter **Mandanten-Einstellungen → Echtheitsprüfung** muss **Name und Logo auf der Prüfseite
   anzeigen** eingeschaltet sein. Der Abschnitt «Eigene Prüf-Domain» zeigt, ob die Domain verwendet
   wird.

**Was sich ändert, sobald die Prüf-Domain aktiv ist:**

- **Neue PDFs** tragen die eigene Prüf-Domain in Fusszeile, QR-Code und Metadaten. Bereits
  erstellte PDFs behalten ihren bisherigen Prüf-Link und bleiben prüfbar.
- **Weiterleitung:** Wer ein Dokument der Organisation auf der Prüfseite von hocX prüft, wird nach
  wenigen Sekunden auf die Prüfseite der Organisation weitergeleitet («Hier bleiben» bricht ab). Die
  Datei muss dort nicht erneut ausgewählt werden: Der Fingerabdruck reist im Teil der Adresse nach
  `#` mit, den der Browser nie an einen Server schickt.
- **Fremde Dokumente:** Wird auf der Prüfseite einer Organisation ein Dokument eines anderen Organisation
  geprüft, steht das deutlich da, und es geht weiter zu dessen Prüf-Domain bzw. zur Prüfseite von
  hocX.
- Die Prüfseite der Organisation zeigt oben Logo und Name. Seine eigenen Dokumente erhalten die Stufe
  **«Prüf-Domain verifiziert»**.

**Stufen auf der Prüfseite** (von schwach nach stark):

| Stufe | Bedeutung |
|---|---|
| **Original** | Die Datei ist unverändert aus hocX. |
| **Prüf-Domain verifiziert** | Die Domain ist per DNS-Eintrag mit dem hocX-Konto der Organisation verbunden. Das belegt nicht, dass das Konto wirklich zur Organisation gehört – eine Domain kann jeder registrieren. |
| **Verifizierte Organisation** | hocX hat bestätigt, dass das Konto zur Organisation gehört (siehe oben). |

!!! info "Wann die Prüf-Domain nicht verwendet wird"
    Neue PDFs und die Weiterleitung nutzen wieder die Prüfseite von hocX, solange Name und Logo
    ausgeblendet sind, die Domain im DNS nicht mehr auf hocX zeigt oder die Zusatzfunktion nicht
    mehr gebucht ist. Gibt die Organisation die Domain ganz auf, funktionieren QR-Codes bereits
    verteilter PDFs nicht mehr. Die Datei bleibt dann aber auf der Prüfseite von hocX prüfbar.
