"use client";

import Link from "next/link";
import type { Route } from "next";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminAvatar, featureIcon, formatChfShort, hasPlanPrice, PlanBadge, planTones } from "@/components/admin/admin-plan-utils";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { NavIcon } from "@/components/ui/nav-icons";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatFileSize, formatRappen } from "@/lib/utils/format";
import {
  AdminFeature,
  AdminFeatureUpdate,
  AdminPlan,
  AdminPlanWrite,
  AdminStoragePackage,
  AdminStoragePackageWrite,
  AdminTenantPage,
  AdminTenantSummary,
} from "@/types/api";

type Props = {
  initialPlans: AdminPlan[];
  initialFeatures: AdminFeature[];
  initialStoragePackages: AdminStoragePackage[];
};

type PlanFormState = {
  code: string;
  isNew: boolean;
  name: string;
  description: string;
  isBookable: boolean;
  priceMonthlyChf: string;
  priceYearlyChf: string;
  userLimit: string;
  userUnlimited: boolean;
  storageGb: string;
  storageUnlimited: boolean;
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
    description: plan.description ?? "",
    isBookable: plan.is_bookable,
    priceMonthlyChf: rpToChfInput(plan.price_monthly_rp),
    priceYearlyChf: rpToChfInput(plan.price_yearly_rp),
    userLimit: plan.included_user_limit === null ? "" : String(plan.included_user_limit),
    userUnlimited: plan.included_user_limit === null,
    storageGb: plan.included_storage_bytes === null ? "" : bytesToGbInput(plan.included_storage_bytes),
    storageUnlimited: plan.included_storage_bytes === null,
    monthlyTouched: isManualMonthly(plan.price_monthly_rp, plan.price_yearly_rp),
    featureCodes: new Set(plan.feature_codes),
  };
}

