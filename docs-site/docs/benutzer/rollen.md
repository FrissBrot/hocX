# Rollen & Berechtigungen

Jedes Benutzerkonto gehört genau einem Mandanten (Organisation). Wer in mehreren Organisationen arbeitet,
braucht pro Organisation ein eigenes Konto (mit eigener E-Mail-Adresse).

Was ein Konto darf, bestimmen seine **Rollen**. Eine Rolle bündelt **Berechtigungen**; ein Konto
kann mehrere Rollen haben und erhält dann alle Berechtigungen dieser Rollen zusammen. Rollen
verwaltet, wer die Berechtigung «Benutzer & Rollen verwalten» hat, unter
**Zugriff → Rollen**. Wer überhaupt einen Login bekommt, steht unter
[Mitglieder & Logins](mitglieder.md#login).

## Standardrollen {#standardrollen}

Jede Organisation startet mit vier Standardrollen. Sie entsprechen den früheren festen Rollen; ohne
Zutun ändert sich für bestehende Konten nichts.

| Rolle | Zugriff |
|---|---|
| Admin | Alle Berechtigungen, auch künftige. Fest, nicht änderbar, nicht löschbar |
| Schreiber | Sitzungen, Protokolle, Vorlagen gestalten, Teilnehmende, Dateien & Fotos, Abgaben; alle Bussen lesen |
| Kassier | Entwürfe lesen, Finanzen und Bussen verwalten, alle Bussen lesen |
| Leser | Abgeschlossene Protokolle lesen, PDF-Export, Kassenbuch und Abgaben ansehen, eigene Bussen |

Schreiber, Kassier und Leser lassen sich umbenennen und anpassen, aber nicht löschen. Eigene Rollen
(z. B. «Revisor» oder «Protokollführung») legt man zusätzlich an. Wer Schreib- und Kassierrechte
braucht, bekommt einfach beide Rollen.

## Berechtigungen {#berechtigungen}

| Bereich | Berechtigung | Erlaubt |
|---|---|---|
| Sitzungen & Protokolle | Sitzungen ansehen | Termine, abgeschlossene Protokolle, Traktanden, Aufgaben, PDF-Export |
| | Entwürfe ansehen | Auch nicht abgeschlossene Protokolle |
| | Sitzungen bearbeiten | Termine, Protokolle, Traktanden, Aufgaben, Listen, Word-Import |
| | Protokolle freigeben | Protokolle abschliessen (mit Vier-Augen-Prinzip nicht die eigenen) |
| | Eigene Pendenzen erledigen | Status der eigenen Pendenzen setzen; ohne dieses Recht ist ein Konto rein lesend |
| Vorlagen | Vorlagen gestalten | Bausteine, Bibliothek und Gestaltung bestehender Vorlagen und Dokumente |
| | Vorlagen verwalten | Sitzungsvorlagen anlegen/löschen, Zyklen, Aufgabenpakete, Tags |
| Teilnehmende | Personen ansehen | Mitgliederliste und Personenseiten, ohne Kontaktdaten |
| | Kontaktdaten sehen | E-Mail-Adressen der Personen |
| | Personendaten exportieren | Datenauskunft für andere Personen (nur mit MFA) |
| | Teilnehmende verwalten | Teilnehmende und Kontaktdaten, Zuordnung zu Vorlagen |
| Finanzen | Kassenbuch ansehen | Konten und Buchungen |
| | Finanzen verwalten | Buchungen und Konten erfassen und ändern |
| | Bussen verwalten | Bussen und Bussen-Regeln erfassen und ändern |
| Auswertungen | Personenbezogene Daten aller | Bussen und Anwesenheit aller Personen (sonst nur die eigenen) |
| Dateien & Fotos | Dateien ansehen | Dokumente in der Ablage |
| | Fotos ansehen / verwalten | Galerie und Alben ansehen bzw. Fotos hochladen, ordnen, Alben pflegen |
| | Dateien verwalten | Dokumente hochladen, ändern, löschen |
| | Öffentlich teilen | Freigabelinks ohne Anmeldung für Dateien, Fotos und Abgaben |
| Abgabebox | Abgaben ansehen / verwalten | Abgaben lesen bzw. Aufträge und Upload-Links verwalten |
| | Abgaben prüfen | Elemente einer Abgabe schliessen und wieder öffnen |
| Administration | Einstellungen verwalten | Profil der Organisation, Datenschutz, Aufbewahrung, Erscheinungsbild |
| | Verlauf ansehen | Verlauf der Organisation (Änderungen, Anmeldungen, Plattformzugriffe) |
| | Benutzer & Rollen verwalten | Logins, Rollen, Rollenzuweisungen, MFA anderer zurücksetzen |
| | Datenexporte | Gesamtexport der Organisation, Datenauskunft für andere Personen |

Im Rollen-Dialog bedeutet das Abzeichen **MFA**, dass sich mit dieser Berechtigung nur mit zweitem
Faktor anmelden lässt; **Modul nicht gebucht** heisst, dass sie erst mit dem Abo-Modul wirkt.
Ausgegraute Berechtigungen hast du selbst nicht oder sie ergeben sich aus einer anderen.

Berechtigungen eines nicht gebuchten Moduls (Finanzen, Abgabebox) wirken erst, wenn das Modul
gebucht ist. Eigene Daten (Profil, Passwort, MFA, eigene Bussen und Aufgaben, eigene Kalender-Abos)
sind immer zugänglich.

## Schutzregeln {#schutzregeln}

- Man kann nur Rollen vergeben, ändern oder anlegen, deren Berechtigungen man selbst hat, und nur
  Konten verwalten, die nicht mehr Rechte haben als man selbst.
- Eine Organisation behält immer mindestens ein aktives Konto mit «Benutzer & Rollen verwalten».
- Die eigene Benutzerverwaltung kann man sich nicht selbst entziehen; das macht ein anderer
  Administrator.
- Wer eine Administrationsberechtigung hat, muss sich mit MFA anmelden – ohne Frist.
- Eine Rolle kann zusätzlich «MFA für diese Rolle verlangen». Bestehende Konten haben dann 3 Tage
  Zeit zum Einrichten (siehe [Zweiter Faktor](konto.md#mfa)), neue richten ihn beim ersten Login ein.
- **Vier-Augen-Prinzip** (Zugriff → Sicherheit): Wer ein Protokoll verfasst hat, kann es nicht selbst
  abschliessen; das macht eine andere Person mit «Protokolle freigeben».
- Rechteänderungen wirken sofort, auch in bereits geöffneten Sitzungen.

## Mandantenübergreifender Zugriff {#mandantenuebergreifend}

Kein normales Konto kann auf eine andere Organisation zugreifen. Eine
mandantenübergreifende Sicht existiert ausschliesslich im getrennten
[Platform-Admin-Panel](../technik/admin-panel.md), das ausschliesslich der Betreiberseite
vorbehalten ist. Dort lässt sich einem Konto im Notfall eine Standardrolle zuweisen (z. B. «Admin»);
eigene Rollen verwaltet die Organisation selbst.
