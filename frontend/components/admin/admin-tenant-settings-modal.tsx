"use client";

import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

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
import { formatFileSize } from "@/lib/utils/format";
import { CATEGORY_COLORS, CATEGORY_HINTS, formatPercent, StorageQuotaComposition } from "@/components/storage/storage-usage-view";
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

export const ROLE_OPTIONS: { code: string; label: string }[] = [
  { code: "reader", label: "Reader" },
  { code: "kassier", label: "Kassier" },
  { code: "writer", label: "Writer" },
  { code: "admin", label: "Admin" }
];

const CLEANUP_CATEGORIES: { key: TenantCleanupCategory; title: string; description: string }[] = [
  {
    key: "protocols",
    title: "Protokolle",
    description: "Alle Protokolle – manuell erstellte und importierte – inklusive der Word-Import-Warteschlange."
  },
  {
    key: "list_entries",
    title: "Daten aus Listen",
    description: "Alle Einträge in allen Listen. Die Listen selbst (Name, Spalten) bleiben erhalten."
  },
  {
    key: "lists_full",
    title: "Listen komplett",
    description: "Listen inklusive ihrer Einträge. Löscht auch Abgabebox-Konfigurationen, die an eine dieser Listen gekoppelt sind."
  },
  {
    key: "events",
    title: "Termine",
    description: "Alle Termine/Anlässe."
  },
  {
    key: "todos",
    title: "Todos",
    description: "Eigenständige Todos. Todos, die an ein Protokoll gebunden sind, verschwinden bereits mit „Protokolle“."
  },
  {
    key: "participants",
    title: "Teilnehmer/Personen",
    description: "Alle angelegten Teilnehmer/Personen-Stammdaten."
  },
  {
    key: "documents",
    title: "Hochgeladene Dokumente",
    description: "Word-/PDF-Importe und Abgabebox-Uploads, inklusive dadurch verwaister Dateien."
  }
];

type SettingsTab = "stammdaten" | "abo" | "benutzer" | "aufraeumen" | "speicher";

