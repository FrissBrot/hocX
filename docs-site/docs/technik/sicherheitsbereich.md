# Sicherheitsbereich der Konsole: Vorfälle und Lagebild (1.6)

Der Sicherheitsbereich des Plattform-Admins (`/admin/security/*`, nur Rolle **owner**) zeigt den
Anmeldeschutz der ganzen Plattform. Ab 1.6 gibt es zwei neue Seiten: **Vorfälle** und das
**Lagebild** (ersetzt die bisherige Übersicht). Sperren, Anmeldeereignisse, Alarmregeln und das
Audit-Log kamen mit 1.6.

## Für Plattform-Admins: so arbeitest du damit

### Vorfälle

- Jede ausgelöste Alarmregel landet automatisch in **genau einem offenen Vorfall** je Regel und
  Quelle (z. B. «Password Spraying aus Netz 3f9a1c07be42»). Löst dieselbe Regel für dieselbe Quelle
  erneut aus, zählt der offene Vorfall eine weitere Auslösung, statt einen zweiten anzulegen.
- **Übernehmen** macht dich zuständig und setzt den Vorfall auf «In Bearbeitung». Zuständig sein
  kann jeder aktive Owner; die Auswahl «Zuständig» ändert das.
- Status: **Neu**, **In Bearbeitung**, **Erledigt**, **Fehlalarm**. Beim Abschliessen kannst du eine
  Begründung angeben (erscheint als Notiz).
- Ein Vorfall schliesst nie von selbst. Klingt die Regel ab, steht in der Zeitleiste «abgeklungen»;
  löst sie wieder aus, solange der Vorfall offen ist, gehört das zum selben Vorfall. Nach dem
  Abschliessen eröffnet erst ein **neues** auslösendes Ereignis einen neuen Vorfall.
- **Notizen** kurz und ohne Personendaten halten (keine Namen, Adressen, E-Mails).
- **Netz sperren (Stufe 5)** gibt es bei Vorfällen eines Netzes (Spraying, viele Fehlversuche aus
  einem Netz, mehrere Mandanten): manuelle Sperre des Netz-Fingerprints (/24 bzw. /48) mit Dauer und
  Begründung, wie «Quelle sperren» bei den Anmeldeereignissen.
- Jede Änderung (Status, Zuständig, Notiz, Sperre) bestätigst du mit deinem **Passkey**; sie steht
  im Audit-Log (`admin.security_incident_*`, ohne Notiztext).
- Filter (Status, Schwere, Zuständig, Ansicht Liste/Board) und der geöffnete Vorfall stehen in der
  Adresse und lassen sich teilen; die Suche (Nummer `INC-0042`, Regel, Pseudonym-Präfix) bleibt
  bewusst draussen.
- Die Glocke und die Zahl am Navigationseintrag «Vorfälle» zählen Vorfälle im Status **Neu**.

### Lagebild

- **Lage**: Ruhig, Erhöht (offene Vorfälle oder eine Regel nahe der Schwelle), Angriff (offener
  kritischer Vorfall, dessen Regel noch auslöst), Angriffsmodus (Credential Stuffing: unbekannte
  Geräte werden zusätzlich geprüft).
- Kennzahlen für 24 h oder 7 Tage mit Vergleich zur Vorperiode und Verlauf; Vorfälle links, das
  gewählte Detail rechts; Verlauf der Anmeldungen mit Vorfall-Markierungen; Fehlversuche nach
  Wochentag und Stunde; Messwert jeder Alarmregel gegen die Schwelle; Herkunft (Ländercode),
  auffällige Netze und Konten (gekürzte Pseudonyme).
- Jedes Diagramm hat «Daten als Tabelle». «Live» aktualisiert alle 30 Sekunden und lässt sich pausieren.

## Technik

### Datenmodell (Migration `0282_security_incidents`)

