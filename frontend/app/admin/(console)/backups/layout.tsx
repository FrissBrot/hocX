import "@/app/styles/admin-backups.css";

// Backups der Konsole (1.6): eigenes Bereichs-CSS nur für /admin/backups laden
// (DESIGN.md Abschnitt 10, scripts/check-css-scopes.py).
export default function BackupsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
