// Welche Katalog-Namespaces (messages/<locale>/<namespace>.json) an den Client gehen.
//
// Hintergrund: Frueher hat das Root-Layout den kompletten Katalog (alle Namespaces, fuer `de`
// rund 420 KB JSON) per NextIntlClientProvider in jede Seite serialisiert - auch auf /login.
// Jetzt liefert das Root-Layout nur ROOT_NAMESPACES; jeder Bereich (Routensegment) legt in
// seinem layout.tsx per <AreaIntlProvider area="..."> die Namespaces nach, die seine
// Client-Komponenten brauchen (siehe components/i18n/area-intl-provider.tsx).
//
// Wichtig: Ein verschachtelter NextIntlClientProvider ERSETZT die Messages des aeusseren, er
// ergaenzt sie nicht. AreaIntlProvider uebergibt deshalb immer GLOBAL_NAMESPACES plus die
// Bereichs-Namespaces.
//
// Pflege: Wer in einer Komponente einen neuen Namespace per useTranslations einfuehrt, muss sicherstellen, dass er
// auf jeder Route, auf der die Komponente rendert, hier eingetragen ist. message-scopes.test.ts
// prueft das automatisch (statische Import-Analyse ab jeder page.tsx) und meldet fehlende
// Namespaces mit Route und Datei. Im Zweifel einen Namespace lieber zu viel eintragen - ein
// fehlender fuehrt zur Laufzeit zu MISSING_MESSAGE (sichtbarer Schluessel statt Text).

// Namespaces, die app-weit gebraucht werden: App-Shell (Navigation, Mobile-Shell,
// Sitzungsablauf, Einstellungen/Profil), gemeinsame Bausteine (Dialoge, Toasts, Fehlertexte),
// Login/Auth, Wartungs- und Ueberlast-Seiten.
export const GLOBAL_NAMESPACES = [
  "auth",
  "common",
  "maintenance",
  "mobile",
  "nav",
  "overload",
  "search",
  "security",
  "settings",
] as const;

