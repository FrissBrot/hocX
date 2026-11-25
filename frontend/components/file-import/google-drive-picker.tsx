"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import {
  apiErrorCode,
  GOOGLE_PICKER_FAKE_SCRIPT,
  GOOGLE_PICKER_SCRIPT,
  pickedFileIds,
  pickerJobId,
  wizardUrl,
  type GooglePickerConfig,
} from "@/lib/files/file-import";

// Ausschnitt der Google-Picker-API, den hocX nutzt (https://developers.google.com/workspace/drive/picker)
type PickerResponse = { action?: string; docs?: { id?: unknown; mimeType?: unknown }[] };
type PickerView = Record<string, (...args: unknown[]) => PickerView>;
type PickerBuilder = Record<string, (...args: unknown[]) => PickerBuilder> & {
  build: () => { setVisible: (visible: boolean) => void; dispose?: () => void };
};
type PickerApi = {
  PickerBuilder: new () => PickerBuilder;
  DocsView: new (viewId?: unknown) => PickerView;
  ViewId: { DOCS: unknown };
  DocsViewMode: { LIST: unknown };
  Feature: { MULTISELECT_ENABLED: unknown };
  Action: { PICKED: string; CANCEL: string };
};
type GoogleWindow = Window & { gapi?: { load: (name: string, callback: () => void) => void }; google?: { picker?: PickerApi } };

type Phase = "loading" | "ready" | "applying" | "cancelled" | "error";

// Ein Ladevorgang je Skript: ein zweiter Aufruf (Strict Mode führt Effekte doppelt aus, erneutes
// Öffnen der Seite) wartet auf denselben Ladevorgang, statt vor dem Laden schon «fertig» zu melden.
const scriptLoads = new Map<string, Promise<void>>();

function loadScript(src: string, nonce: string): Promise<void> {
  const pending = scriptLoads.get(src);
  if (pending) return pending;
  const loading = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.nonce = nonce;
    script.dataset.googlePicker = src;
    script.onload = () => resolve();
    script.onerror = () => {
      // Nächster Versuch lädt neu (z. B. nach einem Netzfehler)
      scriptLoads.delete(src);
      script.remove();
      reject(new Error("script")); // i18n-ok: technischer Fehler, angezeigt wird picker_unavailable
    };
    document.head.appendChild(script);
  });
  scriptLoads.set(src, loading);
  return loading;
}

/** Google Picker: Person wählt Dateien in ihrem Google Drive, hocX erhält damit Zugriff (drive.file). */
export function GoogleDrivePicker({ nonce }: { nonce: string }) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const [jobId, setJobId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const config = useRef<GooglePickerConfig | null>(null);
  const openButton = useRef<HTMLButtonElement>(null);

  const leave = useCallback((id: string | null) => {
    // Voller Seitenwechsel: der Wizard bekommt wieder die normale, strenge CSP
    window.location.assign(wizardUrl(id));
  }, []);

  const apply = useCallback(
    async (id: string, response: PickerResponse) => {
      const picker = (window as GoogleWindow).google?.picker;
      if (response.action === picker?.Action.CANCEL) {
        setPhase("cancelled");
        return;
      }
      if (response.action !== picker?.Action.PICKED) return;
      const refs = pickedFileIds(response.docs ?? [], config.current?.max_items ?? 200);
      if (!refs.length) {
        setError("picker_no_files"); // i18n-ok: Fehlercode, Text über cloud.errors.*
        setPhase("cancelled");
        return;
      }
      setPhase("applying");
      try {
        await browserApiFetch(`/api/cloud-import/jobs/${id}/selection`, { method: "POST", body: JSON.stringify({ refs }) });
        leave(id);
      } catch (failure) {
        setError(apiErrorCode(failure) ?? "generic");
        setPhase("error");
      }
    },
    [leave],
  );

  const open = useCallback(() => {
    const picker = (window as GoogleWindow).google?.picker;
    const current = config.current;
    if (!picker || !current || !jobId) return;
    setError(null);
    const files = new picker.DocsView(picker.ViewId.DOCS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false)
      .setMode(picker.DocsViewMode.LIST);
    const sharedDrives = new picker.DocsView(picker.ViewId.DOCS).setEnableDrives(true).setIncludeFolders(true).setSelectFolderEnabled(false);
    new picker.PickerBuilder()
      .addView(files)
      .addView(sharedDrives)
      .enableFeature(picker.Feature.MULTISELECT_ENABLED)
      .setMaxItems(current.max_items)
      .setOAuthToken(current.access_token)
      .setDeveloperKey(current.api_key)
      .setAppId(current.app_id)
      .setLocale(locale)
      .setOrigin(window.location.origin)
      .setTitle(t("googlePicker.pickerTitle"))
      .setCallback((response: unknown) => void apply(jobId, response as PickerResponse))
      .build()
      .setVisible(true);
    setPhase("ready");
  }, [apply, jobId, locale, t]);

  useEffect(() => {
    const id = pickerJobId(window.location.search);
    setJobId(id);
    if (!id) {
      setError("invalid_status"); // i18n-ok: Fehlercode, Text über cloud.errors.*
      setPhase("error");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const loaded = await browserApiFetch<GooglePickerConfig>(`/api/cloud-import/jobs/${id}/google-drive/picker`, { method: "POST" });
        config.current = loaded;
        await loadScript(loaded.fake ? GOOGLE_PICKER_FAKE_SCRIPT : GOOGLE_PICKER_SCRIPT, nonce);
        const gapi = (window as GoogleWindow).gapi;
        if (!gapi) throw new Error("gapi"); // i18n-ok: technischer Fehler, angezeigt wird picker_unavailable
        await new Promise<void>((resolve) => gapi.load("picker", resolve));
        if (!cancelled) setPhase("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(apiErrorCode(failure) ?? "picker_unavailable");
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
      // Token nicht länger als nötig im Speicher
      config.current = null;
    };
  }, [nonce]);

  // Picker öffnet sich von selbst, sobald alles geladen ist
  const autoOpened = useRef(false);
  useEffect(() => {
    if (phase === "ready" && !autoOpened.current && config.current) {
      autoOpened.current = true;
      open();
    }
    if (phase === "cancelled") openButton.current?.focus();
  }, [open, phase]);

  const message = error && t.has(`cloud.errors.${error}`) ? t(`cloud.errors.${error}`) : error ? t("errors.generic") : null;

  return (
    <section className="section-card file-import-card file-import-picker" aria-live="polite">
      <h1 className="section-title">{t("googlePicker.title")}</h1>
      <p className="muted">{t("googlePicker.intro")}</p>
      {phase === "loading" ? <p>{t("googlePicker.loading")}</p> : null}
      {phase === "applying" ? <p>{t("googlePicker.applying")}</p> : null}
      {phase === "cancelled" && !error ? <p>{t("googlePicker.cancelled")}</p> : null}
      {message ? <StatusBanner tone="warning" message={message} /> : null}
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={() => leave(jobId)} disabled={phase === "applying"}>
          {t("googlePicker.back")}
        </button>
        <button
          ref={openButton}
          type="button"
          className="button-primary"
          onClick={open}
          disabled={phase === "loading" || phase === "applying" || !config.current}
        >
          {t("googlePicker.open")}
        </button>
      </div>
    </section>
  );
}
