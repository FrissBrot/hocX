# Übersicht für Organisationen

hocX begleitet eine Organisation durch den kompletten Zyklus einer Sitzung und eines Arbeitsjahres:

```mermaid
flowchart LR
    A[Vorlage erstellen] --> B[Protokoll aus Vorlage]
    B --> C[Protokoll ausfüllen<br/>geplant / durchgeführt]
    C --> D[Abschliessen]
    D --> E[PDF-Export]
```

## Kernbereiche

| Bereich | Was damit geht |
|---|---|
| [Zyklen & Vorlagen](vorlagen.md) | Wiederkehrende Struktur einer Sitzungsart definieren (Traktanden, Blöcke, Tabellen) |
| [Protokolle](protokolle.md) | Konkrete Sitzung planen, durchführen, abschliessen, exportieren |
| [Termine](termine.md) | Sitzungstermine und weitere Events verwalten |
| [Mitglieder & Logins](mitglieder.md) | Wer gehört dazu, wer nimmt an welcher Sitzung teil, wer kann sich anmelden |
| [Konto & Anmeldung](konto.md) | Anmelden, Passwort, zweiter Faktor |
| [Benachrichtigungen](benachrichtigungen.md) | Welche E-Mails hocX schickt und wie man sie abbestellt |
| [Finanzen & Bussen](finanzen.md) | Konten, Buchungen, Bussenverwaltung |
| [Listen](listen.md) | Frei konfigurierbare Listen (z. B. Vorstand, Inventar) |
| [Todos](todos.md) | Aufgaben aus Protokollen nachverfolgen |
| [Anliegen](anliegen.md) | Punkte für kommende Sitzungen sammeln |
| [Statistik und Dashboard](statistik.md) | Startseite, Kennzahlen, Gruppen und wer welche Zahlen sieht |
| [Abgabebox](abgabebox.md) | Öffentlicher, anmeldefreier Datei-Upload für Externe |
| [Word-Import](word-import.md) | Altprotokolle (.docx/.pdf) als neue Protokolle importieren |
| [Dokumente & Document Studio](dokumente.md) | PDFs exportieren, Vorlagen gestalten, Corporate Design festlegen |
| [Echtheit prüfen](echtheit.md) | Prüfen, ob ein PDF unverändert aus hocX stammt; Name, Logo und Verifizierung auf der Prüfseite |

## Rollen

Der Zugriff innerhalb einer Organisation (Mandant) ist rollenbasiert. Details siehe
[Rollen & Berechtigungen](rollen.md).
