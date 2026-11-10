"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AdminMfaSettings } from "@/components/admin/admin-mfa-settings";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import type { UserMfaOverview } from "@/types/api";

export function AdminAccountSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations("adminShell");
  const common = useTranslations("common");
  const [overview, setOverview] = useState<UserMfaOverview | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setOverview(null);
    setError(false);
    browserApiFetch<UserMfaOverview>("/api/admin/mfa").then(
      (result) => { if (!cancelled) setOverview(result); },
      () => { if (!cancelled) setError(true); },
    );
    return () => { cancelled = true; };
  }, [open, attempt]);

  return (
    <Modal open={open} onClose={onClose} title={t("accountSettings")} size="wide">
      {error ? (
        <div className="grid">
          <StatusBanner tone="error" message={t("accountSettingsLoadFailed")} />
          <button type="button" className="button-secondary" onClick={() => setAttempt((value) => value + 1)}>{common("retry")}</button>
        </div>
      ) : overview ? <AdminMfaSettings initialOverview={overview} /> : <p className="muted" role="status">{common("loading")}</p>}
    </Modal>
  );
}
