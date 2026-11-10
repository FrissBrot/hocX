# hocX – SaaS-Abostrategie

Stand: 2026-10-27. Leitet die Abostufen aus dem tatsächlichen Produkt und dem Feature-Katalog
(`docs/COMPLETE_FEATURE_CATALOG.md`) ab. Technische Umsetzung: `docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md`.
Preise und Limits sind Seeds bzw. Empfehlungen und im Adminportal änderbar; es werden keine
Umsatz- oder Zahlungsbereitschaftszahlen behauptet. Annahmen sind mit [A] markiert.

## 1. Empfohlene Abostufen

Drei Stufen, abgebildet auf die bestehenden Plan-Codes (keine Datenmigration der Mandanten nötig).
Empfohlene Anzeigenamen: **Basic**, **Pro**, **Business** (Umbenennen im Adminportal, Codes bleiben).

| | **Basic** (`starter`) | **Pro** (`standard`, hervorgehoben) | **Business** (`premium`) |
|---|---|---|---|
| Zielkunden | kleine Vereine, Vorstand bis ca. 10 Konten | mittlere Vereine, KMU-Teams mit regelmässigen Sitzungen | grosse Vereine, Verbände, KMU mit Corporate Design und IT-Anforderungen |
| Wichtigste Bedürfnisse | Protokoll ohne Nacharbeit, Pendenzen, Termine, Abgaben | Kasse und Bussen, weniger wiederkehrende Arbeit, eigenes Dokumentdesign, Fotos teilen | Rechte nach Organisation, eigene Domain, unbegrenzte Konten, Priorität |
| Konten mit Login (Seed) | 10 | 30 | unbegrenzt |
| Speicher (Seed) | 5 GiB | 20 GiB | 100 GiB |
| Überlast-Priorität | normal | normal | hoch (Empfehlung) |
| Buchbare Features | `abgabebox` | + `finance`, `task_packages`, `document_designer`, `photo_sharing` | + `custom_roles`, `custom_domain` |
| Preis (Seed, CHF/Monat) | 99 | 199 | 349 |

Umgesetzt in Migration `0158_feature_entitlements.py`: `standard` erhält `task_packages`,
`photo_sharing`, `document_designer`; `premium` zusätzlich `custom_roles`. Alle bestehenden Mandanten
behalten die vier neuen Features als Zusatzmodul (Bestandsschutz).
**Empfehlung, nicht umgesetzt:** `premium.load_priority = 2` und Anzeigenamen Basic/Pro/Business im
Adminportal setzen (kommerzielle Entscheidung).

## 2. Zielkundensegmente [A]

| Segment | Merkmale | Passendes Abo | Typischer Auslöser für Upgrade |
|---|---|---|---|
| Kleiner Verein / Vorstand | 5–10 Personen im Vorstand, monatliche Sitzung, Kasse in Excel | Basic | Kassier will Bussen und Kasse im System; mehr als 10 Logins |
| Jugendverband / mittlerer Verein | Leiterteam 15–30, Gruppen, Jahresprogramm, viele Fotos | Pro | Aufgabenpakete je Lagerjahr, Fotos mit Eltern teilen, eigenes Protokolldesign |
| KMU-Geschäftsleitung | GL-Sitzungen, Corporate Design, Beschlüsse | Pro → Business | eigene Rollen, eigene Domain, SSO |
| Verband / grosser Verein | mehrere Gremien, viele Konten | Business | Gremien (geplant), unbegrenzte Konten, eigene Rollen |

## 3. Vollständige Feature-Matrix

✓ enthalten (vorhanden) · ◐ enthalten, teilweise vorhanden · ○ vorgeschlagen (noch nicht vorhanden) ·
– nicht enthalten · Add-on einzeln buchbar.

