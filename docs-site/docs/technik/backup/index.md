# Backup & Recovery (BorgBackup)

Verschlüsseltes, inkrementelles Offsite-Backup von PostgreSQL und Dateispeicher auf die Hetzner
Storage Box – ohne lokalen Spiegel des Objektspeichers, mit vollständigen
Wiederherstellungspunkten, Voll-Restore, unabhängiger Recovery-CLI und Mandanten-Restore als Kopie.

- [Architektur](architektur.md) – Repository-Layout, inkrementelle Sicherung, Konsistenz (Backup-Hold), Retention
- [Einrichtung und Betrieb](betrieb.md) – Storage Box, Schlüssel, Variablen, erstes Backup, Kapazität, Abnahme
- [Wiederherstellung](restore.md) – Mandant als Kopie, Voll-Restore, Recovery-CLI, Notfälle
- [Sicherheit](sicherheit.md) – Berechtigungen, Secrets, Ransomware-Resistenz und Grenzen
- [Backup-Testbook](../backup-testbook.md) – automatisierte und manuelle Prüfungen, Hetzner-Abnahme
