# hocX – Erweiterungskatalog (neue Features)

Stand: 2026-10-27. Enthält alle **neu vorgeschlagenen** oder **unvollständigen** Features aus
`docs/COMPLETE_FEATURE_CATALOG.md` mit Problem, Lösung, Nutzen, Aufwand und Bewertung. Zeitliche
Einplanung: `docs/PRODUCT_IMPLEMENTATION_ROADMAP.md`.

Bewertungsskala (qualitativ, [A]): Nutzen / Upsell / Differenzierung / Risiko / Wartung / Betriebskosten
je **hoch · mittel · gering**. Aufwand S (≤ 3 Tage), M (1–2 Wochen), L (> 2 Wochen) für eine Person.
Keine Umsatzzahlen; alle Markteinschätzungen sind Hypothesen.

**Notwendig** = vor Vermarktung des Zielpakets nötig. **Optional** = Idee mit späterem oder unsicherem Nutzen.

---

## 1. Fehlende Kernfunktionen (notwendig)

### 1.1 E-Mail-Versand (`platform.email`) – P0, notwendig
- **Problem:** hocX kann keine E-Mail senden. Dadurch fehlen Passwort-Reset, Einladungen, Versand von
  Protokollen, Erinnerungen und Eingangsmeldungen der Abgabebox [F: keine SMTP-Implementierung in
  `backend/app`, `abgabebox-backend`].
- **Lösung:** Versanddienst (SMTP oder Schweizer Provider) mit mehrsprachigen Vorlagen aus
  `frontend/messages`, Versandprotokoll je Mandant (tenant_id + RLS), Job für Warteschlange,
  Bounce-/Abmelde-Handling. Secret vollständig verdrahten (SECURITY-RULES §5.2).
- **Nutzen:** Voraussetzung für sechs Features. **Aufwand:** M. **Abo:** Infrastruktur (alle).
- **Bewertung:** Nutzen hoch, Upsell indirekt hoch, Risiko mittel (Zustellbarkeit, Missbrauch → Rate-Limit),
  Wartung mittel, Betriebskosten gering bis mittel (Provider pro Nachricht).
- **Abhängigkeiten:** keine.

### 1.2 Passwort per E-Mail zurücksetzen (`people.password_reset`) – P0, notwendig
- **Problem:** Vergessenes Passwort = Supportfall für den Vereinsadmin oder hocX.
- **Lösung:** Einmal-Link per E-Mail (Token im Fragment, nie im Query, SECURITY-RULES §3.2),
  Rate-Limit, `session_revoke_at` setzen.
- **Nutzen:** weniger Support, Basiserwartung. **Aufwand:** S–M. **Abo:** Basic.
- **Bewertung:** Nutzen hoch, Risiko mittel (Auth-Bereich → Security-Review), Wartung gering.
- **Abhängigkeiten:** `platform.email`.

### 1.3 Versand von Einladung und Protokoll (`meetings.distribution`) – P0, notwendig
- **Problem:** Das Website-Versprechen «Vorher – Während – Nachher» endet beim PDF-Download; der
  Versand passiert ausserhalb (Medienbruch).
- **Lösung:** Aktion «Versenden» im Export-Dialog: Empfänger aus der Vorlage, PDF als Link (verifizierbar)
  oder Anhang, Versandprotokoll im Protokoll.
- **Nutzen:** schliesst den Kern-Workflow. **Aufwand:** M. **Abo:** Basic (manuell), automatischer
  Versand beim Abschluss in Pro.
- **Bewertung:** Nutzen hoch, Upsell mittel (Automatik), Differenzierung mittel, Risiko gering.
- **Abhängigkeiten:** `platform.email`, `documents.exports`.

### 1.4 Benutzerlimit durchsetzen (`people.user_limit`) – P0, **umgesetzt**
- War nur Anzeige. Jetzt: Konten mit Login (aktiv) zählen, Aktivieren über dem Limit → 409.
  Plattform-Admin darf überschreiten. Code: `services/user_limit_service.py`.

### 1.5 Nur-Lesen-Zustand nach Downgrade – P0, **umgesetzt**
- War: Entzug sperrt auch Lesen. Jetzt: `tenant_feature.access = 'read_only'`, Lesen erlaubt,
  Schreiben gesperrt (`docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md`).

## 2. Abrundung bestehender Module

