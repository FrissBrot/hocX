import type { ReactNode } from "react";

import { SecurityTabs } from "@/components/admin/security/security-tabs";

// Kopf jeder Sicherheitsseite: Titel, ein Satz Beschreibung, optionale Seitenaktion, Unterseiten-Tabs.
export function SecurityPageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="muted">{description}</p>
        </div>
        {actions}
      </div>
      <SecurityTabs />
    </>
  );
}
