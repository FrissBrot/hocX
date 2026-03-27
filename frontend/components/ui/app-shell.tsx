import Link from "next/link";
import { ReactNode } from "react";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/templates", label: "Templates" },
  { href: "/protocols", label: "Protocols" },
  { href: "/settings", label: "Settings" },
  { href: "/login", label: "Login Stub" }
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <main>
      <div className="shell">
        <aside className="sidebar">
          <div className="eyebrow">hocX</div>
          <h2 style={{ margin: "8px 0 0" }}>Protocol Workspace</h2>
          <p className="muted">Next.js App Router frontend for templates, protocols and exports.</p>
          <nav>
            {links.map((link) => (
              <Link href={link.href} key={link.href}>
                {link.label}
              </Link>
            ))}
          </nav>
        </aside>
        {children}
      </div>
    </main>
  );
}

