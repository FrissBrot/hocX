# Backup: Sicherheit und Berechtigungen

## Vertraulichkeit und Integrität

| Massnahme | Umsetzung |
|---|---|
| Clientseitige, authentifizierte Verschlüsselung | Borg `repokey-blake2` (AES-256-CTR + BLAKE2b-MAC); der Worker verweigert unverschlüsselte Repositories (`repository_not_encrypted`) |
| Integrität je Objekt | SHA-256 aus dem Objektregister, beim Lesen aus S3, beim Schreiben in Borg und bei jedem Restore geprüft; Pfad im Pool = SHA-256 |
| Gepinnte Identität | `BACKUP_REPOSITORY_ID` (Abweichung = Abbruch), Borg-Security-Verzeichnis erkennt Rücksetzungen (`repository_replay`) |
| SSH | eigene `known_hosts` bzw. Fingerprint, `StrictHostKeyChecking=yes`, `BatchMode`, nur Schlüssel-Login, `IdentitiesOnly` |
| Keine Secrets in Argumenten/Logs/API | Passphrase über `BORG_PASSCOMMAND` (liest die Secret-Datei), SSH-Schlüssel und `.pgpass` als private Kopien im tmpfs (0600), DB-Passwörter nie im `argv`; API liefert nur «vorhanden/fehlt» |
| Kein Docker-Socket, keine Shell | Borg/pg-Werkzeuge werden mit Argumentlisten gestartet; Archivnamen, Pfade und Datenbanknamen werden per Whitelist-Regex geprüft |
| Keine unkontrollierte Extraktion | nur bekannte Pfade (`pool/<sha>`, `db/…`, `manifest…`) werden gelesen; Manifest-Einträge werden wie fremde Eingaben validiert (Namespace, Key ohne Traversal, SHA-256, Grössen, Pool-Namen); Restores schreiben nur über die ObjectStore-Abstraktion |
| Ressourcen | Container mit `mem_limit`, `cpus`, `pids_limit`, `read_only`, `cap_drop: ALL`, `no-new-privileges`; Staging-Budget, Batchgrössen, Upload-Rate begrenzbar; tmpfs 256 MiB |

## Berechtigungen im Admin-Portal

| Aktion | Rolle | Zusätzlich |
|---|---|---|
| Status, Verlauf, Einstellungen lesen | Owner, Support | – |
| Backup starten, Prüfung, Restore-Test, Abbruch, Einstellungen ändern | Owner | Rate-Limit, Audit-Log (`backup.*`) |
| Restore-Vorschau | Owner | Rate-Limit |
| Restore starten (Voll und Mandant) | Owner | Bestätigungsphrase + **frischer TOTP-Code** (Replay-Schutz, Konto-Sperre nach Fehlversuchen), Audit-Log inkl. abgelehnter Versuche |

Admins ohne TOTP-Faktor (nur Passkey/SSO) können keinen Restore starten – sie müssen zuerst
einen TOTP-Faktor einrichten. Produktive Restores starten nie automatisch; automatisch läuft nur
der Restore-**Test** in eine isolierte Datenbank.

## Trennung der Zugänge

- **Backend**: keine Borg-Secrets, kein SSH, kein Repository-Zugang; legt nur Aufträge an.
- **backup-worker**: append-only-Schlüssel (kann sichern, aber nichts endgültig löschen),
  Passphrase, Superuser-DB-Zugang (pg_dump liest alle Tabellen, ein Voll-Restore legt Datenbanken
  an und benennt sie um).
- **Wartungsschlüssel**: nur offline beim Betreiber; nötig für `compact` (Platz freigeben).

## Ransomware-Resistenz und Grenzen

Angenommen, der Produktivserver ist vollständig kompromittiert (Root, alle Secrets):

| Angriff | Ergebnis |
|---|---|
| Archive löschen (`borg delete`, `prune`, `recreate`) | wirkt nur logisch – im append-only-Modus bleiben die Daten im Repository und der frühere Zustand lässt sich mit dem Wartungszugang wiederherstellen (Transaktionen zurückrollen), solange niemand `compact` mit dem Wartungsschlüssel ausführt |
| Repository-Dateien über SSH löschen/überschreiben | nicht möglich, wenn der Backup-Schlüssel in `authorized_keys` auf `borg serve --append-only` beschränkt ist (kein SFTP/Shell) – **auf der Box abnehmen**, siehe Betrieb |
| Neue, manipulierte Backups schreiben | möglich; ältere Punkte bleiben aber unverändert und verifizierbar |
| Speicher füllen | möglich (Quota der Box), Monitoring meldet ab 85 % |
| Passphrase/Schlüssel stehlen | Angreifer kann alle Backups **lesen** (Vertraulichkeit verloren) – Backups enthalten Passwort-Hashes und TOTP-Secrets; Schutz nur durch Absicherung des Servers |

Zusätzlicher, vom Server unabhängiger Schutz: **automatische Snapshots der Storage Box**
(Hetzner-Konsole). Sie sind per SSH weder sichtbar noch löschbar und decken auch den Fall ab,
dass `command=`-Einschränkungen auf der Box nicht greifen.

Nicht erreicht wird eine echte WORM-Unveränderlichkeit (Object Lock): wer den Wartungsschlüssel
oder den Hetzner-Konsolenzugang hat, kann Daten endgültig löschen. Beides gehört nicht auf den
Produktivserver; der Konsolenzugang braucht 2FA.

## Konsistenz und Datenintegrität bei Prozessabbrüchen

- Pool- und Wiederherstellungspunkt-Archive entstehen nur vollständig (Borg-Transaktion); ein
  abgebrochener Upload hinterlässt kein Archiv.
- Ein Punkt wird zuletzt geschrieben und direkt danach gelesen und verglichen; scheitert das, wird
  er als `.invalid` markiert und nie als erfolgreich gezählt.
- Ein Backup mit fehlenden Pflichtobjekten ist `partial`, nie `completed`.
- Retention und Garbage Collection löschen nur, was kein Punkt im Repository mehr referenziert;
  vorher wird die Referenzintegrität aller Punkte geprüft, bei Unstimmigkeiten wird abgebrochen.
- Während einer Migration wird keine Sicherung gelöscht: Retention und GC laufen exklusiv über
  einen Advisory-Lock und nie gleichzeitig mit einem Backup oder Restore.
