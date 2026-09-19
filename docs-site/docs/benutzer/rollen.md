# Rollen & Berechtigungen

Jedes Benutzerkonto gehört genau einem Mandanten (Verein) und hat dort genau eine Rolle.
Wer in mehreren Vereinen arbeitet, braucht pro Verein ein eigenes Konto (mit eigener
E-Mail-Adresse).

| Rolle | Zugriff |
|---|---|
| `admin` | Voller Zugriff innerhalb des gewählten Vereins, inkl. Struktur (Vorlagen, Zyklen, Einstellungen) |
| `writer` | Arbeitet im Protokoll-Bereich mit und pflegt operative Daten, darf aber keine Struktur oder Finanzen ändern |
| `reader` | Nur Lesezugriff, kann PDF-Export auslösen und sieht nur eigene Bussen |
| `kassier` | Wie `reader`, zusätzlich voller Schreibzugriff auf Finanzen und Bussen |

`writer` und `kassier` sind bewusst gleichrangige Fachrollen mit unterschiedlichen
Aufgaben. `writer` beinhaltet keine Kassier-Rechte und `kassier` keine Schreibrechte im
Protokollbereich. Benötigt eine Person beide Rechte, muss sie derzeit `admin` sein.

## Berechtigungsmatrix

| Bereich | `reader` | `writer` | `kassier` | `admin` |
|---|:---:|:---:|:---:|:---:|
| Finalisierte Protokolle lesen | ✓ | ✓ | ✓ | ✓ |
| Protokolle und operative Daten bearbeiten | – | ✓ | – | ✓ |
| Eigene Bussen lesen | ✓ | ✓ | ✓ | ✓ |
| Alle Bussen und Finanzdaten lesen | – | ✓ | ✓ | ✓ |
| Finanzen und Bussen bearbeiten | – | – | ✓ | ✓ |
| Vorlagen, Zyklen und Tag-Konfiguration ändern | – | – | – | ✓ |
| Benutzer, Rollen und Vereinseinstellungen verwalten | – | – | – | ✓ |

Zusammenführen lassen sich nur zwei Konten desselben Vereins. Dabei werden Rollen nur
automatisch übernommen, wenn eine Rolle die andere vollständig umfasst. Die Kombination `writer` + `kassier`
wird deshalb abgelehnt und muss vor dem Merge fachlich aufgelöst werden.

## Mandantenübergreifender Zugriff

Kein normaler Vereins-Account kann auf einen anderen Verein zugreifen. Eine
mandantenübergreifende Sicht existiert ausschliesslich im getrennten
[Platform-Admin-Panel](../technik/admin-panel.md), das ausschliesslich der Betreiberseite
vorbehalten ist.
