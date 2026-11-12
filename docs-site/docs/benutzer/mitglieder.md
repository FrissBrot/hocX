# Mitglieder & Logins

In hocX gibt es für jede Person genau **einen Datensatz** – egal ob sie sich anmelden kann oder
nicht. Daraus ergeben sich drei Begriffe:

| Begriff | Bedeutung | Wo gepflegt |
|---|---|---|
| **Mitglied** | Jede Person deines Vereins (auch Gäste). Erscheint in Anwesenheit, Bussen und als Verantwortliche bei Aufgaben. | **Mitglieder** |
| **Login** | Die Möglichkeit eines Mitglieds, sich mit E-Mail und Passwort anzumelden. Ein Mitglied hat einen Login oder nicht. | **Logins & Rollen** oder beim Mitglied |
| **Rolle** | Was jemand mit Login darf (siehe [Rollen & Berechtigungen](rollen.md)). | **Logins & Rollen** |

Bekommt ein Mitglied einen Login, bleibt es derselbe Datensatz: Anwesenheit, Bussen und
Aufgaben bleiben erhalten. Wird der Login entzogen, bleibt das Mitglied ebenfalls bestehen.

!!! info "Berechtigungen"
    Mitglieder pflegen braucht «Teilnehmende verwalten». Logins vergeben, entziehen und Rollen
    zuweisen braucht zusätzlich «Benutzer & Rollen verwalten». Konten, die mehr Rechte haben als
    du selbst, kannst du nicht verwalten.

## Mitglied erfassen und bearbeiten {#erfassen}

**Mitglieder** → **Neues Mitglied** oder eine Zeile anklicken. Nur der **Anzeigename** ist
Pflicht. Vor- und Nachname sowie die E-Mail-Adresse sind freiwillig; die E-Mail braucht es
aber für eine Einladung und für E-Mail-Benachrichtigungen.

Unter **Vorlagen** wählst du, zu welchen Sitzungsvorlagen die Person gehört (zum Beispiel
«Vorstandssitzung»). Sie erscheint dann in deren Anwesenheitslisten.

Ist **Speichern** ausgegraut, steht daneben, was noch fehlt.

## Mitgliedschaft: Eintritt und Austritt {#mitgliedschaft}

- **Eintrittsdatum**: Die Person erscheint erst ab diesem Tag in Anwesenheitslisten.
- **Austrittsdatum**: Am Austrittstag ist sie noch Mitglied, ab dem Folgetag erscheint sie nicht
  mehr in Anwesenheitslisten. Frühere Protokolle, Bussen und Aufgaben bleiben unverändert.
- **Aktiv / Inaktiv**: kennzeichnet, ob die Person noch dabei ist. Wird ein Mitglied mit Login
  auf Inaktiv gesetzt, kann es sich nicht mehr anmelden und alle seine Sitzungen enden sofort.

Die Filter über der Liste (Aktiv, Inaktiv, Ausgetreten) nutzen diese Angaben. Für ausgetretene
Mitglieder ist ein Austrittsdatum besser als Löschen: die Geschichte bleibt vollständig.

## Login vergeben {#login}

