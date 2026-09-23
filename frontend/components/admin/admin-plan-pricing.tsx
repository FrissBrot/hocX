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
  storageGb: string;
  monthlyTouched: boolean;
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
  storageGb: string;
  priceMonthlyChf: string;
  priceYearlyChf: string;
  monthlyTouched: boolean;
};

function storagePackageToForm(pkg: AdminStoragePackage): StoragePackageFormState {
  return {
    code: pkg.code,
    isNew: false,
    name: pkg.name,
    storageGb: bytesToGbInput(pkg.bytes),
    priceMonthlyChf: rpToChfInput(pkg.price_monthly_rp),
    priceYearlyChf: rpToChfInput(pkg.price_yearly_rp),
    monthlyTouched: isManualMonthly(pkg.price_monthly_rp, pkg.price_yearly_rp),
  };
}

const emptyStoragePackageForm: StoragePackageFormState = {
  code: "",
  isNew: true,
  name: "",
  storageGb: "",
  priceMonthlyChf: "",
  priceYearlyChf: "",
  monthlyTouched: false,
};

// Monatspreis-Vorschlag: Jahrespreis / 12 + 20 % Aufschlag, auf 5 Rappen gerundet.
function suggestMonthlyRp(yearlyRp: number): number {
  return Math.round(((yearlyRp / 12) * 1.2) / 5) * 5;
}

function suggestMonthlyChf(yearlyChf: string): string {
  const yearlyRp = chfInputToRp(yearlyChf);
  return yearlyRp === null ? "" : rpToChfInput(suggestMonthlyRp(yearlyRp));
}

// Ein bestehender Monatspreis, der vom Vorschlag abweicht, gilt als bewusst gesetzt und wird
// beim Ändern des Jahrespreises nicht mehr automatisch überschrieben.
function isManualMonthly(monthlyRp: number | null, yearlyRp: number | null): boolean {
  if (monthlyRp === null) return false;
  return yearlyRp === null || monthlyRp !== suggestMonthlyRp(yearlyRp);
}

function comparePrice(a: number | null, b: number | null): number {
  if (a === b) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  return a - b;
}

// Gleiche Reihenfolge wie das Backend: günstigster Plan zuoberst, Pläne ohne Preis vorneweg.
function comparePlans(a: AdminPlan, b: AdminPlan): number {
  return (
    comparePrice(a.price_yearly_rp, b.price_yearly_rp) ||
    comparePrice(a.price_monthly_rp, b.price_monthly_rp) ||
    a.code.localeCompare(b.code)
  );
}

// Kleinstes Paket zuoberst.
function compareStoragePackages(a: AdminStoragePackage, b: AdminStoragePackage): number {
  return a.bytes - b.bytes || a.code.localeCompare(b.code);
}

const BYTES_PER_GB = 1024 * 1024 * 1024;

// Speichergrössen werden in GB eingegeben (1 GB = 1024 MB, gleich wie formatFileSize anzeigt).
function bytesToGbInput(bytes: number): string {
  return String(Math.round((bytes / BYTES_PER_GB) * 100) / 100);
}

