"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";

type BridgePreview = { display_name: string; email: string; tenant_name: string };

/**
 * Bestätigung des Domain-Wechsels (MAIN-SEC-006): Ein Anmeldelink von der Hauptdomain meldet
 * auf der Mandanten-Domain erst nach diesem Klick an. So kann niemand einem anderen per Link
 * die eigene Sitzung unterschieben, ohne dass Name und Mandant sichtbar werden.
 */
function BridgeConfirm() {
  const t = useTranslations("auth.bridge");
  const token = useSearchParams().get("token") ?? "";
  const [preview, setPreview] = useState<BridgePreview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setFailed(true);
      return;
    }
    browserApiFetch<BridgePreview>(`/api/auth/bridge/preview?${new URLSearchParams({ token })}`)
      .then((loaded) => { if (!cancelled) setPreview(loaded); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [token]);

  async function confirm() {
    setBusy(true);
    try {
      await browserApiFetch("/api/auth/bridge", { method: "POST", body: JSON.stringify({ token }) });
      window.location.href = "/";
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-heading">
          <h1>{t("title")}</h1>
          {preview ? (
            <p className="login-subtitle">{t("question", { name: preview.display_name, email: preview.email, tenant: preview.tenant_name })}</p>
          ) : null}
        </div>
        {failed ? (
          <>
            <p className="login-status">{t("invalid")}</p>
            <div className="table-actions table-actions-start">
              <a className="button-primary" href="/login">{t("toLogin")}</a>
            </div>
          </>
        ) : preview ? (
          <>
            <p className="muted">{t("hint")}</p>
            <div className="table-actions table-actions-start">
              <a className="button-ghost" href="/login">{t("cancel")}</a>
              <button type="button" className="button-primary" disabled={busy} onClick={() => void confirm()}>{t("confirm")}</button>
            </div>
          </>
        ) : (
          <p className="muted">{t("loading")}</p>
        )}
      </section>
    </main>
  );
}

export default function BridgePage() {
  return (
    <Suspense>
      <BridgeConfirm />
    </Suspense>
  );
}
