"""Anmeldeschutz (Auth-Audit 2026-11-20, docs: RUNBOOK «Anmeldeschutz»).

- ``events``: Sicherheitsereignisse ``auth_event`` schreiben (einheitliches Schema)
- ``context``: Merkmale des Requests (Quelle, Gerät, Browser) als Pseudonyme
- ``devices``: bekannte Geräte (signiertes Cookie, SEC-AUTH-006)
- ``guard``: Schichten der Zähler im Login (L1-L8, SEC-AUTH-003/-007)
- ``risk``: deterministische Risk Engine v1 (Abschnitt 7)
- ``blocks``: Stufenmodell der IP-Sperren (Abschnitt 8)
- ``sessions``: Session-Register (SEC-AUTH-011)
- ``step_up``: frische Anmeldung für kritische Aktionen (SEC-AUTH-010)
- ``notify``: Sicherheitsmails an die Person
- ``threats``: Alarmregeln für den Systemmonitor (Abschnitt 10.3)
- ``read_service``: Abfragen für Dashboards (Plattform und Mandant)
"""
