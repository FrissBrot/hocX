"use client";

import { FormEvent, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataToolbar } from "@/components/ui/data-table";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import type { EmailSettings, EmailSettingsWrite, NotificationTestResult, SmtpSecurity } from "@/types/api";

type FormState = {
  email_enabled: boolean;
  smtp_host: string;
  smtp_port: string;
  smtp_security: SmtpSecurity;
  smtp_username: string;
  smtp_password: string;
  email_from_address: string;
  email_from_name: string;
  email_link_base_url: string;
};

function toForm(settings: EmailSettings): FormState {
  return {
    email_enabled: settings.email_enabled,
    smtp_host: settings.smtp_host ?? "",
    smtp_port: String(settings.smtp_port),
    smtp_security: settings.smtp_security,
    smtp_username: settings.smtp_username ?? "",
    // Das gespeicherte Passwort kommt nie zurück - leer = unverändert lassen.
    smtp_password: "",
    email_from_address: settings.email_from_address ?? "",
    email_from_name: settings.email_from_name,
    email_link_base_url: settings.email_link_base_url ?? "",
  };
}

/** SMTP-Versand der Benachrichtigungen (/admin/notifications). */
export function AdminEmailSettings({ initialSettings }: { initialSettings: EmailSettings }) {
  const t = useTranslations("admin.notifications.email");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [settings, setSettings] = useState(initialSettings);
  const [form, setForm] = useState<FormState>(() => toForm(initialSettings));
  const [saving, setSaving] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [testing, setTesting] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(settings));
  const set = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));

  function payload(overrides: Partial<EmailSettingsWrite> = {}): EmailSettingsWrite {
    return {
      email_enabled: form.email_enabled,
      smtp_host: form.smtp_host.trim() || null,
      smtp_port: Number(form.smtp_port) || 587,
      smtp_security: form.smtp_security,
      smtp_username: form.smtp_username.trim() || null,
      smtp_password: form.smtp_password ? form.smtp_password : null,
      email_from_address: form.email_from_address.trim() || null,
      email_from_name: form.email_from_name.trim() || "hocX",
      email_link_base_url: form.email_link_base_url.trim() || null,
      ...overrides,
    };
  }

  async function save(body: EmailSettingsWrite) {
    setSaving(true);
    try {
      const updated = await browserApiFetch<EmailSettings>("/api/admin/notifications/email", { method: "PUT", body: JSON.stringify(body) });
      setSettings(updated);
      setForm(toForm(updated));
      showToast(t("saved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await save(payload());
  }

  async function removePassword() {
    if (await confirm({ message: t("removePasswordConfirm"), tone: "danger", confirmLabel: t("removePassword") })) {
      await save(payload({ smtp_password: "" }));
    }
  }

  async function sendTest() {
    setTesting(true);
    try {
      const result = await browserApiFetch<NotificationTestResult>("/api/admin/notifications/email/test", {
        method: "POST",
        body: JSON.stringify({ to: testTo.trim() }),
      });
      if (result.ok) showToast(t("testSent"), "success");
      else showToast(t("testFailed", { error: result.error ?? "" }), "error");
      setSettings(await browserApiFetch<EmailSettings>("/api/admin/notifications/email"));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("testFailed", { error: "" }), "error");
    } finally {
      setTesting(false);
    }
  }

  return (
    <section className="card">
      <DataToolbar title={t("title")} description={t("description")} />
      {settings.email_last_error ? (
        <StatusBanner tone="error" message={t("lastError", {
          error: settings.email_last_error,
          date: settings.email_last_error_at ? formatDateTime(settings.email_last_error_at, locale) : "",
        })} />
      ) : null}
      <p className="muted">
        {settings.email_last_sent_at ? t("lastSent", { date: formatDateTime(settings.email_last_sent_at, locale) }) : t("neverSent")}
        {" · "}
        {t("queue", { pending: settings.pending_count, failed: settings.failed_count })}
      </p>
      <form className="grid" onSubmit={submit}>
        <label className="field-stack">
          <span className="field-label">{t("enabledLabel")}</span>
          <Select value={form.email_enabled ? "1" : "0"} onChange={(event) => set({ email_enabled: event.target.value === "1" })}>
            <option value="0">{t("no")}</option>
            <option value="1">{t("yes")}</option>
          </Select>
        </label>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("host")}</span>
            <input value={form.smtp_host} onChange={(event) => set({ smtp_host: event.target.value })} placeholder="smtp.example.com" /> {/* i18n-ok: Beispiel-Hostname */}
          </label>
          <label className="field-stack">
            <span className="field-label">{t("port")}</span>
            <input type="number" min={1} max={65535} value={form.smtp_port} onChange={(event) => set({ smtp_port: event.target.value })} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("security")}</span>
            <Select value={form.smtp_security} onChange={(event) => set({ smtp_security: event.target.value as SmtpSecurity })}>
              <option value="starttls">{t("securityStarttls")}</option>
              <option value="ssl">{t("securitySsl")}</option>
              <option value="none">{t("securityNone")}</option>
            </Select>
          </label>
          <label className="field-stack">
            <span className="field-label">{t("username")}</span>
            <input value={form.smtp_username} autoComplete="off" onChange={(event) => set({ smtp_username: event.target.value })} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("password")}</span>
            <input type="password" autoComplete="new-password" value={form.smtp_password} onChange={(event) => set({ smtp_password: event.target.value })}
              placeholder={settings.smtp_password_set ? t("passwordKeep") : ""} />
            {settings.smtp_password_set ? (
              <button type="button" className="row-text-action row-text-action-danger" onClick={() => void removePassword()}>{t("removePassword")}</button>
            ) : null}
          </label>
          <label className="field-stack">
            <span className="field-label">{t("fromAddress")}</span>
            <input type="email" value={form.email_from_address} onChange={(event) => set({ email_from_address: event.target.value })} placeholder="noreply@example.com" /> {/* i18n-ok: Beispieladresse */}
          </label>
          <label className="field-stack">
            <span className="field-label">{t("fromName")}</span>
            <input value={form.email_from_name} maxLength={100} onChange={(event) => set({ email_from_name: event.target.value })} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("linkBase")}</span>
            <input value={form.email_link_base_url} inputMode="url" onChange={(event) => set({ email_link_base_url: event.target.value })}
              placeholder={settings.effective_link_base_url ?? "https://app.example.com"} /> {/* i18n-ok: Beispiel-URL */}
            <span className="field-help">{t("linkBaseHelp")}</span>
          </label>
        </div>
        <div className="modal-actions">
          <button type="submit" className="button-primary" disabled={!dirty || saving}>{t("save")}</button>
        </div>
      </form>
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">{t("testTo")}</span>
          <input type="email" value={testTo} onChange={(event) => setTestTo(event.target.value)} />
        </label>
        <div>
          <button type="button" className="button-secondary" disabled={testing || dirty || !testTo.trim() || !settings.smtp_host} onClick={() => void sendTest()}>
            {t("sendTest")}
          </button>
          {dirty ? <span className="field-help"> {t("saveBeforeTest")}</span> : null}
        </div>
      </div>
    </section>
  );
}
