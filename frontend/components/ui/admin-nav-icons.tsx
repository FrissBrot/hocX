import { ReactNode } from "react";

import type { AdminIconKey } from "@/components/ui/admin-shell-nav";

/** Linienicons im Stil von nav-icons.tsx, nur für die Admin-Navigation. */
export function AdminNavIcon({ name }: { name: AdminIconKey }) {
  const paths: Record<AdminIconKey, ReactNode> = {
    // Vorfall: Fahne (Sicherheit › Vorfälle, 1.7)
    incidents: (
      <>
        <path d="M5 21V4" />
        <path d="M5 4.5h11l-2 4 2 4H5" />
      </>
    ),
    dashboard: (
      <>
        <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.5" />
        <rect x="13" y="3.5" width="7.5" height="7.5" rx="1.5" />
        <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.5" />
        <rect x="13" y="13" width="7.5" height="7.5" rx="1.5" />
      </>
    ),
    tenants: (
      <>
        <path d="M4 20V10l8-5.5L20 10v10" />
        <path d="M9.5 20v-6h5v6M3 20h18" />
      </>
    ),
    pricing: (
      <>
        <path d="M3.5 12.2V4.5a1 1 0 011-1h7.7l8.3 8.3a1.5 1.5 0 010 2.1l-6.4 6.4a1.5 1.5 0 01-2.1 0z" />
        <circle cx="8" cy="8" r="1.4" />
      </>
    ),
    cashflow: (
      <>
        <path d="M3.5 20.5h17" />
        <path d="M4 15.5l4.5-4.5 3.5 3 7.5-7.5" />
        <path d="M15 6.5h4.5V11" />
      </>
    ),
    users: (
      <>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M2.5 20c.6-3.4 3.2-5.5 6.5-5.5s5.9 2.1 6.5 5.5" />
        <path d="M15.5 4.8a3.5 3.5 0 010 6.4M18 14.8c1.9.7 3.2 2.5 3.5 5.2" />
      </>
    ),
    domains: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M3.5 12h17M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5s1.1-6.1 3.4-8.5z" />
      </>
    ),
    verifications: (
      <>
        <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z" />
        <path d="M9 12l2 2 4-4" />
      </>
    ),
    documents: (
      <>
        <path d="M7 3.5h7l4 4V20.5H7z" />
        <path d="M14 3.5v4h4M9.5 12h6M9.5 15.5h6" />
      </>
    ),
    errors: (
      <>
        <path d="M10.3 4.2L2.8 17.5a2 2 0 001.7 3h15a2 2 0 001.7-3L13.7 4.2a2 2 0 00-3.4 0z" />
        <path d="M12 9.5v4M12 17h.01" />
      </>
    ),
    pipeline: (
      <>
        <path d="M4 7h9M17 7h3M4 17h3M11 17h9M4 12h13M21 12h-.5" />
        <circle cx="15" cy="7" r="2" />
        <circle cx="9" cy="17" r="2" />
        <circle cx="19" cy="12" r="2" />
      </>
    ),
    admins: <path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.1-7.5 9.5-4.4-1.4-7.5-4.9-7.5-9.5V6z" />,
    system: (
      <>
        <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
      </>
    ),
    notifications: (
      <>
        <path d="M6 16.5V11a6 6 0 0112 0v5.5l1.5 2h-15z" />
        <path d="M10 20.5a2 2 0 004 0" />
      </>
    ),
    jobs: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7.5V12l3 2" />
      </>
    ),
    storage: (
      <>
        <ellipse cx="12" cy="6" rx="7.5" ry="2.5" />
        <path d="M4.5 6v6c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5V6" />
        <path d="M4.5 12v6c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-6" />
      </>
    ),
    backups: (
      <>
        <path d="M4.5 12a7.5 7.5 0 101.9-5" />
        <path d="M4.5 4.5V8H8" />
        <path d="M12 8v4l2.5 1.5" />
      </>
    ),
    maintenance: (
      <>
        <path d="M14.5 6.5a4 4 0 00-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 005.3-5.3l-2.4 2.4-2.6-.6-.6-2.6z" />
      </>
    ),
    analytics: (
      <>
        <path d="M4 20.5V10M10 20.5V4M16 20.5v-7M21 20.5H3" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2.5v3M12 18.5v3M4.2 6.2l2.1 2.1M17.7 15.7l2.1 2.1M2.5 12h3M18.5 12h3M4.2 17.8l2.1-2.1M17.7 8.3l2.1-2.1" />
      </>
    ),
    delivery: (
      <>
        <rect x="3" y="5.5" width="18" height="13" rx="2" />
        <path d="M3.5 7l8.5 6 8.5-6" />
      </>
    ),
    blocks: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M6 6l12 12" />
      </>
    ),
    events: (
      <>
        <path d="M4 6h16M4 12h16M4 18h10" />
      </>
    ),
    alerts: (
      <>
        <path d="M12 3.5l9 16H3z" />
        <path d="M12 10v4M12 17h.01" />
      </>
    ),
    policy: (
      <>
        <path d="M7 3.5h10a1 1 0 011 1v15a1 1 0 01-1 1H7a1 1 0 01-1-1v-15a1 1 0 011-1z" />
        <path d="M9 8h6M9 12h6M9 16h3" />
      </>
    ),
    audit: (
      <>
        <circle cx="10.5" cy="10.5" r="6" />
        <path d="M15 15l5.5 5.5M8 10.5h5" />
      </>
    ),
    account: (
      <>
        <circle cx="12" cy="8.5" r="4" />
        <path d="M4.5 20.5c.8-3.8 3.8-6 7.5-6s6.7 2.2 7.5 6" />
      </>
    ),
    security: (
      <>
        <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
        <path d="M8 10.5V7.5a4 4 0 018 0v3" />
      </>
    ),
  };
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={18} height={18} aria-hidden="true" className="nav-link-icon">
      {paths[name]}
    </svg>
  );
}
