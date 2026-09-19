# Abgabebox

Die Abgabebox ist ein **öffentlicher, anmeldefreier Datei-Upload** auf einer eigenen
Subdomain – gedacht für Externe, die z. B. Belege oder Formulare einreichen sollen, ohne
selbst einen hocX-Account zu benötigen.

- Konfiguriert wird eine Abgabe unter *Abgaben* im normalen Vereinsbereich.
- **Zugang per Link:** Die Abgabebox ist nur über einen Link erreichbar, dessen Adresse einen
  zufällig erzeugten Schlüssel enthält – wer den Link kennt, kann die damit verknüpften
  Abgaben nutzen. Unter *Abgaben → Links* legst du beliebig viele Links mit einem frei
  wählbaren Namen an (z. B. „Eltern“, „Leiterteam“). Der Name ist nur für dich sichtbar.
  Im Formular einer Abgabe wählst du, über welche Links sie erreichbar ist. Jeder Verein
  startet mit einem Standard-Link, der bei neuen Abgaben vorausgewählt ist.
- **Link zurückziehen:** Mit „Neuen Schlüssel erzeugen“ wird die bisherige Adresse sofort
  ungültig, ebenso beim Löschen des Links. Abgaben ohne ausgewählten Link sind nicht
  erreichbar.
- Hochgeladene Dateien werden automatisch auf Viren geprüft, bevor sie sichtbar/
  abrufbar sind.
- Der Upload-Bereich läuft aus Sicherheits- und Isolationsgründen als komplett
  getrennte Anwendung mit eigener, stark eingeschränkter Datenbankrolle – Details siehe
  [Technik & Betrieb](../technik/architektur.md#abgabebox).
