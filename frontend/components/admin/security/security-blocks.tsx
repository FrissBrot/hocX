"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch } from "@/lib/admin-step-up";
import {
  BLOCK_DURATION_PRESETS,
  durationParts,
  ganttDayTicks,
  ganttGeometry,
  parseBlockMinutes,
  remainingPercent,
} from "@/lib/admin/security-blocks";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { countryName } from "@/lib/utils/country";
import { formatDateTime, formatShortWeekdayDate } from "@/lib/utils/format";
import type { AuthBlock, AuthBlockHistory, AuthDefenseLadder } from "@/types/admin-security";

// Höchstdauer einer manuellen Sperre (backend app/auth_security/blocks.py::MAX_MANUAL_MINUTES)
const MAX_MINUTES = 30 * 24 * 60;
const POLL_MS = 30_000;
// Unter dieser Restzeit wird die Karte hervorgehoben (läuft bald ab)
const SOON_SECONDS = 30 * 60;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function useNowSeconds(active: boolean): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

/** /admin/security/blocks (1.6, Design «hocX Sicherheit Sperren»): Abwehrleiter, aktive Sperren mit
 * Countdown, Verlängern/Aufheben (Passkey), Verlauf 7 Tage (Gantt + Tabelle), manuelle Sperre. */
export function SecurityBlocks({ canWrite }: { canWrite: boolean }) {
  const t = useTranslations("adminSecurity.blocks");
  const tRoot = useTranslations("adminSecurity");
  const confirm = useConfirm();
  const showToast = useToast();
  const blocks = useAdminResource<AuthBlock[]>("/api/admin/auth-security/blocks");
  const ladder = useAdminResource<AuthDefenseLadder>("/api/admin/auth-security/blocks/ladder");
  const history = useAdminResource<AuthBlockHistory>("/api/admin/auth-security/blocks/history");
  const [createOpen, setCreateOpen] = useState(false);
  const [extending, setExtending] = useState<AuthBlock | null>(null);
  const reloadBlocks = blocks.reload;
  const reloadLadder = ladder.reload;
  const reloadHistory = history.reload;
  const reloadAll = useCallback(() => {
    reloadBlocks();
    reloadLadder();
    reloadHistory();
  }, [reloadBlocks, reloadLadder, reloadHistory]);
  // Live: Liste und Leiter alle 30 s (nur bei sichtbarer Seite)
  const poll = useCallback(() => {
    reloadBlocks();
    reloadLadder();
  }, [reloadBlocks, reloadLadder]);
  useVisibleInterval(poll, POLL_MS);

  const active = blocks.data ?? [];
  const now = useNowSeconds(active.length > 0);

  async function unblock(block: AuthBlock) {
    const confirmed = await confirm({ message: t("unblockConfirm", { subject: block.short }), tone: "danger", confirmLabel: t("unblock") });
    if (!confirmed) return;
    try {
      await stepUpFetch("security-block", `/api/admin/auth-security/blocks/${encodeURIComponent(block.subject)}`, { method: "DELETE" });
      showToast(t("unblocked"), "success");
      reloadAll();
    } catch (error) {
      showToast(t("failed", { message: errorMessage(error) }), "error");
    }
  }

  const header = (
    <SecurityPageHeader
      title={t("title")}
      description={t("description")}
      actions={canWrite ? <button type="button" className="button-primary" onClick={() => setCreateOpen(true)}>{t("add")}</button> : null}
    />
  );

  if (blocks.forbidden) {
    return (
      <>
        {header}
        <StatusBanner tone="neutral" message={tRoot("ownerOnly")} />
      </>
    );
  }

  return (
    <>
      {header}
      {blocks.failed || ladder.failed || history.failed ? <StatusBanner tone="error" message={tRoot("loadFailed")} /> : null}
      {!canWrite ? <StatusBanner tone="neutral" message={t("readOnly")} /> : null}

      {ladder.data ? <DefenseLadder ladder={ladder.data} /> : null}

      <section className="section-stack" aria-labelledby="security-blocks-active">
        <div className="admin-security-section-head">
          <h2 id="security-blocks-active" className="section-title">
            {t("activeTitle")} <span className="muted">{active.length}</span>
          </h2>
          <button type="button" className="button-secondary button-ghost" onClick={reloadAll}>{tRoot("refresh")}</button>
        </div>
        {active.length === 0 ? (
          <p className="muted">{blocks.loading ? null : t("empty")}</p>
        ) : (
          <div className="admin-security-block-grid">
            {active.map((block) => (
              <BlockCard
                key={block.subject}
                block={block}
                now={now}
                canWrite={canWrite}
                onExtend={() => setExtending(block)}
                onUnblock={() => void unblock(block)}
              />
            ))}
          </div>
        )}
      </section>

      {history.data ? <BlockHistory history={history.data} /> : null}

      <ManualBlockModal open={createOpen} onClose={() => setCreateOpen(false)} onDone={reloadAll} />
      <ExtendBlockModal block={extending} onClose={() => setExtending(null)} onDone={reloadAll} />
    </>
  );
}

