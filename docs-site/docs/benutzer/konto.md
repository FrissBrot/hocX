# Konto & Anmeldung

Jede Person mit **Login** hat ein Konto bei genau einem Verein. Wer in mehreren Vereinen
mitarbeitet, braucht pro Verein ein eigenes Konto mit eigener E-Mail-Adresse (siehe
[Rollen & Berechtigungen](rollen.md)).

## Anmelden {#anmelden}

1. Öffne die Adresse deines Vereins und gib **E-Mail** und **Passwort** ein.
2. Hat dein Konto einen zweiten Faktor (oder verlangt deine Rolle einen), bestätigst du danach
   mit einem Code aus der Authenticator-App oder mit einem Passkey. Siehe [Zweiter Faktor](#mfa).

Klappt die Anmeldung nicht:

- **«E-Mail oder Passwort ist ungültig»**: Tippfehler prüfen, sonst
  [Passwort vergessen](#passwort-vergessen).
- Nach mehreren Fehlversuchen sperrt hocX die Anmeldung für dieses Konto kurz. Warte ein paar
  Minuten und versuche es dann erneut.
- Ist dein Konto inaktiv oder wurde dir der Login entzogen, kannst du dich nicht anmelden. Wende
  dich an die Verwaltung deines Vereins.

## Konto einrichten (Einladung) {#einladung}

Meist richtet die Verwaltung deinen Login per **Einladung** ein. Du bekommst eine E-Mail mit
einem Link, öffnest ihn und legst dein Passwort selbst fest (mindestens 12 Zeichen). Danach
kannst du dich anmelden.

Der Link gilt 7 Tage und nur einmal. Ist er abgelaufen, bitte deinen Verein um eine neue
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

## Zweiter Faktor (MFA) {#mfa}

Ein zweiter Faktor schützt dein Konto, auch wenn jemand dein Passwort kennt. Wer eine
Administrationsberechtigung hat, muss einen einrichten. Einrichten unter **Profil** →
**Sicherheit**:

- **Authenticator-App** (z. B. eine App für Einmalcodes): QR-Code scannen und den 6-stelligen
  Code bestätigen.
- **Passkey**: Anmeldung per Fingerabdruck, Gesichtserkennung oder Sicherheitsschlüssel. Passkeys
  lassen sich nur auf der Hauptadresse von hocX hinzufügen.

Du kannst mehrere Faktoren einrichten und einen als Standard wählen. Ist ein zweiter Faktor
Pflicht, lässt sich der letzte nicht entfernen.

## Zweiten Faktor verloren {#verlust}

hocX hat keine Wiederherstellungscodes. Hast du dein Gerät verloren:

1. Wenn möglich, mit einem anderen eingerichteten Faktor anmelden (zum Beispiel Passkey statt App).
2. Sonst eine Person mit «Benutzer & Rollen verwalten» bitten, deinen zweiten Faktor
   zurückzusetzen: **Logins & Rollen** → bei dir **MFA** → Faktor entfernen.
3. Danach anmelden und einen neuen Faktor einrichten.

Jede Änderung am zweiten Faktor meldet hocX dir per E-Mail.

## Wann endet eine Sitzung? {#sitzungen}

Alle Sitzungen eines Kontos enden sofort, wenn

- das Passwort geändert oder zurückgesetzt wird (die Sitzung, in der du es selbst änderst, bleibt),
- die Verwaltung das Konto auf **Inaktiv** setzt oder den **Login entzieht**.

Rechteänderungen (andere Rollen) wirken sofort, ohne neue Anmeldung.

## Eigene Daten herunterladen {#daten}

Unter **Profil** → **Daten** lädst du alle Daten, die hocX über dich speichert, als
passwortgeschützte ZIP-Datei herunter.
