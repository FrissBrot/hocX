# Mandanten Export/Import

Über das Admin-Panel (`/admin/tenants`) lässt sich ein Mandant als portable
`.hocxexport.zip`-Datei exportieren und auf derselben oder einer anderen Instanz wieder
importieren.

## Scopes

| Scope | Enthält |
|---|---|
| `structure` | Zyklen, Formularfelder/Templates, Dokumentvorlagen, Listen, Konten, Benutzerrollen |
| `structure_lists` | zusätzlich die Listeneinträge selbst (Zeileninhalte der unter `structure` bereits enthaltenen Listen) - Bezüge einzelner Einträge zu Teilnehmern/Terminen der Quellinstanz werden beim Import nicht übernommen, da Teilnehmer/Termine in diesem Scope nicht mitexportiert werden |
| `full` | zusätzlich Teilnehmer, Termine, Protokolle, Bussen, Todos (ohne Abgabebox) |
| `full_abgabebox` | zusätzlich Abgabebox-Konfiguration und hochgeladene Dateien |

## Referenz-Auflösung

- Globale Lookup-Tabellen (Rollen, Kategorien, Elementtypen …) werden über einen
  stabilen `code` gemappt, nicht über die numerische ID – damit ist der Export
  installationsunabhängig.
- Benutzer-Referenzen (z. B. Protokoll-Ersteller) werden über die E-Mail gemappt. Fehlt
  der Zielbenutzer, wird die betroffene Zeile übersprungen bzw. das Feld auf `NULL`
  gesetzt, jeweils mit Warnung im Import-Ergebnis.
- Login-relevante Benutzerdaten (nicht nur Verknüpfungstabellen) werden mitexportiert,
  damit importierte Benutzer sich auf der Zielinstanz auch tatsächlich einloggen können.

## Anwendungsfall

Gedacht, um Mandanten portabel zu sichern, zu duplizieren oder zwischen Instanzen zu
verschieben (z. B. Dev → Prod). Für ein reines Duplikat **innerhalb derselben** Instanz
gibt es daneben die schnellere Mandanten-Klon-Funktion.