const STAGES = [1, 2, 3, 4, 5] as const;

function DefenseLadder({ ladder }: { ladder: AuthDefenseLadder }) {
  const t = useTranslations("adminSecurity.blocks.ladder");
  const counts: Record<(typeof STAGES)[number], number> = {
    1: ladder.events_24h.observed,
    2: ladder.events_24h.limited,
    3: ladder.events_24h.challenged,
    4: ladder.automatic,
    5: ladder.manual,
  };
  return (
    <section className="card section-stack" aria-labelledby="security-blocks-ladder">
      <div className="admin-security-section-head">
        <h2 id="security-blocks-ladder" className="section-title">{t("title")}</h2>
        <span className="muted">{t("hint")}</span>
      </div>
      <ol className="admin-security-ladder">
        {STAGES.map((stage) => {
          const count = counts[stage];
          return (
            <li key={stage} className={`admin-security-stage admin-security-stage-${stage}${stage >= 4 && count > 0 ? " admin-security-stage-active" : ""}`}>
              <div className="admin-security-stage-head">
                <span className="admin-security-stage-label">{t("stage", { stage })}</span>
                <strong className="admin-security-stage-count">{count.toLocaleString()}</strong>
              </div>
              <span className="admin-security-stage-title">{t(`stages.${stage}.title`)}</span>
              <span className="admin-security-stage-text">{t(`stages.${stage}.text`)}</span>
              <span className="admin-security-stage-unit">{stage <= 3 ? t("events24h") : t("activeNow")}</span>
            </li>
          );
        })}
      </ol>
      <ul className="admin-security-rules">
        <li>{t("strikes", { strikes: ladder.strikes })}</li>
        <li>{t("durations", { durations: ladder.durations.join(" → ") })}</li>
        <li>{t("limits", { automatic: Math.round(ladder.max_automatic_minutes / 60), manual: Math.round(ladder.max_manual_minutes / 1440) })}</li>
        <li>{t("adminsExempt")}</li>
      </ul>
    </section>
  );
}

function Remaining({ seconds }: { seconds: number }) {
  const t = useTranslations("adminSecurity.blocks");
  const parts = durationParts(seconds);
  const text = parts.days > 0
    ? t("remainingDays", { days: parts.days, hours: parts.hours })
    : parts.hours > 0
      ? t("remainingHours", { hours: parts.hours, minutes: parts.minutes })
      : t("remainingMinutes", { minutes: parts.minutes, seconds: String(parts.seconds).padStart(2, "0") });
  return <>{text}</>;
}

