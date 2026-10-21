"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";

export type RetentionPolicy = {
  submissions_months: number | null;
  former_members_years: number | null;
  unlinked_gallery_years: number | null;
  auto_apply: boolean;
};

type ProposalKind = "submission_upload" | "former_member" | "gallery_image";

type RetentionProposal = {
  id: string;
  kind: ProposalKind;
  label: string | null;
  reference_date: string | null;
  created_at: string;
};

type DecisionResult = { applied: number; dismissed: number; failed: number; missing: number };

const RULES: { key: keyof Omit<RetentionPolicy, "auto_apply">; unit: "months" | "years"; max: number }[] = [
  { key: "submissions_months", unit: "months", max: 240 },
  { key: "former_members_years", unit: "years", max: 50 },
  { key: "unlinked_gallery_years", unit: "years", max: 50 },
];
const KINDS: ProposalKind[] = ["submission_upload", "former_member", "gallery_image"];

// Mandanten-Einstellungen → Aufbewahrung (Datenschutz-Audit Paket 8). Alle Regeln sind
// standardmässig aus; ehemalige Mitglieder werden nur deaktiviert, nie gelöscht.
export function RetentionSettings({ initialPolicy }: { initialPolicy: RetentionPolicy }) {
  const t = useTranslations("tenantSettings.retention");
  const toast = useToast();
  const confirm = useConfirm();
  const [policy, setPolicy] = useState(initialPolicy);
  const [proposals, setProposals] = useState<RetentionProposal[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setProposals(await browserApiFetch<RetentionProposal[]>("/api/retention/proposals"));
    } catch (error) {
      toast(error instanceof Error ? error.message : t("loadFailed"), "error");
    }
  }, [t, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setBusy(true);
    try {
      setPolicy(await browserApiFetch<RetentionPolicy>("/api/retention/policy", { method: "PUT", body: JSON.stringify(policy) }));
      toast(t("saved"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    try {
      setProposals(await browserApiFetch<RetentionProposal[]>("/api/retention/proposals/refresh", { method: "POST" }));
      setSelected(new Set());
    } catch (error) {
      toast(error instanceof Error ? error.message : t("loadFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: "apply" | "dismiss") {
    const ids = Array.from(selected);
    if (!ids.length) return;
    if (action === "apply") {
      const ok = await confirm({ message: t("applyConfirm", { count: ids.length }), tone: "danger", confirmLabel: t("apply") });
      if (!ok) return;
    }
    setBusy(true);
    try {
      const result = await browserApiFetch<DecisionResult>("/api/retention/proposals/decide", { method: "POST", body: JSON.stringify({ ids, action }) });
      toast(t("decided", { done: result.applied + result.dismissed, failed: result.failed }), result.failed ? "error" : "success");
      setSelected(new Set());
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return (
    <div className="docverify">
      <div className="grid docverify-main">
        <p className="muted docverify-intro">{t("intro")}</p>
        <section className="card docverify-card">
          <div className="docverify-card-head">
            <h2 className="docverify-heading">{t("rulesTitle")}</h2>
          </div>
          {RULES.map((rule) => {
            const value = policy[rule.key];
            return (
              <div key={rule.key} className="retention-rule">
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={value !== null}
                    onChange={(event) => setPolicy((current) => ({ ...current, [rule.key]: event.target.checked ? (rule.unit === "months" ? 12 : 5) : null }))}
                  />
                  <span>{t(`rules.${rule.key}.label`)}</span>
                </label>
                {value !== null ? (
                  <label className="field-stack retention-rule-value">
                    <span className="field-label">{t(`unit.${rule.unit}`)}</span>
                    <input
                      type="number"
                      min={1}
                      max={rule.max}
                      value={value}
                      onChange={(event) => setPolicy((current) => ({ ...current, [rule.key]: Math.min(rule.max, Math.max(1, Math.round(Number(event.target.value) || 1))) }))}
                    />
                  </label>
                ) : null}
                <p className="field-help">{t(`rules.${rule.key}.hint`)}</p>
              </div>
            );
          })}
          <label className="checkbox-row">
            <input type="checkbox" checked={policy.auto_apply} onChange={(event) => setPolicy((current) => ({ ...current, auto_apply: event.target.checked }))} />
            <span>{t("autoApply")}</span>
          </label>
          <p className="field-help">{t("autoApplyHint")}</p>
          <div className="table-actions table-actions-start">
            <button type="button" className="button-primary" disabled={busy} onClick={() => void save()}>
              {t("save")}
            </button>
          </div>
        </section>

        <section className="card docverify-card">
          <div className="docverify-card-head">
            <h2 className="docverify-heading">{t("proposalsTitle")}</h2>
            <button type="button" className="button-secondary" disabled={busy} onClick={() => void refresh()}>
              {t("refresh")}
            </button>
          </div>
          {proposals.length === 0 ? <p className="muted">{t("empty")}</p> : null}
          {KINDS.map((kind) => {
            const items = proposals.filter((item) => item.kind === kind);
            if (!items.length) return null;
            return (
              <div key={kind} className="retention-group">
                <h3 className="retention-group-title">{t(`kind.${kind}`, { count: items.length })}</h3>
                <ul className="retention-list">
                  {items.map((item) => (
                    <li key={item.id}>
                      <label className="checkbox-row">
                        <input type="checkbox" checked={selected.has(item.id)} onChange={(event) => toggle(item.id, event.target.checked)} />
                        <span>{item.label || t("unnamed")}</span>
                        {item.reference_date ? <span className="muted">{formatDate(item.reference_date)}</span> : null}
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
          {proposals.length ? (
            <div className="table-actions table-actions-start">
              <button type="button" className="button-ghost" disabled={busy} onClick={() => setSelected(new Set(proposals.map((item) => item.id)))}>
                {t("selectAll")}
              </button>
              <button type="button" className="button-secondary" disabled={busy || !selected.size} onClick={() => void decide("dismiss")}>
                {t("dismiss")}
              </button>
              <button type="button" className="button-danger" disabled={busy || !selected.size} onClick={() => void decide("apply")}>
                {t("apply")}
              </button>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
