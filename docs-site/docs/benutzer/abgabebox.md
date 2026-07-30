# Abgabebox

Die Abgabebox ist ein **öffentlicher, anmeldefreier Datei-Upload** auf einer eigenen
Subdomain – gedacht für Externe, die z. B. Belege oder Formulare einreichen sollen, ohne
selbst einen hocX-Account zu benötigen.

- Konfiguriert wird eine Abgabe unter *Abgabe-Assignments* im normalen Vereinsbereich.
- Hochgeladene Dateien werden automatisch auf Viren geprüft, bevor sie sichtbar/
  abrufbar sind.
- Der Upload-Bereich läuft aus Sicherheits- und Isolationsgründen als komplett
  getrennte Anwendung mit eigener, stark eingeschränkter Datenbankrolle – Details siehe
  [Technik & Betrieb](../technik/architektur.md#abgabebox).