function BlockCard({
  block, now, canWrite, onExtend, onUnblock,
}: {
  block: AuthBlock;
  now: number;
  canWrite: boolean;
  onExtend: () => void;
  onUnblock: () => void;
}) {
  const t = useTranslations("adminSecurity.blocks");
  const locale = useLocale();
  const remaining = Math.max(0, block.until - now);
  const created = block.created || block.until - block.minutes * 60;
  const percent = remainingPercent(block.until, created, now);
  const reason = block.manual ? block.reason : t.has(`reasons.${block.reason}`) ? t(`reasons.${block.reason}`) : block.reason;
  return (
    <article className={`card admin-security-block${remaining < SOON_SECONDS ? " admin-security-block-soon" : ""}`} aria-label={t("cardLabel", { subject: block.short })}>
      <div className="admin-security-block-head">
        <div className="admin-security-block-id">
          <code className="admin-security-block-subject">{block.short}</code>
          <span className="admin-security-block-badges">
            <Badge variant="neutral">{t(`scopes.${block.scope}`)}</Badge>
            <span className={`admin-security-kind admin-security-kind-${block.manual ? "manual" : "automatic"}`}>
              {block.manual ? t("manual") : t("automatic")}
            </span>
            <Badge variant="neutral">{t("stageBadge", { stage: block.stage })}</Badge>
          </span>
        </div>
        <div className="admin-security-block-remaining">
          <strong aria-live="off"><Remaining seconds={remaining} /></strong>
          <span className="muted">{t("remaining")}</span>
        </div>
      </div>
      <div className="admin-security-block-progress">
        <div
          className="admin-security-meter"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(percent)}
          aria-label={t("remainingShare")}
        >
          {/* Breite = Laufzeitwert (Restanteil) */}
          <div className={`admin-security-meter-fill admin-security-meter-${block.manual ? "manual" : "automatic"}`} style={{ width: `${percent}%` }} />
        </div>
        <div className="admin-security-block-times">
          <span>{formatDateTime(new Date(created * 1000).toISOString(), locale)}</span>
          <span>{formatDateTime(new Date(block.until * 1000).toISOString(), locale)}</span>
        </div>
      </div>
      <dl className="admin-security-block-facts">
        <dt>{t("facts.reason")}</dt>
        <dd>{reason || "—"}{!block.manual && block.repeat > 1 ? ` · ${t("repeat", { count: block.repeat })}` : null}</dd>
        <dt>{t("facts.rejected")}</dt>
        <dd>{block.rejected.toLocaleString()}</dd>
        <dt>{t("facts.by")}</dt>
        <dd>{block.manual ? (block.admin_name ?? t("unknownAdmin")) : t("automatic")}</dd>
      </dl>
      {canWrite ? (
        <div className="admin-security-block-actions">
          <button type="button" className="button-secondary" onClick={onExtend}>{t("extend")}</button>
          <button type="button" className="button-danger" onClick={onUnblock}>{t("unblock")}</button>
        </div>
      ) : null}
    </article>
  );
}