Am einfachsten per [Einladung](#einladung). Alternativ setzt die Verwaltung ein Passwort selbst
(mindestens 12 Zeichen) und teilt es der Person sicher mit; die Person kann es danach im Profil
ändern (siehe [Konto & Anmeldung](konto.md#passwort-aendern)).

- Unter **Logins & Rollen** → Reiter **Ohne Login** → **Login aktivieren**, oder
- beim Mitglied selbst (nur mit «Benutzer & Rollen verwalten»).

Jede Login-E-Mail-Adresse darf auf der ganzen Plattform nur einmal vorkommen. Als
Kontaktadresse ohne Login darf dieselbe Adresse mehrfach stehen (zum Beispiel bei Geschwistern).

Neue Logins bekommen die Rolle «Leser». Weitere Rollen vergibst du unter **Logins & Rollen**
beim Konto. Je nach Abo ist die Zahl der Logins begrenzt.

## Einladung per E-Mail {#einladung}

Bei der Einladung bekommt die Person einen Link per E-Mail und legt ihr Passwort selbst fest.
Der Login wird erst aktiv, wenn sie die Einladung annimmt.

- **Mitglieder** → Person öffnen → **Per E-Mail einladen**, oder beim Erfassen
  **Nach dem Erfassen per E-Mail einladen** ankreuzen, oder
- **Logins & Rollen** → **Ohne Login** → **Login aktivieren** → **Per E-Mail einladen**.

Die Einladung geht an die gespeicherte E-Mail-Adresse. Hast du die Adresse gerade geändert,
zuerst speichern. Der Link gilt 7 Tage; offene Einladungen sind in der Liste mit «Eingeladen»
markiert und lassen sich **erneut senden** oder **zurückziehen**. Ändert sich die E-Mail-Adresse
oder wird die Person inaktiv, verfällt die Einladung.

Ist der E-Mail-Versand der Plattform nicht eingerichtet, sind Einladungen nicht möglich; hocX
zeigt dann einen Hinweis, und du setzt das Passwort selbst.

## Login entziehen {#login-entziehen}

**Logins & Rollen** → Reiter **Mit Login** → **Login entziehen**. Die Person kann sich danach
nicht mehr anmelden, laufende Sitzungen enden sofort. Als Mitglied bleibt sie mit allen Daten
erhalten. Der letzte Login mit «Benutzer & Rollen verwalten» lässt sich nicht entziehen.

## Mitglieder importieren (CSV) {#import}

**Mitglieder** → **CSV-Import** → Datei wählen. Vor dem Import zeigt hocX eine Vorschau.

Erkannte Spalten (erste Zeile, Gross-/Kleinschreibung egal; Trennzeichen Semikolon oder Komma):

| Inhalt | Spaltenname |
|---|---|
| Vorname | `Vorname` (oder `First name`) |
| Nachname | `Nachname` (oder `Last name`) |
| Anzeigename | `Übername` oder `Anzeigename` (oder `Display name`, `Name`) |
| Firma | `Firmenname` oder `Firma` |
| E-Mail | `Haupt-E-Mail` oder `E-Mail` (oder `Email`, `Mail`) |

Der Anzeigename ist der Übername, sonst «Vorname Nachname», sonst der Firmenname. Zeilen ohne
Namen werden übersprungen. Über **Vorlage herunterladen** bekommst du eine passende Datei.

- **Duplikate**: Personen mit gleichem Anzeigenamen oder gleicher E-Mail-Adresse wie ein
  bestehendes Mitglied werden nicht doppelt angelegt, sondern als «übersprungen» gemeldet.
  Du kannst dieselbe Liste deshalb gefahrlos erneut importieren.
- Wird keine Person oder keine E-Mail-Spalte erkannt, warnt die Vorschau; ohne erkannte Person
  bleibt der Import gesperrt.
- Importierte Personen sind aktiv, haben keinen Login und die Rolle «Leser».

## Löschen {#loeschen}

**Löschen** (im Aktionsmenü einer Zeile oder für mehrere markierte) entfernt die Person
**endgültig** – mit Login, Anwesenheit, Bussen und Aufgaben-Zuordnungen. hocX fragt vorher nach.
Meist ist etwas anderes gemeint:

- Person ist ausgetreten → **Austrittsdatum** setzen.
- Person soll sich nicht mehr anmelden → **Login entziehen**.
- Person macht vorübergehend nicht mit → **Inaktiv**.

Das eigene Konto und den letzten Administrator kann man nicht löschen.

## Datenauskunft {#datenauskunft}

Mit der Berechtigung «Datenexporte» erstellst du für eine Person eine Auskunft über alle in
hocX gespeicherten Daten: Aktionsmenü der Zeile → **Datenauskunft**. Die ZIP-Datei ist
passwortgeschützt, der Abruf wird protokolliert. Jede Person kann ihre eigenen Daten selbst im
Profil herunterladen.