| Tabelle | Inhalt |
|---|---|
| `security_incident` | `id` (Anzeige `INC-0042`), `rule_key` (`auth:<regel>[:<pseudonym>]`), `rule`, `subject`, `severity` (warning/critical), `status` (new/in_progress/resolved/false_positive), `assignee_admin_id` (SET NULL), `tenant_id` (nur Regel «tenant», CASCADE), `first_seen_at`, `last_triggered_at`, `active`, `cleared_at`, `trigger_count`, `acknowledged_at` (erste Übernahme/Statusänderung), `closed_at`, `updated_at` |
| `security_incident_activity` | Zeitleiste: `triggered`, `retriggered`, `cleared`, `escalated`, `status`, `assigned`, `note`, `block` mit Admin, Von/Nach und Notiz (≤ 1000 Zeichen) |

- Partial-Unique-Index `uq_security_incident_open_key` auf `rule_key` für offene Status: genau ein
  offener Vorfall je Schlüssel, auch bei gleichzeitigen Läufen.
- Plattformdaten: RLS wie `auth_event` (ohne Mandantenbindung alles, mit Bindung nur eigene Zeilen),
  die Zeitleiste über den Vorfall. Gelesen und geschrieben wird nur über die Owner-Routen.
- Übernahme aus 0209: aktive Warnungen in `system_alert_state` wurden Vorfälle, quittierte «In
  Bearbeitung» mit dem quittierenden Admin und der Notiz. Die Quittungs-Spalten bleiben (Downgrade),
  werden aber nicht mehr geschrieben; die Routen `alerts/ack` und `alerts/unack` sind entfernt.

### Bündelung

`system_alert_service.evaluate_and_notify` (Loop `system_monitor`, alle 30 s) ruft nach dem
ntfy-Teil `app/auth_security/incidents.py::correlate` mit den Treffern von `threats.detect`:

1. offener Vorfall zum Schlüssel → `last_triggered_at`; war er abgeklungen → `retriggered`,
   `trigger_count + 1`; Schwere steigt → `escalated`;
2. kein offener → neuer Vorfall, ausser das letzte auslösende Ereignis liegt nicht nach `closed_at`
   des letzten abgeschlossenen Vorfalls desselben Schlüssels;
3. Schlüssel nicht mehr ausgelöst → `active = false`, `cleared`.

Schlägt die Erkennung fehl (`_auth_threats` = `None`), bleibt alles unverändert. Fehler in der
Bündelung landen im Fehlerprotokoll, ntfy läuft weiter.

### Lesen

Fakten, Zeitleiste, Beteiligte, Risikogründe (Gewichte aus `details.weights`) und die höchste
Abwehrstufe kommen beim Lesen aus `auth_event`: Bereich der Regel (Netz- bzw. Konto-Präfix mit den
Indizes `(src_net_hash, ts)`/`(subject_hash, ts)`, Admin, Mandant; plattformweite Regeln über ihre
Bedingung aus `threats._RULE_SQL`), Zeitraum = Regelfenster vor der ersten Erkennung bis jetzt bzw.
bis zum Abklingen, höchstens 14 Tage. Ältere Ereignisse sind nach `AUTH_EVENT_RETENTION_DAYS`
(90 Tage) gelöscht; der Vorfall selbst bleibt.

| Route (`/api/admin/auth-security/…`) | Recht |
|---|---|
| `GET situation?range=24h\|7d` | owner, 30 s Cache |
| `GET incidents`, `incidents/stats`, `incidents/{id}` | owner |
| `POST incidents/{id}/status`, `/assign`, `/notes` | owner + Passkey `security-incident`, Audit |
| `POST incidents/{id}/block` | owner + Passkey `security-block`, Audit, Sperre trägt `incident_id` |

### Aufbewahrung

Job `security_incident_retention` (täglich, Lock-ID 202600071, `/admin/jobs`) löscht Vorfälle samt
Zeitleiste und Notizen, deren letzte Aktivität (`updated_at` und `last_triggered_at`) älter als
`SECURITY_INCIDENT_RETENTION_DAYS` (Standard 365) ist. Vorfälle eines Mandanten verschwinden mit
dessen Löschung (CASCADE).

### Grenzen

- Ein Vorfall gehört zu genau einem Regelschlüssel; manuelles Zusammenführen kommt später.
- Nicht umgesetzt (Design-Ideen): Knoten-Graph (als Listen «Beteiligte» umgesetzt), «Mandanten
  informieren», «Gerät widerrufen», «Alle Admin-Sessions beenden».
