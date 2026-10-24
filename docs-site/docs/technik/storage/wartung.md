# Wartungsmodus

## Wartungsfenster

`maintenance_window` (persistiert in PostgreSQL) beschreibt genau einen Grund:

| Feld | Bedeutung |
|---|---|
| `kind` | `full` (Anwendung gesperrt) oder `partial` |
| `block_scope` | `all`, `writes`, `uploads` |
| `state` | `scheduled`, `preparing`, `active`, `verifying`, `overdue`, `failed`, `completed`, `cancelled` |
| `release_conditions` | feste, serverseitig geprüfte Bedingungen (z. B. `storage_migration_settled`) |
| `estimate`, `estimated_end_at`, `original_estimated_end_at`, `safety_margin_seconds` | Schätzung |
| `public_message` | Text je Sprache (leer = Standardtext) |

Blockierend sind `preparing`, `active`, `verifying`, `overdue` **und `failed`**. Mehrere Fenster
können gleichzeitig blockieren; die Sperre endet erst, wenn kein blockierendes mehr besteht.
Kein Timer und kein Job beendet ein Fenster: `release()` prüft die Bedingungen und lehnt sonst ab
(Ablehnung im Verlauf). Zusätzlich gilt immer «kein offener Cutover» – auch manuelle Wartung
kann kein Fence umgehen.

| Job | Wartung |
|---|---|
| Erstmigration des Speichers | voll, Freigabe nach bestandener Endprüfung |
| Live-Kopie | keine |
| Cutover einer Live-Migration | `partial/writes`, nur für die Unterbrechung |
| gewöhnliche Hintergrundjobs | keine (pausieren aber während voller Wartung) |
| manuelle Wartung | voll oder teilweise, Freigabe durch Admin |

## Durchsetzung

- **Backend**: ASGI-Middleware `app/core/maintenance_middleware.py`. Volle Wartung → jede
  `/api`-Anfrage 503 mit `Retry-After` und `code: maintenance`, WebSockets werden mit 1013
  geschlossen. Ausgenommen: `/api/health`, `/api/public/maintenance-status`, die Admin-API
  (Notfallzugang über den geschützten Admin-Zugang), `/api/system-status/summary`, Logout,
  Mandantenauflösung der Anmeldeseite. Teilweise Wartung sperrt nur Schreib- bzw. Upload-Anfragen.
- **Abgabebox**: eigene Middleware (`abgabebox-backend/app/maintenance.py`) über
  `maintenance_effective_state()`.
- **Hintergrundjobs**: `run_advisory_locked_loop` überspringt Ticks während voller Wartung
  (ausser `system_monitor` und `maintenance_supervisor`); der Foto-Worker übernimmt keine Aufträge.
- **Speicher**: zusätzlich das Schreib-Fence (siehe Architektur) – eine zweite, unabhängige Sperre.
- Prozesse cachen den Zustand max. 2 s; bei DB-Ausfall gilt der letzte bekannte Zustand weiter.

## Anzeige

- Anmeldeseite: Hinweis «hocX wird gerade gewartet», Anmeldung ausgeblendet, Polling alle 15 s,
  danach automatisch wieder das normale Formular.
- Angemeldete Benutzer: 503 mit Wartungscode bzw. die Sitzungsprüfung leiten auf `/maintenance`
  (kehrt nach dem Ende automatisch zurück).
- Geplante Wartungen werden vorab angekündigt.

## Dauerabschätzung

`app/services/maintenance_estimator.py`:

```
Rate        = min(aktuelle Rate, Durchschnitt, p10 historischer Raten) × 0.75
Kopie       = verbleibende Bytes / Rate + verbleibende Objekte × Overhead / Parallelität
Basis       = Initialisierung + Kopie + Verifikation + Cutover + Healthchecks
Reserve     = max(Mindestreserve, Basis × (p90 historischer Überschreitung − 1))   # ≥ 3 Läufe
            = max(Mindestreserve, Basis × Sicherheitsfaktor)                       # sonst
Spanne      = [Basis, Basis + Reserve]
```

Ohne Grundlage (vor der Inventur) gibt es keine Zahl («wird ermittelt»). Angezeigt werden
gerundete Spannen (5-Minuten-Schritte ab 15 min, Stunden ab 2 h). Das geschätzte Ende rückt bei
Verzögerung nach hinten; überschritten → Zustand `overdue` und die Meldung «Die Wartungsarbeiten
dauern länger als erwartet …» – nie ein Countdown auf null. Für den Cutover einer Live-Migration
zählt nur die Unterbrechung.

## Öffentlicher Endpunkt

`GET /api/public/maintenance-status` (`Cache-Control: no-store`): aktiv, teilweise, Sperrumfang,
Grund-Code, Meldungen, betroffene Bereiche, Beginn, Schätzstatus, geschätztes Ende, gerundete
Restspanne, Ankündigungen, Zeitstempel. Keine Job-IDs, Profil-/Bucket-Namen oder Fehlertexte.

## Verwaltung (System → Wartung)

Aktuelle Fenster mit Grund, Verursacher, Beginn, Laufzeit, geschätztem und ursprünglichem Ende,
Reserve, Fortschritt, betroffenen Bereichen, Fehlern und Freigabebedingungen; geplante Fenster;
Verlauf. Aktionen: planen, sofort kontrolliert starten, Meldung je Sprache bearbeiten, absagen,
beenden (nur bei erfüllten Bedingungen). Alles mit Audit-Log.