// Zusaetzliche Namespaces pro Bereich (immer zusammen mit GLOBAL_NAMESPACES ausgeliefert).
// Schluessel = Bereichsname, wie er in <AreaIntlProvider area="..."> steht.
export const AREA_NAMESPACES = {
  admin: [
    "admin",
    "adminAnalytics",
    "adminBackups",
    "adminCashflow",
    "adminMaintenance",
    "adminOverview",
    "adminSecurity",
    "adminShell",
    "adminStorage",
    "adminTenantDetail",
    "files",
    "storage",
  ],
  // Unterbereich von admin: das Document Studio ist gross und wird nur hier gebraucht.
  adminDocumentTemplates: [
    "admin",
    "adminAnalytics",
    "adminBackups",
    "adminCashflow",
    "adminMaintenance",
    "adminOverview",
    "adminSecurity",
    "adminShell",
    "adminStorage",
    "adminTenantDetail",
    "documentStudio",
    "files",
    "storage",
  ],
  // Unterbereich von admin: Plattform-Übersicht der Datei-Importe nutzt Quellen-/Statusnamen des Wizards.
  adminCloudImports: [
    "admin",
    "adminAnalytics",
    "adminBackups",
    "adminCashflow",
    "adminMaintenance",
    "adminOverview",
    "adminSecurity",
    "adminShell",
    "adminStorage",
    "adminTenantDetail",
    "fileImport",
    "files",
    "storage",
  ],
  agenda: ["agenda", "protocols"],
  connections: ["connections"],
  // Startseite (app/page.tsx): Dashboard-Kacheln und Mobile-Dashboard.
  dashboard: ["connections", "dashboard", "events", "finances", "protocols", "statistics", "todos"],
  documents: ["documentPdf", "documentStudio", "files", "photos", "protocols", "sharedLinks", "templates", "uploads"],
  elements: ["documentStudio", "files", "photos", "protocols", "sharedLinks", "submissionAssignments", "templates", "uploads"],
  events: ["connections", "documentStudio", "events"],
  files: ["files", "sharedLinks", "uploads"],
  // Upload-Verlauf der Ablage (app/files/uploads): Vorgangsdetail bettet das Fotoraster ein.
  fileUploads: ["files", "photos", "protocols", "sharedLinks", "uploads"],
  // Datei-Import (app/files/import): Wizard, Regeln, Bericht.
  fileImport: ["fileImport", "files", "sharedLinks"],
  finances: ["documentStudio", "finances"],
  lists: ["documentStudio", "lists", "protocols"],
  participants: ["files", "participants", "roles", "sharedLinks", "users"],
  // Benutzer-, Rollen-, Zyklen- und Freigabeverwaltung teilen sich dieselben Bausteine.
  people: ["cycles", "roles", "sharedLinks", "users"],
  photos: ["files", "photos", "protocols", "sharedLinks", "uploads"],
  protocols: [
    "agenda",
    "documentStudio",
    "events",
    "finances",
    "lists",
    "protocols",
    "submissionAssignments",
    "templates",
    "todos",
  ],
  share: ["share"],
  statistics: ["documentStudio", "statistics"],
  submissionAccess: ["submissionAccess"],
  submissionAssignments: ["files", "sharedLinks", "submissionAssignments"],
  taskPackages: ["files", "photos", "protocols", "sharedLinks", "taskPackages", "uploads"],
  templates: ["documentPdf", "documentStudio", "finances", "protocols", "submissionAssignments", "templates"],
  tenantSettings: ["cycles", "documents", "protocols", "roles", "sharedLinks", "storage", "tenantSettings", "users"],
  todos: ["connections", "documentStudio", "finances", "protocols", "todos"],
  // «Meine Aufgaben» zeigt dieselbe Pendenzen-Ansicht (TodoListView personal)
  myTasks: ["connections", "documentStudio", "finances", "protocols", "todos"],
  tools: ["files", "photos", "protocols", "sharedLinks", "templates", "todos", "tools", "uploads"],
  website: ["website"],
} as const satisfies Record<string, readonly string[]>;

export type MessageArea = keyof typeof AREA_NAMESPACES;

// Was das Root-Layout ausliefert.
//
// UEBERGANG: Die Protokoll-Routen (app/protocols/**) haben noch kein eigenes layout.tsx mit
// <AreaIntlProvider area="protocols">. Bis es existiert, liefert das Root-Layout deren
// Namespaces mit aus, damit dort nichts fehlt. Sobald app/protocols/layout.tsx angelegt ist,
// hier nur noch GLOBAL_NAMESPACES zurueckgeben (message-scopes.test.ts prueft beides).
export const ROOT_NAMESPACES: readonly string[] = [...GLOBAL_NAMESPACES, ...AREA_NAMESPACES.protocols];

export function areaNamespaces(area: MessageArea): string[] {
  return Array.from(new Set<string>([...GLOBAL_NAMESPACES, ...AREA_NAMESPACES[area]]));
}

// Liefert die Namespaces eines Bereichs nur dann, wenn das Root-Layout sie nicht ohnehin schon
// alle ausliefert - sonst null (kein zusaetzlicher Provider noetig, keine doppelten Messages im
// HTML).
export function extraAreaNamespaces(area: MessageArea): string[] | null {
  const needed = areaNamespaces(area);
  return needed.every((namespace) => ROOT_NAMESPACES.includes(namespace)) ? null : needed;
}

// Waehlt die angegebenen Top-Level-Namespaces aus dem vollen Katalog aus. Fehlende Namespaces
// (z.B. Tippfehler) werden einfach uebergangen; der Test faengt das ab.
export function pickNamespaces(
  messages: Record<string, unknown>,
  namespaces: readonly string[]
): Record<string, unknown> {
  const picked: Record<string, unknown> = {};
  for (const namespace of namespaces) {
    if (namespace in messages) {
      picked[namespace] = messages[namespace];
    }
  }
  return picked;
}
