// Rollenbasierte Sichtbarkeit der Dashboard-Kacheln. Bewusst ohne "use client", damit auch
// app/page.tsx (Server Component) damit entscheiden kann, welche Daten geladen werden.
// Rollen und Rechte spiegeln backend/app/core/security.py (require_writer, require_finance_write, ...).

export type DashboardAccess = {
  role: string | null;
  features: string[];
};

export function dashboardPermissions({ role, features }: DashboardAccess) {
  const isWriter = role === "admin" || role === "writer";
  const hasFinance = role !== null && features.includes("finance");
  return {
    canWrite: isWriter,
    canExcuse: isWriter,
    canConfigure: role === "admin",
    hasFinance,
    // Reader sehen ueber /api/fines nur ihre eigenen Bussen (siehe backend fines.py).
    ownFinesOnly: role === "reader",
    // Kontostaende: fuer die Rollen, die Finanzen auch verbuchen (require_finance_write).
    showAccounts: hasFinance && (role === "kassier" || role === "admin"),
    showSubmissions: isWriter && features.includes("abgabebox"),
  };
}

export type DashboardPermissions = ReturnType<typeof dashboardPermissions>;
