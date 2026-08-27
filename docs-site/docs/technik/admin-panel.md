# Platform-Admin-Panel

`/admin` ist ein komplett getrennter Betreiber-Bereich, unabhängig vom normalen
Kunden-Login:

- Eigene Accounts-Tabelle `platform_admin` (nicht `app_user`).
- Eigenes Session-Cookie `hocx_admin_session` mit eigenem Secret
  (`ADMIN_AUTH_SECRET`, getrennt von `AUTH_SECRET`).
- Einzige Stelle mit mandantenübergreifender Sicht: Mandanten anlegen, Benutzer über
  Mandanten hinweg verwalten/mergen, globales SSO für Admin-Accounts konfigurieren.

## Betreiberrollen

| Rolle | Zugriff |
|---|---|
| `owner` | Vollzugriff auf Plattformverwaltung, Mandanten, Benutzer, Exporte, MFA-Metadaten und Error-Logs |
| `support` | Nur lesender Zugriff auf nicht sensible technische Mandanten- und Domaininformationen |

Mandantenübergreifende Benutzer- und Mitgliederdaten, MFA-Informationen, Error-Logs,
Platform-Admin-Konten und Tenant-Exporte sind wegen der enthaltenen personenbezogenen
oder sicherheitsrelevanten Daten ausschliesslich für `owner` sichtbar. `support` kann
keine Daten verändern und erhält keinen Zugriff auf diese Ansichten.

## Bootstrap

Der erste Admin-Account wird beim ersten Start aus `INITIAL_ADMIN_EMAIL` /
`INITIAL_ADMIN_PASSWORD` in `.env` angelegt – nur solange die `platform_admin`-Tabelle
noch leer ist. Danach werden weitere Admins ausschliesslich über das Panel selbst
(`/admin/admins`) verwaltet.

## Funktionen

- **Mandanten** (`/admin/tenants`): anlegen, Stammdaten, Benutzer-Tab pro Mandant
  (Rolle ändern/entfernen/hinzufügen), Export/Import.
- **Benutzer** (`/admin/users`): mandantenübergreifende Benutzerverwaltung, Merge zweier
  Accounts.
- **Domains** (`/admin/domains`): Custom-Domains pro Mandant.
- **SSO** (`/admin/sso`): genau ein global konfigurierter OIDC-Provider, ausschliesslich
  für den Login ins Admin-Panel selbst (kein Mandanten-seitiges SSO).
- **Error-Logs** (`/admin/error-logs`).

## Wichtig: zwei getrennte Passwort-Systeme

Ein Platform-Admin-Account und ein regulärer Vereins-Account können dieselbe
E-Mail-Adresse haben, sind aber vollständig unabhängige Datensätze mit eigenen
Passwort-Hashes. `/api/auth/login` (Kunde) und `/api/admin/auth/login`
(Platform-Admin) sind getrennte Endpunkte.
