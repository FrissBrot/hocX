# Mitglieder & Teilnehmer

- **Benutzer** (`Users`) sind Login-Accounts, systemweit eindeutig über ihre E-Mail,
  aber pro Verein einzeln mit einer [Rolle](rollen.md) verknüpft.
- **Teilnehmer** (`Participants`) sind Personen, die an Sitzungen/Terminen teilnehmen
  können, aber nicht zwingend einen eigenen Login benötigen. Ein Teilnehmer kann
  nachträglich Login-Zugriff erhalten; hocX verknüpft ihn dann automatisch mit einem
  bestehenden Benutzer-Account mit derselben E-Mail (oder legt einen neuen an).

Beide Listen lassen sich in Protokollen referenzieren, z. B. für Anwesenheitslisten
oder "Verantwortlich"-Zuordnungen.
