"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { MaintenanceScreen } from "@/components/maintenance/maintenance-screen";
import { maintenanceView, useMaintenanceStatus } from "@/lib/maintenance";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { cleanStatusPageUrl } from "@/lib/status-page-url";

/** Wartungs- bzw. Update-Ansicht für bereits angemeldete Benutzer (Weiterleitung aus
 * requireSession bzw. bei einer 503-Antwort mit Wartungscode). Deploy-Fenster → Update-Seite (1b),
 * jede andere volle Wartung → Wartungsseite (1a). Kehrt automatisch zurück, sobald sie endet. */
export default function MaintenancePage() {
  const t = useTranslations("maintenance");
  const tc = useTranslations("common");
  const router = useRouter();
  const { status, loaded, nextCheckAt, refresh } = useMaintenanceStatus();
  const [loadedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [config, setConfig] = useState<{ version: string | null; statusPageUrl: string | null }>({ version: null, statusPageUrl: null });

  useEffect(() => {
    const runtime = getRuntimeConfig();
    setConfig({ version: runtime.version && runtime.version !== "dev" ? runtime.version : null, statusPageUrl: cleanStatusPageUrl(runtime.statusPageUrl) });
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (loaded && status !== null && !status.active) {
      router.replace("/");
    }
  }, [loaded, status, router]);

  const check = useCallback(async () => {
    const next = await refresh();
    if (next !== null && !next.active) router.replace("/");
  }, [refresh, router]);

  const copyright = <span className="maint-copyright">{tc("copyright", { year: new Date(now).getFullYear() })}</span>;

  if (!status?.active) {
    return (
      <div className="maint-frame">
        <main className="maint-page">
          <p className="muted" role="status">{loaded ? t("ended") : t("checking")}</p>
        </main>
      </div>
    );
  }
  return (
    <div className="maint-frame">
      <MaintenanceScreen
        status={status}
        view={maintenanceView(status, now, loadedAt)}
        now={now}
        nextCheckAt={nextCheckAt}
        runningVersion={config.version}
        statusPageUrl={config.statusPageUrl}
        onCheck={check}
        copyright={copyright}
      />
    </div>
  );
}
