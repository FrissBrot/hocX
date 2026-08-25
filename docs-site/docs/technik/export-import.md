# Mandanten Export/Import

Über das Admin-Panel (`/admin/tenants`) lässt sich ein Mandant als portable
`.hocxexport.zip`-Datei exportieren und auf derselben oder einer anderen Instanz wieder
importieren.

## Scopes

| Scope | Enthält |
|---|---|
| `structure` | Zyklen, Formularfelder/Templates, Dokumentvorlagen, Listen, Konten, Benutzerrollen, verifizierte Domains |
| `structure_lists` | zusätzlich die Listeneinträge selbst (Zeileninhalte der unter `structure` bereits enthaltenen Listen) - Bezüge einzelner Einträge zu Teilnehmern/Terminen der Quellinstanz werden beim Import nicht übernommen, da Teilnehmer/Termine in diesem Scope nicht mitexportiert werden |
| `full` | zusätzlich Teilnehmer, Termine, Protokolle, Bussen, Todos, Dateien (inkl. Fotos-Galerie-Zuordnung, ohne Abgabebox) |
| `full_abgabebox` | zusätzlich Abgabebox-Konfiguration und hochgeladene Dateien |

## Domains

`structure` (und höher) exportiert auch `tenant_domain` - Domain, Zweck (App/Abgabebox),
Status, `verified_at` und **denselben Prüfcode** (`verification_token`), unverändert. Eine
bereits verifizierte Domain bleibt nach dem Import verifiziert, ohne dass die erneute
DNS-Prüfung nötig ist - der DNS-TXT-Eintrag beim Domain-Provider trägt ja bereits genau
diesen Code. Eine Domain ist installationsweit eindeutig (`uq_tenant_domain_domain`); ist sie
auf der Zielinstanz bereits vergeben (durch hocX selbst oder einen anderen Mandanten), wird
die betroffene Zeile mit Warnung übersprungen statt den ganzen Import abzubrechen. War eine
importierte Domain `active`, wird die Traefik-Routingkonfiguration nach dem Import neu
generiert.

## Bekannte Lücken (bewusst)

- `word_import_profile` (gemerkte Zuordnungs-Overrides des Word-Importers) und
  `word_import_document` (Warteschlange offener/importierter Word-Import-Dokumente) werden
  **nicht** exportiert - ihre JSON-Konfiguration verweist intern auf Teilnehmer-/Listen-/
  Termin-IDs der Quellinstanz; ein 1:1-Übertrag ohne vollständiges Remapping dieser IDs würde
  auf der Zielinstanz auf falsche oder fremde Datensätze zeigen, statt schlicht zu fehlen -
  das wäre schlechter als ein sauberes Weglassen. `word_import_profile` baut sich beim
  nächsten Import ohnehin automatisch neu auf.
- `protocol_export_cache` (gecachtes PDF/LaTeX einer Protokoll-Exportanfrage) wird nicht
  exportiert - reine Performance-Cache, wird bei Bedarf neu generiert.

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
