"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { NavIcon, NavIconKey } from "@/components/ui/nav-icons";
import { colorForUser, initials } from "@/components/protocol/collaboration-presence";
import { CATEGORY_COLORS, CATEGORY_HINTS, StorageQuotaComposition } from "@/components/storage/storage-usage-view";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize, formatRappen } from "@/lib/utils/format";
import { StorageUsageRead, TenantSubscription, TenantSummary, UserSummary } from "@/types/api";

type Props = {
  initialTenant: TenantSummary;
};

const FEATURE_ICONS: Record<string, NavIconKey> = {
  abgabebox: "submissions",
  finance: "finances",
};

export function TenantSubscriptionView({ initialTenant }: Props) {
  const tenantId = initialTenant.id;

  const [subscription, setSubscription] = useState<TenantSubscription | null>(null);
  const [subscriptionLoading, setSubscriptionLoading] = useState(false);
  const [storageUsage, setStorageUsage] = useState<StorageUsageRead | null>(null);
  const [tenantUsers, setTenantUsers] = useState<UserSummary[]>([]);

  useEffect(() => {
    void loadSubscription();
    void loadStorageUsage();
    void loadTenantUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  async function loadSubscription() {
    setSubscriptionLoading(true);
    try {
      const result = await browserApiFetch<TenantSubscription>(`/api/tenants/${tenantId}/subscription`);
      setSubscription(result);
    } catch {
      // kein Abo bzw. Fehler beim Laden - Abschnitt zeigt dann nur den Ladehinweis
    } finally {
      setSubscriptionLoading(false);
    }
  }

  async function loadStorageUsage() {
    try {
      const result = await browserApiFetch<StorageUsageRead>("/api/storage/usage");
      setStorageUsage(result);
    } catch {
      // Speicherdaten nicht verfuegbar - Karte zeigt dann nur die Summe aus dem Abo
    }
  }

  async function loadTenantUsers() {
    try {
      const result = await browserApiFetch<UserSummary[]>("/api/users");
      setTenantUsers(result);
    } catch {
      // Nutzerliste nicht verfuegbar (z.B. keine Admin-Rechte) - Avatare bleiben dann leer
    }
  }

  return (
    <>
      {subscriptionLoading && !subscription ? (
        <section className="card">
          <div className="eyebrow">Aktueller Plan</div>
          <div className="muted">Wird geladen…</div>
        </section>
      ) : !subscription ? (
        <section className="card">
          <div className="eyebrow">Aktueller Plan</div>
          <div className="muted">Abo-Daten konnten nicht geladen werden.</div>
        </section>
      ) : (
        <>
          <section className="card tenant-usage-plan-head">
            <div>
              <div className="eyebrow">Aktueller Plan</div>
              <div className="tenant-usage-plan-title">
                <h2 className="tenant-usage-plan-name">{subscription.plan_name ?? "Kein Plan zugewiesen"}</h2>
                <span className="pill">{subscription.billing_cycle === "monthly" ? "Monatlich" : "Jährlich"}</span>
              </div>
              {subscription.plan_code === "legacy" ? (
                <p className="muted">Übernommen aus dem bisherigen System — ohne Limits bei Nutzern und Speicher.</p>
              ) : null}
            </div>
            <div className="tenant-usage-plan-stats">
              <div>
                <div className="tenant-usage-stat-label">Abrechnung</div>
                <div className="tenant-usage-stat-value">{subscription.billing_cycle === "monthly" ? "Monatlich" : "Jährlich"}</div>
              </div>
              <div>
                <div className="tenant-usage-stat-label">Kosten</div>
                <div className="tenant-usage-stat-value">
                  {(subscription.billing_cycle === "monthly"
                    ? subscription.estimated_monthly_cost_rp
                    : subscription.estimated_yearly_cost_rp) === null
                    ? "Noch nicht festgelegt"
                    : formatRappen(
                        subscription.billing_cycle === "monthly"
                          ? subscription.estimated_monthly_cost_rp
                          : subscription.estimated_yearly_cost_rp
                      )}
                </div>
              </div>
            </div>
          </section>

          <div className="two-col">
            <section className="card grid">
              <div className="tenant-usage-card-head">
                <div className="eyebrow">Nutzer</div>
              </div>
              <div>
                <span className="tenant-usage-big-number">{subscription.user_count}</span>
                <span className="tenant-usage-big-number-unit">von {subscription.effective_user_limit ?? "unbegrenzt"}</span>
              </div>
              <div className="tenant-user-dots">
                {Array.from({ length: Math.min(subscription.effective_user_limit ?? Math.max(subscription.user_count * 10, 40), 60) }).map(
                  (_, index) => (
                    <span key={index} className={index < subscription.user_count ? "tenant-user-dot tenant-user-dot-filled" : "tenant-user-dot"} />
                  )
                )}
              </div>
              {tenantUsers.length > 0 ? (
                <div className="tenant-user-avatars">
                  {tenantUsers.slice(0, 8).map((u) => (
                    <span key={u.id} className="tenant-user-avatar" style={{ backgroundColor: colorForUser(u.id) }} title={u.display_name}>
                      {initials(u.display_name)}
                    </span>
                  ))}
                  {tenantUsers.length > 8 ? (
                    <span className="tenant-user-avatar tenant-user-avatar-overflow">+{tenantUsers.length - 8}</span>
                  ) : null}
                </div>
              ) : null}
              <Link href="/users" className="tenant-usage-link">
                Benutzer verwalten →
              </Link>
            </section>

            <section className="card grid tenant-usage-storage-card">
              <div className="tenant-usage-card-head">
                <div className="eyebrow">Speicher</div>
                {storageUsage?.quota_bytes != null && storageUsage.total_bytes > storageUsage.quota_bytes ? (
                  <Badge variant="danger">Kontingent überschritten</Badge>
                ) : (
                  <span className="muted">
                    {storageUsage?.quota_bytes != null ? `${formatFileSize(storageUsage.quota_bytes)} Kontingent` : "Kein Kontingent gesetzt"}
                  </span>
                )}
              </div>
              <div>
                <span className="tenant-usage-big-number">{formatFileSize(storageUsage?.total_bytes ?? subscription.storage_used_bytes)}</span>
                <span className="tenant-usage-big-number-unit">belegt</span>
              </div>
              <StorageQuotaComposition
                planStorageBytes={subscription.included_storage_bytes}
                packageStorageBytes={subscription.package_storage_bytes}
              />

              {storageUsage && storageUsage.categories.some((c) => c.bytes > 0) ? (
                <>
                  <div className="storage-usage-bar">
                    {storageUsage.categories
                      .filter((c) => c.bytes > 0)
                      .map((category) => (
                        <div
                          key={category.key}
                          className="storage-usage-segment"
                          style={{ width: `${(category.bytes / storageUsage.total_bytes) * 100}%`, background: CATEGORY_COLORS[category.key] }}
                          title={`${category.label}: ${formatFileSize(category.bytes)}`}
                        />
                      ))}
                  </div>
                  <div className="grid tenant-storage-legend">
                    {storageUsage.categories
                      .filter((c) => c.bytes > 0)
                      .map((category) => (
                        <div key={category.key}>
                          <div className="tenant-storage-legend-row">
                            <span>
                              <span className="storage-legend-dot" style={{ background: CATEGORY_COLORS[category.key] }} />
                              {category.label}
                            </span>
                            <span>{formatFileSize(category.bytes)}</span>
                          </div>
                          <div className="muted tenant-storage-legend-hint">{CATEGORY_HINTS[category.key]}</div>
                        </div>
                      ))}
                  </div>
                </>
              ) : null}
            </section>
          </div>

          <section className="card">
            <div className="eyebrow">Im Plan enthaltene Module</div>
            {subscription.features.length === 0 ? (
              <div className="muted">Keine Module gebucht.</div>
            ) : (
              <div className="grid tenant-module-list">
                {subscription.features.map((feature) => (
                  <div key={feature.code} className="tenant-module-card">
                    <span className="tenant-module-icon">
                      <NavIcon name={FEATURE_ICONS[feature.code] ?? "documents"} />
                    </span>
                    <div className="tenant-module-copy">
                      <strong>{feature.name}</strong>
                      {feature.description ? <div className="muted">{feature.description}</div> : null}
                      {!feature.included_in_plan && feature.standalone_price_monthly_rp !== null ? (
                        <div className="muted">+{formatRappen(feature.standalone_price_monthly_rp)}/Monat</div>
                      ) : null}
                    </div>
                    <Badge variant="success" dot className="tenant-module-status">
                      Aktiv
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