| Modul | Feature | Status | Basic | Pro | Business |
|---|---|---|---|---|---|
| Sitzungen und Protokolle | `meetings.protocols` Protokolle führen | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.collaboration` Live-Zusammenarbeit | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.track_changes` Änderungsverfolgung | PARTIAL | ◐ | ◐ | ◐ |
| Sitzungen und Protokolle | `meetings.closing` Abschluss und Archiv | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.session_templates` Sitzungsvorlagen | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.building_blocks` Bausteine | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.cycles` Zyklen | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.agenda_items` Anliegen | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.todos` Pendenzen | PARTIAL | ◐ | ◐ | ◐ |
| Sitzungen und Protokolle | `meetings.events` Termine und Jahresprogramm | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.attendance` Anwesenheit | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.lists` Listen und Jahresstände | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.statistics` Auswertungen | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.calendar_feeds` Kalender-Abos | EXISTING | ✓ | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.word_import` Word-/PDF-Import | PARTIAL | ◐ | ◐ | ◐ |
| Sitzungen und Protokolle | `meetings.task_packages` Aufgabenpakete | EXISTING | – | ✓ | ✓ |
| Sitzungen und Protokolle | `meetings.distribution` Versand von Einladung und Protokoll | PROPOSED | ○ | ○ | ○ |
| Sitzungen und Protokolle | `meetings.reminders` Erinnerungen | PROPOSED | – | ○ | ○ |
| Sitzungen und Protokolle | `meetings.rsvp` An-/Abmeldung per Link | PROPOSED | – | ○ | ○ |
| Sitzungen und Protokolle | `meetings.decisions` Beschlussregister | PROPOSED | – | ○ | ○ |
| Sitzungen und Protokolle | `meetings.search` Globale Suche | PROPOSED | ○ | ○ | ○ |
| Sitzungen und Protokolle | `meetings.committees` Gremien und Bereiche | PROPOSED | – | – | ○ |
| Sitzungen und Protokolle | `meetings.reports` Jahresbericht | PROPOSED | – | ○ | ○ |
| Mitglieder und Zugänge | `people.participants` Teilnehmende und Mitgliedschaft | EXISTING | ✓ | ✓ | ✓ |
| Mitglieder und Zugänge | `people.accounts` Konten mit Login | EXISTING | ✓ | ✓ | ✓ |
| Mitglieder und Zugänge | `people.user_limit` Benutzerlimit | EXISTING | ✓ | ✓ | ✓ |
| Mitglieder und Zugänge | `people.standard_roles` Standardrollen | EXISTING | ✓ | ✓ | ✓ |
| Mitglieder und Zugänge | `people.custom_roles` Eigene Rollen | EXISTING | – | – | ✓ |
| Mitglieder und Zugänge | `people.personal_data` Datenauskunft | EXISTING | ✓ | ✓ | ✓ |
| Mitglieder und Zugänge | `people.password_reset` Passwort per E-Mail zurücksetzen | PROPOSED | ○ | ○ | ○ |
| Mitglieder und Zugänge | `people.invitations` Login-Einladung | PROPOSED | ○ | ○ | ○ |
| Mitglieder und Zugänge | `people.sso` Anmeldung mit Microsoft/Google (SSO) | PROPOSED | – | – | ○ |
| Dokumente und Erscheinungsbild | `documents.exports` Dokumente und Exporte | EXISTING | ✓ | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.system_templates` Systemvorlagen | EXISTING | ✓ | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.brand` Erscheinungsbild | EXISTING | ✓ | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.design_examples` Gestaltungsbeispiele | EXISTING | – | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.designer` Dokument-Designer | EXISTING | – | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.verification` Echtheitsprüfung | EXISTING | ✓ | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.verified_org` Verifizierte Organisation | EXISTING | ✓ | ✓ | ✓ |
| Dokumente und Erscheinungsbild | `documents.verify_domain` Eigene Prüf-Domain | EXISTING | Add-on | Add-on | Add-on |
| Dokumente und Erscheinungsbild | `documents.signature` Digitale Signatur | PLANNED | Add-on | Add-on | Add-on |
| Finanzen | `finance.ledger` Kassenbuch | EXISTING | – | ✓ | ✓ |
| Finanzen | `finance.fines` Bussen | EXISTING | – | ✓ | ✓ |
| Finanzen | `finance.reports` Finanzberichte | EXISTING | – | ✓ | ✓ |
| Finanzen | `finance.dues` Mitgliederbeiträge | PROPOSED | – | ○ | ○ |
| Finanzen | `finance.import` Bankimport | PROPOSED | – | ○ | ○ |
| Finanzen | `finance.categories` Kategorien und Budget | PROPOSED | – | ○ | ○ |
| Medien und Dateien | `media.photos` Fotos und Alben | EXISTING | ✓ | ✓ | ✓ |
| Medien und Dateien | `media.photo_intelligence` Fotos sortieren | EXISTING | ✓ | ✓ | ✓ |
| Medien und Dateien | `media.files` Dateien | EXISTING | ✓ | ✓ | ✓ |
| Medien und Dateien | `media.sharing` Teilen von Fotos | EXISTING | – | ✓ | ✓ |
| Abgaben | `submissions.box` Abgabebox | EXISTING | ✓ | ✓ | ✓ |
| Abgaben | `submissions.notifications` Eingangsbenachrichtigung | PROPOSED | – | ○ | ○ |
| Verwaltung und Datenschutz | `admin.tenant_settings` Vereinsprofil und Einstellungen | EXISTING | ✓ | ✓ | ✓ |
| Verwaltung und Datenschutz | `admin.custom_domain` Eigene Domain | EXISTING | – | – | ✓ |
| Verwaltung und Datenschutz | `admin.privacy` Datenschutzeinstellungen | EXISTING | ✓ | ✓ | ✓ |
| Verwaltung und Datenschutz | `admin.retention` Aufbewahrung und Löschvorschläge | EXISTING | ✓ | ✓ | ✓ |
| Verwaltung und Datenschutz | `admin.activity` Aktivitätsprotokoll | EXISTING | ✓ | ✓ | ✓ |
| Verwaltung und Datenschutz | `admin.data_export` Vereinsexport | EXISTING | ✓ | ✓ | ✓ |
| Verwaltung und Datenschutz | `admin.subscription` Abo und Nutzung | PARTIAL | ◐ | ◐ | ◐ |
| Verwaltung und Datenschutz | `admin.api` API und Webhooks | PROPOSED | Add-on | Add-on | Add-on |

