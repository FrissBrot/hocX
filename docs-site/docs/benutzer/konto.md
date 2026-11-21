# Konto & Anmeldung

Jede Person mit **Login** hat ein Konto bei genau einer Organisation. Wer in mehreren Organisationen
mitarbeitet, braucht pro Organisation ein eigenes Konto mit eigener E-Mail-Adresse (siehe
[Rollen & Berechtigungen](rollen.md)).

## Anmelden {#anmelden}

1. Öffne die Adresse deiner Organisation und gib **E-Mail** und **Passwort** ein.
2. Hat dein Konto einen zweiten Faktor (oder verlangt deine Rolle einen), bestätigst du danach
   mit einem Code aus der Authenticator-App oder mit einem Passkey. Siehe [Zweiter Faktor](#mfa).

Klappt die Anmeldung nicht:

- **«E-Mail oder Passwort ist ungültig»**: Tippfehler prüfen, sonst
  [Passwort vergessen](#passwort-vergessen).
- Nach mehreren Fehlversuchen sperrt hocX die Anmeldung für dieses Konto kurz. Warte ein paar
  Minuten und versuche es dann erneut.
- Ist dein Konto inaktiv oder wurde dir der Login entzogen, kannst du dich nicht anmelden. Wende
  dich an die Verwaltung deiner Organisation.

## Konto einrichten (Einladung) {#einladung}

Meist richtet die Verwaltung deinen Login per **Einladung** ein. Du bekommst eine E-Mail mit
einem Link, öffnest ihn und legst dein Passwort selbst fest (mindestens 12 Zeichen). Danach
kannst du dich anmelden.

Der Link gilt 7 Tage und nur einmal. Ist er abgelaufen, bitte deine Organisation um eine neue
Einladung – «Passwort vergessen» hilft hier nicht, weil dein Konto noch keinen Login hat.

## Passwort vergessen {#passwort-vergessen}

1. Auf der Anmeldeseite **Passwort vergessen?** wählen und deine E-Mail-Adresse eingeben.
2. Hat diese Adresse ein Konto mit Login, kommt eine E-Mail mit einem Link. Er gilt 60 Minuten
   und nur einmal.
3. Neues Passwort festlegen. Danach sind alle bisherigen Sitzungen beendet.

Aus Datenschutzgründen zeigt hocX nicht an, ob es zu einer Adresse ein Konto gibt. Kommt keine
Mail, prüfe den Spam-Ordner oder frag die Verwaltung. Der Link «Passwort vergessen» erscheint nur,
wenn der E-Mail-Versand eingerichtet ist; sonst setzt die Verwaltung ein neues Passwort.

## Passwort ändern {#passwort-aendern}

**Profil** (oben rechts) → Reiter **Sicherheit** → **Passwort ändern**: aktuelles Passwort und
zweimal das neue (mindestens 12 Zeichen) eingeben.

Du bleibst auf dem aktuellen Gerät angemeldet; alle anderen Sitzungen (zum Beispiel auf dem
Handy) werden beendet. Du bekommst einen Sicherheitshinweis per E-Mail.

## Passwortregel {#passwortregel}

Ein neues Passwort braucht mindestens 12 Zeichen und darf nicht leicht zu erraten sein (kein Name,
keine E-Mail-Adresse, keine häufigen Wörter). Zusätzlich lehnt hocX Passwörter ab, die aus einem
bekannten **Datenleck** stammen («Dieses Passwort ist aus einem Datenleck bekannt»), auch wenn sie
sonst stark aussehen – solche Passwörter probieren Angreifer zuerst. Wähle dann ein anderes, am besten
eine Passphrase aus mehreren Wörtern oder ein Passwort aus einem Passwort-Manager.

**Datenschutz:** Dein Passwort verlässt den Server nie. hocX berechnet einen Hash (SHA-1) und schickt
nur dessen **erste 5 Zeichen** an den Dienst «Have I Been Pwned» (Pwned Passwords, k-Anonymität). Der
Dienst antwortet mit allen bekannten Einträgen, die so beginnen, ergänzt um Fülleinträge; verglichen
wird nur auf dem Server. Ist der Dienst nicht erreichbar, prüft hocX gegen eine Liste häufiger
geleakter Passwörter, die auf dem Server liegt. Geprüft wird nur beim Festlegen eines neuen
Passworts, nicht bei jeder Anmeldung.

## Zweiter Faktor (MFA) {#mfa}

Ein zweiter Faktor schützt dein Konto, auch wenn jemand dein Passwort kennt. Pflicht ist er, wenn
du eine Administrationsberechtigung hast, eine deiner Rollen MFA verlangt oder deine Organisation
MFA für alle Logins verlangt. Einrichten unter **Profil** → **Sicherheit**:

- **Authenticator-App** (z. B. eine App für Einmalcodes): QR-Code scannen und den 6-stelligen
  Code bestätigen.
- **Passkey**: Anmeldung per Fingerabdruck, Gesichtserkennung oder Sicherheitsschlüssel. Passkeys
  lassen sich nur auf der Hauptadresse von hocX hinzufügen.

Du kannst mehrere Faktoren einrichten und einen als Standard wählen. Ist ein zweiter Faktor
Pflicht, lässt sich der letzte nicht entfernen.

**Frist von 3 Tagen:** Wird der zweite Faktor für dein bestehendes Konto neu Pflicht (über eine
Rolle oder die Organisation), hast du 3 Tage Zeit. Bis dahin erscheint die Einrichtung bei jeder
Anmeldung mit «Später einrichten», und in der App erinnert ein Hinweis mit dem Enddatum. Danach
geht die Anmeldung nur noch mit zweitem Faktor. Keine Frist gibt es bei Administrationsrechten und
für neue Konten: Sie richten den Faktor gleich bei der ersten Anmeldung ein.

## Zweiten Faktor verloren {#verlust}

hocX hat keine Wiederherstellungscodes. Hast du dein Gerät verloren:

1. Wenn möglich, mit einem anderen eingerichteten Faktor anmelden (zum Beispiel Passkey statt App).
2. Sonst eine Person mit «Benutzer & Rollen verwalten» bitten, deinen zweiten Faktor
   zurückzusetzen: **Zugriff** → bei dir **MFA** → Faktor entfernen.
3. Danach anmelden und einen neuen Faktor einrichten.

Jede Änderung am zweiten Faktor meldet hocX dir per E-Mail.

## Wann endet eine Sitzung? {#sitzungen}

Alle Sitzungen eines Kontos enden sofort, wenn

- das Passwort geändert oder zurückgesetzt wird (die Sitzung, in der du es selbst änderst, bleibt),
- die Verwaltung das Konto auf **Inaktiv** setzt oder den **Login entzieht**.

Rechteänderungen (andere Rollen) wirken sofort, ohne neue Anmeldung.

## Angemeldete Geräte und Land {#geraete}

Unter **Profil** → **Sicherheit** → **Angemeldete Geräte** siehst du deine aktiven Sitzungen und
bekannten Geräte mit grober Gerätebeschreibung («Firefox · Windows») und – falls eingerichtet – dem
**Land** der Anmeldung. Hinweis-Mails zu einer Anmeldung von einem neuen Gerät oder mit erhöhtem
Risiko nennen ebenfalls das Land.

**Datenschutz:** Das Land ermittelt der Server selbst aus der IP-Adresse, mit der Datenbank
«IP to Country Lite» von [DB-IP.com](https://db-ip.com) (Lizenz CC BY 4.0), die auf dem Server liegt –
es geht keine Anfrage an einen fremden Dienst. Gespeichert wird nur das Land, nie die IP-Adresse, und
nur so lange wie die übrigen Anmeldeereignisse (90 Tage) bzw. die Sitzung oder das Gerät. Zweck ist
allein die Sicherheit deines Kontos (berechtigtes Interesse): Eine erfolgreiche Anmeldung aus einem
Land, aus dem du dich in den letzten 90 Tagen nie angemeldet hast, erhöht die Risikobewertung leicht.
Allein führt das nie zu einer Sperre; zusammen mit anderen Auffälligkeiten (neues Gerät, neues Netz)
kann hocX einen zweiten Faktor oder einen Bestätigungscode per E-Mail verlangen.

## Eigene Daten herunterladen {#daten}

Unter **Profil** → **Daten** lädst du alle Daten, die hocX über dich speichert, als
passwortgeschützte ZIP-Datei herunter.
