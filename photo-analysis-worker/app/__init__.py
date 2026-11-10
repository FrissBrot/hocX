import os

# Gemeinsame Dateiablage (HOCX_STORAGE_PATH): Verzeichnisse 2770 und Dateien 0660 der Gruppe 5001,
# die alle Dienste teilen; deploy.sh prüft genau das und verlangt sonst root. Mit der Docker-
# Standard-umask 0022 legten die Dienste 2755/0644 an (andere Dienste der Gruppe konnten dort
# nicht schreiben, jeder weitere Deploy brach ab), über `docker compose exec` gestartete Skripte
# je nach Laufzeit sogar 2777/0666. Gilt für jeden Prozess, der dieses Paket lädt (Web, Worker,
# Skripte); Geheimnisse und SSH-Schlüssel setzen ihre Rechte weiterhin selbst (0600).
os.umask(0o007)
