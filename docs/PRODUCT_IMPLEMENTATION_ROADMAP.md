# hocX – Umsetzungsplan Produkt- und Abostruktur

Stand: 2026-10-27. Reihenfolge nach Abhängigkeiten, Kundennutzen und Wirtschaftlichkeit. Aufwand je
Person [A]: S ≤ 3 Tage, M 1–2 Wochen, L > 2 Wochen. Status: ✅ erledigt (dieser Change) · ⏳ offen.

**Vor einer Vermarktung der neuen Pakete notwendig:** Phase 1 und 2 (erledigt bzw. klein) sowie aus
Phase 3 E-Mail-Versand, Passwort-Reset und Versand von Einladung/Protokoll. Alles Weitere kann nach
dem Marktstart folgen.

## Phase 1 – Bestehende Funktionen korrekt strukturieren

| # | Arbeit | Aufwand | Status |
|---|---|---|---|
| 1.1 | Vollständige Bestandsaufnahme, Modulstruktur, Feature-Katalog, Abo-Strategie (`docs/*`) | – | ✅ |
| 1.2 | Feature-Katalog als einzige Quelle (`permissions/features.json`, `sync-feature-catalog.py`, CI/Pre-Commit) | S | ✅ |
| 1.3 | Benutzerlimit durchsetzen; Zählweise «Konten mit Login» | S | ✅ |
| 1.4 | Feature-Beschreibung `finance` («Beiträge») korrigieren oder Beiträge bauen (Phase 4) | S | ⏳ |
| 1.5 | Website-CTA «30 Tage testen» an die Realität anpassen (Demo-Anfrage) | S | ⏳ |
| 1.6 | Job-Text «Gesichtserkennung» → «Gesichtsqualität» | S | ⏳ |

## Phase 2 – Modul- und Feature-Architektur vereinheitlichen

| # | Arbeit | Aufwand | Status |
|---|---|---|---|
| 2.1 | Nur-Lesen-Zustand nach Downgrade (`tenant_feature.access`), Herkunft (`source`), Planwechsel konsistent | M | ✅ |
| 2.2 | Neue buchbare Features `task_packages`, `custom_roles`, `photo_sharing`, `document_designer` inkl. Bestandsschutz und Plan-Zuordnung | M | ✅ |
| 2.3 | Frontend: `featureAccess`, Hinweise «nicht im Abo»/«nur lesend», Admin-Dialog mit Nur-Lesen-Zustand | S | ✅ |
| 2.4 | Rechte-Übersicht zeigt Feature-Prüfungen (`route-map.json`, «(lesen)») | S | ✅ |
| 2.5 | Seiten-Gates `/documents*`, `/tools/*` an Backend-Rechte angleichen | S | ⏳ |
| 2.6 | Navigation umgruppieren (Import in Protokolle, Listen zu Sitzungen, Konten zu Mitglieder) | S–M | ⏳ |
| 2.7 | Legacy entfernen: `GroupEntity`, `Leader`, `UserProtocolAccess`, Blocktypen `display`/`static_text`/`bullet_list` (Daten migrieren), `EventCategory` (in Tags), `GET /files/stats`, verwaiste «bald»-Texte | M | ⏳ |
| 2.8 | Upgrade-Hinweise in Modals (z. B. Freigabelink) statt Backend-Meldung | S | ⏳ |
| 2.9 | Abgabebox-Speicherdeckel an Plan koppeln statt fixer 2 GiB | S | ⏳ |

## Phase 3 – Notwendige fehlende Kernfeatures (vor Vermarktung)

| # | Feature | Aufwand | Abhängigkeit | Status |
|---|---|---|---|---|
| 3.1 | E-Mail-Versand (`platform.email`) | M | – | ⏳ |
| 3.2 | Passwort per E-Mail zurücksetzen (`people.password_reset`) | S–M | 3.1 | ⏳ |
| 3.3 | Versand von Einladung und Protokoll (`meetings.distribution`) | M | 3.1 | ⏳ |
| 3.4 | Pendenzenstatus «abgebrochen» in der Oberfläche | S | – | ⏳ |
| 3.5 | Abo-Seite mit Upgrade-Anfrage (`admin.subscription`) | S | – | ⏳ |

