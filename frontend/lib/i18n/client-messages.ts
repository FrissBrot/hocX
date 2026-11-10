import deCommon from "@/messages/de/common.json";

// Uebersetzte Fehlermeldungen fuer Module ohne React-Kontext (lib/api/client.ts, lib/webauthn.ts,
// lib/offline-store.ts). Diese Texte landen ueber error.message direkt in Toasts und Statusanzeigen;
// frueher standen sie fest auf Deutsch im Code (Audit MAIN-FE-010). Die Uebersetzungsfunktion der
// aktuellen UI-Sprache registriert ClientMessagesBridge (im Root-Layout innerhalb des
// NextIntlClientProvider). Ohne Registrierung (Server-Code, Tests ohne Provider) gilt der Default-
// Katalog - die Texte kommen also auch dann aus messages/, nicht aus dem Code.

export type ClientMessageKey = keyof typeof deCommon.clientErrors;
type Values = Record<string, string | number>;
type Translate = (key: ClientMessageKey, values?: Values) => string;

let translate: Translate | null = null;

export function registerClientMessageTranslator(fn: Translate | null) {
  translate = fn;
}

function fallback(key: ClientMessageKey, values?: Values): string {
  const template: string = deCommon.clientErrors[key];
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (values && name in values ? String(values[name]) : match));
}

export function clientMessage(key: ClientMessageKey, values?: Values): string {
  if (translate) {
    try {
      return translate(key, values);
    } catch {
      return fallback(key, values);
    }
  }
  return fallback(key, values);
}