export function AdminTenantSettingsModal({ open, onClose, tenant, onSaved }: Props) {
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
      showToast(error instanceof Error ? error.message : "Speicherpaket-Katalog konnte nicht geladen werden", "error");
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
      showToast(delta > 0 ? "Speicherpaket hinzugefügt" : "Speicherpaket entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Speicherpakete konnten nicht gespeichert werden", "error");
    } finally {
      setPackagesBusy(false);
    }
  }

  async function loadFeatureCatalog() {
    try {
      const result = await browserApiFetch<AdminFeature[]>("/api/admin/features");
      setFeatureCatalog(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Feature-Katalog konnte nicht geladen werden", "error");
    }
  }

  async function loadPlanCatalog() {
    try {
      const result = await browserApiFetch<AdminPlan[]>("/api/admin/plans");
      setPlanCatalog(result);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Plan-Katalog konnte nicht geladen werden", "error");
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
  const cycleUnit = subscriptionForm.billing_cycle === "monthly" ? "Monat" : "Jahr";

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
      showToast("Abo gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Abo konnte nicht gespeichert werden", "error");
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
      showToast(error instanceof Error ? error.message : "Speicherverbrauch konnte nicht geladen werden", "error");
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
      showToast(error instanceof Error ? error.message : "Vorschau konnte nicht geladen werden", "error");
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

  const allCleanupSelected = CLEANUP_CATEGORIES.every((category) => cleanupSelected.has(category.key));

  function toggleAllCleanupCategories() {
    setCleanupSelected(allCleanupSelected ? new Set() : new Set(CLEANUP_CATEGORIES.map((category) => category.key)));
  }

  const cleanupNameMatches = !!tenant && cleanupConfirmName.trim() === tenant.name;

  async function submitCleanup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant || cleanupSelected.size === 0 || !cleanupNameMatches) return;
    if (
      !(await confirm({
        message: `${cleanupSelected.size} Datenkategorie(n) von "${tenant.name}" werden unwiderruflich gelöscht. Fortfahren?`,
        tone: "danger",
        confirmLabel: "Endgültig löschen"
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
      showToast("Mandant aufgeräumt", "success");
      void loadCleanupPreview(tenant.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Aufräumen fehlgeschlagen", "error");
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
      showToast(error instanceof Error ? error.message : "Benutzer konnten nicht geladen werden", "error");
    } finally {
      setUsersLoading(false);
    }
  }

  function pickProfileImage(file: File | null | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      showToast("Bitte ein Bild (PNG oder JPG) wählen", "error");
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
      showToast("Mandant gespeichert", "success");
      onSaved(updated);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mandant konnte nicht gespeichert werden", "error");
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
      showToast("Rolle geändert", "success");
    } catch (error) {
      setTenantUsers(previous);
      showToast(error instanceof Error ? error.message : "Rolle konnte nicht geändert werden", "error");
    }
  }

  async function removeUser(userId: string, displayName: string) {
    if (!tenant) return;
    if (
      !(await confirm({
        message: `Benutzer "${displayName}" endgültig löschen? Das Konto gehört nur zu diesem Mandanten und ist danach weg.`,
        tone: "danger",
        confirmLabel: "Löschen"
      }))
    )
      return;
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}/users/${userId}`, { method: "DELETE" });
      setTenantUsers((current) => current.filter((u) => u.user_id !== userId));
      showToast("Benutzer gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Benutzer konnte nicht gelöscht werden", "error");
    }
  }


  if (!tenant) {
    return null;
  }

  const storageQuota = storageUsage?.quota_bytes ?? null;
  const storageTotal = storageUsage?.total_bytes ?? tenant.storage_used_bytes;
  const storageBarTotal = storageQuota !== null && storageQuota > storageTotal ? storageQuota : storageTotal;
  const visibleCategories = storageUsage?.categories.filter((category) => category.bytes > 0) ?? [];
  const effectiveUserLimit = subscriptionForm.user_limit_override ?? selectedPlan?.included_user_limit ?? null;
  const effectiveStorageLimit =
    selectedPlan?.included_storage_bytes == null && tenant.package_storage_bytes === 0
      ? null
      : (selectedPlan?.included_storage_bytes ?? 0) + tenant.package_storage_bytes;

  const closeButton = (
    <button type="button" className="button-ghost" onClick={onClose}>
      Schliessen
    </button>
  );

  const footer =
    activeTab === "stammdaten" ? (
      <div className="modal-footer-actions">
        {closeButton}
        <button type="submit" form="admin-tenant-stammdaten" className="button-primary" disabled={tenantBusy}>
          {tenantBusy ? "Wird gespeichert…" : "Speichern"}
        </button>
      </div>
    ) : activeTab === "abo" ? (
      <>
        <span className="muted">
          {cost.totalRp === null ? "Plan ohne Preis" : `Total ${formatChfShort(cost.totalRp)} / ${cycleUnit}`}
        </span>
        <div className="modal-footer-actions">
          {closeButton}
          <button type="submit" form="admin-tenant-abo" className="button-primary" disabled={subscriptionBusy}>
            {subscriptionBusy ? "Wird gespeichert…" : "Abo speichern"}
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
      title={`Mandant-Einstellungen – ${tenant.name}`}
      size="wide"
      className="admin-tenant-modal"
      header={
        <div className="admin-modal-heading">
          <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} size="lg" />
          <div>
            <div className="eyebrow">Mandant-Einstellungen</div>
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
            label: "Stammdaten",
            content: (
              <form id="admin-tenant-stammdaten" className="grid admin-tenant-form" onSubmit={submitTenant}>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">Mandantenname</span>
                    <input value={tenantForm.name} onChange={(event) => setTenantForm((current) => ({ ...current, name: event.target.value }))} required />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">Öffentlicher Slug (Abgabebox-URL)</span>
                    <input
                      value={tenantForm.publicSlug}
                      onChange={(event) => setTenantForm((current) => ({ ...current, publicSlug: event.target.value.toLowerCase() }))}
                      placeholder="z.B. musterverein"
                      pattern="[a-z0-9-]+"
                    />
                  </label>
                </div>
                <div className="field-stack">
                  <span className="field-label">Profilbild</span>
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
                        {tenantForm.profileImage ? `${tenantForm.profileImage.name} · ` : "Bild hierher ziehen oder "}
                        <button type="button" className="admin-inline-link" onClick={() => fileInputRef.current?.click()}>
                          {tenantForm.profileImage ? "anderes wählen" : "Datei wählen"}
                        </button>
                      </div>
                      <div className="muted">PNG oder JPG, quadratisch</div>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg"
                      className="admin-image-drop-input"
                      aria-label="Profilbild wählen"
                      onChange={(event) => pickProfileImage(event.target.files?.[0])}
                    />
                  </div>
                </div>
                <div className="admin-tenant-meta">
                  <span>
                    Erstellt am <strong>{new Date(tenant.created_at).toLocaleDateString("de-CH")}</strong>
                  </span>
                  <span>
                    Teilnehmer <strong>{tenant.participant_count}</strong>
                  </span>
                </div>
              </form>
            )
          },
          {
            id: "abo",
            label: "Plan & Abo",
            content: (
              <form id="admin-tenant-abo" className="admin-abo-layout" onSubmit={submitSubscription}>
                <div className="admin-abo-main">
                  <section className="admin-form-section">
                    <div className="admin-section-title">Plan</div>
                    <div className="admin-plan-options" role="radiogroup" aria-label="Plan">
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
                    <div className="admin-section-title">Abrechnung</div>
                    <BillingCycleToggle
                      value={subscriptionForm.billing_cycle}
                      onChange={(billing_cycle) => setSubscriptionForm((current) => ({ ...current, billing_cycle }))}
                    />
                  </section>

                  <section className="admin-form-section">
                    <div className="admin-section-title">Module</div>
                    {featureCatalog.length === 0 ? (
                      <div className="muted">Keine Module im Katalog.</div>
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
                                    ? "Im Plan enthalten"
                                    : feature.standalone_price_monthly_rp !== null
                                      ? `Add-on · +${formatChfShort(feature.standalone_price_monthly_rp)} / Monat`
                                      : planOnly
                                        ? "Nur in Plänen verfügbar"
                                        : "Individuell gebucht"}
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
                      <span className="field-label">Rabatt</span>
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
                      <span className="field-label">Interne Notiz</span>
                      <input
                        value={subscriptionForm.billing_note ?? ""}
                        onChange={(event) => setSubscriptionForm((current) => ({ ...current, billing_note: event.target.value }))}
                        placeholder="z.B. Vereinsrabatt bis 2027"
                      />
                    </label>
                  </div>
                  <label className="field-stack">
                    <span className="field-label">Benutzerlimit überschreiben</span>
                    <input
                      type="number"
                      min={1}
                      value={subscriptionForm.user_limit_override ?? ""}
                      placeholder={selectedPlan?.included_user_limit != null ? `Plan-Limit: ${selectedPlan.included_user_limit}` : "Plan-Limit: unbegrenzt"}
                      onChange={(event) =>
                        setSubscriptionForm((current) => ({
                          ...current,
                          user_limit_override: event.target.value.trim() === "" ? null : Number(event.target.value),
                        }))
                      }
                    />
                    <span className="field-help">
                      Leer = Plan-Limit gilt. Aktuell {tenant.user_count} Benutzer
                      {effectiveUserLimit !== null && tenant.user_count >= effectiveUserLimit ? " – Limit erreicht oder überschritten." : "."}
                    </span>
                  </label>
                </div>

                <aside className="admin-abo-side">
                  <div className="admin-section-title">Kosten</div>
                  <div className="card admin-cost-card">
                    <div className="admin-cost-row">
                      <span>Plan {selectedPlan?.name ?? "–"}</span>
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
                        <span>Rabatt</span>
                        <span>– {subscriptionForm.discount_percent}%</span>
                      </div>
                    ) : null}
                    <div className="admin-cost-total">
                      <span>Total</span>
                      <strong>{cost.totalRp === null ? "Noch nicht festgelegt" : `${formatChfShort(cost.totalRp)}`}</strong>
                    </div>
                    <div className="muted admin-cost-hint">
                      {cost.totalRp === null
                        ? selectedPlan && !hasPlanPrice(selectedPlan)
                          ? "Bestandsplan ohne Preis"
                          : "Kein Plan gewählt"
                        : `pro ${cycleUnit}, exkl. MWST`}
                    </div>
                  </div>

                  <div className="admin-section-title">Limits nach Wechsel</div>
                  <dl className="admin-limit-list">
                    <div>
                      <dt>Benutzer</dt>
                      <dd>{effectiveUserLimit === null ? "unbegrenzt" : effectiveUserLimit}</dd>
                    </div>
                    <div>
                      <dt>Speicher</dt>
                      <dd>{effectiveStorageLimit === null ? "unbegrenzt" : formatFileSize(effectiveStorageLimit)}</dd>
                    </div>
                  </dl>
                  <p className="muted admin-side-note">
                    Der Mandant sieht Plan, Module und geschätzte Kosten unter Mandant-Einstellungen → Abo &amp; Nutzung.
                  </p>
                </aside>
              </form>
            )
          },
          {
            id: "benutzer",
            label: `Benutzer (${tenantUsers.length})`,
            content: (
              <div className="grid">
                <div className="table-shell admin-user-table">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>E-Mail</th>
                        <th>Rolle</th>
                        <th>MFA</th>
                        <th aria-label="Aktion" />
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
                                {!u.login_enabled && <div className="muted admin-cell-sub">Login deaktiviert</div>}
                              </div>
                            </div>
                          </td>
                          <td className="muted">{u.email}</td>
                          <td>
                            <select value={u.role_code} onChange={(event) => changeUserRole(u.user_id, event.target.value)} aria-label={`Rolle von ${u.display_name}`}>
                              {ROLE_OPTIONS.map((r) => (
                                <option key={r.code} value={r.code}>
                                  {r.label}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <button type="button" className="button-ghost" onClick={() => setMfaModalUser(u)}>
                              Anzeigen
                            </button>
                          </td>
                          <td className="admin-cell-end">
                            <button type="button" className="button-danger" onClick={() => removeUser(u.user_id, u.display_name)}>
                              Löschen
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!usersLoading && tenantUsers.length === 0 && <div className="table-empty muted">Dieser Mandant hat noch keine Benutzer.</div>}
                </div>
                <p className="muted">Jedes Konto gehört genau einem Mandanten. Neue Benutzer legst du unter „Benutzer“ an und wählst dort den Mandanten.</p>
              </div>
            )
          },
          {
            id: "aufraeumen",
            label: "Aufräumen",
            content: (
              <form className="grid admin-tenant-form" onSubmit={submitCleanup}>
                <div className="form-error-banner">
                  Diese Aktion löscht Daten endgültig aus der Datenbank – es gibt kein Zurück. Der Mandant selbst, Vorlagen,
                  Formularfelder und Benutzerzugriffe bleiben in jedem Fall erhalten.
                </div>

                <div className="field-stack">
                  <span className="field-label">Was soll gelöscht werden?</span>
                  <label className="field-radio-option admin-cleanup-all">
                    <input type="checkbox" checked={allCleanupSelected} onChange={toggleAllCleanupCategories} />
                    <span>
                      <strong>Alle Daten löschen</strong>
                      <div className="muted">Wählt alle Kategorien unten auf einmal aus.</div>
                    </span>
                  </label>
                  {CLEANUP_CATEGORIES.map((category) => (
                    <label key={category.key} className="field-radio-option">
                      <input
                        type="checkbox"
                        checked={cleanupSelected.has(category.key)}
                        onChange={() => toggleCleanupCategory(category.key)}
                      />
                      <span>
                        <strong>
                          {category.title}
                          {cleanupCounts ? <span className="muted admin-cleanup-count"> – {cleanupCounts[category.key]} vorhanden</span> : null}
                        </strong>
                        <div className="muted">{category.description}</div>
                      </span>
                    </label>
                  ))}
                </div>

                {cleanupLastResult ? (
                  <div className="muted">
                    Zuletzt gelöscht: {Object.entries(cleanupLastResult)
                      .filter(([, count]) => count > 0)
                      .map(([key, count]) => `${CLEANUP_CATEGORIES.find((c) => c.key === key)?.title ?? key}: ${count}`)
                      .join(", ") || "nichts (0 Treffer in den gewählten Kategorien)"}
                  </div>
                ) : null}

                <label className="field-stack">
                  <span className="field-label">Zur Bestätigung Mandantenname eintippen: „{tenant.name}“</span>
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
                    {cleanupBusy ? "Wird gelöscht…" : "Ausgewählte Daten löschen"}
                  </button>
                </div>
              </form>
            )
          },
          {
            id: "speicher",
            label: "Speicher",
            content: (
              <div className="grid admin-tenant-form">
                {storageUsage ? (
                  <section className="admin-storage-overview">
                    <div className="admin-storage-total">
                      <span className="admin-storage-total-value">{formatFileSize(storageUsage.total_bytes)}</span>
                      <span className="muted">
                        {storageQuota !== null
                          ? `von ${formatFileSize(storageQuota)} belegt (${formatPercent(storageUsage.total_bytes, storageQuota)})`
                          : "belegt · kein Speicherlimit"}
                      </span>
                      {storageQuota !== null && storageUsage.total_bytes > storageQuota ? <Badge variant="danger">Kontingent überschritten</Badge> : null}
                    </div>
                    <div className="storage-usage-bar admin-storage-usage-bar">
                      {storageBarTotal > 0
                        ? visibleCategories.map((category) => (
                            <div
                              key={category.key}
                              className="storage-usage-segment"
                              style={{ width: `${(category.bytes / storageBarTotal) * 100}%`, background: CATEGORY_COLORS[category.key] }}
                              title={`${category.label}: ${formatFileSize(category.bytes)} – ${CATEGORY_HINTS[category.key]}`}
                            />
                          ))
                        : null}
                    </div>
                    {visibleCategories.length === 0 ? (
                      <div className="muted">Noch keine Dateien vorhanden.</div>
                    ) : (
                      <div className="admin-storage-legend">
                        {visibleCategories.map((category) => (
                          <div key={category.key} className="admin-storage-legend-item" title={CATEGORY_HINTS[category.key]}>
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
                  <div className="muted">{storageLoading ? "Wird geladen…" : "Keine Daten verfügbar."}</div>
                )}

                <section className="admin-form-section">
                  <div className="admin-section-title">Zusatz-Speicherpakete</div>
                  {tenant.assigned_storage_packages.length === 0 ? (
                    <div className="muted">Keine Zusatzpakete gebucht.</div>
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
                              Entfernen
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                  {storagePackageCatalog.length === 0 ? (
                    <div className="muted">Keine Speicherpakete im Katalog.</div>
                  ) : (
                    <div className="table-actions table-actions-start">
                      <select value={packageToAdd} onChange={(event) => setPackageToAdd(event.target.value)} aria-label="Speicherpaket">
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
                        {packagesBusy ? "Wird gespeichert…" : "+ Paket hinzufügen"}
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
        title={mfaModalUser ? `MFA von ${mfaModalUser.display_name}` : "MFA"}
        loadPath={mfaModalUser ? `/api/admin/users/${mfaModalUser.user_id}/mfa` : null}
        deletePathBase={mfaModalUser ? `/api/admin/users/${mfaModalUser.user_id}/mfa/factors` : null}
      />
    </Modal>
  );
}
