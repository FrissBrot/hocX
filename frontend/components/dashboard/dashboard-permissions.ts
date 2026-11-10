// Berechtigungsbasierte Sichtbarkeit der Dashboard-Kacheln. Bewusst ohne "use client", damit auch
// app/page.tsx (Server Component) damit entscheiden kann, welche Daten geladen werden.
// Spiegelt die Prüfungen im Backend (require_permission, siehe lib/permissions.ts).

import { can } from "@/lib/permissions";

export type DashboardAccess = {
  permissions: string[];
  features: string[];
};

export function dashboardPermissions({ permissions, features }: DashboardAccess) {
  const session = { permissions, current_tenant: { enabled_features: features } } as Parameters<typeof can>[0];
  const isWriter = can(session, "meetings.edit");
  return {
    canWrite: isWriter,
    canExcuse: isWriter,
    canConfigure: can(session, "templates.manage"),
    // Eigene Bussen sieht jedes Konto, sobald Finanzen gebucht sind (GET /api/fines).
    hasFinance: permissions.length > 0 && features.includes("finance"),
    // Ohne reports.personal liefert /api/fines nur die eigenen Bussen.
    ownFinesOnly: !can(session, "reports.personal"),
    // Kontostaende: fuer alle, die Finanzen auch verbuchen (finances.manage).
    showAccounts: can(session, "finances.manage"),
    showSubmissions: can(session, "submissions.manage"),
  };
}

export type DashboardPermissions = ReturnType<typeof dashboardPermissions>;
