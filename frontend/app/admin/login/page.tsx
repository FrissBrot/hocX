"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { browserApiFetch, browserApiBaseUrl } from "@/lib/api/client";
import { AdminSessionInfo, PlatformOidcConfigPublic } from "@/types/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [oidcConfig, setOidcConfig] = useState<PlatformOidcConfigPublic | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function checkSession() {
      try {
        const session = await browserApiFetch<AdminSessionInfo>("/api/admin/auth/session");
        if (session.authenticated) {
          router.replace("/admin");
        }
      } catch {}
    }
    void checkSession();
  }, [router]);

  useEffect(() => {
    async function loadOidc() {
      try {
        const cfg = await browserApiFetch<PlatformOidcConfigPublic>("/api/admin/auth/oidc/public-config");
        setOidcConfig(cfg ?? null);
      } catch {
        setOidcConfig(null);
      }
    }
    void loadOidc();
  }, []);

  function loginWithOidc() {
    window.location.href = `${browserApiBaseUrl}/api/admin/auth/oidc/authorize?redirect_to=/admin`;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatusMsg("Anmeldung läuft…");
    try {
      await browserApiFetch<AdminSessionInfo>("/api/admin/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      // Nur replace(), kein zusätzliches refresh() - beide lösen sonst nahezu gleichzeitig
      // eine Server-Neuladen für die Zielroute aus, was zu einem kurzen Hin-und-Her zwischen
      // /admin/login und /admin führte (spürbar als Login-Loop, da staleTimes.dynamic=0 ohnehin
      // schon jede Navigation frisch vom Server lädt - refresh() ist hier redundant).
      router.replace("/admin");
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Login fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="eyebrow">hocX Platform-Admin</div>
        <h1>Admin-Anmeldung</h1>

        {oidcConfig?.enabled && (
          <div className="login-sso">
            <button type="button" className="button-inline oidc-button" onClick={loginWithOidc}>
              Mit {new URL(oidcConfig.issuer_url).hostname} anmelden
            </button>
            <div className="login-divider"><span>oder</span></div>
          </div>
        )}

        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label className="field-stack">
            <span className="field-label">Passwort</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
          </label>
          <button type="submit" className="button-inline" disabled={loading}>
            {loading ? "…" : "Einloggen"}
          </button>
        </form>

        {statusMsg && <p className="muted">{statusMsg}</p>}
      </section>
    </main>
  );
}
