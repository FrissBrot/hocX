"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { ApiError, browserApiFetch, browserApiUpload, LONG_RUNNING_TIMEOUT_MS } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-message";
import { postAndDownload } from "@/lib/download";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { SubmissionAccessView } from "@/types/api";

const STORAGE_KEY = "hocx-submission-access";

/**
 * Token aus dem URL-Fragment (#<token> oder #token=<token>) lesen und sofort aus Adresszeile und
 * Verlauf entfernen. Danach hält nur der Speicher dieses Tabs (sessionStorage) den Link: nach dem
 * Neuladen geht es weiter, in einem neuen Tab nicht (docs/SUBMISSION_OWNER_ACCESS.md).
 */
function takeToken(): string {
  const hash = window.location.hash.slice(1);
  let token = "";
  if (hash) {
    token = new URLSearchParams(hash).get("token") ?? (hash.includes("=") ? "" : hash);
    window.history.replaceState(null, "", window.location.pathname);
    try {
      if (token) window.sessionStorage.setItem(STORAGE_KEY, token);
    } catch {
      // ohne sessionStorage gilt der Link nur bis zum Neuladen
    }
  }
  if (!token) {
    try {
      token = window.sessionStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      token = "";
    }
  }
  return token;
}

type State = { kind: "loading" } | { kind: "invalid" } | { kind: "error" } | { kind: "ready"; view: SubmissionAccessView };

/**
 * «Meine Abgabe»: die eigene Abgabe über den persönlichen Link aus der Mail ansehen und - wenn die
 * Abgabe es erlaubt - zurückziehen und neu abgeben. Ohne Login und ohne App-Navigation, gleiches
 * Muster wie /auth/set-password.
 */
