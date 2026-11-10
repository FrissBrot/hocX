# Dateispeicher (S3) und Wartung

hocX speichert alle persistenten Dateien ausschliesslich in einem S3-kompatiblen Objektspeicher.
Eine Neuinstallation startet direkt auf dem eingebauten lokalen S3 (Garage, Profil «Lokales S3
(Garage)»). Der Speicher lässt sich im laufenden Betrieb zwischen beliebigen S3-Profilen (lokal,
AWS, Hetzner, andere S3-kompatible Anbieter) migrieren.

Den Dateisystem-Speicher von 1.2 (Generation 0) gibt es nicht mehr. Wer von 1.2.x aktualisiert,
liest zuerst [Upgrade auf S3-only](migration.md#upgrade-auf-s3-only).

| Seite | Inhalt |
|---|---|
| [Architektur](architektur.md) | Abstraktion, Keys, Generationen, Fencing, Journal, Sicherheitsmodell |
| [Installation & Konfiguration](betrieb.md) | Umgebungsvariablen, externe Anbieter, Monitoring, Troubleshooting |
| [Lokales S3](lokales-s3.md) | Garage-Container, Einrichtung, Host-Controller |
| [Migrationen](migration.md) | Live-Migration, Cutover, Zustände, Fehlerfälle, Upgrade auf S3-only |
| [Wartungsmodus](wartung.md) | Wartungsfenster, Sperre, Schätzung, Freigabe |
| [Backup, Restore & Recovery](backup.md) | Konsistente Sicherung, Wiederherstellung, Rollback, Bereinigung |
