# Abgabebox

Die Abgabebox ist ein **öffentlicher, anmeldefreier Datei-Upload** auf einer eigenen
Subdomain – gedacht für Externe, die z. B. Belege oder Formulare einreichen sollen, ohne
selbst einen hocX-Account zu benötigen.

- Konfiguriert wird eine Abgabe unter *Abgaben* im normalen Vereinsbereich.
- **Verknüpfung:** Eine Abgabe ist an *Termine* (ein Abgabefeld pro Termin mit einem Tag,
  mit Zeitfenster relativ zum Termin), an eine *Liste* (ein Abgabefeld pro Listeneintrag, mit
  gemeinsamem Stichtag) oder *manuell* gekoppelt. Eine manuelle Abgabe hat genau ein
  Abgabefeld, das wie die Abgabe heisst, unabhängig von Terminen und Listen; ein Stichtag ist
  optional. Ohne Zeitfenster bzw. Stichtag bleibt eine Abgabe offen, bis sie manuell
  geschlossen wird.
- **Zyklusfilter (bei Terminen):** Eine Abgabe nach Terminen lässt sich auf einen Zyklus
  beschränken, z. B. nur auf Termine des aktuellen oder des vorigen Zyklus.
- **Doppelte Dateien:** Reicht jemand exakt dieselbe Datei für dasselbe Abgabefeld erneut
  ein, bestätigt die Abgabebox den Upload wie gewohnt, speichert die Datei aber nur einmal.
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