export function SubmissionAccessPage() {
  const t = useTranslations("submissionAccess");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [token, setToken] = useState("");
  const [state, setState] = useState<State>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const tokenRef = useRef<string | null>(null);

  function handleError(error: unknown) {
    const code = apiErrorCode(error);
    if (code === "link_invalid") {
      setState({ kind: "invalid" });
      return;
    }
    if (code === "rate_limited") {
      showToast(t("rateLimited"), "error");
      return;
    }
    const detail = error instanceof ApiError ? error.detail : null;
    const message = detail && typeof detail === "object" && "message" in detail ? String((detail as { message: unknown }).message) : null;
    showToast(message ?? t("failed"), "error");
  }

  useEffect(() => {
    tokenRef.current ??= takeToken();
    const current = tokenRef.current;
    setToken(current);
    if (!current) {
      setState({ kind: "invalid" });
      return;
    }
    let cancelled = false;
    browserApiFetch<SubmissionAccessView>("/api/public/submission-access/view", { method: "POST", body: JSON.stringify({ token: current }) })
      .then((view) => { if (!cancelled) setState({ kind: "ready", view }); })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (apiErrorCode(error) === "link_invalid") setState({ kind: "invalid" });
        else setState({ kind: "error" });
      });
    return () => { cancelled = true; };
  }, []);

  async function download(fileId: string, name: string) {
    try {
      await postAndDownload("/api/public/submission-access/download", { token, file_id: fileId }, name);
    } catch {
      showToast(t("downloadFailed"), "error");
    }
  }

  async function withdraw() {
    const ok = await confirm({ tone: "danger", message: t("withdrawConfirm"), confirmLabel: t("withdraw") });
    if (!ok) return;
    setBusy(true);
    try {
      const view = await browserApiFetch<SubmissionAccessView>("/api/public/submission-access/withdraw", {
        method: "POST", body: JSON.stringify({ token, confirm: true }),
      });
      setState({ kind: "ready", view });
      showToast(t("withdrawn"), "success");
    } catch (error) {
      handleError(error);
    } finally {
      setBusy(false);
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) return;
    // Token im Header: der Multipart-Schutz des Backends prüft ihn, bevor er den Upload liest
    const body = new FormData();
    for (const file of files) body.append("files", file);
    setBusy(true);
    setProgress(0);
    try {
      const result = await browserApiUpload<{ view: SubmissionAccessView; errors: string[] }>("/api/public/submission-access/upload", body, {
        timeoutMs: LONG_RUNNING_TIMEOUT_MS,
        headers: { "X-Submission-Access-Token": token }, // i18n-ok: Header-Name
        onProgress: (loaded, total) => setProgress(total ? Math.round((loaded / total) * 100) : null),
      });
      setState({ kind: "ready", view: result.view });
      if (result.errors.length > 0) showToast(result.errors.join(" · "), "error");
      else showToast(t("uploaded"), "success");
    } catch (error) {
      handleError(error);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  if (state.kind !== "ready") {
    return (
      <main className="login-frame">
        <section className="login-panel">
          <div className="login-heading"><h1>{t("title")}</h1></div>
          {state.kind === "loading" ? <p className="muted">{t("loading")}</p> : null}
          {state.kind === "invalid" ? <p className="login-status" role="alert">{t("invalid")}</p> : null}
          {state.kind === "error" ? <p className="login-status" role="alert">{t("failed")}</p> : null}
        </section>
      </main>
    );
  }

  const view = state.view;
  const statusVariant = view.status === "submitted" ? "success" : view.status === "closed" ? "neutral" : "warning";
  const accept = view.allowed_file_types.length > 0 ? view.allowed_file_types.map((type) => `.${type.replace(/^\./, "")}`).join(",") : undefined;

  return (
    <main className="login-frame">
      <section className="login-panel submission-access-panel">
        <div className="login-heading">
          <p className="submission-access-eyebrow">{view.tenant_name}</p>
          <h1>{view.title}</h1>
          <p className="login-subtitle">{t("greeting", { name: view.person_name, element: view.element_label })}</p>
        </div>

        <div className="submission-access-meta">
          <Badge variant={statusVariant}>{t(`status.${view.status}`)}</Badge>
          {view.window_end ? <span className="muted">{t("until", { date: formatDate(view.window_end) })}</span> : null}
          {view.submitted_at ? <span className="muted">{t("submittedAt", { date: formatDateTime(view.submitted_at, locale) })}</span> : null}
        </div>
        {view.description ? <p className="submission-access-description">{view.description}</p> : null}

        <div className="field-stack">
          <span className="field-label">{t("files")}</span>
          {view.files.length === 0 ? (
            <p className="muted">{t("noFiles")}</p>
          ) : (
            <ul className="submission-access-files">
              {view.files.map((file) => (
                <li key={file.id}>
                  <span className="submission-access-file-name">{file.name}</span>
                  <span className="muted">{file.size ? formatFileSize(file.size, locale) : ""}</span>
                  {file.scan_status === "clean" ? (
                    <button type="button" className="button-secondary button-ghost" onClick={() => void download(file.id, file.name)}>{t("download")}</button>
                  ) : (
                    <Badge variant={file.scan_status === "pending" ? "info" : "danger"}>{t(`scan.${file.scan_status === "pending" ? "pending" : "blocked"}`)}</Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {view.status === "closed" ? <StatusBanner tone="neutral" message={t("closedHint")} /> : null}
        {!view.can_upload && !view.can_withdraw && view.status !== "closed" ? <p className="muted">{t("viewOnlyHint")}</p> : null}

        {view.can_upload || view.can_withdraw ? (
          <div className="table-actions table-actions-start">
            {view.can_withdraw ? (
              <button type="button" className="button-danger" disabled={busy} onClick={() => void withdraw()}>{t("withdraw")}</button>
            ) : null}
            {view.can_upload ? (
              <>
                <input ref={fileInputRef} type="file" multiple hidden accept={accept} onChange={(event) => void upload(event)} />
                <button type="button" className="button-primary" disabled={busy || view.remaining_files === 0} onClick={() => fileInputRef.current?.click()}>
                  {progress !== null ? t("uploading", { percent: progress }) : view.files.length > 0 ? t("uploadMore") : t("upload")}
                </button>
              </>
            ) : null}
          </div>
        ) : null}
        {view.can_upload ? (
          <p className="field-help">
            {t("rules", { size: view.max_file_size_mb, types: view.allowed_file_types.length ? view.allowed_file_types.join(", ") : t("anyType") })}
            {view.remaining_files !== null ? ` ${t("remaining", { count: view.remaining_files })}` : ""}
          </p>
        ) : null}
        {view.can_withdraw ? <p className="field-help">{t("withdrawHint")}</p> : null}
        <p className="field-help submission-access-privacy">{t("privacyHint")}</p>
      </section>
    </main>
  );
}