### 2.1 Mitgliederbeiträge mit QR-Rechnung (`finance.dues`) – P1, notwendig für Pro
- **Problem:** Das Feature `finance` verspricht «Kassenbuch, Beiträge und Bussen», Beiträge fehlen
  [F: `0084_tenant_feature.py`]. Der Beitragseinzug ist die aufwändigste Kassieraufgabe [A].
- **Lösung:** Beitragskategorien, Zuordnung je Person (aus `people.participants`), Rechnungslauf als
  Dokument mit Swiss QR Bill, offene Posten, manueller Zahlungsabgleich, Buchung ins Kassenbuch.
- **Nutzen:** hoch für Vereine. **Aufwand:** M–L. **Abo:** Pro.
- **Bewertung:** Nutzen hoch, Upsell hoch (stärkster Grund für Finanzen), Differenzierung hoch,
  Risiko mittel (Rechnungsrecht, QR-Spezifikation), Wartung mittel.
- **Abhängigkeiten:** `finance.ledger`, Dokument-Engine; neue Tabellen mit `tenant_id` + RLS.
- **Übergang:** bis zur Umsetzung Feature-Beschreibung korrigieren (Quick Win).

### 2.2 Pendenzenstatus «abgebrochen» (`meetings.todos`) – P2, Quick Win
- Backend kennt `cancelled`, Oberfläche nicht. Aufwand S. Abo: Basic.

### 2.3 Änderungsverfolgung vereinheitlichen (`meetings.track_changes`) – P2
- Aktiv nur im Status «geplant», Bereinigung erst nach «vorbereitet»; Default DB `true` ↔ Schema `False`.
  Lösung: klares Modell (Vorbereitung = nachverfolgt, Sitzung = Markierungen auflösen), Default angleichen.
  Aufwand S–M. Abo: Basic.

### 2.4 Word-Import: eine Oberfläche (`meetings.word_import`) – P2
- Zwei parallele Wege (Warteschlange `/tools/import`, Assistent `/tools/word-import`). Zusammenführen in
  der Protokollliste. Aufwand M. Abo: Basic. Nutzen: weniger Verwirrung beim Onboarding.

### 2.5 Abo-Seite mit Upgrade-Anfrage (`admin.subscription`) – P1, Quick Win
- Heute nur lesend. Lösung: Feature-Liste des nächsthöheren Plans mit «Anfrage senden» (Audit-Eintrag +
  Benachrichtigung an hocX; später Self-Service). Aufwand S. Upsell hoch.

### 2.6 Eingangsbenachrichtigung Abgabebox (`submissions.notifications`) – P2
- Verantwortliche erfahren nicht von neuen Abgaben. E-Mail je Abgabe oder Tageszusammenfassung.
  Aufwand S (nach `platform.email`). Abo: Pro.

## 3. Produktivitätsverbesserungen

### 3.1 Globale Suche (`meetings.search`) – P2, optional
- Problem: nur Suche in der Protokollliste und im einzelnen Protokoll. Lösung: PostgreSQL-Volltext über
  Protokolltext, Pendenzen, Anliegen, Termine, Dateinamen, berechtigungsgefiltert.
  Aufwand M–L. Abo: Basic. Wert steigt mit Archivgrösse; kein Upsell-Feature.

### 3.2 Login-Einladung (`people.invitations`) – P1
- Admin setzt heute Passwörter. Einladung per E-Mail mit Erstanmeldung. Aufwand S–M. Abo: Basic.

### 3.3 Jahresbericht (`meetings.reports`) – P2, Quick Win
- Systemvorlage «Jahresbericht» aus vorhandenen Bausteinen (Statistik, Anwesenheit, Pendenzen, Finanzen).
  Aufwand S–M. Abo: Pro.

## 4. Automatisierung

### 4.1 Erinnerungen (`meetings.reminders`) – P1
- **Problem:** Vorstände fassen Pendenzen und Anmeldungen von Hand nach.
- **Lösung:** Job für fällige/überfällige Pendenzen und bevorstehende Sitzungen; Einstellungen je Konto;
  Abmeldelink (siehe 4.2).
- **Aufwand:** M. **Abo:** Pro. **Bewertung:** Nutzen hoch, Upsell hoch, Wartung mittel, Kosten gering.
- **Abhängigkeiten:** `platform.email`.

### 4.2 An-/Abmeldung per Link (`meetings.rsvp`) – P1
- Personen ohne Login melden sich über persönlichen Link ab; Status fliesst in die Anwesenheit.
  Token nie im Query (Fragment), Rate-Limit. Aufwand M. Abo: Pro.

