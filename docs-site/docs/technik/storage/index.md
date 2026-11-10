# Dateispeicher (S3) und Wartung

Seit 1.2 liegen alle persistenten Dateien von hocX in einem S3-kompatiblen Objektspeicher.
Beim ersten Deployment stellt hocX ein lokales S3 (Garage) automatisch bereit; der bisherige
Dateibestand wird in einem Wartungsfenster einmalig dorthin übertragen. Danach lässt sich der
Speicher im laufenden Betrieb zwischen beliebigen S3-Profilen (lokal, AWS, Hetzner, andere
S3-kompatible Anbieter) migrieren.

| Seite | Inhalt |
|---|---|
| [Architektur](architektur.md) | Abstraktion, Keys, Generationen, Fencing, Journal, Sicherheitsmodell |
| [Installation & Konfiguration](betrieb.md) | Umgebungsvariablen, externe Anbieter, Monitoring, Troubleshooting |
| [Lokales S3](lokales-s3.md) | Garage-Container, Einrichtung, Host-Controller |
| [Migrationen](migration.md) | Erstmigration, Live-Migration, Cutover, Zustände, Fehlerfälle |
| [Wartungsmodus](wartung.md) | Wartungsfenster, Sperre, Schätzung, Freigabe |
| [Backup, Restore & Recovery](backup.md) | Konsistente Sicherung, Wiederherstellung, Rollback, Bereinigung |
