"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { PlatformOidcConfigRead, PlatformOidcConfigWrite } from "@/types/api";

type Props = {
  initialConfig: PlatformOidcConfigRead | null;
};

const defaultForm: PlatformOidcConfigWrite = {
  enabled: false,
  issuer_url: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile"
};

function toForm(cfg: PlatformOidcConfigRead | null): PlatformOidcConfigWrite {
  if (!cfg) return defaultForm;
  return {
    enabled: cfg.enabled,
    issuer_url: cfg.issuer_url,
    client_id: cfg.client_id,
    client_secret: "",
    scopes: cfg.scopes
  };
}

export function AdminSsoSettings({ initialConfig }: Props) {
  const t = useTranslations("admin.sso");
  const showToast = useToast();
  const [form, setForm] = useState<PlatformOidcConfigWrite>(() => toForm(initialConfig));
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    try {
      const updated = await browserApiFetch<PlatformOidcConfigRead>("/api/admin/oidc-config", {
        method: "PUT",
        body: JSON.stringify(form)
      });
      setForm(toForm(updated));
      showToast(t("saved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <div className="eyebrow">{t("eyebrow")}</div>
      <p className="muted">
        {t("description")}
      </p>
      <form className="grid" onSubmit={submit}>
        <label className="field-stack">
          <span className="field-label">{t("enabledLabel")}</span>
          <select value={form.enabled ? "1" : "0"} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.value === "1" }))}>
            <option value="0">{t("no")}</option>
            <option value="1">{t("yes")}</option>
          </select>
        </label>

        <label className="field-stack">
          <span className="field-label">{t("issuerUrl")}</span>
          <input
            value={form.issuer_url}
            onChange={(e) => setForm((f) => ({ ...f, issuer_url: e.target.value }))}
            placeholder="https://accounts.example.com"
            disabled={!form.enabled}
          />
        </label>

        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("clientId")}</span>
            <input
              value={form.client_id}
              onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}
              placeholder="my-app" // i18n-ok: Beispiel-Platzhalter, keine UI-Sprache
              disabled={!form.enabled}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("clientSecret")}</span>
            <input
              type="password"
              value={form.client_secret}
              onChange={(e) => setForm((f) => ({ ...f, client_secret: e.target.value }))}
              placeholder={t("clientSecretPlaceholder")}
              autoComplete="new-password"
              disabled={!form.enabled}
            />
          </label>
        </div>

        <label className="field-stack">
          <span className="field-label">{t("scopes")}</span>
          <input
            value={form.scopes}
            onChange={(e) => setForm((f) => ({ ...f, scopes: e.target.value }))}
            placeholder="openid email profile" // i18n-ok: Beispiel-Platzhalter (OAuth-Scopes), keine UI-Sprache
            disabled={!form.enabled}
          />
        </label>

        <div className="table-actions table-actions-start">
          <button type="submit" className="button-secondary" disabled={loading}>
            {loading ? "…" : t("save")}
          </button>
        </div>
      </form>
    </section>
  );
}
