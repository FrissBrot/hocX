# Umsetzungsplan: Berechtigungen, Datei-Kontexte und Kontext-Freigaben

Vorgabe des Produktverantwortlichen vom 18.11.2026, Ziel Release 1.4.0. Der Plan wurde ohne
Einblick in den Code erstellt; Namen sind Vorschläge und werden an die Konventionen des Repos
angepasst.

**Entscheide (18.11.2026):**
- Umsetzung vollständig in 1.4.0.
- Bestehende englische Berechtigungsschlüssel bleiben (`files.manage`, `meetings.edit`, …). Neue
  Rechte im selben Schema, deutsche Namen nur als Anzeige-Texte (`roles.permissions.*`).
- Was es schon gibt: Katalog im Code (`permissions/catalog.json` mit `implies`, MFA,
  Sync-Skript), zentrale Prüfung `require_permission`/`user.can`, generierte Rechte-Übersicht
  `permissions/route-map.json`, `tests/test_route_permission_inventory.py`, Regel gegen
  Rollen-Code-Vergleiche, wöchentliches RBAC-Audit, Registry öffentlicher Links
  (`backend/app/public_links/providers.py`). Phase 0/1 ergänzen das, statt es neu zu bauen.

**Entscheide zu den offenen Fragen (18.11.2026):**
- Teilnehmende ohne Login gibt es (Personen ohne Login-Zugang); Freigaben an «alle Teilnehmenden»
  wirken nur für Personen mit Login.
- Eigene Pendenzen abhaken: heute nur mit `meetings.edit`. Neues Recht «eigene Pendenzen
  erledigen» (Reichweite eigene), bei der Migration für **alle Rollen inkl. Leser**; entziehbar –
  ohne dieses Recht ist der Zugang rein lesend (read-only Benutzer).
- Vier-Augen-Prinzip: **pro Organisation wählbar** (Einstellung, Standard aus). An: der Verfasser
  darf sein eigenes Protokoll nicht abschliessen; zusätzlich braucht Abschliessen das Recht
  «Protokolle freigeben».
- Zielgruppe «Gruppen» = **Rollen** (Freigabe an eine oder mehrere Rollen des Mandanten).
- Ordner-Freigaben in der Ablage: nein.
- Umsetzung «alles auf einmal» in 1.4.0 (ein Zweig, Commits je Phase).

## Arbeitsweise
- Phasenweise in der angegebenen Reihenfolge, jede Phase eigener Zweig mit eigenen Commits.
- Nach jeder Phase: alle bestehenden Tests und die Berechtigungsmatrix (Phase 0) grün.
- Keine Verhaltensänderung in Phase 1 und 2, ausser wo explizit beschrieben.
- Datenmigrationen immer mit Dry-Run (Report) und reversibel (Down-Migration oder Backup-Tabelle).
- Fachliche Unklarheiten: fragen statt raten (offene Fragen unten).

## Zielbild
**Ebene 1: Rollen-Berechtigungen.** Jede Berechtigung = Bereich × Stufe × Reichweite.
Stufe: ansehen → bearbeiten → verwalten (höhere implizieren tiefere). Reichweite (nur wo
sinnvoll): alle | zugewiesene | eigene. Katalog im Code, DB speichert nur Rolle → Schlüssel +
Reichweite.

**Ebene 2: Kontext-Freigaben (neu).** Dateien gehören immer zu einem Kontext: protokoll | abgabe
| album | ablage. Zugriff erbt vom Kontext. Kontexte können zusätzlich Sichtrechte freigeben (pro
Modul ein Standard, pro Objekt überschreibbar), nur additiv und nur lesend.

| Modul | zusätzlich sichtbar für | Dateitypen |
|---|---|---|
| Abgaben | alle Teilnehmenden | nur Bilder |
| Protokolle | niemand (nur Rolle) | – |
| Alben | alle Teilnehmenden | alle |

Zielgruppen (audience): nur_rolle | einreichende_eigene | alle_teilnehmenden | gruppen.
Dateifilter (file_filter): alle | bilder.

