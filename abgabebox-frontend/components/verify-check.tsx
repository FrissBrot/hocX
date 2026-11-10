"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { formatDate } from "@/lib/format";
import {
  classifyResult,
  isSiteDocument,
  parseHashFragment,
  redirectTarget,
  sha256Hex,
  shortDocumentId,
  shortHash,
  verifyHash,
  type VerifyOutcome,
  type VerifyRedirect,
  type VerifySite,
} from "@/lib/verify";

// Der Hash wird im Speicher berechnet - sehr grosse Dateien sind keine hocX-PDFs.
const MAX_FILE_MB = 200;
// Bedenkzeit vor der automatischen Weiterleitung (mit «Hier bleiben» abbrechbar)
const REDIRECT_SECONDS = 4;

// fileName null: Prüfung über den Hash aus der Weiterleitung, ohne Datei auf dieser Seite
type State =
  | { phase: "idle" }
  | { phase: "checking"; fileName: string | null; size: number | null }
  | { phase: "done"; fileName: string | null; hash: string; outcome: VerifyOutcome; redirect: VerifyRedirect | null }
  | { phase: "error"; message: string };

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


export function VerifyCheck({ documentId, site }: { documentId: string | null; site: VerifySite | null }) {
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
      setState({ phase: "checking", fileName: file.name, size: file.size });
      let hash: string;
      try {
        hash = await sha256Hex(await file.arrayBuffer());
      } catch {
        setState({ phase: "error", message: t("readError") });
        return;
      }
      await checkHash(hash, file.name);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [documentId, t]
  );

  async function checkHash(hash: string, fileName: string | null) {
    try {
      const result = await verifyHash(hash, documentId);
      const redirect = redirectTarget(result, { currentHost: window.location.hostname, site, documentId, sha256: hash });
      setState({ phase: "done", fileName, hash, outcome: classifyResult(result), redirect });
    } catch {
      setState({ phase: "error", message: t("error") });
    }
  }

  // Weitergeleitet von einer anderen Prüfseite: Hash aus dem Fragment sofort prüfen und das
  // Fragment entfernen (kein erneutes Prüfen beim Neuladen, nichts in der Verlaufs-URL).
  useEffect(() => {
    const hash = parseHashFragment(window.location.hash);
    if (!hash) return;
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    setState({ phase: "checking", fileName: null, size: null });
    void checkHash(hash, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      {site && <VerifySiteHeader site={site} />}
      <div className="box-step-head">
        <h1>{t("title")}</h1>
        <p className="muted">{site?.tenant_name ? t("site.hint", { name: site.tenant_name }) : t("hint")}</p>
      </div>

      {documentId && state.phase !== "done" && (
        <p className="verify-expected">{t("documentHint", { id: shortDocumentId(documentId) })}</p>
      )}

      {state.phase === "checking" && (
        <div className="verify-checking" role="status" aria-live="polite">
          <span className="verify-spinner" aria-hidden="true" />
          <div className="verify-checking-text">
            <span className="verify-checking-title">{state.fileName === null ? t("checking") : t("checkingHash")}</span>
            {state.fileName !== null && (
              <span className="verify-checking-file">
                {state.size !== null ? t("fileWithSize", { name: state.fileName, size: formatSize(state.size) }) : state.fileName}
              </span>
            )}
          </div>
        </div>
      )}

      {(state.phase === "idle" || state.phase === "error") && (
        <div
          className={`drop-zone verify-drop${dragging ? " drop-zone-active" : ""}`}
          role="button"
          tabIndex={0}
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
          <span className="drop-zone-icon verify-drop-icon" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 3.5h8l4 4v13H6zM14 3.5v4h4M12 17v-6m0 0l-2.5 2.5M12 11l2.5 2.5" />
            </svg>
          </span>
          <div className="drop-zone-label">
            {dragging ? (
              t("dropRelease")
            ) : (
              <>
                <span className="drop-label-pointer">{t("dropTitle")}</span>
                <span className="drop-label-touch">{t("dropLabelTouch")}</span>
              </>
            )}
          </div>
          {!dragging && (
            <div className="drop-zone-hint drop-label-pointer">
              {t.rich("dropOr", { choose: (chunks) => <span className="verify-drop-choose">{chunks}</span> })}
            </div>
          )}
          {/* Auf dem Smartphone fehlt der Datenschutzhinweis der Markenfläche. */}
          <div className="drop-zone-hint verify-drop-privacy">{t("privacy")}</div>
        </div>
      )}

      {state.phase === "error" && <p className="error" role="alert">{state.message}</p>}

      {state.phase === "done" && (
        <div aria-live="polite">
          {state.redirect && <VerifyRedirectNotice redirect={state.redirect} outcome={state.outcome} site={site} />}
          <VerifyResultCard outcome={state.outcome} fileName={state.fileName} hash={state.hash} site={site} />
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

function TenantLogo({ tenantId, hasLogo, name }: { tenantId?: string; hasLogo?: boolean; name: string }) {
  const t = useTranslations("abgabebox.verify");
  return hasLogo && tenantId ? (
    <img className="verify-identity-logo" src={`/verify/logo/${tenantId}`} alt={t("logoAlt", { name })} />
  ) : (
    <span className="verify-identity-logo verify-identity-initial" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
  );
}

function OrganizationBadge() {
  const t = useTranslations("abgabebox.verify");
  return (
    <span className="verify-badge">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
      {t("verifiedBadge")}
    </span>
  );
}

// Schwächere Stufe als die Bestätigung durch hocX: belegt nur, dass die Domain per DNS mit dem
// Konto verbunden ist - eine Domain kann jeder registrieren.
function DomainBadge({ domain }: { domain: string }) {
  const t = useTranslations("abgabebox.verify");
  return (
    <span className="verify-badge verify-badge-domain">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
      </svg>
      {t("domainBadge", { domain })}
    </span>
  );
}

// Kopf der Prüfseite unter der Prüf-Domain eines Mandanten
function VerifySiteHeader({ site }: { site: VerifySite }) {
  const t = useTranslations("abgabebox.verify");
  const name = site.tenant_name ?? "";
  return (
    <section className="verify-site" aria-label={t("site.label", { name })}>
      <TenantLogo tenantId={site.tenant_public_id} hasLogo={site.tenant_has_logo} name={name} />
      <div className="verify-identity-text">
        <span className="verify-site-eyebrow">{t("site.eyebrow")}</span>
        <span className="verify-identity-name">{name}</span>
        <span className="verify-site-badges">
          {site.organization_verified && <OrganizationBadge />}
          {site.domain && <DomainBadge domain={site.domain} />}
        </span>
        <span className="verify-identity-hint">{t("site.poweredBy")}</span>
      </div>
    </section>
  );
}

function VerifyRedirectNotice({ redirect, outcome, site }: { redirect: VerifyRedirect; outcome: VerifyOutcome; site: VerifySite | null }) {
  const t = useTranslations("abgabebox.verify");
  const [seconds, setSeconds] = useState(REDIRECT_SECONDS);
  const [stayed, setStayed] = useState(false);
  const name = outcome.kind === "original" ? outcome.result.tenant_name ?? "" : "";

  useEffect(() => {
    if (stayed) return;
    if (seconds <= 0) {
      window.location.assign(redirect.url);
      return;
    }
    const timer = window.setTimeout(() => setSeconds((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [seconds, stayed, redirect.url]);

  const title = redirect.kind === "tenant" ? t("redirect.tenantTitle", { name }) : t("redirect.centralTitle");
  const text = stayed
    ? redirect.kind === "tenant"
      ? t("redirect.tenantStayed", { name, domain: redirect.domain })
      : t("redirect.centralStayed", { site: site?.tenant_name ?? "" })
    : redirect.kind === "tenant"
      ? t("redirect.tenantText", { name, domain: redirect.domain, seconds })
      : t("redirect.centralText", { site: site?.tenant_name ?? "", seconds });

  return (
    <section className="verify-redirect" role="status">
      <h2 className="verify-redirect-title">{title}</h2>
      <p>{text}</p>
      <div className="verify-redirect-actions">
        {!stayed && (
          <button type="button" className="button button-outline" onClick={() => setStayed(true)}>{t("redirect.stay")}</button>
        )}
        <a className="button" href={redirect.url}>{redirect.kind === "tenant" ? t("redirect.openTenant") : t("redirect.openCentral")}</a>
      </div>
    </section>
  );
}

function VerifyFileChip({ fileName, hash }: { fileName: string | null; hash: string }) {
  const t = useTranslations("abgabebox.verify");
  return (
    <div className="verify-file-chip">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true">
        <path d="M6 3.5h8l4 4v13H6zM14 3.5v4h4" />
      </svg>
      <div className="verify-file-chip-text">
        <span className="verify-file-chip-name">{fileName === null ? t("forwardedShort") : fileName}</span>
        <span className="verify-file-chip-hash" title={hash}>{t("hashLabel", { hash: shortHash(hash) })}</span>
      </div>
    </div>
  );
}

function ResultHead({ kind, title, lead }: { kind: "ok" | "fail"; title: string; lead: string }) {
  return (
    <div className="verify-result-head">
      <span className="verify-result-icon" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d={kind === "ok" ? "M5 12.5l4.5 4.5L19 7.5" : "M7 7l10 10M17 7L7 17"} />
        </svg>
      </span>
      <div className="verify-result-headline">
        <h2 className="verify-result-title">{title}</h2>
        <p className="verify-result-lead">{lead}</p>
      </div>
    </div>
  );
}

export function VerifyResultCard({
  outcome,
  fileName,
  hash,
  site = null,
}: {
  outcome: VerifyOutcome;
  fileName: string | null;
  hash: string;
  site?: VerifySite | null;
}) {
  const t = useTranslations("abgabebox.verify");
  if (outcome.kind === "not_found") {
    return (
      <section className="verify-result verify-result-fail" role="status">
        <ResultHead kind="fail" title={t("notFoundTitle")} lead={t("notFoundText")} />
        <div className="verify-result-body">
          <div className="verify-reasons">
            <h3 className="verify-reasons-title">{t("notFoundReasons.title")}</h3>
            <ul>
              <li>{t("notFoundReasons.changed")}</li>
              <li>{t("notFoundReasons.resaved")}</li>
              <li>{t("notFoundReasons.notHocx")}</li>
            </ul>
            <p className="verify-result-note">{t("notFoundHint")}</p>
          </div>
        </div>
        <VerifyFileChip fileName={fileName} hash={hash} />
      </section>
    );
  }
  const { result, identity } = outcome;
  const name = result.tenant_name ?? "";
  // Stufe «Prüf-Domain verifiziert» nur für Dokumente des Mandanten hinter dieser Prüf-Domain
  const ownSite = isSiteDocument(result, site);
  const siteDomain = ownSite ? site?.domain ?? null : null;
  const foreign = Boolean(site?.tenant_public_id) && !ownSite;
  const docType = result.document_type && t.has(`docType.${result.document_type}`) ? t(`docType.${result.document_type}`) : result.document_type;
  const status = result.status_code && t.has(`statusLabel.${result.status_code}`) ? t(`statusLabel.${result.status_code}`) : null;
  return (
    <section className="verify-result verify-result-ok" role="status">
      <ResultHead kind="ok" title={t("originalTitle")} lead={t("originalText", { date: formatDate(result.created_at) })} />
      <div className="verify-result-body">
        {identity !== "anonymous" && (
          <div className="verify-identity">
            <TenantLogo tenantId={result.tenant_public_id} hasLogo={result.tenant_has_logo} name={name} />
            <div className="verify-identity-text">
              <span className="verify-site-eyebrow">{t("issuedBy")}</span>
              <span className="verify-identity-line">
                <span className="verify-identity-name">{name}</span>
                {identity === "verified" && <OrganizationBadge />}
                {siteDomain && <DomainBadge domain={siteDomain} />}
              </span>
              <span className="verify-identity-hint">
                {identity === "verified" ? t("verifiedExplanation", { name }) : t("createdBy", { name })}
              </span>
              {siteDomain && <span className="verify-identity-hint">{t("domainExplanation", { domain: siteDomain, name })}</span>}
            </div>
          </div>
        )}

        {foreign && <p className="verify-notice verify-notice-warning">{t("foreignDocument", { site: site?.tenant_name ?? "" })}</p>}
        {outcome.otherDocument && <p className="verify-notice verify-notice-warning">{t("otherDocument")}</p>}
        {outcome.importUnverified && <p className="verify-notice verify-notice-warning">{t("importUnverified")}</p>}
        {outcome.titleOverridden && <p className="verify-notice verify-notice-info">{t("titleOverridden")}</p>}
        {outcome.newerVersion && <p className="verify-notice verify-notice-info">{t("newerVersion", { version: outcome.newerVersion })}</p>}

        <dl className="verify-facts">
          {docType && <div><dt>{t("fields.documentType")}</dt><dd>{docType}</dd></div>}
          {result.title && <div><dt>{t("fields.title")}</dt><dd>{result.title}</dd></div>}
          {status && <div><dt>{t("fields.status")}</dt><dd>{status}</dd></div>}
          {result.version_label && <div><dt>{t("fields.version")}</dt><dd>{result.version_label}</dd></div>}
          {result.document_id && <div><dt>{t("fields.documentId")}</dt><dd className="verify-id">{shortDocumentId(result.document_id)}</dd></div>}
        </dl>
      </div>
      <VerifyFileChip fileName={fileName} hash={hash} />
    </section>
  );
}
