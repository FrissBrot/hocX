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
nur diesen zur Prüfung. hocX speichert weder Fingerabdruck noch IP-Adresse der Prüfung.

| Ergebnis | Bedeutung |
|---|---|
| **Original** | Die Datei ist eine unveränderte Kopie eines Dokuments aus hocX. Angezeigt werden Dokumenttyp, Titel, Status (z. B. Entwurf, Abgeschlossen), Version, Dokument-ID und Erstellungsdatum. |
| **Neuere Version vorhanden** | Nur bei Protokollen: Es gibt eine neuere Version (z. B. v1.3). Der Inhalt wird nicht gezeigt. |
| **Gehört zu einem anderen Dokument** | Die Datei ist echt, passt aber nicht zum gescannten QR-Code. |
| **Nicht gefunden** | Die Datei wurde verändert oder stammt nicht aus hocX. |

!!! warning "Schon kleine Änderungen zählen"
    Erneutes Speichern, «Drucken als PDF», Komprimieren oder das Ausfüllen von Formularfeldern
    verändert die Datei, auch wenn der Inhalt gleich aussieht. Geprüft werden kann nur die
    ursprünglich erhaltene Datei.

Die Prüfseite funktioniert auch auf der eigenen Abgabebox-Adresse eines Vereins.

## Name und Logo auf der Prüfseite anzeigen

Unter **Vorlagen → Echtheitsprüfung** (nur Administratorinnen und Administratoren):

- **Name und Logo auf der Prüfseite anzeigen** (Standard: aus). Ausgeschaltet zeigt die Prüfseite
  nur, dass das Dokument unverändert aus hocX stammt – nicht, von welchem Verein.
- **Auf neuere Versionen hinweisen** (Standard: an). Gilt für Protokolle.
- Eine **Vorschau** zeigt, wie das Ergebnis aussieht, und **Prüfseite öffnen** führt direkt hin.

Welche Angaben im PDF selbst stehen (Prüfadresse, Dokument-ID, QR-Code), legt der Hausstil fest:
**Vorlagen → Hausstile**, Abschnitt «Echtheitsprüfung im Dokument».

## Verifizierte Organisation

hocX kann bestätigen, dass ein Konto wirklich zu einer Organisation gehört. Auf der Prüfseite
erscheint dann das Abzeichen **«Verifizierte Organisation»** – aber nur, wenn Name und Logo
angezeigt werden. Ohne Verifizierung steht dort «Erstellt im hocX-Konto von …».

1. Unter **Vorlagen → Echtheitsprüfung** auf **Verifizierung beantragen** klicken, optional mit
   einer Nachricht (z. B. Eintrag im Handelsregister, Website, Statuten).
2. hocX prüft den Antrag und bestätigt oder lehnt ihn mit Begründung ab. Der Stand ist auf
   derselben Seite sichtbar; ein offener Antrag lässt sich zurückziehen.

Bestätigt wird der Name zum Zeitpunkt des Antrags. **Ändert sich der Name des Vereins, wird die
Verifizierung automatisch aufgehoben** und kann neu beantragt werden. Ein neues Logo ändert nichts.
