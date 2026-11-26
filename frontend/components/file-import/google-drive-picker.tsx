"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import {
  GOOGLE_PICKER_FAKE_SCRIPT,
  GOOGLE_PICKER_SCRIPT,
  pickedFileIds,
  pickerTicket,
  safeReturnUrl,
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

// Die Seite läuft auf ihrer eigenen Origin (CLOUD_IMPORT_PICKER_DOMAIN) ohne hocX-Sitzung: sie kennt
// nur das Ticket aus dem Fragment (backend services/cloud_import/picker_tickets.py). Anfragen gehen
// ohne Cookies an die Ticket-Routen derselben Origin.
const TOKEN_PATH = "/api/cloud-import/picker/google-drive/token";
const APPLY_PATH = "/api/cloud-import/picker/google-drive/apply";

class PickerRequestError extends Error {
  constructor(
    readonly code: string,
    readonly returnUrl: string | null,
  ) {
    super(code);
  }
}

async function postTicket<T>(path: string, body: Record<string, unknown>): Promise<T> { // i18n-ok: TypeScript-Generik, kein JSX-Text
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new PickerRequestError("picker_unavailable", null); // i18n-ok: Fehlercode, Text über cloud.errors.*
  }
  const data = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  if (!response.ok) {
    const detail = (data?.detail ?? {}) as { code?: unknown; return_url?: unknown };
    throw new PickerRequestError(typeof detail.code === "string" ? detail.code : "generic", safeReturnUrl(detail.return_url));
  }
  return data as T;
}

// Ticket einmal aus dem Fragment lesen und sofort aus der Adresszeile entfernen. Das Einlösen ist
// einmalig - ein zweiter Effektlauf (Strict Mode) wartet auf dieselbe Anfrage.
let fragmentTicket: string | null | undefined;
const exchanges = new Map<string, Promise<GooglePickerConfig>>();

function takeTicket(): string | null {
  if (fragmentTicket === undefined) {
    fragmentTicket = pickerTicket(window.location.hash);
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
  }
  return fragmentTicket;
}

function exchange(ticket: string): Promise<GooglePickerConfig> {
  const pending = exchanges.get(ticket);
  if (pending) return pending;
  const request = postTicket<GooglePickerConfig>(TOKEN_PATH, { ticket });
  exchanges.set(ticket, request);
  return request;
}

/** Google Picker: Person wählt Dateien in ihrem Google Drive, hocX erhält damit Zugriff (drive.file). */
export function GoogleDrivePicker({ nonce }: { nonce: string }) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [returnUrl, setReturnUrl] = useState<string | null>(null);
  const config = useRef<GooglePickerConfig | null>(null);
  const openButton = useRef<HTMLButtonElement>(null);

  const leave = useCallback(() => {
    // Voller Seitenwechsel zurück auf die App-Origin (Adresse vom Backend, safeReturnUrl)
    if (returnUrl) window.location.assign(returnUrl);
    else window.history.back();
  }, [returnUrl]);

  const apply = useCallback(async (response: PickerResponse) => {
    const picker = (window as GoogleWindow).google?.picker;
    const current = config.current;
    if (response.action === picker?.Action.CANCEL) {
      setPhase("cancelled");
      return;
    }
    if (response.action !== picker?.Action.PICKED || !current) return;
    const fileIds = pickedFileIds(response.docs ?? [], current.max_items);
    if (!fileIds.length) {
      setError("picker_no_files"); // i18n-ok: Fehlercode, Text über cloud.errors.*
      setPhase("cancelled");
      return;
    }
    setPhase("applying");
    try {
      const applied = await postTicket<{ return_url: string }>(APPLY_PATH, { ticket: current.apply_ticket, file_ids: fileIds });
      // Token und Ticket nicht länger als nötig im Speicher
      config.current = null;
      const target = safeReturnUrl(applied.return_url);
      if (target) window.location.assign(target);
      else setPhase("error");
    } catch (failure) {
      // Das Apply-Ticket ist verbraucht: nur noch zurück in den Wizard
      config.current = null;
      setError(failure instanceof PickerRequestError ? failure.code : "generic");
      setPhase("error");
    }
  }, []);

  const open = useCallback(() => {
    const picker = (window as GoogleWindow).google?.picker;
    const current = config.current;
    if (!picker || !current) return;
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
      .setCallback((response: unknown) => void apply(response as PickerResponse))
      .build()
      .setVisible(true);
    setPhase("ready");
  }, [apply, locale, t]);

  useEffect(() => {
    const ticket = takeTicket();
    if (!ticket) {
      setError("ticket_invalid"); // i18n-ok: Fehlercode, Text über cloud.errors.*
      setPhase("error");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const loaded = await exchange(ticket);
        if (cancelled) return;
        config.current = loaded;
        setReturnUrl(safeReturnUrl(loaded.return_url));
        await loadScript(loaded.fake ? GOOGLE_PICKER_FAKE_SCRIPT : GOOGLE_PICKER_SCRIPT, nonce);
        const gapi = (window as GoogleWindow).gapi;
        if (!gapi) throw new Error("gapi"); // i18n-ok: technischer Fehler, angezeigt wird picker_unavailable
        await new Promise<void>((resolve) => gapi.load("picker", resolve));
        if (!cancelled) setPhase("ready");
      } catch (failure) {
        if (cancelled) return;
        if (failure instanceof PickerRequestError) {
          setReturnUrl(failure.returnUrl);
          setError(failure.code);
        } else {
          setError("picker_unavailable"); // i18n-ok: Fehlercode, Text über cloud.errors.*
        }
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
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
        <button type="button" className="button-ghost" onClick={leave} disabled={phase === "applying"}>
          {t("googlePicker.back")}
        </button>
        <button
          ref={openButton}
          type="button"
          className="button-primary"
          onClick={open}
          disabled={phase === "loading" || phase === "applying" || phase === "error" || !config.current}
        >
          {t("googlePicker.open")}
        </button>
      </div>
    </section>
  );
}
