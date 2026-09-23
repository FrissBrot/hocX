"use client";

import { FormEvent, useState } from "react";

import { ActionMenu } from "@/components/ui/action-menu";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatFileSize, formatRappen } from "@/lib/utils/format";
import { AdminFeature, AdminFeatureUpdate, AdminPlan, AdminPlanWrite, AdminStoragePackage, AdminStoragePackageWrite } from "@/types/api";

type Props = {
  initialPlans: AdminPlan[];
  initialFeatures: AdminFeature[];
  initialStoragePackages: AdminStoragePackage[];
};

type PlanFormState = {
  code: string;
  isNew: boolean;
  name: string;
  priceMonthlyChf: string;
  priceYearlyChf: string;
  userLimit: string;
  storageMb: string;
  sortOrder: string;
  featureCodes: Set<string>;
};

type FeatureFormState = {
  code: string;
  name: string;
  description: string;
  priceMonthlyChf: string;
};

type StoragePackageFormState = {
  code: string;
  isNew: boolean;
  name: string;
  storageMb: string;
  priceMonthlyChf: string;
  priceYearlyChf: string;
  sortOrder: string;
};

function storagePackageToForm(pkg: AdminStoragePackage): StoragePackageFormState {
  return {
    code: pkg.code,
    isNew: false,
    name: pkg.name,
    storageMb: String(Math.round(pkg.bytes / (1024 * 1024))),
    priceMonthlyChf: rpToChfInput(pkg.price_monthly_rp),
    priceYearlyChf: rpToChfInput(pkg.price_yearly_rp),
    sortOrder: String(pkg.sort_order),
  };
}

const emptyStoragePackageForm: StoragePackageFormState = {
  code: "",
  isNew: true,
  name: "",
  storageMb: "",
  priceMonthlyChf: "",
  priceYearlyChf: "",
  sortOrder: "0",
};

function rpToChfInput(rp: number | null): string {
  return rp === null ? "" : (rp / 100).toFixed(2);
}

function chfInputToRp(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed.replace(",", "."));
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : null;
}

function planToForm(plan: AdminPlan): PlanFormState {
  return {
    code: plan.code,
    isNew: false,
    name: plan.name,
    priceMonthlyChf: rpToChfInput(plan.price_monthly_rp),
    priceYearlyChf: rpToChfInput(plan.price_yearly_rp),
    userLimit: plan.included_user_limit === null ? "" : String(plan.included_user_limit),
    storageMb: plan.included_storage_bytes === null ? "" : String(Math.round(plan.included_storage_bytes / (1024 * 1024))),
    sortOrder: String(plan.sort_order),
    featureCodes: new Set(plan.feature_codes),
  };
}

const emptyPlanForm: PlanFormState = {
  code: "",
  isNew: true,
  name: "",
  priceMonthlyChf: "",
  priceYearlyChf: "",
  userLimit: "",
  storageMb: "",
  sortOrder: "0",
  featureCodes: new Set(),
};

function featureToForm(feature: AdminFeature): FeatureFormState {
  return {
    code: feature.code,
    name: feature.name,
    description: feature.description ?? "",
    priceMonthlyChf: rpToChfInput(feature.standalone_price_monthly_rp),
  };
}