function gbInputToBytes(value: string): number {
  return Math.round(Number(value.trim().replace(",", ".")) * BYTES_PER_GB);
}

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
    storageGb: plan.included_storage_bytes === null ? "" : bytesToGbInput(plan.included_storage_bytes),
    monthlyTouched: isManualMonthly(plan.price_monthly_rp, plan.price_yearly_rp),
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
  storageGb: "",
  monthlyTouched: false,
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
  const [plans, setPlans] = useState<AdminPlan[]>(() => [...initialPlans].sort(comparePlans));
  const [features, setFeatures] = useState<AdminFeature[]>(initialFeatures);
  const [storagePackages, setStoragePackages] = useState<AdminStoragePackage[]>(() =>
    [...initialStoragePackages].sort(compareStoragePackages)
  );

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
    setPlanBusy(true);
    try {
      const payload: AdminPlanWrite = {
        name: planForm.name,
        price_monthly_rp: chfInputToRp(planForm.priceMonthlyChf),
        price_yearly_rp: chfInputToRp(planForm.priceYearlyChf),
        included_user_limit: planForm.userLimit.trim() === "" ? null : Number(planForm.userLimit),
        included_storage_bytes: planForm.storageGb.trim() === "" ? null : gbInputToBytes(planForm.storageGb),
        sort_order: 0,
        feature_codes: Array.from(planForm.featureCodes),
      };
      // Neue Pläne per POST - der Code wird im Backend aus dem Namen erzeugt.
      const updated = await browserApiFetch<AdminPlan>(
        planForm.isNew ? "/api/admin/plans" : `/api/admin/plans/${encodeURIComponent(planForm.code)}`,
        { method: planForm.isNew ? "POST" : "PUT", body: JSON.stringify(payload) }
      );
      setPlans((current) => [...current.filter((p) => p.code !== updated.code), updated].sort(comparePlans));
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
    setStoragePackageBusy(true);
    try {
      const payload: AdminStoragePackageWrite = {
        name: storagePackageForm.name,
        bytes: gbInputToBytes(storagePackageForm.storageGb),
        price_monthly_rp: chfInputToRp(storagePackageForm.priceMonthlyChf),
        price_yearly_rp: chfInputToRp(storagePackageForm.priceYearlyChf),
        sort_order: 0,
      };
      const updated = await browserApiFetch<AdminStoragePackage>(
        storagePackageForm.isNew
          ? "/api/admin/storage-packages"
          : `/api/admin/storage-packages/${encodeURIComponent(storagePackageForm.code)}`,
        { method: storagePackageForm.isNew ? "POST" : "PUT", body: JSON.stringify(payload) }
      );
      setStoragePackages((current) =>
        [...current.filter((p) => p.code !== updated.code), updated].sort(compareStoragePackages)
      );
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
        columns={["Plan", "Preis/Jahr", "Preis/Monat", "Nutzerlimit", "Speicher", "Enthaltene Module", ""]}
        emptyMessage="Noch keine Pläne angelegt."
      >
        {plans.map((plan) => (
          <tr key={plan.code}>
            <td>
              <strong>{plan.name}</strong>
            </td>
            <td>{formatRappen(plan.price_yearly_rp)}</td>
            <td>{formatRappen(plan.price_monthly_rp)}</td>
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

      <DataTable columns={["Paket", "Grösse", "Preis/Jahr", "Preis/Monat", ""]} emptyMessage="Noch keine Speicherpakete angelegt.">
        {storagePackages.map((pkg) => (
          <tr key={pkg.code}>
            <td>
              <strong>{pkg.name}</strong>
            </td>
            <td>{formatFileSize(pkg.bytes)}</td>
            <td>{formatRappen(pkg.price_yearly_rp)}</td>
            <td>{formatRappen(pkg.price_monthly_rp)}</td>
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
            <label className="field-stack">
              <span className="field-label">Name</span>
              <input
                value={planForm.name}
                onChange={(event) => setPlanForm((current) => (current ? { ...current, name: event.target.value } : current))}
                required
              />
            </label>
            <PriceFields
              yearlyChf={planForm.priceYearlyChf}
              monthlyChf={planForm.priceMonthlyChf}
              monthlyTouched={planForm.monthlyTouched}
              onChange={(prices) => setPlanForm((current) => (current ? { ...current, ...prices } : current))}
            />
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
                <span className="field-label">Speicherlimit (GB, leer = kein Limit)</span>
                <input
                  type="number"
                  min={0.01}
                  step="any"
                  value={planForm.storageGb}
                  onChange={(event) => setPlanForm((current) => (current ? { ...current, storageGb: event.target.value } : current))}
                />
              </label>
            </div>
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
                <span className="field-label">Name</span>
                <input
                  value={storagePackageForm.name}
                  onChange={(event) => setStoragePackageForm((current) => (current ? { ...current, name: event.target.value } : current))}
                  required
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Grösse (GB)</span>
                <input
                  type="number"
                  min={0.01}
                  step="any"
                  value={storagePackageForm.storageGb}
                  onChange={(event) =>
                    setStoragePackageForm((current) => (current ? { ...current, storageGb: event.target.value } : current))
                  }
                  required
                />
              </label>
            </div>
            <PriceFields
              yearlyChf={storagePackageForm.priceYearlyChf}
              monthlyChf={storagePackageForm.priceMonthlyChf}
              monthlyTouched={storagePackageForm.monthlyTouched}
              onChange={(prices) => setStoragePackageForm((current) => (current ? { ...current, ...prices } : current))}
            />
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

type PriceFieldsValue = { priceYearlyChf: string; priceMonthlyChf: string; monthlyTouched: boolean };

/** Jahrespreis zuerst; der Monatspreis wird daraus vorgeschlagen (Jahr / 12 + 20 %), solange er
 * nicht von Hand geändert wurde. */
function PriceFields({
  yearlyChf,
  monthlyChf,
  monthlyTouched,
  onChange,
}: {
  yearlyChf: string;
  monthlyChf: string;
  monthlyTouched: boolean;
  onChange: (value: PriceFieldsValue) => void;
}) {
  return (
    <div className="two-col">
      <label className="field-stack">
        <span className="field-label">Preis pro Jahr (CHF, leer = kein Preis)</span>
        <input
          type="number"
          min={0}
          step="0.05"
          value={yearlyChf}
          onChange={(event) =>
            onChange({
              priceYearlyChf: event.target.value,
              priceMonthlyChf: monthlyTouched ? monthlyChf : suggestMonthlyChf(event.target.value),
              monthlyTouched,
            })
          }
        />
      </label>
      <label className="field-stack">
        <span className="field-label">Preis pro Monat (CHF, Vorschlag: Jahr / 12 + 20 %)</span>
        <input
          type="number"
          min={0}
          step="0.05"
          value={monthlyChf}
          onChange={(event) =>
            onChange({
              priceYearlyChf: yearlyChf,
              priceMonthlyChf: event.target.value,
              // Leeren schaltet den automatischen Vorschlag wieder ein.
              monthlyTouched: event.target.value.trim() !== "",
            })
          }
        />
      </label>
    </div>
  );
}
