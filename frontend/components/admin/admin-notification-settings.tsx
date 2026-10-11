"use client";

import { FormEvent, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataToolbar } from "@/components/ui/data-table";
import { CopyField } from "@/components/ui/copy-field";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import { NotificationSettings, NotificationSettingsWrite, NotificationTestResult } from "@/types/api";

type Props = {
  initialSettings: NotificationSettings;
};

type FormState = {
  ntfy_enabled: boolean;
  ntfy_server_url: string;
  ntfy_topic: string;
  ntfy_token: string;
  admin_url: string;
  reminder_hours: number;
};

function toForm(settings: NotificationSettings): FormState {
  return {
    ntfy_enabled: settings.ntfy_enabled,
    ntfy_server_url: settings.ntfy_server_url ?? "",
    ntfy_topic: settings.ntfy_topic ?? "",
    // Das gespeicherte Token kommt nie zurück - leer = unverändert lassen.
    ntfy_token: "",
    admin_url: settings.admin_url ?? "",
    reminder_hours: settings.reminder_hours,
  };
}

export function AdminNotificationSettings({ initialSettings }: Props) {
  const t = useTranslations("admin.notifications");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [settings, setSettings] = useState(initialSettings);
  const [form, setForm] = useState<FormState>(() => toForm(initialSettings));
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(settings));

  async function save(payload: NotificationSettingsWrite) {
    setSaving(true);
    try {
      const updated = await browserApiFetch<NotificationSettings>("/api/admin/notifications", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setSettings(updated);
      setForm(toForm(updated));
      showToast(t("saved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  function payloadFromForm(overrides: Partial<NotificationSettingsWrite> = {}): NotificationSettingsWrite {
    return {
      ntfy_enabled: form.ntfy_enabled,
      ntfy_server_url: form.ntfy_server_url.trim() || null,
      ntfy_topic: form.ntfy_topic.trim() || null,
      ntfy_token: form.ntfy_token.trim() ? form.ntfy_token.trim() : null,
      admin_url: form.admin_url.trim() || null,
      reminder_hours: form.reminder_hours,
      ...overrides,
    };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await save(payloadFromForm());
  }

  async function removeToken() {
    const confirmed = await confirm({ message: t("removeTokenConfirm"), tone: "danger", confirmLabel: t("removeToken") });
    if (confirmed) await save(payloadFromForm({ ntfy_token: "" }));
  }

  async function sendTest() {
    setTesting(true);
    try {
      const result = await browserApiFetch<NotificationTestResult>("/api/admin/notifications/test", { method: "POST" });
      if (result.ok) showToast(t("testSent"), "success");
      else showToast(t("testFailed", { error: result.error ?? "" }), "error");
      setSettings(await browserApiFetch<NotificationSettings>("/api/admin/notifications"));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("testFailed", { error: "" }), "error");
    } finally {
      setTesting(false);
    }
  }

  async function rotateStatusToken() {
    if (settings.status_token) {
      const confirmed = await confirm({ message: t("rotateConfirm"), tone: "danger", confirmLabel: t("rotate") });
      if (!confirmed) return;
    }
    try {
      const updated = await browserApiFetch<NotificationSettings>("/api/admin/notifications/status-token", { method: "POST" });
      setSettings(updated);
      showToast(t("rotated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar title={t("title")} description={t("description")} />

      <section className="card">
        <DataToolbar title={t("ntfyTitle")} description={t("ntfyDescription")} />
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">{t("enabledLabel")}</span>
            <select value={form.ntfy_enabled ? "1" : "0"} onChange={(e) => setForm((f) => ({ ...f, ntfy_enabled: e.target.value === "1" }))}>
              <option value="0">{t("no")}</option>
              <option value="1">{t("yes")}</option>
            </select>
          </label>

          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("serverUrl")}</span>
              <input
                value={form.ntfy_server_url}
                onChange={(e) => setForm((f) => ({ ...f, ntfy_server_url: e.target.value }))}
                placeholder="https://ntfy.example.com" // i18n-ok: Beispiel-URL, keine UI-Sprache
                inputMode="url"
              />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("topic")}</span>
              <input
                value={form.ntfy_topic}
                onChange={(e) => setForm((f) => ({ ...f, ntfy_topic: e.target.value }))}
                placeholder="hocx-alerts" // i18n-ok: Beispiel-Topic, keine UI-Sprache
              />
              <span className="field-help">{t("topicHelp")}</span>
            </label>
          </div>

          <label className="field-stack">
            <span className="field-label">{t("token")}</span>
            <input
              type="password"
              value={form.ntfy_token}
              onChange={(e) => setForm((f) => ({ ...f, ntfy_token: e.target.value }))}
              placeholder={settings.ntfy_token_set ? t("tokenSetPlaceholder") : t("tokenPlaceholder")}
              autoComplete="new-password"
            />
            <span className="field-help">{t("tokenHelp")}</span>
          </label>

          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("adminUrl")}</span>
              <input
                value={form.admin_url}
                onChange={(e) => setForm((f) => ({ ...f, admin_url: e.target.value }))}
                placeholder="https://admin.example.com" // i18n-ok: Beispiel-URL, keine UI-Sprache
                inputMode="url"
              />
              <span className="field-help">{t("adminUrlHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("reminderHours")}</span>
              <input
                type="number"
                min={0}
                max={168}
                value={form.reminder_hours}
                onChange={(e) => setForm((f) => ({ ...f, reminder_hours: Math.max(0, Math.min(168, Number(e.target.value) || 0)) }))}
              />
              <span className="field-help">{t("reminderHelp")}</span>
            </label>
          </div>

          {settings.last_send_error && settings.last_send_error_at && (
            <StatusBanner tone="error" message={t("lastError", { time: formatDateTime(settings.last_send_error_at, locale), error: settings.last_send_error })} />
          )}
          {!settings.last_send_error && settings.last_sent_at && (
            <StatusBanner tone="success" message={t("lastSent", { time: formatDateTime(settings.last_sent_at, locale) })} />
          )}

          <div className="modal-actions">
            {settings.ntfy_token_set && (
              <button type="button" className="button-danger" onClick={() => void removeToken()} disabled={saving}>
                {t("removeToken")}
              </button>
            )}
            <button type="button" className="button-secondary" onClick={() => void sendTest()} disabled={testing || dirty || !settings.ntfy_server_url}>
              {testing ? "…" : t("sendTest")}
            </button>
            <button type="submit" className="button-primary" disabled={saving || !dirty}>
              {saving ? "…" : t("save")}
            </button>
          </div>
          {dirty && <span className="field-help">{t("saveBeforeTest")}</span>}
        </form>
      </section>

      <section className="card">
        <DataToolbar
          title={t("statusTitle")}
          description={t("statusDescription")}
          actions={
            <button type="button" className="button-secondary" onClick={() => void rotateStatusToken()}>
              {settings.status_token ? t("rotate") : t("createToken")}
            </button>
          }
        />
        {settings.status_url ? (
          <div className="grid">
            <CopyField label={t("statusUrl")} value={settings.status_url} />
            <p className="muted admin-job-description">{t("statusHelp")}</p>
          </div>
        ) : (
          <p className="muted">{t("noStatusToken")}</p>
        )}
      </section>
    </div>
  );
}
