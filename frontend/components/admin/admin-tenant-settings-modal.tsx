"use client";

import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  AdminAvatar,
  estimateSubscriptionCost,
  formatChfShort,
  hasPlanPrice,
  PlanBadge,
  planTones,
  BillingCycleToggle,
  PlanOption,
} from "@/components/admin/admin-plan-utils";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import { CATEGORY_COLORS, categoryHints, formatPercent, StorageQuotaComposition } from "@/components/storage/storage-usage-view";
import {
  AdminFeature,
  AdminPlan,
  AdminStoragePackage,
  AdminTenantStoragePackageItem,
  AdminTenantSubscriptionUpdate,
  AdminTenantSummary,
  AdminTenantUser,
  StorageUsageRead,
  TenantCleanupCategory,
  TenantCleanupCounts,
} from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  tenant: AdminTenantSummary | null;
  onSaved: (tenant: AdminTenantSummary) => void;
};

type TenantFormState = {
  name: string;
  publicSlug: string;
  profileImage: File | null;
  profileImageUrl: string | null;
};

const emptyTenantForm: TenantFormState = { name: "", publicSlug: "", profileImage: null, profileImageUrl: null };

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

// `t` ist immer ein useTranslations("admin")-Translator - siehe section-tabs.ts (dashboardTabs(t)
// etc.) fuer dasselbe Muster bei reinen Modul-Konstanten ohne eigene Komponente.
export function getRoleOptions(t: TFunc): { code: string; label: string }[] {
  return [
    { code: "reader", label: t("roleOptions.reader") },
    { code: "kassier", label: t("roleOptions.kassier") },
    { code: "writer", label: t("roleOptions.writer") },
    { code: "admin", label: t("roleOptions.admin") }
  ];
}

function getCleanupCategories(t: TFunc): { key: TenantCleanupCategory; title: string; description: string }[] {
  return [
    { key: "protocols", title: t("tenantModal.cleanup.categories.protocols.title"), description: t("tenantModal.cleanup.categories.protocols.description") },
    { key: "list_entries", title: t("tenantModal.cleanup.categories.list_entries.title"), description: t("tenantModal.cleanup.categories.list_entries.description") },
    { key: "lists_full", title: t("tenantModal.cleanup.categories.lists_full.title"), description: t("tenantModal.cleanup.categories.lists_full.description") },
    { key: "events", title: t("tenantModal.cleanup.categories.events.title"), description: t("tenantModal.cleanup.categories.events.description") },
    { key: "todos", title: t("tenantModal.cleanup.categories.todos.title"), description: t("tenantModal.cleanup.categories.todos.description") },
    { key: "participants", title: t("tenantModal.cleanup.categories.participants.title"), description: t("tenantModal.cleanup.categories.participants.description") },
    { key: "documents", title: t("tenantModal.cleanup.categories.documents.title"), description: t("tenantModal.cleanup.categories.documents.description") },
  ];
}

type SettingsTab = "stammdaten" | "abo" | "benutzer" | "aufraeumen" | "speicher";