## Phase 4 – Attraktive und vollständige Abopakete

| # | Feature | Abo | Aufwand | Status |
|---|---|---|---|---|
| 4.1 | Mitgliederbeiträge mit QR-Rechnung (`finance.dues`) | Pro | M–L | ⏳ |
| 4.2 | Erinnerungen (`meetings.reminders`) | Pro | M | ⏳ |
| 4.3 | An-/Abmeldung per Link (`meetings.rsvp`) | Pro | M | ⏳ |
| 4.4 | Login-Einladung (`people.invitations`) | Basic | S–M | ⏳ |
| 4.5 | Anzeigenamen Basic/Pro/Business und `premium.load_priority = 2` im Adminportal | – | S | ⏳ (kommerzielle Entscheidung) |
| 4.6 | Benutzerpakete als Add-on (analog Speicherpakete) | Add-on | M | ⏳ |

## Phase 5 – Premiumfunktionen und Upselling

| # | Feature | Abo | Aufwand | Status |
|---|---|---|---|---|
| 5.1 | Beschlussregister (`meetings.decisions`) | Pro | M | ⏳ |
| 5.2 | Mandanten-SSO (`people.sso`) | Business | M–L | ⏳ |
| 5.3 | Gremien und Bereiche (`meetings.committees`) | Business | L | ⏳ |
| 5.4 | Jahresbericht (`meetings.reports`) | Pro | S–M | ⏳ |
| 5.5 | Eingangsbenachrichtigung Abgabebox | Pro | S | ⏳ |
| 5.6 | Registrierung und Testphase (`platform.self_signup`) | – | M–L | ⏳ |

## Phase 6 – Langfristige Erweiterungen

Globale Suche, Word-Import-Oberflächen zusammenführen, Bankimport, Online-Zahlung der Abos, API und
Webhooks (Add-on, nur bei Nachfrage), Kategorien/Budget, digitale Signatur (zurückgestellt), mobile
Ansichten für Konfigurationsbereiche.

## Nicht entwickeln

Vollständige Buchhaltung, Gesichtserkennung, CRDT-Bearbeitung, native Apps, Chat, Feature-Flags für
einzelne Oberflächenelemente; KI-Zusammenfassungen erst nach Kundenbefragung und Datenschutzklärung.
Begründungen: `docs/FEATURE_EXPANSION_ROADMAP.md`, Abschnitt 9.

## Abhängigkeitsgraph (Kurzform)

```
platform.email ─┬─ people.password_reset
                ├─ people.invitations
                ├─ meetings.distribution ── automatischer Versand (Pro)
                ├─ meetings.reminders ── meetings.rsvp
                └─ submissions.notifications
finance.ledger ── finance.dues ── finance.import
RBAC + UserTemplateAccess ── meetings.committees
platform_oidc_service ── people.sso
```

## Qualitätskontrolle aus vier Perspektiven

- **Softwarearchitekt:** Eine Quelle (`features.json`), bestehende Tabellen erweitert statt neue
  Abstraktion, eine Prüffunktion mit `write`-Flag, Backend als einzige Durchsetzung, Katalog- und
  Routen-Checks in CI. Risiko: Prüfungen in neuen Routen vergessen → durch Route-Map-Diff sichtbar.
- **Produktmanager:** Alle bestehenden Funktionen sind einem von 69 Katalogeinträgen zugeordnet; sieben
  Module statt einer gewachsenen Navigation; Legacy klar benannt. Business ist das schwächste Paket.
- **SaaS-Unternehmer:** Pro und Business sind ohne Neuentwicklung marktfähig; der grösste Hebel ist die
  E-Mail-Infrastruktur. Aufwand ist auf Features mit klarem Zeitgewinn für Kunden gelenkt.
- **Kunde:** Basic ist vollständig nutzbar (nichts Grundlegendes künstlich gesperrt), höhere Pakete
  bringen echte Zusatzfunktionen, ein Downgrade nimmt keine Daten weg.

Vereinfachungen gegenüber einem «Enterprise»-Modell: keine Feature-Flags, keine Mengenlimits pro
Objektart, nur acht buchbare Features, keine Preislogik im Code.