## Berechtigungskatalog (Ziel, fachlich; Schlüssel werden ins englische Schema übersetzt)
| Bereich | Recht | Reichweite | MFA | Notiz |
|---|---|---|---|---|
| Sitzungen | sitzungen.ansehen | – | | |
| | sitzungen.entwuerfe_ansehen | – | | |
| | sitzungen.bearbeiten | – | | inkl. Word-Import |
| | protokolle.freigeben | – | | neu, Vier-Augen-Prinzip |
| | aufgaben.eigene_erledigen | eigene | | neu, Standard für alle |
| Vorlagen | vorlagen.gestalten | – | | |
| | vorlagen.verwalten | – | | |
| Teilnehmende | teilnehmende.ansehen | – | | neu, ohne Kontaktdaten |
| | teilnehmende.kontaktdaten_ansehen | – | | neu |
| | teilnehmende.verwalten | – | | |
| | personendaten.exportieren | – | | neu |
| Finanzen | kassenbuch.ansehen | – | | |
| | finanzen.verwalten | – | | |
| | bussen.verwalten | – | | neu, abgetrennt |
| Auswertungen | personendaten.ansehen | alle / eigene | | ersetzt «Personenbezogene Daten aller» |
| Abgaben | abgaben.ansehen | alle / zugewiesene | | |
| | abgaben.pruefen | alle / zugewiesene | | neu: annehmen, ablehnen, kommentieren |
| | abgaben.auftraege_verwalten | – | | Aufträge, Prüfer zuweisen |
| Dateien | fotos.ansehen | – | | neu |
| | fotos.verwalten | – | | Galerie, Alben |
| | ablage.ansehen | – | | neu, freie Ablage |
| | ablage.verwalten | – | | |
| Teilen | oeffentlich.teilen | – | ✔ | neu, modulübergreifend |
| Administration | einstellungen.verwalten | – | ✔ | |
| | aktivitaetsprotokoll.ansehen | – | | neu, abgetrennt |
| | benutzer_rollen.verwalten | – | ✔ | |

implies (Beispiele): *.verwalten ⇒ *.bearbeiten ⇒ *.ansehen; abgaben.pruefen ⇒ abgaben.ansehen;
teilnehmende.verwalten ⇒ teilnehmende.kontaktdaten_ansehen ⇒ teilnehmende.ansehen;
sitzungen.bearbeiten ⇒ sitzungen.entwuerfe_ansehen ⇒ sitzungen.ansehen.

## Datenmodell (Vorschlag)
```
role_permissions(role_id, permission_key, scope)        -- scope: alle|zugewiesene|eigene|NULL
resource_assignments(resource_type, resource_id, user_id, funktion)   -- z. B. Prüfer eines Abgabe-Auftrags
files: + context_type, + context_id                       -- protokoll|abgabe|album|ablage
context_visibility(id, context_type, context_id NULL,     -- NULL = Modul-Standard
                   audience, group_id NULL, file_filter, show_in_gallery bool)
public_links(id, resource_type, resource_id, token, kind, -- kind: download|upload|album
             expires_at, created_by, created_at, revoked_at)
permission_audit_log(id, actor_id, action, target_type, target_id, before jsonb, after jsonb, at)
```

## Zentrale Prüflogik
```python
def can(user, action: str, resource=None) -> bool:
    # 1. Rolle (inkl. implies + Reichweite)
    if role_allows(user, action, resource):
        return True
    # 2. Kontext-Freigabe: nur Lesen, nur Dateien
    if action.endswith(".ansehen") and is_file(resource):
        return context_grant_allows(user, resource.context_type, resource.context_id, resource.mime)
    return False

def visible_files_query(user, context_type=None):
    """Gleiche Logik als DB-Filter für Listen/Galerie (keine N+1-Einzelprüfungen)."""
```
Alle Dateizugriffe laufen über can() / visible_files_query(): Download, Thumbnails/Vorschauen,
signierte URLs, ZIP-Downloads, PDF-Exporte mit eingebetteten Bildern, Galerie, Suche, API.

## Phasen
**Phase 0: Inventar und Sicherheitsnetz.** `docs/permissions-inventory.md`: jeder Endpoint / jede
View / jeder Dateizugriff → heute geprüfte Berechtigung (oder «keine»). Alle Stellen, die Dateien
ausliefern (inkl. Thumbnails, signierte URLs, Exporte). Matrix-Test Rolle × Endpoint →
erlaubt/verweigert, Ist-Zustand festhalten. Fertig: Inventar vollständig, Matrix grün, Lücken als
Liste dokumentiert (nicht stillschweigend fixen, sondern melden).

**Phase 1: Katalog und can(), ohne Verhaltensänderung.** Katalog mit allen heutigen Rechten
(Schlüssel, Label, Hilfetext, MFA, implies). can() implementieren, alle Endpoints darauf
umstellen, verstreute Prüfungen entfernen. Unbekannter Schlüssel ⇒ Fehler in Dev/Test, False in
Produktion. Fertig: Matrix unverändert grün; kein direkter Rollen-Check ausserhalb von can().

**Phase 2: Dateien bekommen einen Kontext.** files.context_type/context_id (zuerst nullable).
Datenmigration mit Dry-Run: über heutige Verknüpfungen zuordnen, nicht zuordenbare → ablage;
Report pro Kontext + Liste der Ablage-Fälle. Danach NOT NULL + Index (context_type, context_id).
can() für Dateien erbt vom Kontext (protokoll → sitzungen.ansehen bzw. entwuerfe_ansehen bei
Entwurf; abgabe → abgaben.ansehen mit Reichweite; album → fotos.ansehen; ablage → ablage.ansehen).
Upload-Pfade setzen den Kontext immer explizit. Fertig: jede Datei hat einen Kontext; Matrix um
Datei-Fälle erweitert und grün; bisherige Inhaber von «Dateien & Fotos verwalten» sehen weiterhin
alles.

