# Rollen & Berechtigungen

Berechtigungen sind pro Mandant (Verein) vergeben – ein Benutzer kann in verschiedenen
Vereinen unterschiedliche Rollen haben.

| Rolle | Zugriff |
|---|---|
| `admin` | Voller Zugriff innerhalb des gewählten Vereins, inkl. Struktur (Vorlagen, Zyklen, Einstellungen) |
| `writer` | Arbeitet im Protokoll-Bereich mit, darf aber keine Struktur ändern |
| `reader` | Nur Lesezugriff, kann PDF-Export auslösen |
| `kassier` | Wie `reader`, zusätzlich voller Zugriff auf Finanzen und Bussen |

## Mandantenübergreifender Zugriff

Kein normaler Vereins-Account kann auf einen anderen Verein zugreifen. Eine
mandantenübergreifende Sicht existiert ausschliesslich im getrennten
[Platform-Admin-Panel](../technik/admin-panel.md), das ausschliesslich der Betreiberseite
vorbehalten ist.
