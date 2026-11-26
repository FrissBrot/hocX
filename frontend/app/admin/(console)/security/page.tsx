import { Suspense } from "react";

import { SecuritySituationView } from "@/components/admin/security/security-situation";

// Lagebild (1.6, ersetzt die Übersicht aus Plan §2 D): Zeitraum, Vorfall-Auswahl und Warteschlange in
// der URL (useSearchParams braucht eine Suspense-Grenze). Das persönliche Profil liegt unter /admin/account.
export default function AdminSecurityPage() {
  return (
    <section className="panel section-stack admin-security-panel">
      <Suspense fallback={null}>
        <SecuritySituationView />
      </Suspense>
    </section>
  );
}