**Phase 3: Neue Rechte und Rollen-Migration.** Katalog auf Zielstand. Mapping alt → neu, so dass
niemand Rechte verliert oder gewinnt:
- «Dateien & Fotos verwalten» → fotos.verwalten + ablage.verwalten + oeffentlich.teilen
- «Finanzen verwalten» → + bussen.verwalten
- «Teilnehmende verwalten» → + teilnehmende.kontaktdaten_ansehen + personendaten.exportieren
- «Einstellungen verwalten» → + aktivitaetsprotokoll.ansehen
- «Sitzungen bearbeiten» → + protokolle.freigeben (bisheriges Verhalten beibehalten)
- «Abgaben verwalten» → abgaben.auftraege_verwalten + abgaben.pruefen + oeffentlich.teilen
- «Personenbezogene Daten aller» → personendaten.ansehen scope alle; ohne → scope eigene
- alle Rollen → + aufgaben.eigene_erledigen (bisheriges Verhalten prüfen)
Dry-Run-Report pro Rolle vorher/nachher. Matrix auf neue Schlüssel umstellen, Ergebnisse
identisch zum Ist-Zustand.

**Phase 4: Reichweite «zugewiesene».** resource_assignments + UI im Abgabe-Auftrag (Prüfer
zuweisen). role_allows berücksichtigt scope. Tests: Prüfer mit «zugewiesene» sieht nur
zugewiesene Aufträge und deren Dateien.

**Phase 5: Kontext-Freigaben.** Tabelle context_visibility, Seed der Modul-Standards (Protokolle:
nur_rolle). context_grant_allows() und visible_files_query(): Objekt-Override → sonst
Modul-Standard; bilder ⇒ nur image/*; alle_teilnehmenden ⇒ nur Benutzer mit verknüpftem
Teilnehmenden-Datensatz; einreichende_eigene ⇒ nur eigene Einreichungen. UI: Einstellungen →
«Sichtbarkeit von Dateien» pro Modul; Abgabe-Auftrag → «Wer darf eingereichte Dateien sehen?»
(Standard/überschreiben) + Dateitypen + «In Fotogalerie anzeigen»; Ansicht «Fotos aus Abgaben»
für Teilnehmende ohne Rollenrechte. Tests: Teilnehmende sehen Abgabe-Bilder, nicht Abgabe-PDFs,
nicht Protokoll-Dateien; Thumbnails, Downloads, ZIP gleich geschützt.

**Phase 6: Öffentliche Links vereinheitlichen.** Tabelle public_links; bestehende Freigabelinks
(Dateien, Alben, Abgabe-Upload-Links) migrieren, Tokens beibehalten. Erstellen/Widerrufen nur mit
oeffentlich.teilen (MFA). Einstellungen → «Aktive öffentliche Links» mit Ablauf und Widerrufen.

**Phase 7: UI und Rollen-Vorlagen.** Rollen-Dialog: Gruppen wie bisher; implies automatisch
anhaken und ausgrauen; Reichweite als Dropdown pro Recht; Hilfetexte aus dem Katalog.
Rollen-Vorlagen (kopierbar, nicht verknüpft): Präsident, Aktuar, Kassier, Revisor, Abgabe-Prüfer,
Mitglied. «Ansehen als …»: Vorschau, was ein Benutzer sieht (nur benutzer_rollen.verwalten, nur
lesend, im Aktivitätsprotokoll vermerkt).

**Phase 8: Nachvollziehbarkeit.** Änderungen an Rollen, Zuordnungen, Kontext-Freigaben und
öffentlichen Links → permission_audit_log / Aktivitätsprotokoll (vorher/nachher).

## Offene Fragen (vor der jeweiligen Phase klären)
1. Haben alle Teilnehmenden ein Benutzerkonto, oder gibt es Teilnehmende ohne Login? (Phase 5)
2. Können Teilnehmende heute schon eigene Aufgaben abhaken? (Phase 3)
3. Gibt es Gruppen/Teams als Zielgruppe für Freigaben, oder müssen sie neu entstehen? (Phase 5)
4. Sollen Protokoll-Freigaben technisch erzwungen werden (Abschluss nur durch andere Person als
   Verfasser), oder reicht das Recht? (Phase 3)
5. Kontext-Freigaben auch für die freie Ablage (Ordner-Freigaben)? Vorerst: nein.

## Nicht-Ziele
Keine Verbots-Regeln (Deny) auf Ebene 2. Kein Schreibzugriff über Kontext-Freigaben. Keine frei
definierbaren Berechtigungsschlüssel durch Vereine.
