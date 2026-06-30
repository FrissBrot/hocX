"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { browserApiFetch, browserApiBaseUrl } from "@/lib/api/client";
import { SessionInfo } from "@/types/api";

type OidcPublicConfig = {
  tenant_id: number;
  enabled: boolean;
  auto_redirect: boolean;
  issuer_url: string;
};

type TenantOption = { tenant_id: number; tenant_name: string };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantId, setTenantId] = useState<number | null>(null);
  const [availableTenants, setAvailableTenants] = useState<TenantOption[]>([]);
  const [oidcConfig, setOidcConfig] = useState<OidcPublicConfig | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [loading, setLoading] = useState(false);

  // Check existing session, then load tenants
  useEffect(() => {
    async function init() {
      try {
        const session = await browserApiFetch<SessionInfo>("/api/auth/session");
        if (session.authenticated) { router.replace("/"); return; }
        setAvailableTenants(session.available_tenants ?? []);
      } catch {}

      // Load all tenants for the login tenant selector
      try {
        const tenants = await browserApiFetch<{ id: number; name: string }[]>("/api/tenants");
        if (tenants?.length) {
          setAvailableTenants(tenants.map((t) => ({ tenant_id: t.id, tenant_name: t.name })));
          setTenantId(tenants[0].id);
        }
      } catch {}
    }
    void init();
  }, [router]);

  // Load OIDC config when tenant changes
  useEffect(() => {
    if (!tenantId) { setOidcConfig(null); return; }
    async function loadOidc() {
      try {
        const cfg = await browserApiFetch<OidcPublicConfig>(`/api/auth/oidc/public-config/${tenantId}`);
        setOidcConfig(cfg ?? null);
      } catch {
        setOidcConfig(null);
      }
    }
    void loadOidc();
  }, [tenantId]);

  async function submitLocal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setStatusMsg("Anmeldung läuft…");
    try {
      await browserApiFetch<SessionInfo>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, tenant_id: tenantId }),
      });
      router.replace("/");
      router.refresh();
    } catch (error) {
      setStatusMsg(error instanceof Error ? error.message : "Login fehlgeschlagen");
    } finally {
      setLoading(false);
    }
  }

  function loginWithOidc() {
    window.location.href = `${browserApiBaseUrl}/api/auth/oidc/authorize?tenant_id=${tenantId}&redirect_to=/`;
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="eyebrow">hocX</div>
        <h1>Anmelden</h1>

        {availableTenants.length > 1 && (
          <label className="field-stack">
            <span className="field-label">Organisation</span>
            <select value={tenantId ?? ""} onChange={(e) => setTenantId(Number(e.target.value))}>
              {availableTenants.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>{t.tenant_name}</option>
              ))}
            </select>
          </label>
        )}

        {oidcConfig?.enabled && (
          <button type="button" className="button-inline oidc-button" onClick={loginWithOidc}>
            Mit {new URL(oidcConfig.issuer_url).hostname} anmelden
          </button>
        )}

        {oidcConfig?.enabled && <div className="login-divider"><span>oder</span></div>}

        <form className="grid" onSubmit={submitLocal}>
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