### 4.3 Automatischer Versand beim Abschluss – P1 (Teil von `meetings.distribution`)
- Protokoll wird beim Abschluss automatisch versendet. Aufwand S nach 1.3. Abo: Pro.

## 5. Reporting

- `meetings.reports` (3.3).
- **Aktivitätsprotokoll exportieren** (Erweiterung `admin.activity`) – P3, Business, Aufwand S.
- **Rechte-Bericht** (wer darf was) aus RBAC – P3, Business, Aufwand S. Nutzen für Revisionen.

## 6. Premiumfunktionen

### 6.1 Beschlussregister (`meetings.decisions`) – P1
- Beschluss als eigener Blocktyp mit Abstimmungsresultat; Register über alle Protokolle; Darstellung
  «Beschluss» existiert bereits (Zitat-Variante Kasten/Linien im Brand Studio).
- Aufwand M. Abo: Pro. Differenzierung hoch für GL/Vorstände.

### 6.2 Gremien und Bereiche (`meetings.committees`) – P2
- Mehrere Gremien je Mandant mit eigenem Zugriff (heute ungenutzt: `UserTemplateAccess`).
- Aufwand L. Abo: Business. Skaliert mit Organisationsgrösse; Alternative heute: mehrere Mandanten.

### 6.3 Mandanten-SSO (`people.sso`) – P2
- OIDC für Benutzer (Microsoft/Google), Wiederverwendung der Plattform-OIDC. Aufwand M–L. Abo: Business.

## 7. Integrationen und Add-ons

| Add-on | Empfehlung | Begründung |
|---|---|---|
| Eigene Prüf-Domain (`verify_domain`) | Add-on beibehalten | Nische, Betriebsaufwand je Domain |
| Speicherpakete | Add-on beibehalten | nutzungsbasiert, verursachergerecht |
| Zusatzkonten (Benutzerpakete) | **neu als Add-on** | wachsende Vereine ohne Planwechsel; Limit ist jetzt durchgesetzt |
| Word-Import als Dienstleistung | als Service anbieten | Website verspricht «übernehmen wir für Sie» |
| API und Webhooks (`admin.api`) | nur bei Nachfrage, Add-on | Sicherheits- und Wartungsaufwand hoch |
| Eigene Domain (`custom_domain`) | in Business, als Add-on für Pro | Betriebsaufwand, Prestige |
| Digitale Signatur (`documents.signature`) | zurückstellen | hoher Aufwand, wenige Kunden |

## 8. Langfristige Erweiterungen (optional)

- Registrierung und Testphase (`platform.self_signup`) – P1 für Wachstum, M–L.
- Online-Zahlung der Abos (`platform.payments`) – P2, ab grösserer Kundenzahl.
- Bankimport (`finance.import`) – P2 nach Beiträgen.
- Kategorien und Budget (`finance.categories`) – P3.
- Mobile Ansichten für Desktop-only-Bereiche (Bausteine, Aufgabenpakete, Designer) – P3, geringer Nutzen,
  da Konfiguration am Desktop stattfindet.

## 9. Nicht empfohlen

| Idee | Warum nicht |
|---|---|
| Vollständige Buchhaltung (MWST, Bilanz, Kontenrahmen) | Fremdes Fachgebiet, hoher Wartungsaufwand; Kassenbuch + Beiträge + Export reicht für Vereine [A] |
| Gesichtserkennung (Personen identifizieren) | Datenschutzrisiko, widerspricht Positionierung; heutige Detektion nur zur Qualitätsbewertung beibehalten |
| Gleichzeitiges Bearbeiten desselben Felds (CRDT/OT) | Feldsperren reichen für Sitzungen; hoher Aufwand und Risiko |
| Native Apps | Mobile Web deckt Kernfälle ab; doppelter Wartungsaufwand |
| Chat/Messenger | Kein Kernnutzen, Wettbewerb mit WhatsApp & Co. |
| KI-Protokollzusammenfassung | Hypothese: interessant, aber Datenschutz (Personendaten an Drittanbieter) und Kosten ungeklärt – erst nach Kundenbefragung prüfen |
| Feature-Flags für einzelne Buttons/Ansichten | Erhöht Komplexität ohne kommerziellen Nutzen (Grundsatz der Entitlement-Architektur) |
