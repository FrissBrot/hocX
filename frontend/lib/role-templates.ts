// Rollen-Vorlagen (Plan «Berechtigungen», Phase 7): kopierbar, nicht verknüpft. «Neue Rolle aus
// Vorlage» füllt nur das Formular vor; gespeichert wird eine normale eigene Rolle über
// POST /api/roles - das Backend prüft dort wie immer (role_service: keine Rechteausweitung).
//
// Bewusst als Frontend-Konstante (Entscheid Phase 7): Vorlagen gewähren nichts, sind reine
// Benutzerführung; Name und Beschreibung sind Übersetzungen (roles.templates.<key>.*), die ohnehin
// im Frontend liegen; eine Lese-Route brächte nur eine zweite Quelle ohne Sicherheitsgewinn.
// Rechte nur aus dem Katalog (PermissionKey prüft tsc), die Vorlagen-Tests prüfen Implikationen.

import { SCOPED_PERMISSIONS, expandPermissions, minimalPermissions, type PermissionScope } from "@/lib/permissions";
import { SYSTEM_ROLE_PERMISSIONS, type PermissionKey } from "@/lib/permissions.generated";

export type RoleTemplateKey = "president" | "secretary" | "treasurer" | "auditor" | "reviewer" | "member";

export type RoleTemplate = {
  key: RoleTemplateKey;
  // Kleinste Menge; Implikationen ergänzt das Formular
  permissions: readonly PermissionKey[];
  // Abweichende Reichweiten (sonst «alle»)
  scopes?: Partial<Record<PermissionKey, PermissionScope>>;
};

export const ROLE_TEMPLATES: readonly RoleTemplate[] = [
  {
    // Leitet Sitzungen, schliesst Protokolle ab (Vier-Augen-Prinzip: nicht das selbst verfasste),
    // sieht Kasse und Personenauswertungen; keine Administration (dafür die Rolle Admin, MFA)
    key: "president",
    permissions: [
      "meetings.edit", "meetings.approve", "todos.complete_own", "templates.edit", "participants.contacts",
      "finances.read", "reports.personal", "files.read", "photos.read", "submissions.read",
    ],
  },
  {
    // Schreibt Protokolle, pflegt Vorlagen, Mitglieder und Ablage; schliesst nicht selbst ab
    key: "secretary",
    permissions: [
      "meetings.edit", "todos.complete_own", "templates.manage", "participants.manage",
      "files.manage", "photos.manage", "sharing.public",
    ],
  },
  {
    // Kasse und Bussen, dazu Entwürfe (Traktandum Finanzen) und die Mitgliederliste
    key: "treasurer",
    permissions: ["meetings.read_drafts", "todos.complete_own", "participants.read", "finances.manage", "fines.manage", "reports.personal"],
  },
  {
    // Revision: nur lesend inkl. Finanzen; ohne «eigene Pendenzen erledigen» = rein lesender Zugang
    key: "auditor",
    permissions: ["meetings.read_drafts", "participants.read", "finances.read", "reports.personal", "files.read", "photos.read"],
  },
  {
    // Prüft nur die Abgabe-Aufträge, denen es zugewiesen ist (Phase 4)
    key: "reviewer",
    permissions: ["meetings.read", "todos.complete_own", "submissions.review"],
    scopes: { "submissions.review": "assigned", "submissions.read": "assigned" },
  },
  {
    // Wie die Standardrolle Leser (Mitglied)
    key: "member",
    permissions: [...SYSTEM_ROLE_PERMISSIONS.reader],
  },
];

export type TemplateSelection = {
  // Gewählte Rechte (kleinste Menge) - nur solche, die die handelnde Person selbst hat
  selected: Set<PermissionKey>;
  scopes: Partial<Record<PermissionKey, PermissionScope>>;
  // Rechte der Vorlage (inkl. Implikationen), die die handelnde Person nicht vergeben darf
  omitted: PermissionKey[];
};

/** Formular-Vorbelegung aus einer Vorlage: nur eigene Rechte (keine Rechteausweitung, wie
 * role_service._ensure_subset); wer ein Recht selbst nur für zugewiesene hat, vergibt es so. */
export function templateSelection(
  template: RoleTemplate,
  own: ReadonlySet<string>,
  ownAssignedOnly: ReadonlySet<string> = new Set(),
): TemplateSelection {
  const wanted = expandPermissions(template.permissions);
  const allowed = [...wanted].filter((key) => own.has(key));
  const omitted = [...wanted].filter((key) => !own.has(key));
  const selected = minimalPermissions(allowed);
  const effective = expandPermissions(selected);
  const scopes: Partial<Record<PermissionKey, PermissionScope>> = {};
  for (const key of effective) {
    if (!SCOPED_PERMISSIONS.has(key)) continue;
    const scope = ownAssignedOnly.has(key) ? "assigned" : template.scopes?.[key];
    if (scope) scopes[key] = scope;
  }
  return { selected, scopes, omitted };
}
