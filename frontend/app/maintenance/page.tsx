"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { MaintenanceNotice } from "@/components/maintenance/maintenance-notice";
import { CopyrightNotice } from "@/components/ui/copyright-notice";
import { useMaintenanceStatus } from "@/lib/maintenance";

/** Wartungsansicht für bereits angemeldete Benutzer (Weiterleitung aus requireSession bzw. bei
 * einer 503-Antwort mit Wartungscode). Kehrt automatisch zurück, sobald die Wartung beendet ist. */
export default function MaintenancePage() {
  const t = useTranslations("maintenance");
  const router = useRouter();
  const { status, loaded } = useMaintenanceStatus();

  useEffect(() => {
    if (loaded && status !== null && !status.active) {
      router.replace("/");
    }
  }, [loaded, status, router]);

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-brand">
          <div className="login-avatar login-avatar-fallback">
            <span>hX</span>
          </div>
          <div className="eyebrow">hocX</div>
        </div>
        {status?.active ? (
          <MaintenanceNotice status={status} variant="page" />
        ) : (
          <p className="muted" role="status">{loaded ? t("ended") : t("checking")}</p>
        )}
      </section>
      <CopyrightNotice className="login-copyright" />
    </main>
  );
}
