"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import {
  apiErrorCode,
  GOOGLE_PICKER_PAGE,
  isPhotosPickerUri,
  photosPickerUrl,
  type ImportJob,
  type PhotosPoll,
  type PhotosSession,
} from "@/lib/files/file-import";

type ErrorText = (error: unknown) => string;

/** Google Drive (drive.file): Auswahl nur im Google Picker auf eigener Seite (eigene CSP). */
export function GoogleDriveSelect({ job, onCancel, busy }: { job: ImportJob; onCancel: () => void; busy: boolean }) {
  const t = useTranslations("fileImport");
  return (
    <>
      <p className="muted">{t("cloud.google.driveHint")}</p>
      <p className="field-help">{t("cloud.google.driveFolders")}</p>
      <div className="modal-actions">
        <button type="button" className="button-ghost" disabled={busy} onClick={onCancel}>{t("cancel.label")}</button>
        {/* Voller Seitenwechsel (kein Link der App): nur die Picker-Seite bekommt die gelockerte CSP */}
        <a className="button-primary" href={`${GOOGLE_PICKER_PAGE}?job=${encodeURIComponent(job.id)}`}>
          {t("cloud.google.driveChoose")}
        </a>
      </div>
    </>
  );
}

type PhotosState = { uri: string; pollMs: number; deadline: number | null } | null;

/** Google Fotos: Auswahl in Google Fotos (neues Fenster), hocX fragt den Stand im Takt von Google ab. */
export function GooglePhotosSelect({
  job,
  onJob,
  onCancel,
  errorText,
}: {
  job: ImportJob;
  onJob: (job: ImportJob) => void;
  onCancel: () => void;
  errorText: ErrorText;
}) {
  const t = useTranslations("fileImport");
  const showToast = useToast();
  const [session, setSession] = useState<PhotosState>(null);
  const [busy, setBusy] = useState(false);
  const [expired, setExpired] = useState(false);
  const onJobRef = useRef(onJob);
  onJobRef.current = onJob;

  useEffect(() => {
    if (!session) return;
    let stopped = false;
    let timer: number | undefined;
    const tick = async () => {
      if (stopped) return;
      if (session.deadline !== null && Date.now() > session.deadline) {
        setSession(null);
        setExpired(true);
        return;
      }
      try {
        const poll = await browserApiFetch<PhotosPoll>(`/api/cloud-import/jobs/${job.id}/google-photos/session/poll`, { method: "POST" });
        if (stopped) return;
        if (poll.done) {
          setSession(null);
          onJobRef.current(poll.job);
          return;
        }
        timer = window.setTimeout(tick, Math.max(2000, poll.poll_seconds * 1000));
      } catch (error) {
        if (stopped) return;
        if (apiErrorCode(error) === "photos_session_expired") {
          setSession(null);
          setExpired(true);
          return;
        }
        timer = window.setTimeout(tick, session.pollMs * 2);
      }
    };
    timer = window.setTimeout(tick, session.pollMs);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [job.id, session]);

  async function start() {
    setBusy(true);
    setExpired(false);
    // Fenster sofort im Klick öffnen (Popup-Blocker), Adresse folgt nach der Antwort
    const popup = window.open("", "_blank");
    try {
      const created = await browserApiFetch<PhotosSession>(`/api/cloud-import/jobs/${job.id}/google-photos/session`, { method: "POST" });
      if (!isPhotosPickerUri(created.picker_uri, window.location.origin)) {
        throw Object.assign(new Error("picker_uri"), { detail: { code: "provider_bad_response" } }); // i18n-ok: Fehlercode, Text über cloud.errors.*
      }
      const uri = photosPickerUrl(created.picker_uri);
      if (popup) {
        popup.opener = null;
        popup.location.href = uri;
      }
      setSession({
        uri,
        pollMs: Math.max(2000, created.poll_seconds * 1000),
        deadline: created.timeout_seconds ? Date.now() + created.timeout_seconds * 1000 : null,
      });
    } catch (error) {
      popup?.close();
      showToast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="muted">{t("cloud.google.photosHint")}</p>
      {expired ? <StatusBanner tone="warning" message={t("cloud.errors.photos_session_expired")} /> : null}
      {session ? (
        <div className="file-import-photos-waiting" aria-live="polite">
          <progress className="gallery-upload-progress" aria-label={t("cloud.google.photosWaiting")} />
          <p>{t("cloud.google.photosWaiting")}</p>
          <p className="field-help">
            {t("cloud.google.photosPopupHint")}{" "}
            <a href={session.uri} target="_blank" rel="noopener noreferrer">{t("cloud.google.photosOpen")}</a>
          </p>
        </div>
      ) : null}
      <div className="modal-actions">
        <button type="button" className="button-ghost" disabled={busy} onClick={onCancel}>{t("cancel.label")}</button>
        <button type="button" className="button-primary" disabled={busy} onClick={() => void start()}>
          {session ? t("cloud.google.photosRestart") : t("cloud.google.photosChoose")}
        </button>
      </div>
    </>
  );
}
