"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { attemptBridgeRedirect } from "@/lib/bridge-redirect";
import { browserApiFetch, browserApiBaseUrl } from "@/lib/api/client";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { SessionInfo } from "@/types/api";

type OidcPublicConfig = {
  tenant_id: number;
  enabled: boolean;
  auto_redirect: boolean;
  issuer_url: string;
};

type ResolvedTenant = { tenant_id: number; tenant_name: string; profile_image_url: string | null };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [resolvedTenant, setResolvedTenant] = useState<ResolvedTenant | null>(null);
  const [oidcConfig, setOidcConfig] = useState<OidcPublicConfig | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [loading, setLoading] = useState(false);
  // Leer bis nach dem Mount (nicht direkt aus getRuntimeConfig() in der JSX gelesen), sonst
  // würde die SSR-Fallback (kein `window` server-seitig) von der echten Laufzeit-Version
  // abweichen und einen Hydration-Mismatch auslösen.
  const [appVersion, setAppVersion] = useState("");
  // Resolves once the `?from=` domain lookup below settles (or immediately with null if there
  // is no `from` param). submitLocal awaits this instead of reading `resolvedTenant` state
  // directly, so a fast submit (autofilled credentials, quick Enter) can never race ahead of
  // the async domain→tenant lookup and silently fall back to the account's default tenant.
  const resolvedTenantPromise = useRef<Promise<ResolvedTenant | null>>(Promise.resolve(null));

  // Login läuft ausschließlich auf der Hauptdomain — wer eine Mandanten-Custom-Domain direkt
  // ansteuert (Lesezeichen, Deep-Link, abgelaufene Session), landet sofort dort.
  useEffect(() => {
    const mainDomain = getRuntimeConfig().mainAppDomain;
    if (mainDomain && window.location.hostname !== mainDomain) {
      window.location.replace(`https://${mainDomain}/login?from=${encodeURIComponent(window.location.hostname)}`);
    }
  }, []);

  useEffect(() => {
    setAppVersion(getRuntimeConfig().version);
  }, []);

  // Kam der Besuch von der Custom Domain eines Mandanten (Redirect mit ?from=<domain>), wird
  // der Mandant automatisch aufgelöst — keine manuelle Organisations-Auswahl mehr nötig.
  useEffect(() => {
    const fromDomain = new URLSearchParams(window.location.search).get("from");
    if (!fromDomain) return;
    const promise = browserApiFetch<ResolvedTenant>(`/api/auth/tenant-by-domain?domain=${encodeURIComponent(fromDomain)}`)
      .then((tenant) => {
        setResolvedTenant(tenant);
        return tenant;
      })
      .catch(() => {
        // unbekannte/nicht mehr aktive Domain — normales Login ohne Vorauswahl
        return null;
      });
    resolvedTenantPromise.current = promise;
  }, []);

  // Check existing session — bridging to a custom domain only ever happens as the direct
  // result of submitting the login form below, never as a side-effect of just loading this
  // page with an existing cookie (that caused a redirect loop for stale main-domain sessions).
  useEffect(() => {
    async function init() {
      try {
        const session = await browserApiFetch<SessionInfo>("/api/auth/session");
        if (session.authenticated) {
          router.replace("/");
        }
      } catch {}
    }
    void init();
  }, [router]);

  // Load OIDC config for the auto-resolved tenant, if any
  useEffect(() => {
    if (!resolvedTenant) { setOidcConfig(null); return; }
    async function loadOidc() {
      try {
        const cfg = await browserApiFetch<OidcPublicConfig>(`/api/auth/oidc/public-config/${resolvedTenant!.tenant_id}`);
        setOidcConfig(cfg ?? null);
      } catch {
        setOidcConfig(null);
      }
    }
    void loadOidc();
  }, [resolvedTenant]);

  async function submitLocal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatusMsg("Anmeldung läuft…");
    try {
      const tenant = await resolvedTenantPromise.current;
      const session = await browserApiFetch<SessionInfo>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, tenant_id: tenant?.tenant_id ?? null }),
      });
      if (session.bridge_redirect_url && attemptBridgeRedirect(session.bridge_redirect_url)) {
        return;
      }
      router.replace("/");
      router.refresh();
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Login fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  function loginWithOidc() {
    window.location.href = `${browserApiBaseUrl}/api/auth/oidc/authorize?tenant_id=${resolvedTenant?.tenant_id}&redirect_to=/`;
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-brand">
          <div className={`login-avatar${resolvedTenant?.profile_image_url ? "" : " login-avatar-fallback"}`}>
            {resolvedTenant?.profile_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={resolvedTenant.profile_image_url} alt={resolvedTenant.tenant_name} />
            ) : (
              <span>hX</span>
            )}
          </div>
          <div className="eyebrow">hocX</div>
        </div>

        <div className="login-heading">
          <h1>Anmelden bei hocX</h1>
          {resolvedTenant && <p className="login-subtitle">für {resolvedTenant.tenant_name}</p>}
        </div>

        {oidcConfig?.enabled && (
          <div className="login-sso">
            <button type="button" className="button-inline oidc-button" onClick={loginWithOidc}>
              Mit {new URL(oidcConfig.issuer_url).hostname} anmelden
            </button>
            <div className="login-divider"><span>oder</span></div>
          </div>
        )}

        <form className="login-form" onSubmit={submitLocal}>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label className="field-stack">
            <span className="field-label">Passwort</span>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
          </label>
          <button type="submit" className="button-inline login-submit" disabled={loading}>
            {loading ? "…" : "Einloggen"}
          </button>
        </form>

        {statusMsg && <p className="login-status">{statusMsg}</p>}
      </section>
      {appVersion && <p className="login-version">hocX {appVersion}</p>}
    </main>
  );
}