const emptyPlanForm: PlanFormState = {
  code: "",
  isNew: true,
  name: "",
  description: "",
  isBookable: true,
  priceMonthlyChf: "",
  priceYearlyChf: "",
  userLimit: "10",
  userUnlimited: false,
  storageGb: "5",
  storageUnlimited: false,
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

type PricingView = "plans" | "modules" | "packages";

export function AdminPlanPricing({ initialPlans, initialFeatures, initialStoragePackages }: Props) {
  const t = useTranslations("admin.pricing");
  const locale = useLocale();
  const showToast = useToast();
  const [view, setView] = useState<PricingView>("plans");
  const [plans, setPlans] = useState<AdminPlan[]>(() => [...initialPlans].sort(comparePlans));
  const [features, setFeatures] = useState<AdminFeature[]>(initialFeatures);
  const [storagePackages, setStoragePackages] = useState<AdminStoragePackage[]>(() =>
    [...initialStoragePackages].sort(compareStoragePackages)
  );

  const [planForm, setPlanForm] = useState<PlanFormState | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planTenants, setPlanTenants] = useState<AdminTenantSummary[] | null>(null);
  const [featureForm, setFeatureForm] = useState<FeatureFormState | null>(null);
  const [featureBusy, setFeatureBusy] = useState(false);
  const [storagePackageForm, setStoragePackageForm] = useState<StoragePackageFormState | null>(null);
  const [storagePackageBusy, setStoragePackageBusy] = useState(false);

  const tones = useMemo(() => planTones(plans), [plans]);

  // "Mandanten mit diesem Plan" in der Vorschau des Plan-Editors.
  const editedPlanCode = planForm && !planForm.isNew ? planForm.code : null;
  useEffect(() => {
    setPlanTenants(null);
    if (!editedPlanCode) return;
    let cancelled = false;
    browserApiFetch<AdminTenantPage>(`/api/admin/tenants?limit=8&offset=0&plan=${encodeURIComponent(editedPlanCode)}`)
      .then((page) => {
        if (!cancelled) setPlanTenants(page.items);
      })
      .catch(() => {
        if (!cancelled) setPlanTenants([]);
      });
    return () => {
      cancelled = true;
    };
  }, [editedPlanCode]);

  function updatePlanForm(patch: Partial<PlanFormState>) {
    setPlanForm((current) => (current ? { ...current, ...patch } : current));
  }

  async function submitPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!planForm) return;
    setPlanBusy(true);
    try {
      const payload: AdminPlanWrite = {
        name: planForm.name.trim(),
        description: planForm.description.trim() === "" ? null : planForm.description.trim(),
        is_bookable: planForm.isBookable,
        price_monthly_rp: chfInputToRp(planForm.priceMonthlyChf),
        price_yearly_rp: chfInputToRp(planForm.priceYearlyChf),
        included_user_limit: planForm.userUnlimited || planForm.userLimit.trim() === "" ? null : Number(planForm.userLimit),
        included_storage_bytes: planForm.storageUnlimited || planForm.storageGb.trim() === "" ? null : gbInputToBytes(planForm.storageGb),
        sort_order: 0,
        feature_codes: Array.from(planForm.featureCodes),
      };
      // Neue Pläne per POST - ohne Code erzeugt das Backend ihn aus dem Namen.
      const updated = await browserApiFetch<AdminPlan>(
        planForm.isNew ? "/api/admin/plans" : `/api/admin/plans/${encodeURIComponent(planForm.code)}`,
        { method: planForm.isNew ? "POST" : "PUT", body: JSON.stringify(payload) }
      );
      setPlans((current) => [...current.filter((p) => p.code !== updated.code), updated].sort(comparePlans));
      setPlanForm(null);
      showToast(t("planSaved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("planSaveFailed"), "error");
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
      showToast(t("featureSaved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("featureSaveFailed"), "error");
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
      showToast(t("packageSaved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("packageSaveFailed"), "error");
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

  const headerAction =
    view === "plans" ? (
      <button type="button" className="button-primary" onClick={() => setPlanForm(emptyPlanForm)}>
        + Neuer Plan
      </button>
    ) : view === "packages" ? (
      <button type="button" className="button-primary" onClick={() => setStoragePackageForm(emptyStoragePackageForm)}>
        + Neues Speicherpaket
      </button>
    ) : null;

  const previewMonthlyRp = planForm ? chfInputToRp(planForm.priceMonthlyChf) : null;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        {headerAction}
      </div>

      <div>
        <FilterTabs
          value={view}
          onChange={setView}
          options={[
            { value: "plans", label: t("tabPlans"), count: plans.length },
            { value: "modules", label: t("tabModules"), count: features.length },
            { value: "packages", label: t("tabStoragePackages"), count: storagePackages.length },
          ]}
        />
      </div>

      {view === "plans" ? (
        <>
          {plans.length === 0 ? (
            <div className="card muted">{t("noPlansYet")}</div>
          ) : (
            <div className="admin-plan-grid">
              {plans.map((plan) => {
                const tone = tones.get(plan.code) ?? "neutral";
                return (
                  <article key={plan.code} className={`card admin-plan-card admin-plan-card-${tone}`}>
                    <div className="admin-plan-card-head">
                      <h2>{plan.name}</h2>
                      <Badge variant={plan.is_bookable ? "success" : "neutral"}>{plan.is_bookable ? t("bookable") : t("notBookable")}</Badge>
                    </div>
                    <p className="muted admin-plan-card-description">{plan.description ?? "\u00a0"}</p>
                    {hasPlanPrice(plan) ? (
                      <div className="admin-plan-card-price">
                        <div>
                          <span className="admin-plan-card-amount">{formatChfShort(plan.price_monthly_rp ?? plan.price_yearly_rp)}</span>
                          <span className="muted"> / {plan.price_monthly_rp !== null ? t("month") : t("year")}</span>
                        </div>
                        <div className="muted">
                          {plan.price_monthly_rp !== null && plan.price_yearly_rp !== null
                            ? t("orPerYear", { price: formatChfShort(plan.price_yearly_rp) })
                            : "\u00a0"}
                        </div>
                      </div>
                    ) : (
                      <div className="admin-plan-card-price">
                        <div>
                          <span className="admin-plan-card-amount">–</span> <span className="muted">{t("noPriceSet")}</span>
                        </div>
                        <div className="muted">{t("individualPerTenant")}</div>
                      </div>
                    )}
                    <dl className="admin-limit-list">
                      <div>
                        <dt>{t("users")}</dt>
                        <dd>{plan.included_user_limit === null ? t("unlimited") : t("upTo", { count: plan.included_user_limit })}</dd>
                      </div>
                      <div>
                        <dt>{t("storage")}</dt>
                        <dd>{plan.included_storage_bytes === null ? t("unlimited") : formatFileSize(plan.included_storage_bytes)}</dd>
                      </div>
                    </dl>
                    <ul className="admin-plan-card-features">
                      {features.map((feature) => {
                        const included = plan.feature_codes.includes(feature.code);
                        return (
                          <li key={feature.code} className={included ? "admin-plan-feature-included" : undefined}>
                            <span className="admin-plan-feature-mark" aria-hidden="true">
                              {included ? "✓" : "–"}
                            </span>
                            <span className="admin-sr-only">{included ? t("includedPrefix") : t("notIncludedPrefix")}</span>
                            {feature.name}
                          </li>
                        );
                      })}
                    </ul>
                    <div className="admin-plan-card-foot">
                      <Link href={`/admin/tenants?plan=${encodeURIComponent(plan.code)}` as Route} className="admin-plan-card-link">
                        {t("tenantCount", { count: plan.tenant_count })} →
                      </Link>
                      <button type="button" className="button-ghost" onClick={() => setPlanForm(planToForm(plan))}>
                        {t("edit")}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
          <p className="muted admin-page-footnote">
            {t("nonBookablePlansFootnote")}
          </p>
        </>
      ) : null}

      {view === "modules" ? (
        <>
          <DataTable columns={[t("colModule"), t("colAddonPrice"), t("colIncludedIn"), t("colAsAddon"), ""]} emptyMessage={t("noModulesInCatalog")}>
            {features.map((feature) => {
              const includedIn = plans.filter((plan) => plan.feature_codes.includes(feature.code));
              return (
                <tr key={feature.code}>
                  <td>
                    <div className="admin-module-name">
                      <span className="tenant-module-icon admin-module-icon">
                        <NavIcon name={featureIcon(feature)} />
                      </span>
                      <div>
                        <strong>{feature.name}</strong>
                        {feature.description ? <div className="muted admin-cell-sub">{feature.description}</div> : null}
                      </div>
                    </div>
                  </td>
                  <td>
                    <strong>
                      {feature.standalone_price_monthly_rp === null ? "–" : t("perMonth", { price: formatChfShort(feature.standalone_price_monthly_rp) })}
                    </strong>
                  </td>
                  <td>
                    <div className="admin-badge-row">
                      {includedIn.length === 0 ? <span className="muted">–</span> : null}
                      {includedIn.map((plan) => (
                        <PlanBadge key={plan.code} name={plan.name} tone={tones.get(plan.code) ?? "neutral"} />
                      ))}
                    </div>
                  </td>
                  <td>
                    {feature.standalone_price_monthly_rp === null ? (
                      <span className="admin-status-dot admin-status-dot-off">{t("no")}</span>
                    ) : (
                      <span className="admin-status-dot admin-status-dot-on">{t("bookable")}</span>
                    )}
                  </td>
                  <td className="admin-cell-end">
                    <button type="button" className="button-ghost" onClick={() => setFeatureForm(featureToForm(feature))}>
                      {t("edit")}
                    </button>
                  </td>
                </tr>
              );
            })}
          </DataTable>
          <p className="muted admin-page-footnote">
            {t("coreFeatureFootnote")}
          </p>
        </>
      ) : null}

      {view === "packages" ? (
        <>
          <DataTable columns={[t("colPackage"), t("colSize"), t("colPricePerYear"), t("colPricePerMonth"), ""]} emptyMessage={t("noPackagesYet")}>
            {storagePackages.map((pkg) => (
              <tr key={pkg.code}>
                <td>
                  <strong>{pkg.name}</strong>
                </td>
                <td>{formatFileSize(pkg.bytes)}</td>
                <td>{formatRappen(pkg.price_yearly_rp, locale)}</td>
                <td>{formatRappen(pkg.price_monthly_rp, locale)}</td>
                <td className="admin-cell-end">
                  <ActionMenu items={[{ label: t("edit"), onClick: () => setStoragePackageForm(storagePackageToForm(pkg)) }]} />
                </td>
              </tr>
            ))}
          </DataTable>
          <p className="muted admin-page-footnote">{t("storagePackagesFootnote")}</p>
        </>
      ) : null}

      <Modal
        open={planForm !== null}
        onClose={() => setPlanForm(null)}
        title={planForm?.isNew ? t("newPlan") : t("editPlanNamed", { name: planForm?.name ?? "" })}
        size="wide"
        className="admin-plan-modal"
        header={
          planForm ? (
            <div className="admin-plan-modal-heading">
              <div className="eyebrow">{planForm.isNew ? t("newPlan") : t("editPlan")}</div>
              <input
                className="admin-plan-name-input"
                form="admin-plan-form"
                value={planForm.name}
                onChange={(event) => updatePlanForm({ name: event.target.value })}
                placeholder={t("planNamePlaceholder")}
                aria-label={t("planNamePlaceholder")}
                required
              />
            </div>
          ) : null
        }
        footer={
          <div className="modal-footer-actions">
            <button type="button" className="button-ghost" onClick={() => setPlanForm(null)}>
              {t("cancel")}
            </button>
            <button type="submit" form="admin-plan-form" className="button-primary" disabled={planBusy || !planForm || planForm.name.trim() === ""}>
              {planBusy ? t("saving") : planForm?.isNew ? t("createPlan") : t("save")}
            </button>
          </div>
        }
      >
        {planForm && (
          <form id="admin-plan-form" className="grid admin-abo-layout" onSubmit={submitPlan}>
            <div className="admin-abo-main">
              <section className="admin-form-section">
                <div className="admin-section-title">{t("basics")}</div>
                <div className="admin-plan-availability">
                  <div className="field-stack">
                    <span className="field-label">{t("availability")}</span>
                    <div>
                      <FilterTabs
                        value={planForm.isBookable ? "bookable" : "hidden"}
                        onChange={(value) => updatePlanForm({ isBookable: value === "bookable" })}
                        options={[
                          { value: "bookable", label: t("bookable") },
                          { value: "hidden", label: t("notBookable") },
                        ]}
                      />
                    </div>
                  </div>
                  <p className="field-help">{planForm.isBookable ? t("tenantsCanBookThemselves") : t("onlyAdminCanAssign")}</p>
                </div>
                <label className="field-stack">
                  <span className="field-label">{t("description2")}</span>
                  <textarea rows={3} value={planForm.description} onChange={(event) => updatePlanForm({ description: event.target.value })} />
                </label>
              </section>

              <section className="admin-form-section">
                <div className="admin-section-title">{t("price")}</div>
                <PriceFields
                  yearlyChf={planForm.priceYearlyChf}
                  monthlyChf={planForm.priceMonthlyChf}
                  monthlyTouched={planForm.monthlyTouched}
                  onChange={(prices) => updatePlanForm(prices)}
                />
                <span className="field-help">
                  {t("priceHelp")}
                </span>
              </section>

              <section className="admin-form-section">
                <div className="admin-section-title">{t("usersAndStorage")}</div>
                <div className="two-col">
                  <div className="field-stack">
                    <span className="field-label">{t("users")}</span>
                    <div className="admin-limit-input">
                      <input
                        type="number"
                        min={1}
                        placeholder={planForm.userUnlimited ? t("unlimited") : t("numberOfUsers")}
                        value={planForm.userUnlimited ? "" : planForm.userLimit}
                        disabled={planForm.userUnlimited}
                        onChange={(event) => updatePlanForm({ userLimit: event.target.value })}
                        aria-label={t("userLimit")}
                      />
                      <label className="admin-inline-check">
                        <input type="checkbox" checked={planForm.userUnlimited} onChange={(event) => updatePlanForm({ userUnlimited: event.target.checked })} />
                        {t("unlimitedLower")}
                      </label>
                    </div>
                  </div>
                  <div className="field-stack">
                    <span className="field-label">{t("storageGb")}</span>
                    <div className="admin-limit-input">
                      <input
                        type="number"
                        min={0.01}
                        step="any"
                        placeholder={planForm.storageUnlimited ? t("unlimited") : t("storageInGb")}
                        value={planForm.storageUnlimited ? "" : planForm.storageGb}
                        disabled={planForm.storageUnlimited}
                        onChange={(event) => updatePlanForm({ storageGb: event.target.value })}
                        aria-label={t("storageLimitInGb")}
                      />
                      <label className="admin-inline-check">
                        <input
                          type="checkbox"
                          checked={planForm.storageUnlimited}
                          onChange={(event) => updatePlanForm({ storageUnlimited: event.target.checked })}
                        />
                        {t("unlimitedLower")}
                      </label>
                    </div>
                  </div>
                </div>
                <span className="field-help">{t("storageLimitHelp")}</span>
              </section>

              <section className="admin-form-section">
                <div className="admin-section-title">{t("includedModules")}</div>
                {features.length === 0 ? (
                  <div className="muted">{t("noModulesInCatalog")}</div>
                ) : (
                  <div className="admin-module-options">
                    {features.map((feature) => {
                      const checked = planForm.featureCodes.has(feature.code);
                      return (
                        <label key={feature.code} className={checked ? "admin-module-option admin-module-option-checked" : "admin-module-option"}>
                          <input type="checkbox" checked={checked} onChange={() => toggleFeatureCode(feature.code)} />
                          <span>
                            <strong>{feature.name}</strong>
                            {feature.description ? <span className="muted">{feature.description}</span> : null}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>

            <aside className="admin-abo-side">
              <div className="admin-section-title">{t("previewForTenant")}</div>
              <div className="card admin-plan-preview">
                <Badge variant={planForm.isBookable ? "success" : "neutral"}>{planForm.isBookable ? t("bookable") : t("notBookable")}</Badge>
                <div className="admin-plan-preview-name">{planForm.name.trim() || t("newPlan")}</div>
                <dl className="admin-plan-preview-stats">
                  <div>
                    <dt>{t("monthlyPrice")}</dt>
                    <dd>{previewMonthlyRp === null ? t("notSetYet") : t("perMonth", { price: formatChfShort(previewMonthlyRp) })}</dd>
                  </div>
                  <div>
                    <dt>{t("usersShort")}</dt>
                    <dd>{planForm.userUnlimited || planForm.userLimit.trim() === "" ? t("unlimitedLower") : planForm.userLimit}</dd>
                  </div>
                  <div>
                    <dt>{t("storage")}</dt>
                    <dd>{planForm.storageUnlimited || planForm.storageGb.trim() === "" ? t("unlimitedLower") : t("gbValue", { value: planForm.storageGb })}</dd>
                  </div>
                </dl>
              </div>
              <div className="admin-section-title">{t("tenantsWithThisPlan")}</div>
              {planForm.isNew || (planTenants !== null && planTenants.length === 0) ? (
                <p className="muted admin-side-note">{t("notAssignedToAnyTenant")}</p>
              ) : planTenants === null ? (
                <p className="muted admin-side-note">{t("loading")}</p>
              ) : (
                <ul className="admin-plan-tenant-list">
                  {planTenants.map((tenant) => (
                    <li key={tenant.id}>
                      <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} size="sm" />
                      <span>{tenant.name}</span>
                    </li>
                  ))}
                </ul>
              )}
            </aside>
          </form>
        )}
      </Modal>

      <Modal
        open={featureForm !== null}
        onClose={() => setFeatureForm(null)}
        title={featureForm ? t("editFeatureNamed", { name: featureForm.name }) : t("editFeature")}
        size="default"
      >
        {featureForm && (
          <form className="grid" onSubmit={submitFeature}>
            <label className="field-stack">
              <span className="field-label">{t("name")}</span>
              <input
                value={featureForm.name}
                onChange={(event) => setFeatureForm((current) => (current ? { ...current, name: event.target.value } : current))}
                required
              />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("description2")}</span>
              <input
                value={featureForm.description}
                onChange={(event) => setFeatureForm((current) => (current ? { ...current, description: event.target.value } : current))}
              />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("addonPricePerMonth")}</span>
              <input
                type="number"
                min={0}
                step="0.05"
                value={featureForm.priceMonthlyChf}
                onChange={(event) => setFeatureForm((current) => (current ? { ...current, priceMonthlyChf: event.target.value } : current))}
              />
              <span className="field-help">{t("addonPriceHelp")}</span>
            </label>
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setFeatureForm(null)}>
                {t("cancel")}
              </button>
              <button type="submit" className="button-primary" disabled={featureBusy}>
                {featureBusy ? t("saving") : t("save")}
              </button>
            </div>
          </form>
        )}
      </Modal>

      <Modal
        open={storagePackageForm !== null}
        onClose={() => setStoragePackageForm(null)}
        title={storagePackageForm?.isNew ? t("createStoragePackage") : t("editStoragePackageNamed", { name: storagePackageForm?.name ?? "" })}
        size="default"
      >
        {storagePackageForm && (
          <form className="grid" onSubmit={submitStoragePackage}>
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("name")}</span>
                <input
                  value={storagePackageForm.name}
                  onChange={(event) => setStoragePackageForm((current) => (current ? { ...current, name: event.target.value } : current))}
                  required
                />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("sizeGb")}</span>
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
                {t("cancel")}
              </button>
              <button type="submit" className="button-primary" disabled={storagePackageBusy}>
                {storagePackageBusy ? t("saving") : t("save")}
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
  const t = useTranslations("admin.pricing");
  return (
    <div className="two-col">
      <label className="field-stack">
        <span className="field-label">{t("yearlyPriceChf")}</span>
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
        <span className="field-label">{t("monthlyPriceChf")}</span>
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
