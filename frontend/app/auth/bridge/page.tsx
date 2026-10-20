"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";

type BridgePreview = { display_name: string; email: string; tenant_name: string };

/**
 * Bestätigung des Domain-Wechsels (MAIN-SEC-006): Ein Anmeldelink von der Hauptdomain meldet
 * auf der Mandanten-Domain erst nach diesem Klick an. So kann niemand einem anderen per Link
 * die eigene Sitzung unterschieben, ohne dass Name und Mandant sichtbar werden.
 *
 * Das Token kommt im URL-Fragment (`#token=…`, SEC-019): Der Browser schickt es an keinen Server,
 * und die Seite entfernt es sofort aus Adresszeile und Verlauf. Vorschau und Einlösen senden es
 * nur im Request-Body.
 */
function readTokenFromFragment(): string {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  return token;
}

export default function BridgePage() {
  const t = useTranslations("auth.bridge");
  const [token, setToken] = useState("");
  const [preview, setPreview] = useState<BridgePreview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fragmentToken = readTokenFromFragment();
    if (!fragmentToken) {
      setFailed(true);
      return;
    }
    setToken(fragmentToken);
    browserApiFetch<BridgePreview>("/api/auth/bridge/preview", { method: "POST", body: JSON.stringify({ token: fragmentToken }) })
      .then((loaded) => { if (!cancelled) setPreview(loaded); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, []);

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
