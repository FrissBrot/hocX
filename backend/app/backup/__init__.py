"""Backup-Kern (BorgBackup 1.4, Hetzner Storage Box) - siehe docs-site/docs/technik/backup/.

Die Module hier hängen bewusst NICHT von app.core.config/app.core.db ab: die Recovery-CLI
(app.backup.cli) muss auf einem frisch aufgesetzten Server ohne laufendes Backend, ohne Redis und
ohne hocX-Datenbank funktionieren. Datenbankzugriff bekommen sie immer als Parameter.
"""
