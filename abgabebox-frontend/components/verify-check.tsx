"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { formatDate } from "@/lib/format";
import { classifyResult, sha256Hex, shortDocumentId, verifyHash, type VerifyOutcome } from "@/lib/verify";

// Der Hash wird im Speicher berechnet - sehr grosse Dateien sind keine hocX-PDFs.
const MAX_FILE_MB = 200;

type State =
  | { phase: "idle" }
  | { phase: "checking"; fileName: string }
  | { phase: "done"; fileName: string; outcome: VerifyOutcome }
  | { phase: "error"; message: string };

export function VerifyCheck({ documentId }: { documentId: string | null }) {
  const t = useTranslations("abgabebox.verify");
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ phase: "idle" });
  const [dragging, setDragging] = useState(false);
  const [pageDrag, setPageDrag] = useState(false);

  const check = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      if (typeof crypto === "undefined" || !crypto.subtle) {
        setState({ phase: "error", message: t("noCrypto") });
        return;
      }
      if (file.size > MAX_FILE_MB * 1024 * 1024) {
        setState({ phase: "error", message: t("tooLarge", { size: MAX_FILE_MB }) });
        return;
      }
      setState({ phase: "checking", fileName: file.name });
      let hash: string;
      try {
        hash = await sha256Hex(await file.arrayBuffer());
      } catch {
        setState({ phase: "error", message: t("readError") });
        return;
      }
      try {
        const result = await verifyHash(hash, documentId);
        setState({ phase: "done", fileName: file.name, outcome: classifyResult(result) });
      } catch {
        setState({ phase: "error", message: t("error") });
      }
    },
    [documentId, t]
  );

  // Seitenweites Ablegen (Desktop): Overlay, sobald eine Datei über das Fenster gezogen wird.
  useEffect(() => {
    let depth = 0;
    const hasFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
    const onEnter = (event: DragEvent) => { if (hasFiles(event)) { depth += 1; setPageDrag(true); } };
    const onLeave = (event: DragEvent) => { if (hasFiles(event)) { depth = Math.max(0, depth - 1); if (depth === 0) setPageDrag(false); } };
    const onOver = (event: DragEvent) => { if (hasFiles(event)) event.preventDefault(); };
    const onDrop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setPageDrag(false);
      setDragging(false);
      void check(event.dataTransfer?.files?.[0]);
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [check]);

  const reset = () => {
    setState({ phase: "idle" });
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="box-step verify-page">
      <div className="box-step-head">
        <h1>{t("title")}</h1>
        <p className="muted">{t("hint")}</p>
      </div>

      {documentId && state.phase !== "done" && (
        <p className="verify-expected">{t("documentHint", { id: shortDocumentId(documentId) })}</p>
      )}

      {state.phase !== "done" && (
        <div
          className={`drop-zone verify-drop${dragging ? " drop-zone-active" : ""}`}
          role="button"
          tabIndex={0}
          aria-busy={state.phase === "checking"}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inputRef.current?.click(); } }}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
        >
          <input
            ref={inputRef}
            className="sr-only"
            type="file"
            accept="application/pdf,.pdf"
            tabIndex={-1}
            onChange={(event) => void check(event.target.files?.[0])}
          />
          <span className="drop-zone-icon" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9">
              <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z" />
              <path d="M9 12l2 2 4-4" />
            </svg>
          </span>
          <div className="drop-zone-label">
            {state.phase === "checking" ? (
              t("checking")
            ) : dragging ? (
              t("dropRelease")
            ) : (
              <>
                <span className="drop-label-pointer">{t("dropLabel")}</span>
                <span className="drop-label-touch">{t("dropLabelTouch")}</span>
              </>
            )}
          </div>
          <div className="drop-zone-hint">{t("privacy")}</div>
        </div>
      )}

      {state.phase === "error" && <p className="error" role="alert">{state.message}</p>}

      {state.phase === "done" && (
        <div aria-live="polite">
          <VerifyResultCard outcome={state.outcome} fileName={state.fileName} />
          <button type="button" className="button button-outline verify-again" onClick={reset}>{t("checkAnother")}</button>
        </div>
      )}

      {pageDrag && (
        <div className="file-drop-overlay" role="presentation" aria-hidden="true">
          <div className="file-drop-overlay-card">
            <p className="drop-zone-label">{t("dropOverlay")}</p>
            <p className="drop-zone-hint">{t("privacy")}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export function VerifyResultCard({ outcome, fileName }: { outcome: VerifyOutcome; fileName: string }) {
  const t = useTranslations("abgabebox.verify");
  if (outcome.kind === "not_found") {
    return (
      <section className="verify-result verify-result-fail" role="status">
        <h2 className="verify-result-title">
          <span className="verify-result-icon" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </span>
          {t("notFoundTitle")}
        </h2>
        <p>{t("notFoundText")}</p>
        <p className="verify-result-note">{t("notFoundHint")}</p>
        <p className="verify-file">{t("fileName", { name: fileName })}</p>
      </section>
    );
  }
  const { result, identity } = outcome;
  const name = result.tenant_name ?? "";
  const docType = result.document_type && t.has(`docType.${result.document_type}`) ? t(`docType.${result.document_type}`) : result.document_type;
  const status = result.status_code && t.has(`statusLabel.${result.status_code}`) ? t(`statusLabel.${result.status_code}`) : null;
  return (
    <section className="verify-result verify-result-ok" role="status">
      <h2 className="verify-result-title">
        <span className="verify-result-icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
        </span>
        {t("originalTitle")}
      </h2>
      <p>{t("originalText", { date: formatDate(result.created_at) })}</p>

      {identity !== "anonymous" && (
        <div className="verify-identity">
          {result.tenant_has_logo && result.tenant_public_id ? (
            <img className="verify-identity-logo" src={`/verify/logo/${result.tenant_public_id}`} alt={t("logoAlt", { name })} />
          ) : (
            <span className="verify-identity-logo verify-identity-initial" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
          )}
          <div className="verify-identity-text">
            <span className="verify-identity-name">{name}</span>
            {identity === "verified" ? (
              <>
                <span className="verify-badge">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
                  {t("verifiedBadge")}
                </span>
                <span className="verify-identity-hint">{t("verifiedExplanation", { name })}</span>
              </>
            ) : (
              <span className="verify-identity-hint">{t("createdBy", { name })}</span>
            )}
          </div>
        </div>
      )}

      {outcome.otherDocument && <p className="verify-notice verify-notice-warning">{t("otherDocument")}</p>}
      {outcome.newerVersion && <p className="verify-notice verify-notice-info">{t("newerVersion", { version: outcome.newerVersion })}</p>}

      <dl className="verify-facts">
        {docType && (<><dt>{t("fields.documentType")}</dt><dd>{docType}</dd></>)}
        {result.title && (<><dt>{t("fields.title")}</dt><dd>{result.title}</dd></>)}
        {status && (<><dt>{t("fields.status")}</dt><dd>{status}</dd></>)}
        {result.version_label && (<><dt>{t("fields.version")}</dt><dd>{result.version_label}</dd></>)}
        {result.document_id && (<><dt>{t("fields.documentId")}</dt><dd className="verify-id">{shortDocumentId(result.document_id)}</dd></>)}
      </dl>
      <p className="verify-file">{t("fileName", { name: fileName })}</p>
    </section>
  );
}