export function AdminPlanPricing({ initialPlans, initialFeatures, initialStoragePackages }: Props) {
  const showToast = useToast();
  const [plans, setPlans] = useState<AdminPlan[]>(initialPlans);
  const [features, setFeatures] = useState<AdminFeature[]>(initialFeatures);
  const [storagePackages, setStoragePackages] = useState<AdminStoragePackage[]>(initialStoragePackages);

  const [planForm, setPlanForm] = useState<PlanFormState | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [featureForm, setFeatureForm] = useState<FeatureFormState | null>(null);
  const [featureBusy, setFeatureBusy] = useState(false);
  const [storagePackageForm, setStoragePackageForm] = useState<StoragePackageFormState | null>(null);
  const [storagePackageBusy, setStoragePackageBusy] = useState(false);

  function featureName(code: string): string {
    return features.find((f) => f.code === code)?.name ?? code;
  }

  async function submitPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!planForm) return;
    const code = planForm.code.trim();
    if (!code) {
      showToast("Code darf nicht leer sein", "error");
      return;
    }
    setPlanBusy(true);
    try {
      const payload: AdminPlanWrite = {
        name: planForm.name,
        price_monthly_rp: chfInputToRp(planForm.priceMonthlyChf),
        price_yearly_rp: chfInputToRp(planForm.priceYearlyChf),
        included_user_limit: planForm.userLimit.trim() === "" ? null : Number(planForm.userLimit),
        included_storage_bytes: planForm.storageMb.trim() === "" ? null : Number(planForm.storageMb) * 1024 * 1024,
        sort_order: Number(planForm.sortOrder) || 0,
        feature_codes: Array.from(planForm.featureCodes),
      };
      const updated = await browserApiFetch<AdminPlan>(`/api/admin/plans/${encodeURIComponent(code)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setPlans((current) => {
        const withoutCurrent = current.filter((p) => p.code !== updated.code);
        return [...withoutCurrent, updated].sort((a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code));
      });
      setPlanForm(null);
      showToast("Plan gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Plan konnte nicht gespeichert werden", "error");
    } finally {
      setPlanBusy(false);
    }
  }

  async function submitFeature(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!featureForm) return;
    setFeatureBusy(true);
    try {
      const payload: AdminFeatureUpdate = {
        name: featureForm.name,
        description: featureForm.description.trim() === "" ? null : featureForm.description.trim(),
        standalone_price_monthly_rp: chfInputToRp(featureForm.priceMonthlyChf),
      };
      const updated = await browserApiFetch<AdminFeature>(`/api/admin/features/${encodeURIComponent(featureForm.code)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setFeatures((current) => current.map((f) => (f.code === updated.code ? updated : f)));
      setFeatureForm(null);
      showToast("Feature gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Feature konnte nicht gespeichert werden", "error");
    } finally {
      setFeatureBusy(false);
    }
  }

  async function submitStoragePackage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!storagePackageForm) return;
    const code = storagePackageForm.code.trim();
    if (!code) {
      showToast("Code darf nicht leer sein", "error");
      return;
    }
    setStoragePackageBusy(true);
    try {
      const payload: AdminStoragePackageWrite = {
        name: storagePackageForm.name,
        bytes: Number(storagePackageForm.storageMb) * 1024 * 1024,
        price_monthly_rp: chfInputToRp(storagePackageForm.priceMonthlyChf),
        price_yearly_rp: chfInputToRp(storagePackageForm.priceYearlyChf),
        sort_order: Number(storagePackageForm.sortOrder) || 0,
      };
      const updated = await browserApiFetch<AdminStoragePackage>(`/api/admin/storage-packages/${encodeURIComponent(code)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setStoragePackages((current) => {
        const withoutCurrent = current.filter((p) => p.code !== updated.code);
        return [...withoutCurrent, updated].sort((a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code));
      });
      setStoragePackageForm(null);
      showToast("Speicherpaket gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Speicherpaket konnte nicht gespeichert werden", "error");
    } finally {
      setStoragePackageBusy(false);
    }
  }

  function toggleFeatureCode(code: string) {
    setPlanForm((current) => {
      if (!current) return current;
      const next = new Set(current.featureCodes);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return { ...current, featureCodes: next };
    });
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Preise"
        description="Pläne, Module und deren Preise für den Preiskatalog verwalten."
        actions={
          <button type="button" className="button-primary" onClick={() => setPlanForm(emptyPlanForm)}>
            + Plan
          </button>
        }
      />

      <DataTable
        columns={["Plan", "Preis/Monat", "Preis/Jahr", "Nutzerlimit", "Speicher", "Enthaltene Module", ""]}
        emptyMessage="Noch keine Pläne angelegt."
      >
        {plans.map((plan) => (
          <tr key={plan.code}>
            <td>
              <strong>{plan.name}</strong>
              <div className="muted">{plan.code}</div>
            </td>
            <td>{formatRappen(plan.price_monthly_rp)}</td>
            <td>{formatRappen(plan.price_yearly_rp)}</td>
            <td>{plan.included_user_limit === null ? "Kein Limit" : plan.included_user_limit}</td>
            <td>{plan.included_storage_bytes === null ? "Kein Limit" : formatFileSize(plan.included_storage_bytes)}</td>
            <td className="muted">{plan.feature_codes.map(featureName).join(", ") || "–"}</td>
            <td>
              <ActionMenu items={[{ label: "Bearbeiten", onClick: () => setPlanForm(planToForm(plan)) }]} />
            </td>
          </tr>
        ))}
      </DataTable>

      <DataTable columns={["Modul", "Beschreibung", "Preis/Monat einzeln", ""]} emptyMessage="Kein Katalog-Feature vorhanden.">
        {features.map((feature) => (
          <tr key={feature.code}>
            <td>
              <strong>{feature.name}</strong>
              <div className="muted">{feature.code}</div>
            </td>
            <td className="muted">{feature.description ?? "–"}</td>
            <td>{formatRappen(feature.standalone_price_monthly_rp)}</td>
            <td>
              <ActionMenu items={[{ label: "Bearbeiten", onClick: () => setFeatureForm(featureToForm(feature)) }]} />
            </td>
          </tr>
        ))}
      </DataTable>

      <DataToolbar
        title="Speicherpakete"
        description="Zusatzpakete, die Mandanten zusätzlich zum Plan-Kontingent zubuchen können."
        actions={
          <button type="button" className="button-primary" onClick={() => setStoragePackageForm(emptyStoragePackageForm)}>
            + Speicherpaket
          </button>
        }
      />

      <DataTable columns={["Paket", "Grösse", "Preis/Monat", "Preis/Jahr", ""]} emptyMessage="Noch keine Speicherpakete angelegt.">
        {storagePackages.map((pkg) => (
          <tr key={pkg.code}>
            <td>
              <strong>{pkg.name}</strong>
              <div className="muted">{pkg.code}</div>
            </td>
            <td>{formatFileSize(pkg.bytes)}</td>
            <td>{formatRappen(pkg.price_monthly_rp)}</td>
            <td>{formatRappen(pkg.price_yearly_rp)}</td>
            <td>
              <ActionMenu items={[{ label: "Bearbeiten", onClick: () => setStoragePackageForm(storagePackageToForm(pkg)) }]} />
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={planForm !== null}
        onClose={() => setPlanForm(null)}
        title={planForm?.isNew ? "Plan anlegen" : `Plan bearbeiten – ${planForm?.name ?? ""}`}
        size="default"
      >
        {planForm && (
          <form className="grid" onSubmit={submitPlan}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Code</span>
                <input
                  value={planForm.code}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, code: event.target.value.toLowerCase() } : current))}
                  pattern="[a-z0-9_-]+"
                  required
                  disabled={!planForm.isNew}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Name</span>
                <input
                  value={planForm.name}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, name: event.target.value } : current))}
                  required
                />
              </label>
            </div>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Preis pro Monat (CHF, leer = kein Preis)</span>
                <input
                  type="number"
                  min={0}
                  step="0.05"
                  value={planForm.priceMonthlyChf}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, priceMonthlyChf: event.target.value } : current))}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Preis pro Jahr (CHF, leer = kein Preis)</span>
                <input
                  type="number"
                  min={0}
                  step="0.05"
                  value={planForm.priceYearlyChf}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, priceYearlyChf: event.target.value } : current))}
                />
              </label>
            </div>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Nutzerlimit (leer = kein Limit)</span>
                <input
                  type="number"
                  min={1}
                  value={planForm.userLimit}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, userLimit: event.target.value } : current))}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Speicherlimit (MB, leer = kein Limit)</span>
                <input
                  type="number"
                  min={1}
                  value={planForm.storageMb}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, storageMb: event.target.value } : current))}
                />
              </label>
            </div>
            <label className="field-stack">
              <span className="field-label">Reihenfolge (kleiner = weiter vorne)</span>
              <input
                type="number"
                value={planForm.sortOrder}
                onChange={(event) => setPlanForm((current) => (current ? { ...current, sortOrder: event.target.value } : current))}
              />
            </label>
            <div className="field-stack">
              <span className="field-label">Enthaltene Module</span>
              {features.length === 0 ? (
                <div className="muted">Keine Module im Katalog.</div>
              ) : (
                features.map((feature) => (
                  <label key={feature.code} className="field-radio-option">
                    <input
                      type="checkbox"
                      checked={planForm.featureCodes.has(feature.code)}
                      onChange={() => toggleFeatureCode(feature.code)}
                    />
                    <span>
                      <strong>{feature.name}</strong>
                    </span>
                  </label>
                ))
              )}
            </div>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setPlanForm(null)}>
                Abbrechen
              </button>
              <button type="submit" className="button-primary" disabled={planBusy}>
                {planBusy ? "Wird gespeichert…" : "Speichern"}
              </button>
            </div>
          </form>
        )}
      </Modal>

      <Modal
        open={featureForm !== null}
        onClose={() => setFeatureForm(null)}
        title={featureForm ? `Modul bearbeiten – ${featureForm.name}` : "Modul bearbeiten"}
        size="default"
      >
        {featureForm && (
          <form className="grid" onSubmit={submitFeature}>
            <label className="field-stack">
              <span className="field-label">Name</span>
              <input
                value={featureForm.name}
                onChange={(event) => setFeatureForm((current) => (current ? { ...current, name: event.target.value } : current))}
                required
              />
            </label>
            <label className="field-stack">
              <span className="field-label">Beschreibung</span>
              <input
                value={featureForm.description}
                onChange={(event) => setFeatureForm((current) => (current ? { ...current, description: event.target.value } : current))}
              />
            </label>
            <label className="field-stack">
              <span className="field-label">Preis pro Monat einzeln (CHF, leer = nur gebündelt über einen Plan)</span>
              <input
                type="number"
                min={0}
                step="0.05"
                value={featureForm.priceMonthlyChf}
                onChange={(event) => setFeatureForm((current) => (current ? { ...current, priceMonthlyChf: event.target.value } : current))}
              />
            </label>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setFeatureForm(null)}>
                Abbrechen
              </button>
              <button type="submit" className="button-primary" disabled={featureBusy}>
                {featureBusy ? "Wird gespeichert…" : "Speichern"}
              </button>
            </div>
          </form>
        )}
      </Modal>

      <Modal
        open={storagePackageForm !== null}
        onClose={() => setStoragePackageForm(null)}
        title={storagePackageForm?.isNew ? "Speicherpaket anlegen" : `Speicherpaket bearbeiten – ${storagePackageForm?.name ?? ""}`}
        size="default"
      >
        {storagePackageForm && (
          <form className="grid" onSubmit={submitStoragePackage}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Code</span>
                <input
                  value={storagePackageForm.code}
                  onChange={(event) =>
                    setStoragePackageForm((current) => (current ? { ...current, code: event.target.value.toLowerCase() } : current))
                  }
                  pattern="[a-z0-9_-]+"
                  required
                  disabled={!storagePackageForm.isNew}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Name</span>
                <input
                  value={storagePackageForm.name}
                  onChange={(event) => setStoragePackageForm((current) => (current ? { ...current, name: event.target.value } : current))}
                  required
                />
              </label>
            </div>
            <label className="field-stack">
              <span className="field-label">Grösse (MB)</span>
              <input
                type="number"
                min={1}
                value={storagePackageForm.storageMb}
                onChange={(event) => setStoragePackageForm((current) => (current ? { ...current, storageMb: event.target.value } : current))}
                required
              />
            </label>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">Preis pro Monat (CHF, leer = kein Preis)</span>
                <input
                  type="number"
                  min={0}
                  step="0.05"
                  value={storagePackageForm.priceMonthlyChf}
                  onChange={(event) =>
                    setStoragePackageForm((current) => (current ? { ...current, priceMonthlyChf: event.target.value } : current))
                  }
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Preis pro Jahr (CHF, leer = kein Preis)</span>
                <input
                  type="number"
                  min={0}
                  step="0.05"
                  value={storagePackageForm.priceYearlyChf}
                  onChange={(event) =>
                    setStoragePackageForm((current) => (current ? { ...current, priceYearlyChf: event.target.value } : current))
                  }
                />
              </label>
            </div>
            <label className="field-stack">
              <span className="field-label">Reihenfolge (kleiner = weiter vorne)</span>
              <input
                type="number"
                value={storagePackageForm.sortOrder}
                onChange={(event) => setStoragePackageForm((current) => (current ? { ...current, sortOrder: event.target.value } : current))}
              />
            </label>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setStoragePackageForm(null)}>
                Abbrechen
              </button>
              <button type="submit" className="button-primary" disabled={storagePackageBusy}>
                {storagePackageBusy ? "Wird gespeichert…" : "Speichern"}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
