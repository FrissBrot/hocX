/**
 * Vorschau des Mitglieder-CSV-Imports. Liest die Datei wie das Backend
 * (backend/app/services/participant_service.py: csv-Modul, Trennzeichen ; oder , aus der
 * Kopfzeile, Anführungszeichen, dieselben Spaltennamen), damit Vorschau und Import übereinstimmen.
 */

export type CsvPreviewRow = { display_name: string; first_name: string | null; last_name: string | null; email: string | null };

type CsvField = "first_name" | "last_name" | "nickname" | "company_name" | "email";

// Gleiche Liste wie CSV_COLUMNS im Backend - beide gemeinsam ändern. Vergleich ohne Gross-/Kleinschreibung.
export const CSV_COLUMNS: Record<CsvField, readonly string[]> = {
  first_name: ["vorname", "first name", "firstname", "prénom", "nome"],
  last_name: ["nachname", "last name", "lastname", "nom", "cognome"],
  nickname: ["übername", "anzeigename", "display name", "name"],
  company_name: ["firmenname", "firma", "company"],
  email: ["haupt-e-mail", "e-mail", "email", "e-mail-adresse", "mail"],
};

/** Vorlage zum Herunterladen (Kopfzeile plus Beispielzeile, Semikolon wie Excel in CH). */
export const CSV_TEMPLATE = "Vorname;Nachname;Übername;Firmenname;Haupt-E-Mail\nAnna;Muster;;;anna@example.org\n"; // i18n-ok: Spaltennamen sind Dateiformat, keine UI

/** Zerlegt CSV-Text in Zeilen und Zellen (RFC 4180: "…" mit "" als Escape, Zeilenumbrüche in Anführungszeichen). */
export function splitCsv(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

export type CsvPreview = { rows: CsvPreviewRow[]; recognizedColumns: CsvField[]; missingEmailColumn: boolean };

export function parseParticipantCsv(text: string): CsvPreview {
  const normalized = text.replace(/^﻿/, "");
  const firstLine = normalized.split("\n")[0] ?? "";
  const delimiter = firstLine.split(";").length > firstLine.split(",").length ? ";" : ",";
  const [header = [], ...body] = splitCsv(normalized, delimiter);
  const headers = header.map((cell) => cell.trim().toLowerCase());
  const indexes = Object.fromEntries(
    (Object.keys(CSV_COLUMNS) as CsvField[]).map((field) => [field, CSV_COLUMNS[field].map((name) => headers.indexOf(name)).filter((index) => index >= 0)])
  ) as Record<CsvField, number[]>;
  const recognizedColumns = (Object.keys(indexes) as CsvField[]).filter((field) => indexes[field].length > 0);
  const rows: CsvPreviewRow[] = [];
  for (const cells of body) {
    const get = (field: CsvField) => {
      for (const index of indexes[field]) {
        const value = (cells[index] ?? "").trim();
        if (value) return value;
      }
      return null;
    };
    const first_name = get("first_name");
    const last_name = get("last_name");
    const display_name = get("nickname") ?? ([first_name, last_name].filter(Boolean).join(" ") || null) ?? get("company_name");
    if (!display_name) continue;
    rows.push({ display_name, first_name, last_name, email: get("email") });
  }
  return { rows, recognizedColumns, missingEmailColumn: !recognizedColumns.includes("email") };
}