## 4. Vorhandene und fehlende Features je Abo (Gap-Analyse)

### 4.1 Basic
1. **Sofort nutzbar:** Protokolle mit Workflow und Live-Zusammenarbeit, Sitzungsvorlagen, Bausteine,
   Zyklen, Anliegen, Pendenzen, Termine, Anwesenheit, Listen, Auswertungen, Kalender-Abos, Word-Import,
   Teilnehmende, Konten mit MFA, Standardrollen, Datenauskunft, Dokumente mit Systemvorlagen und eigenem
   Erscheinungsbild (alle Darstellungsvarianten), Echtheitsprüfung, Fotos, Dateien, Abgabebox,
   Datenschutz, Aufbewahrung, Aktivität, Vereinsexport.
2. **Fertigzustellen:** Pendenzenstatus «abgebrochen», Word-Import-Oberfläche vereinheitlichen,
   Abo-Seite mit Upgrade-Anfrage.
3. **Neu empfohlen:** E-Mail-Versand (Infrastruktur), Passwort-Reset, Versand von Einladung/Protokoll
   (manuell), Login-Einladung.
4. **Später:** Globale Suche.
- **Zielzustand:** Ein kleiner Verein organisiert Sitzungen vollständig in hocX, inklusive Versand.
- **Minimum Marketable Package:** vorhandene Funktionen + Passwort-Reset + manueller Versand. Ohne
  Passwort-Reset ist das Paket nur mit Supportaufwand vermarktbar.
- **Bewertung:** Stark; eher zu grosszügig (Abgabebox und Designvarianten) – bewusst als Einstiegsargument.

### 4.2 Pro
1. **Sofort nutzbar:** alles aus Basic + Kassenbuch, Bussen, Finanzberichte, Aufgabenpakete,
   Dokument-Designer und Gestaltungsbeispiele, Teilen von Fotos (Links, Partner-Alben).
2. **Fertigzustellen:** Feature-Beschreibung Finanzen («Beiträge») ehrlich machen.
3. **Neu empfohlen:** Mitgliederbeiträge mit QR-Rechnung, Erinnerungen, An-/Abmeldung per Link,
   automatischer Versand beim Abschluss, Beschlussregister.
4. **Später:** Jahresbericht, Eingangsbenachrichtigung Abgabebox, Bankimport.
- **Zielzustand:** Der Verein spart messbar wiederkehrende Arbeit (Kasse, Erinnerungen, Pakete).
- **Minimum Marketable Package:** heute bereits glaubwürdig (Finanzen + Aufgabenpakete + Designer +
  Teilen). Beiträge und Erinnerungen machen es deutlich stärker, sind aber keine Voraussetzung.
- **Bewertung:** Klarer Abstand zu Basic durch echte Zusatzfunktionen statt Einschränkungen.

### 4.3 Business
1. **Sofort nutzbar:** alles aus Pro + eigene Rollen, eigene Domain, unbegrenzte Konten, 100 GiB.
2. **Fertigzustellen:** Überlast-Priorität «hoch» im Plan setzen.
3. **Neu empfohlen:** Mandanten-SSO, Gremien und Bereiche.
4. **Später:** Aktivitätsexport, Rechte-Bericht, API/Webhooks (Add-on).
- **Zielzustand:** Organisationen mit IT- und Governance-Anforderungen.
- **Minimum Marketable Package:** vorhanden, aber dünn (eigene Rollen + Domain + Limits). Vor einer
  aktiven Vermarktung an Verbände SSO oder Gremien ergänzen [A].
- **Bewertung:** Schwächstes Paket; aktuell vor allem «mehr vom Gleichen». Gremien sind das
  stärkste fehlende Argument.

### 4.4 Ist die Abgrenzung klar?
- Basic ↔ Pro: klar (Finanzen, Automatisierung, Gestaltung, Teilen).
- Pro ↔ Business: heute schwächer; wird mit SSO und Gremien klar.
- Kein Paket schränkt Grundfunktionen künstlich ein: Datenschutz, Export, Echtheitsprüfung, Standardrollen,
  Live-Zusammenarbeit sind überall enthalten.
