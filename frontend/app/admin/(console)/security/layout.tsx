import "@/app/styles/admin-security.css";

// Sicherheitsbereich der Konsole (1.6): eigenes Bereichs-CSS nur für /admin/security/* laden
// (DESIGN.md Abschnitt 10, scripts/check-css-scopes.py).
export default function SecurityLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
