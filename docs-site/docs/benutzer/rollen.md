# Rollen & Berechtigungen

Jedes Benutzerkonto gehört genau einem Mandanten (Verein). Wer in mehreren Vereinen arbeitet,
braucht pro Verein ein eigenes Konto (mit eigener E-Mail-Adresse).

Was ein Konto darf, bestimmen seine **Rollen**. Eine Rolle bündelt **Berechtigungen**; ein Konto
kann mehrere Rollen haben und erhält dann alle Berechtigungen dieser Rollen zusammen. Rollen
verwaltet, wer die Berechtigung «Benutzer & Rollen verwalten» hat, unter
**Teilnehmer mit Login → Rollen**.

## Standardrollen

Jeder Verein startet mit vier Standardrollen. Sie entsprechen den früheren festen Rollen; ohne
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

## Berechtigungen

| Bereich | Berechtigung | Erlaubt |
|---|---|---|
| Sitzungen & Protokolle | Sitzungen ansehen | Termine, abgeschlossene Protokolle, Traktanden, Aufgaben, PDF-Export |
| | Entwürfe ansehen | Auch nicht abgeschlossene Protokolle |
| | Sitzungen bearbeiten | Termine, Protokolle, Traktanden, Aufgaben, Listen, Word-Import |
| Vorlagen | Vorlagen gestalten | Bausteine, Bibliothek und Gestaltung bestehender Vorlagen und Dokumente |
| | Vorlagen verwalten | Sitzungsvorlagen anlegen/löschen, Zyklen, Aufgabenpakete, Tags |
| Teilnehmende | Teilnehmende verwalten | Teilnehmende und Kontaktdaten, Zuordnung zu Vorlagen |
| Finanzen | Kassenbuch ansehen | Konten und Buchungen |
| | Finanzen verwalten | Buchungen, Konten und Bussen erfassen und ändern |
| Auswertungen | Personenbezogene Daten aller | Bussen und Anwesenheit aller Personen (sonst nur die eigenen) |
| Dateien & Fotos | Dateien & Fotos verwalten | Dateien, Fotos, Alben, öffentliche Freigabelinks |
| Abgabebox | Abgaben ansehen / verwalten | Abgaben lesen bzw. Aufträge und Upload-Links verwalten |
| Administration | Einstellungen verwalten | Vereinsprofil, Datenschutz, Aufbewahrung, Erscheinungsbild, Aktivitätsprotokoll |
| | Benutzer & Rollen verwalten | Logins, Rollen, Rollenzuweisungen, MFA anderer zurücksetzen |
| | Datenexporte | Gesamtexport des Vereins, Datenauskunft für andere Personen |

Berechtigungen eines nicht gebuchten Moduls (Finanzen, Abgabebox) wirken erst, wenn das Modul
gebucht ist. Eigene Daten (Profil, Passwort, MFA, eigene Bussen und Aufgaben, eigene Kalender-Abos)
sind immer zugänglich.

## Schutzregeln

- Man kann nur Rollen vergeben, ändern oder anlegen, deren Berechtigungen man selbst hat, und nur
  Konten verwalten, die nicht mehr Rechte haben als man selbst.
- Ein Verein behält immer mindestens ein aktives Konto mit «Benutzer & Rollen verwalten».
- Die eigene Benutzerverwaltung kann man sich nicht selbst entziehen; das macht ein anderer
  Administrator.
- Wer eine Administrationsberechtigung hat, muss sich mit MFA anmelden.
- Rechteänderungen wirken sofort, auch in bereits geöffneten Sitzungen.

## Mandantenübergreifender Zugriff

Kein normaler Vereins-Account kann auf einen anderen Verein zugreifen. Eine
mandantenübergreifende Sicht existiert ausschliesslich im getrennten
[Platform-Admin-Panel](../technik/admin-panel.md), das ausschliesslich der Betreiberseite
vorbehalten ist. Dort lässt sich einem Konto im Notfall eine Standardrolle zuweisen (z. B. «Admin»);
eigene Rollen verwaltet der Verein selbst.