function BlockHistory({ history }: { history: AuthBlockHistory }) {
  const t = useTranslations("adminSecurity.blocks.history");
  const tBlocks = useTranslations("adminSecurity.blocks");
  const locale = useLocale();
  const summaryId = useId();
  const [asTable, setAsTable] = useState(false);
  const ticks = useMemo(() => ganttDayTicks(history.start, history.end), [history.start, history.end]);
  const bars = history.sources.reduce((sum, source) => sum + source.bars.length, 0);
  const manual = history.sources.reduce((sum, source) => sum + source.bars.filter((bar) => bar.manual).length, 0);

  function barLabel(bar: AuthBlockHistory["sources"][number]["bars"][number]): string {
    const status = bar.cleared ? t("status.cleared") : bar.replaced ? t("status.extended") : new Date(bar.end).getTime() > Date.now() ? t("status.active") : t("status.expired");
    return t("barLabel", {
      kind: bar.manual ? tBlocks("manual") : tBlocks("automatic"),
      start: formatDateTime(bar.start, locale),
      minutes: bar.minutes,
      status,
    });
  }

  return (
    <section className="card section-stack" aria-labelledby="security-blocks-history">
      <div className="admin-security-section-head">
        <div>
          <h2 id="security-blocks-history" className="section-title">{t("title")}</h2>
          <p className="muted" id={summaryId}>{t("summary", { sources: history.sources.length, bars, manual })}</p>
        </div>
        <div className="admin-security-legend">
          <span><span className="admin-security-swatch admin-security-swatch-automatic" aria-hidden="true" />{tBlocks("automatic")}</span>
          <span><span className="admin-security-swatch admin-security-swatch-manual" aria-hidden="true" />{tBlocks("manual")}</span>
          <span><span className="admin-security-swatch admin-security-swatch-cleared" aria-hidden="true" />{t("status.cleared")}</span>
          <button type="button" className="button-secondary button-ghost" aria-pressed={asTable} onClick={() => setAsTable((value) => !value)}>
            {asTable ? t("showChart") : t("showTable")}
          </button>
        </div>
      </div>
      {history.sources.length === 0 ? (
        <p className="muted">{t("empty")}</p>
      ) : asTable ? (
        <DataTable columns={[t("columns.source"), t("columns.kind"), t("columns.start"), t("columns.end"), t("columns.minutes"), t("columns.status")]}>
          {history.sources.flatMap((source) =>
            source.bars.map((bar) => (
              <tr key={`${source.subject}-${bar.start}`}>
                <td><code>{source.subject}</code></td>
                <td>{bar.manual ? tBlocks("manual") : tBlocks("automatic")}</td>
                <td>{formatDateTime(bar.start, locale)}</td>
                <td>{formatDateTime(bar.end, locale)}</td>
                <td>{bar.minutes.toLocaleString()}</td>
                <td>{bar.cleared ? t("status.cleared") : bar.replaced ? t("status.extended") : new Date(bar.end).getTime() > Date.now() ? t("status.active") : t("status.expired")}</td>
              </tr>
            ))
          )}
        </DataTable>
      ) : (
        <div className="admin-security-gantt-scroll">
          <div className="admin-security-gantt" role="img" aria-label={t("title")} aria-describedby={summaryId}>
            <div className="admin-security-gantt-row admin-security-gantt-axis" aria-hidden="true">
              <span />
              <div className="admin-security-gantt-track">
                {ticks.map((tick) => (
                  <span key={tick.date.toISOString()} className="admin-security-gantt-tick" style={{ left: `${tick.left}%` }}>
                    {formatShortWeekdayDate(tick.date.toISOString(), locale)}
                  </span>
                ))}
              </div>
            </div>
            {history.sources.map((source) => (
              <div key={source.subject} className="admin-security-gantt-row">
                <span className="admin-security-gantt-label">
                  <code>{source.subject}</code>
                  <span className="muted">
                    {[source.country ? countryName(source.country, locale) : null, source.scope ? tBlocks(`scopes.${source.scope}`) : null].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <div className="admin-security-gantt-track admin-security-gantt-grid">
                  {source.bars.map((bar) => {
                    const geometry = ganttGeometry(bar.start, bar.end, history.start, history.end);
                    const kind = bar.cleared ? "cleared" : bar.manual ? "manual" : "automatic";
                    return (
                      <span
                        key={bar.start}
                        className={`admin-security-gantt-bar admin-security-gantt-bar-${kind}`}
                        style={{ left: `${geometry.left}%`, width: `${geometry.width}%` }}
                        title={barLabel(bar)}
                      />
                    );
                  })}
                  <span className="admin-security-gantt-now" />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function DurationField({
  preset, custom, onPreset, onCustom,
}: {
  preset: string;
  custom: string;
  onPreset: (value: string) => void;
  onCustom: (value: string) => void;
}) {
  const t = useTranslations("adminSecurity.blocks");
  const options = [
    ...BLOCK_DURATION_PRESETS.map((minutes) => ({ value: String(minutes), label: t(`presets.${minutes}`) })),
    { value: "custom", label: t("presets.custom") },
  ];
  return (
    <div className="field-stack">
      <span className="field-label">{t("durationLabel")}</span>
      <FilterTabs variant="chips" options={options} value={preset} onChange={onPreset} />
      {preset === "custom" ? (
        <label className="field-stack">
          <span className="field-label">{t("minutesLabel")}</span>
          <input type="number" min={1} max={MAX_MINUTES} inputMode="numeric" value={custom} onChange={(event) => onCustom(event.target.value)} />
          <span className="field-help">{t("minutesHelp", { max: MAX_MINUTES })}</span>
        </label>
      ) : null}
    </div>
  );
}

function ManualBlockModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const t = useTranslations("adminSecurity.blocks");
  const showToast = useToast();
  const [ip, setIp] = useState("");
  const [scope, setScope] = useState<"source" | "net">("source");
  const [preset, setPreset] = useState("60");
  const [custom, setCustom] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const minutes = parseBlockMinutes(preset, custom, MAX_MINUTES);
  const valid = ip.trim().length > 0 && reason.trim().length > 2 && minutes !== null;

  async function submit() {
    if (!valid || minutes === null) return;
    setBusy(true);
    const body = JSON.stringify({ ip: ip.trim(), scope, minutes, reason: reason.trim() });
    try {
      await stepUpFetch("security-block", "/api/admin/auth-security/blocks", { method: "POST", body });
      showToast(t("created"), "success");
      setIp("");
      setReason("");
      onClose();
      onDone();
    } catch (error) {
      showToast(t("failed", { message: errorMessage(error) }), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={t("modalTitle")} description={t("modalDescription")} onClose={onClose}>
      <ModalSaveForm className="section-stack" onSubmit={(event) => { event.preventDefault(); return submit(); }}>
        <label className="field-stack">
          <span className="field-label">{t("ipLabel")}</span>
          <input value={ip} onChange={(event) => setIp(event.target.value)} maxLength={64} autoComplete="off" spellCheck={false} className="admin-security-mono" />
          <span className="field-help">{t("ipHelp")}</span>
        </label>
        <div className="field-stack">
          <span className="field-label">{t("scopeLabel")}</span>
          <FilterTabs
            options={[
              { value: "source", label: t("scopeOptions.source") },
              { value: "net", label: t("scopeOptions.net") },
            ]}
            value={scope}
            onChange={(value) => setScope(value === "net" ? "net" : "source")}
          />
        </div>
        <DurationField preset={preset} custom={custom} onPreset={setPreset} onCustom={setCustom} />
        <label className="field-stack">
          <span className="field-label">{t("reasonLabel")}</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} required />
          <span className="field-help">{t("reasonHelp")}</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="button-primary" disabled={!valid || busy}>{t("save")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}

function ExtendBlockModal({ block, onClose, onDone }: { block: AuthBlock | null; onClose: () => void; onDone: () => void }) {
  const t = useTranslations("adminSecurity.blocks");
  const showToast = useToast();
  const [preset, setPreset] = useState("60");
  const [custom, setCustom] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const minutes = parseBlockMinutes(preset, custom, MAX_MINUTES);
  const valid = reason.trim().length > 2 && minutes !== null;

  async function submit() {
    if (!block || !valid || minutes === null) return;
    setBusy(true);
    const body = JSON.stringify({ minutes, reason: reason.trim() });
    try {
      await stepUpFetch("security-block", `/api/admin/auth-security/blocks/${encodeURIComponent(block.subject)}/extend`, { method: "POST", body });
      showToast(t("extended"), "success");
      setReason("");
      onClose();
      onDone();
    } catch (error) {
      showToast(t("failed", { message: errorMessage(error) }), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={block !== null} title={t("extendTitle", { subject: block?.short ?? "" })} description={t("extendDescription")} onClose={onClose}>
      <ModalSaveForm className="section-stack" onSubmit={(event) => { event.preventDefault(); return submit(); }}>
        <DurationField preset={preset} custom={custom} onPreset={setPreset} onCustom={setCustom} />
        <label className="field-stack">
          <span className="field-label">{t("reasonLabel")}</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} required />
          <span className="field-help">{t("reasonHelp")}</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="button-primary" disabled={!valid || busy}>{t("extendSave")}</button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