export function AdminTenantSettingsModal({ open, onClose, tenant, onSaved }: Props) {
  const t = useTranslations("admin");
  const roleOptions = useMemo(() => getRoleOptions(t), [t]);
  const cleanupCategories = useMemo(() => getCleanupCategories(t), [t]);
  const showToast = useToast();
  const confirm = useConfirm();
  const [activeTab, setActiveTab] = useState<SettingsTab>("stammdaten");
  const [tenantForm, setTenantForm] = useState<TenantFormState>(emptyTenantForm);
  const [tenantBusy, setTenantBusy] = useState(false);
  const [profilePreviewUrl, setProfilePreviewUrl] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [tenantUsers, setTenantUsers] = useState<AdminTenantUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [mfaModalUser, setMfaModalUser] = useState<AdminTenantUser | null>(null);

  const [cleanupCounts, setCleanupCounts] = useState<TenantCleanupCounts | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupSelected, setCleanupSelected] = useState<Set<TenantCleanupCategory>>(new Set());
  const [cleanupConfirmName, setCleanupConfirmName] = useState("");
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [cleanupLastResult, setCleanupLastResult] = useState<TenantCleanupCounts | null>(null);

  const [storageUsage, setStorageUsage] = useState<StorageUsageRead | null>(null);
  const [storageLoading, setStorageLoading] = useState(false);

  const [featureCatalog, setFeatureCatalog] = useState<AdminFeature[]>([]);
  const [selectedFeatures, setSelectedFeatures] = useState<Set<string>>(new Set());

  const [planCatalog, setPlanCatalog] = useState<AdminPlan[]>([]);
  const [subscriptionForm, setSubscriptionForm] = useState<AdminTenantSubscriptionUpdate>({
    plan_code: null,
    billing_cycle: "monthly",
    user_limit_override: null,
    discount_percent: 0,
    billing_note: null,
  });
  const [subscriptionBusy, setSubscriptionBusy] = useState(false);

  const [storagePackageCatalog, setStoragePackageCatalog] = useState<AdminStoragePackage[]>([]);
  const [packageToAdd, setPackageToAdd] = useState("");
  const [packagesBusy, setPackagesBusy] = useState(false);

  // Nur beim Öffnen bzw. Wechsel des Mandanten auf den ersten Tab springen - nicht nach jedem
  // Speichern (onSaved reicht ein neues tenant-Objekt herein).
  useEffect(() => {
    if (open) setActiveTab("stammdaten");
  }, [open, tenant?.id]);

  // Vorschau des gewählten, noch nicht gespeicherten Profilbilds.
  useEffect(() => {
    if (!tenantForm.profileImage) {
      setProfilePreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(tenantForm.profileImage);
    setProfilePreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [tenantForm.profileImage]);

  useEffect(() => {
    if (!open || !tenant) {
      return;
    }
    setTenantForm({
      name: tenant.name,
      publicSlug: tenant.public_slug ?? "",
      profileImage: null,
      profileImageUrl: tenant.profile_image_url
    });

    void loadTenantUsers(tenant.id);

    setCleanupSelected(new Set());
    setCleanupConfirmName("");
    setCleanupLastResult(null);
    void loadCleanupPreview(tenant.id);

    void loadStorageUsage(tenant.id);

    setSelectedFeatures(new Set(tenant.enabled_features));
    void loadFeatureCatalog();

    setSubscriptionForm({
      plan_code: tenant.plan_code,
      billing_cycle: tenant.billing_cycle,
      user_limit_override: tenant.user_limit_override,
      discount_percent: tenant.discount_percent,
      billing_note: tenant.billing_note,
    });
    void loadPlanCatalog();

    setPackageToAdd("");
    void loadStoragePackageCatalog();
  }, [open, tenant]);

  async function loadStoragePackageCatalog() {
    try {
      const result = await browserApiFetch<AdminStoragePackage[]>("/api/admin/storage-packages");
      setStoragePackageCatalog(result);
      setPackageToAdd((current) => current || (result[0]?.code ?? ""));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.storagePackageCatalogLoadFailed"), "error");
    }
  }

  // Im GUI wird jedes Paket einzeln hinzugefügt/entfernt; das Backend speichert weiterhin
  // eine Anzahl pro Paket, deshalb wird hier nur quantity +1 / -1 gerechnet.
  async function changeStoragePackage(packageCode: string, delta: 1 | -1) {
    if (!tenant || !packageCode) return;
    const quantities = new Map(tenant.assigned_storage_packages.map((p) => [p.package_code, p.quantity]));
    quantities.set(packageCode, (quantities.get(packageCode) ?? 0) + delta);
    const items: AdminTenantStoragePackageItem[] = Array.from(quantities)
      .filter(([, quantity]) => quantity > 0)
      .map(([package_code, quantity]) => ({ package_code, quantity }));
    setPackagesBusy(true);
    try {
      const updated = await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${tenant.id}/storage-packages`, {
        method: "PUT",
        body: JSON.stringify({ items }),
      });
      onSaved(updated);
      showToast(delta > 0 ? t("tenantModal.toasts.packageAdded") : t("tenantModal.toasts.packageRemoved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.packagesSaveFailed"), "error");
    } finally {
      setPackagesBusy(false);
    }
  }

  async function loadFeatureCatalog() {
    try {
      const result = await browserApiFetch<AdminFeature[]>("/api/admin/features");
      setFeatureCatalog(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.featureCatalogLoadFailed"), "error");
    }
  }

  async function loadPlanCatalog() {
    try {
      const result = await browserApiFetch<AdminPlan[]>("/api/admin/plans");
      setPlanCatalog(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.planCatalogLoadFailed"), "error");
    }
  }

  const tones = useMemo(() => planTones(planCatalog), [planCatalog]);
  const selectedPlan = planCatalog.find((plan) => plan.code === subscriptionForm.plan_code);
  const planFeatureCodes = useMemo(() => new Set(selectedPlan?.feature_codes ?? []), [selectedPlan]);
  // Zusatzmodule = gebucht, aber nicht im gewählten Plan enthalten.
  const addOnFeatures = featureCatalog.filter(
    (feature) => selectedFeatures.has(feature.code) && !planFeatureCodes.has(feature.code) && feature.standalone_price_monthly_rp !== null
  );
  const cost = estimateSubscriptionCost({
    plan: selectedPlan,
    cycle: subscriptionForm.billing_cycle,
    addOns: addOnFeatures,
    discountPercent: subscriptionForm.discount_percent,
  });
  const cycleUnit = subscriptionForm.billing_cycle === "monthly" ? t("tenantModal.cycleUnit.monthly") : t("tenantModal.cycleUnit.yearly");

  async function submitSubscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    setSubscriptionBusy(true);
    try {
      await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${tenant.id}/subscription`, {
        method: "PATCH",
        body: JSON.stringify(subscriptionForm),
      });
      // Module als Full-Replace: Plan-Module sind immer dabei, Zusatzmodule nur wenn angehakt.
      const enabledCodes = Array.from(new Set([...selectedFeatures, ...planFeatureCodes]));
      const updated = await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${tenant.id}/features`, {
        method: "PUT",
        body: JSON.stringify({ enabled_codes: enabledCodes }),
      });
      onSaved(updated);
      setSelectedFeatures(new Set(updated.enabled_features));
      showToast(t("tenantModal.toasts.subscriptionSaved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.subscriptionSaveFailed"), "error");
    } finally {
      setSubscriptionBusy(false);
    }
  }

  function toggleFeature(code: string) {
    setSelectedFeatures((current) => {
      const next = new Set(current);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  }

  async function loadStorageUsage(tenantId: string) {
    setStorageLoading(true);
    try {
      const result = await browserApiFetch<StorageUsageRead>(`/api/admin/tenants/${tenantId}/storage`);
      setStorageUsage(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.storageLoadFailed"), "error");
    } finally {
      setStorageLoading(false);
    }
  }

  async function loadCleanupPreview(tenantId: string) {
    setCleanupLoading(true);
    try {
      const result = await browserApiFetch<TenantCleanupCounts>(`/api/admin/tenants/${tenantId}/cleanup/preview`);
      setCleanupCounts(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.previewLoadFailed"), "error");
    } finally {
      setCleanupLoading(false);
    }
  }

  function toggleCleanupCategory(key: TenantCleanupCategory) {
    setCleanupSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  const allCleanupSelected = cleanupCategories.every((category) => cleanupSelected.has(category.key));

  function toggleAllCleanupCategories() {
    setCleanupSelected(allCleanupSelected ? new Set() : new Set(cleanupCategories.map((category) => category.key)));
  }

  const cleanupNameMatches = !!tenant && cleanupConfirmName.trim() === tenant.name;

  async function submitCleanup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant || cleanupSelected.size === 0 || !cleanupNameMatches) return;
    if (
      !(await confirm({
        message: t("tenantModal.cleanup.confirmMessage", { count: cleanupSelected.size, tenant: tenant.name }),
        tone: "danger",
        confirmLabel: t("tenantModal.cleanup.confirmFinalDelete")
      }))
    )
      return;
    setCleanupBusy(true);
    try {
      const result = await browserApiFetch<TenantCleanupCounts>(`/api/admin/tenants/${tenant.id}/cleanup`, {
        method: "POST",
        body: JSON.stringify({ categories: Array.from(cleanupSelected), confirm_name: cleanupConfirmName.trim() })
      });
      setCleanupLastResult(result);
      setCleanupSelected(new Set());
      setCleanupConfirmName("");
      showToast(t("tenantModal.toasts.cleanupDone"), "success");
      void loadCleanupPreview(tenant.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.cleanupFailed"), "error");
    } finally {
      setCleanupBusy(false);
    }
  }

  async function loadTenantUsers(tenantId: string) {
    setUsersLoading(true);
    try {
      const result = await browserApiFetch<AdminTenantUser[]>(`/api/admin/tenants/${tenantId}/users`);
      setTenantUsers(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.usersLoadFailed"), "error");
    } finally {
      setUsersLoading(false);
    }
  }

  function pickProfileImage(file: File | null | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      showToast(t("tenantModal.toasts.imagePickInvalid"), "error");
      return;
    }
    setTenantForm((current) => ({ ...current, profileImage: file }));
  }

  function handleProfileDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDropActive(false);
    pickProfileImage(event.dataTransfer.files?.[0]);
  }

  async function submitTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    setTenantBusy(true);
    try {
      const formData = new FormData();
      formData.append("name", tenantForm.name);
      if (tenantForm.publicSlug.trim()) {
        formData.append("public_slug", tenantForm.publicSlug.trim());
      }
      if (tenantForm.profileImage) {
        formData.append("profile_image", tenantForm.profileImage);
      }
      const updated = await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${tenant.id}`, {
        method: "PATCH",
        body: formData
      });
      setTenantForm((current) => ({ ...current, profileImage: null, profileImageUrl: updated.profile_image_url }));
      showToast(t("tenantModal.toasts.tenantSaved"), "success");
      onSaved(updated);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.tenantSaveFailed"), "error");
    } finally {
      setTenantBusy(false);
    }
  }

  async function changeUserRole(userId: string, roleCode: string) {
    if (!tenant) return;
    const previous = tenantUsers;
    setTenantUsers((current) => current.map((u) => (u.user_id === userId ? { ...u, role_code: roleCode } : u)));
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}/users/${userId}`, {
        method: "PUT",
        body: JSON.stringify({ role_code: roleCode })
      });
      showToast(t("tenantModal.toasts.roleChanged"), "success");
    } catch (error) {
      setTenantUsers(previous);
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.roleChangeFailed"), "error");
    }
  }

  async function removeUser(userId: string, displayName: string) {
    if (!tenant) return;
    if (
      !(await confirm({
        message: t("tenantModal.toasts.userDeleteConfirm", { name: displayName }),
        tone: "danger",
        confirmLabel: t("tenantModal.table.delete")
      }))
    )
      return;
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}/users/${userId}`, { method: "DELETE" });
      setTenantUsers((current) => current.filter((u) => u.user_id !== userId));
      showToast(t("tenantModal.toasts.userDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tenantModal.toasts.userDeleteFailed"), "error");
    }
  }


  if (!tenant) {
    return null;
  }

  const storageQuota = storageUsage?.quota_bytes ?? null;
  const storageTotal = storageUsage?.total_bytes ?? tenant.storage_used_bytes;
  const storageBarTotal = storageQuota !== null && storageQuota > storageTotal ? storageQuota : storageTotal;
  const visibleCategories = storageUsage?.categories.filter((category) => category.bytes > 0) ?? [];
  const storageHints = categoryHints(useTranslations("storage"));
  const effectiveUserLimit = subscriptionForm.user_limit_override ?? selectedPlan?.included_user_limit ?? null;
  const effectiveStorageLimit =
    selectedPlan?.included_storage_bytes == null && tenant.package_storage_bytes === 0
      ? null
      : (selectedPlan?.included_storage_bytes ?? 0) + tenant.package_storage_bytes;

  const closeButton = (
    <button type="button" className="button-ghost" onClick={onClose}>
      {t("tenantModal.close")}
    </button>
  );

  const footer =
    activeTab === "stammdaten" ? (
      <div className="modal-footer-actions">
        {closeButton}
        <button type="submit" form="admin-tenant-stammdaten" className="button-primary" disabled={tenantBusy}>
          {tenantBusy ? t("tenantModal.saving") : t("tenantModal.save")}
        </button>
      </div>
    ) : activeTab === "abo" ? (
      <>
        <span className="muted">
          {cost.totalRp === null ? t("tenantModal.planWithoutPrice") : t("tenantModal.total", { amount: formatChfShort(cost.totalRp), unit: cycleUnit })}
        </span>
        <div className="modal-footer-actions">
          {closeButton}
          <button type="submit" form="admin-tenant-abo" className="button-primary" disabled={subscriptionBusy}>
            {subscriptionBusy ? t("tenantModal.saving") : t("tenantModal.saveSubscription")}
          </button>
        </div>
      </>
    ) : (
      <div className="modal-footer-actions">{closeButton}</div>
    );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("tenantModal.title", { tenant: tenant.name })}
      size="wide"
      className="admin-tenant-modal"
      header={
        <div className="admin-modal-heading">
          <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} size="lg" />
          <div>
            <div className="eyebrow">{t("tenantModal.eyebrow")}</div>
            <h2>{tenant.name}</h2>
          </div>
        </div>
      }
      headerActions={
        tenant.plan_code ? <PlanBadge name={tenant.plan_name ?? tenant.plan_code} tone={tones.get(tenant.plan_code) ?? "neutral"} /> : null
      }
      footer={footer}
    >
      <Tabs
        activeId={activeTab}
        onChange={(id) => setActiveTab(id as SettingsTab)}
        tabs={[
          {
            id: "stammdaten",
            label: t("tenantModal.tabs.masterData"),
            content: (
              <form id="admin-tenant-stammdaten" className="grid admin-tenant-form" onSubmit={submitTenant}>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("tenantModal.fields.tenantName")}</span>
                    <input value={tenantForm.name} onChange={(event) => setTenantForm((current) => ({ ...current, name: event.target.value }))} required />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("tenantModal.fields.publicSlug")}</span>
                    <input
                      value={tenantForm.publicSlug}
                      onChange={(event) => setTenantForm((current) => ({ ...current, publicSlug: event.target.value.toLowerCase() }))}
                      placeholder={t("tenantModal.fields.publicSlugPlaceholder")}
                      pattern="[a-z0-9-]+"
                    />
                  </label>
                </div>
                <div className="field-stack">
                  <span className="field-label">{t("tenantModal.fields.profileImage")}</span>
                  <div
                    className={dropActive ? "admin-image-drop admin-image-drop-active" : "admin-image-drop"}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDropActive(true);
                    }}
                    onDragLeave={() => setDropActive(false)}
                    onDrop={handleProfileDrop}
                  >
                    <AdminAvatar name={tenant.name} imageUrl={profilePreviewUrl ?? tenantForm.profileImageUrl} toneKey={tenant.id} size="lg" />
                    <div>
                      <div>
                        {tenantForm.profileImage ? t("tenantModal.fields.profileImageSelected", { filename: tenantForm.profileImage.name }) : t("tenantModal.fields.dragHint")}
                        <button type="button" className="admin-inline-link" onClick={() => fileInputRef.current?.click()}>
                          {tenantForm.profileImage ? t("tenantModal.fields.chooseOther") : t("tenantModal.fields.chooseFile")}
                        </button>
                      </div>
                      <div className="muted">{t("tenantModal.fields.imageHint")}</div>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg"
                      className="admin-image-drop-input"
                      aria-label={t("tenantModal.fields.profileImageAria")}
                      onChange={(event) => pickProfileImage(event.target.files?.[0])}
                    />
                  </div>
                </div>
                <div className="admin-tenant-meta">
                  <span>
                    {t("tenantModal.meta.createdAt")} <strong>{formatDate(tenant.created_at)}</strong>
                  </span>
                  <span>
                    {t("tenantModal.meta.participants")} <strong>{tenant.participant_count}</strong>
                  </span>
                </div>
              </form>
            )
          },
          {
            id: "abo",
            label: t("tenantModal.tabs.plan"),
            content: (
              <form id="admin-tenant-abo" className="admin-abo-layout" onSubmit={submitSubscription}>
                <div className="admin-abo-main">
                  <section className="admin-form-section">
                    <div className="admin-section-title">{t("tenantModal.plan.sectionTitle")}</div>
                    <div className="admin-plan-options" role="radiogroup" aria-label={t("tenantModal.plan.ariaLabel")}>
                      {planCatalog.map((plan) => (
                        <PlanOption
                          key={plan.code}
                          plan={plan}
                          name="tenant-plan"
                          checked={subscriptionForm.plan_code === plan.code}
                          cycle={subscriptionForm.billing_cycle}
                          onSelect={() => setSubscriptionForm((current) => ({ ...current, plan_code: plan.code }))}
                        />
                      ))}
                    </div>
                  </section>

                  <section className="admin-form-section">
                    <div className="admin-section-title">{t("tenantModal.billing.sectionTitle")}</div>
                    <BillingCycleToggle
                      value={subscriptionForm.billing_cycle}
                      onChange={(billing_cycle) => setSubscriptionForm((current) => ({ ...current, billing_cycle }))}
                    />
                  </section>

                  <section className="admin-form-section">
                    <div className="admin-section-title">{t("tenantModal.modules.sectionTitle")}</div>
                    {featureCatalog.length === 0 ? (
                      <div className="muted">{t("tenantModal.modules.empty")}</div>
                    ) : (
                      <div className="admin-module-options">
                        {featureCatalog.map((feature) => {
                          const inPlan = planFeatureCodes.has(feature.code);
                          const booked = selectedFeatures.has(feature.code);
                          // Ohne Einzelpreis nur über einen Plan buchbar - ein bereits gebuchtes Modul
                          // bleibt aber abwählbar.
                          const planOnly = !inPlan && feature.standalone_price_monthly_rp === null && !booked;
                          return (
                            <label
                              key={feature.code}
                              className={`admin-module-option${inPlan || booked ? " admin-module-option-checked" : ""}${inPlan || planOnly ? " admin-module-option-locked" : ""}`}
                            >
                              <input type="checkbox" checked={inPlan || booked} disabled={inPlan || planOnly} onChange={() => toggleFeature(feature.code)} />
                              <span>
                                <strong>{feature.name}</strong>
                                <span className="muted">
                                  {inPlan
                                    ? t("tenantModal.modules.includedInPlan")
                                    : feature.standalone_price_monthly_rp !== null
                                      ? t("tenantModal.modules.addon", { price: formatChfShort(feature.standalone_price_monthly_rp) })
                                      : planOnly
                                        ? t("tenantModal.modules.planOnly")
                                        : t("tenantModal.modules.individuallyBooked")}
                                </span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </section>

                  <div className="two-col">
                    <label className="field-stack">
                      <span className="field-label">{t("tenantModal.fields.discount")}</span>
                      <span className="admin-input-suffix">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={subscriptionForm.discount_percent}
                          onChange={(event) =>
                            setSubscriptionForm((current) => ({
                              ...current,
                              discount_percent: Math.min(100, Math.max(0, Math.round(Number(event.target.value) || 0))),
                            }))
                          }
                        />
                        <span aria-hidden="true">%</span>
                      </span>
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("tenantModal.fields.internalNote")}</span>
                      <input
                        value={subscriptionForm.billing_note ?? ""}
                        onChange={(event) => setSubscriptionForm((current) => ({ ...current, billing_note: event.target.value }))}
                        placeholder={t("tenantModal.fields.internalNotePlaceholder")}
                      />
                    </label>
                  </div>
                  <label className="field-stack">
                    <span className="field-label">{t("tenantModal.fields.userLimitOverride")}</span>
                    <input
                      type="number"
                      min={1}
                      value={subscriptionForm.user_limit_override ?? ""}
                      placeholder={selectedPlan?.included_user_limit != null ? t("tenantModal.fields.userLimitPlanLimit", { limit: selectedPlan.included_user_limit }) : t("tenantModal.fields.userLimitUnlimited")}
                      onChange={(event) =>
                        setSubscriptionForm((current) => ({
                          ...current,
                          user_limit_override: event.target.value.trim() === "" ? null : Number(event.target.value),
                        }))
                      }
                    />
                    <span className="field-help">
                      {t("tenantModal.fields.userLimitHelp", {
                        count: tenant.user_count,
                        suffix: effectiveUserLimit !== null && tenant.user_count >= effectiveUserLimit ? t("tenantModal.fields.userLimitExceeded") : "."
                      })}
                    </span>
                  </label>
                </div>

                <aside className="admin-abo-side">
                  <div className="admin-section-title">{t("tenantModal.cost.sectionTitle")}</div>
                  <div className="card admin-cost-card">
                    <div className="admin-cost-row">
                      <span>{t("tenantModal.cost.plan", { name: selectedPlan?.name ?? "–" })}</span>
                      <span>{cost.planRp === null ? "–" : formatChfShort(cost.planRp)}</span>
                    </div>
                    {addOnFeatures.map((feature) => (
                      <div className="admin-cost-row" key={feature.code}>
                        <span>+ {feature.name}</span>
                        <span>
                          {formatChfShort(
                            (feature.standalone_price_monthly_rp ?? 0) * (subscriptionForm.billing_cycle === "monthly" ? 1 : 12)
                          )}
                        </span>
                      </div>
                    ))}
                    {subscriptionForm.discount_percent > 0 ? (
                      <div className="admin-cost-row">
                        <span>{t("tenantModal.cost.discount")}</span>
                        <span>– {subscriptionForm.discount_percent}%</span>
                      </div>
                    ) : null}
                    <div className="admin-cost-total">
                      <span>{t("tenantModal.cost.total")}</span>
                      <strong>{cost.totalRp === null ? t("tenantModal.cost.totalUndetermined") : `${formatChfShort(cost.totalRp)}`}</strong>
                    </div>
                    <div className="muted admin-cost-hint">
                      {cost.totalRp === null
                        ? selectedPlan && !hasPlanPrice(selectedPlan)
                          ? t("tenantModal.cost.existingPlanNoPrice")
                          : t("tenantModal.cost.noPlanSelected")
                        : t("tenantModal.cost.perUnitExclVat", { unit: cycleUnit })}
                    </div>
                  </div>

                  <div className="admin-section-title">{t("tenantModal.limits.sectionTitle")}</div>
                  <dl className="admin-limit-list">
                    <div>
                      <dt>{t("tenantModal.limits.users")}</dt>
                      <dd>{effectiveUserLimit === null ? t("tenantModal.limits.unlimited") : effectiveUserLimit}</dd>
                    </div>
                    <div>
                      <dt>{t("tenantModal.limits.storage")}</dt>
                      <dd>{effectiveStorageLimit === null ? t("tenantModal.limits.unlimited") : formatFileSize(effectiveStorageLimit)}</dd>
                    </div>
                  </dl>
                  <p className="muted admin-side-note">
                    {t("tenantModal.sideNote")}
                  </p>
                </aside>
              </form>
            )
          },
          {
            id: "benutzer",
            label: t("tenantModal.tabs.users", { count: tenantUsers.length }),
            content: (
              <div className="grid">
                <div className="table-shell admin-user-table">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t("tenantModal.table.name")}</th>
                        <th>{t("tenantModal.table.email")}</th>
                        <th>{t("tenantModal.table.role")}</th>
                        <th>{t("tenantModal.table.mfa")}</th>
                        <th aria-label={t("tenantModal.table.actionAria")} />
                      </tr>
                    </thead>
                    <tbody>
                      {tenantUsers.map((u) => (
                        <tr key={u.user_id}>
                          <td>
                            <div className="admin-user-name">
                              <AdminAvatar name={u.display_name} toneKey={u.user_id} size="sm" />
                              <div>
                                <strong>{u.display_name}</strong>
                                {!u.login_enabled && <div className="muted admin-cell-sub">{t("tenantModal.table.loginDisabled")}</div>}
                              </div>
                            </div>
                          </td>
                          <td className="muted">{u.email}</td>
                          <td>
                            <select value={u.role_code} onChange={(event) => changeUserRole(u.user_id, event.target.value)} aria-label={t("tenantModal.table.roleAria", { name: u.display_name })}>
                              {roleOptions.map((r) => (
                                <option key={r.code} value={r.code}>
                                  {r.label}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <button type="button" className="button-ghost" onClick={() => setMfaModalUser(u)}>
                              {t("tenantModal.table.show")}
                            </button>
                          </td>
                          <td className="admin-cell-end">
                            <button type="button" className="button-danger" onClick={() => removeUser(u.user_id, u.display_name)}>
                              {t("tenantModal.table.delete")}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!usersLoading && tenantUsers.length === 0 && <div className="table-empty muted">{t("tenantModal.table.empty")}</div>}
                </div>
                <p className="muted">{t("tenantModal.usersHint")}</p>
              </div>
            )
          },
          {
            id: "aufraeumen",
            label: t("tenantModal.tabs.cleanup"),
            content: (
              <form className="grid admin-tenant-form" onSubmit={submitCleanup}>
                <div className="form-error-banner">
                  {t("tenantModal.cleanup.warning")}
                </div>

                <div className="field-stack">
                  <span className="field-label">{t("tenantModal.cleanup.whatLabel")}</span>
                  <label className="field-radio-option admin-cleanup-all">
                    <input type="checkbox" checked={allCleanupSelected} onChange={toggleAllCleanupCategories} />
                    <span>
                      <strong>{t("tenantModal.cleanup.allLabel")}</strong>
                      <div className="muted">{t("tenantModal.cleanup.allHint")}</div>
                    </span>
                  </label>
                  {cleanupCategories.map((category) => (
                    <label key={category.key} className="field-radio-option">
                      <input
                        type="checkbox"
                        checked={cleanupSelected.has(category.key)}
                        onChange={() => toggleCleanupCategory(category.key)}
                      />
                      <span>
                        <strong>
                          {category.title}
                          {cleanupCounts ? <span className="muted admin-cleanup-count">{t("tenantModal.cleanup.countAvailable", { count: cleanupCounts[category.key] })}</span> : null}
                        </strong>
                        <div className="muted">{category.description}</div>
                      </span>
                    </label>
                  ))}
                </div>

                {cleanupLastResult ? (
                  <div className="muted">
                    {t("tenantModal.cleanup.lastDeletedPrefix")}{Object.entries(cleanupLastResult)
                      .filter(([, count]) => count > 0)
                      .map(([key, count]) => `${cleanupCategories.find((c) => c.key === key)?.title ?? key}: ${count}`)
                      .join(", ") || t("tenantModal.cleanup.nothingDeleted")}
                  </div>
                ) : null}

                <label className="field-stack">
                  <span className="field-label">{t("tenantModal.cleanup.confirmLabel", { name: tenant.name })}</span>
                  <input
                    value={cleanupConfirmName}
                    onChange={(event) => setCleanupConfirmName(event.target.value)}
                    placeholder={tenant.name}
                    autoComplete="off"
                  />
                </label>

                <div className="table-actions table-actions-start">
                  <button
                    type="submit"
                    className="button-danger"
                    disabled={cleanupSelected.size === 0 || !cleanupNameMatches || cleanupBusy || cleanupLoading}
                  >
                    {cleanupBusy ? t("tenantModal.cleanup.deleting") : t("tenantModal.cleanup.deleteSelected")}
                  </button>
                </div>
              </form>
            )
          },
          {
            id: "speicher",
            label: t("tenantModal.tabs.storage"),
            content: (
              <div className="grid admin-tenant-form">
                {storageUsage ? (
                  <section className="admin-storage-overview">
                    <div className="admin-storage-total">
                      <span className="admin-storage-total-value">{formatFileSize(storageUsage.total_bytes)}</span>
                      <span className="muted">
                        {storageQuota !== null // i18n-ok: Ternary-Bedingung, kein UI-Text - der Checker liest "?" als JSX-Textende
                          ? t("tenantModal.storage.belegt", { quota: formatFileSize(storageQuota), percent: formatPercent(storageUsage.total_bytes, storageQuota) })
                          : t("tenantModal.storage.noLimit")}
                      </span>
                      {storageQuota !== null && storageUsage.total_bytes > storageQuota ? <Badge variant="danger">{t("tenantModal.storage.quotaExceeded")}</Badge> : null /* i18n-ok: Vergleichsoperator > vor Ternary, kein UI-Text */}
                    </div>
                    <div className="storage-usage-bar admin-storage-usage-bar">
                      {storageBarTotal > 0
                        ? visibleCategories.map((category) => (
                            <div
                              key={category.key}
                              className="storage-usage-segment"
                              style={{ width: `${(category.bytes / storageBarTotal) * 100}%`, background: CATEGORY_COLORS[category.key] }}
                              title={`${category.label}: ${formatFileSize(category.bytes)} – ${storageHints[category.key]}`}
                            />
                          ))
                        : null}
                    </div>
                    {visibleCategories.length === 0 ? (
                      <div className="muted">{t("tenantModal.storage.noFiles")}</div>
                    ) : (
                      <div className="admin-storage-legend">
                        {visibleCategories.map((category) => (
                          <div key={category.key} className="admin-storage-legend-item" title={storageHints[category.key]}>
                            <span>
                              <span className="storage-legend-dot" style={{ background: CATEGORY_COLORS[category.key] }} />
                              {category.label}
                            </span>
                            <strong>{formatFileSize(category.bytes)}</strong>
                          </div>
                        ))}
                      </div>
                    )}
                    <StorageQuotaComposition planStorageBytes={tenant.plan_storage_bytes} packageStorageBytes={tenant.package_storage_bytes} />
                  </section>
                ) : (
                  <div className="muted">{storageLoading ? t("tenantModal.storage.loading") : t("tenantModal.storage.noData")}</div>
                )}

                <section className="admin-form-section">
                  <div className="admin-section-title">{t("tenantModal.storage.extraPackagesTitle")}</div>
                  {tenant.assigned_storage_packages.length === 0 ? (
                    <div className="muted">{t("tenantModal.storage.noExtraPackages")}</div>
                  ) : (
                    <div className="admin-package-list">
                      {tenant.assigned_storage_packages.flatMap((pkg) =>
                        Array.from({ length: pkg.quantity }, (_, index) => (
                          <div key={`${pkg.package_code}-${index}`} className="admin-package-row">
                            <span>
                              <strong>{pkg.name}</strong> <span className="muted">{formatFileSize(pkg.bytes)}</span>
                            </span>
                            <button
                              type="button"
                              className="button-ghost"
                              disabled={packagesBusy}
                              onClick={() => void changeStoragePackage(pkg.package_code, -1)}
                            >
                              {t("tenantModal.storage.remove")}
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                  {storagePackageCatalog.length === 0 ? (
                    <div className="muted">{t("tenantModal.storage.noPackagesInCatalog")}</div>
                  ) : (
                    <div className="table-actions table-actions-start">
                      <select value={packageToAdd} onChange={(event) => setPackageToAdd(event.target.value)} aria-label={t("tenantModal.storage.packageAria")}>
                        {storagePackageCatalog.map((pkg) => (
                          <option key={pkg.code} value={pkg.code}>
                            {pkg.name} ({formatFileSize(pkg.bytes)})
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="button-secondary"
                        disabled={packagesBusy || !packageToAdd}
                        onClick={() => void changeStoragePackage(packageToAdd, 1)}
                      >
                        {packagesBusy ? t("tenantModal.saving") : t("tenantModal.storage.addPackage")}
                      </button>
                    </div>
                  )}
                </section>
              </div>
            )
          }
        ]}
      />

      <MfaAdminModal
        open={!!mfaModalUser}
        onClose={() => setMfaModalUser(null)}
        title={mfaModalUser ? t("tenantModal.mfaTitle", { name: mfaModalUser.display_name }) : t("tenantModal.mfaTitleFallback")}
        loadPath={mfaModalUser ? `/api/admin/users/${mfaModalUser.user_id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/admin/users/${mfaModalUser.user_id}/mfa/factors` : null}
      />
    </Modal>
  );
}