- Feature im falschen Paket? `abgabebox` in Basic ist grosszügig, aber Differenzierung; Kosten werden
  über das Speicherkontingent begrenzt. `custom_roles` wäre auch in Pro vertretbar – bewusst Business,
  weil es vor allem grössere Organisationen brauchen [A].

## 5. Upgrade-Pfade (Upselling)

### 5.1 Feature-basiert
| Situation | Mehrwert im höheren Abo |
|---|---|
| Kassier führt Kasse und Bussen in Excel neben hocX | Pro: Bussen entstehen aus der Anwesenheit und werden als Buchung eingezogen |
| Jedes Lagerjahr dieselben 40 Aufgaben neu erfassen | Pro: Aufgabenpakete erzeugen sie je Zyklus automatisch |
| Vorstand will Protokolle im Vereinsdesign | Pro: Designer und Gestaltungsbeispiele (Basic sieht die Beispiele, Import verlangt Pro) |
| Fotos sollen Eltern/Partnervereinen gezeigt werden | Pro: Freigabelinks und Partner-Alben |
| GL braucht Rollen wie «Revisor» oder «Kommission» | Business: eigene Rollen |

### 5.2 Wachstumsbasiert
- Mehr als 10 bzw. 30 Konten mit Login → nächster Plan oder Benutzerpaket (Limit jetzt durchgesetzt).
- Mehrere Gremien (geplant) → Business.

### 5.3 Nutzungsbasiert
- Speicher (Fotos, Abgaben) → Speicherpakete oder nächster Plan. Kontingent wird durchgesetzt; bestehende
  Dateien bleiben, nur neue Uploads werden abgelehnt.

### 5.4 Add-on-Umsätze
- Speicherpakete, eigene Prüf-Domain, eigene Domain für Pro, Benutzerpakete (vorgeschlagen),
  Word-Import als Dienstleistung.

### 5.5 Was bewusst vermieden wird
- Keine Sperre von Lesezugriff nach Downgrade (Nur-Lesen-Zustand).
- Keine Begrenzung der Anzahl Protokolle, Pendenzen oder Termine.
- Annehmen von Partner-Alben bleibt in jedem Abo möglich (Netzwerkeffekt).

## 6. Nutzungslimits

| Limit | Basic | Pro | Business | Durchsetzung |
|---|---|---|---|---|
| Konten mit Login | 10 | 30 | unbegrenzt | `user_limit_service.py` (neu) |
| Speicher | 5 GiB | 20 GiB | 100 GiB | `upload_pipeline.py` (bestehend) |
| Abgabebox-Speicher | min(Kontingent, 2 GiB) | dito | dito | `abgabebox-backend` (bestehend; Empfehlung: an Plan koppeln) |
| Überlast-Priorität | normal | normal | hoch (Empfehlung) | `db_admission.py` |

Keine Mengenlimits für Protokolle, Dokumente oder Fotos: sie verärgern Kunden und sind über Speicher
bereits begrenzt.

## 7. Wirtschaftliche Bewertung

- Die neue Struktur nutzt vorhandene Funktionen für die Differenzierung: Pro und Business sind ohne
  Neuentwicklung marktfähig. Neuentwicklung braucht es vor allem für Basic-Vollständigkeit (E-Mail,
  Passwort-Reset, Versand) und für die Stärkung von Pro (Beiträge, Erinnerungen) und Business (SSO, Gremien).
- Kostenrelevante Funktionen (Speicher, Rechenzeit Fotoanalyse, Domains) sind über Limits oder Add-ons
  abgedeckt.
- Grösster Hebel [A]: E-Mail-Infrastruktur – sie schaltet sechs Features frei.

## 8. Risiken und offene Annahmen

| Risiko/Annahme | Umgang |
|---|---|
| Bestandsschutz gibt allen Bestandsmandanten die neuen Features dauerhaft | gewollt (kein stiller Funktionsverlust); bei Vertragsverlängerung bewusst in einen Plan überführen |
| Basic könnte für kleine Vereine zu teuer sein (CHF 99 Seed) [A] | Preis im Adminportal prüfen; ggf. Jahresrabatt nutzen |
| Business ist ohne SSO/Gremien schwach | Vertrieb an Verbände erst nach Phase 4/5 |
| Zählweise der Benutzer geändert (nur Konten mit Login) | Zahlen in Abo-Ansicht sinken; fair, aber Kommunikation nötig |
| Abgabebox-Speicherdeckel (2 GiB) unabhängig vom Plan | an Plan koppeln (Roadmap) |
| Bekommt eines der vier Bestandsschutz-Features später einen Einzelpreis, würde er allen Bestandsmandanten berechnet (`cashflow_service` bepreist Zusatzmodule) | vor dem Setzen eines Einzelpreises Bestandsschutz-Zeilen kennzeichnen oder ausnehmen; Nur-Lesen-Features werden bereits nicht mehr berechnet |
