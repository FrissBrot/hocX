import { useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { NavIconKey } from "@/components/ui/nav-icons";
import { formatFileSize } from "@/lib/utils/format";
import { AdminFeature, AdminPlan } from "@/types/api";

/** Farbton eines Plans (Badge, Kartenrand). Pläne ohne Preis sind neutral, die übrigen bekommen
 * nach Preis aufsteigend einen festen Ton - so bleibt "Start" grün und "Verband" violett, egal in
 * welcher Reihenfolge die API sie liefert. */
export type PlanTone = Extract<BadgeVariant, "neutral" | "success" | "info" | "violet" | "warning">;

const PRICED_TONES: PlanTone[] = ["success", "info", "violet", "warning"];

export function hasPlanPrice(plan: Pick<AdminPlan, "price_monthly_rp" | "price_yearly_rp">): boolean {
  return plan.price_monthly_rp !== null || plan.price_yearly_rp !== null;
}

export function planTones(plans: AdminPlan[]): Map<string, PlanTone> {
  const priced = plans
    .filter(hasPlanPrice)
    .sort((a, b) => (a.price_yearly_rp ?? a.price_monthly_rp ?? 0) - (b.price_yearly_rp ?? b.price_monthly_rp ?? 0) || a.code.localeCompare(b.code));
  const tones = new Map<string, PlanTone>();
  for (const plan of plans) tones.set(plan.code, "neutral");
  priced.forEach((plan, index) => tones.set(plan.code, PRICED_TONES[Math.min(index, PRICED_TONES.length - 1)]));
  return tones;
}

export function PlanBadge({ name, tone }: { name: string; tone: PlanTone }) {
  return <Badge variant={tone}>{name}</Badge>;
}

/** Kurzform für Preise im Katalog: "CHF 9.–" bei ganzen Franken, sonst "CHF 14.50". */
export function formatChfShort(rp: number | null | undefined): string {
  if (rp === null || rp === undefined || Number.isNaN(rp)) return "–";
  const francs = rp / 100;
  return Number.isInteger(francs) ? `CHF ${francs}.–` : `CHF ${francs.toFixed(2)}`;
}

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

/** "CHF 190.00 / Jahr" bzw. "Kein Preis festgelegt" für eine Tabellenzelle. */
export function formatPlanPrice(plan: AdminPlan | undefined, cycle: "monthly" | "yearly", t: TFunc): string {
  if (!plan) return t("noPlanAssigned");
  const rp = cycle === "monthly" ? plan.price_monthly_rp : plan.price_yearly_rp;
  if (rp === null) return t("noPriceSet");
  return t("pricePerCycle", { price: `CHF ${(rp / 100).toFixed(2)}`, cycle: cycle === "monthly" ? t("month") : t("year") });
}

const FEATURE_ICON_HINTS: [RegExp, NavIconKey][] = [
  [/financ|finanz|kasse/, "finances"],
  [/abgabe|submission/, "submissions"],
  [/word|import/, "documents"],
  [/photo|foto/, "photos"],
  [/domain/, "tenant"],
];

export function featureIcon(feature: Pick<AdminFeature, "code">): NavIconKey {
  const code = feature.code.toLowerCase();
  return FEATURE_ICON_HINTS.find(([pattern]) => pattern.test(code))?.[1] ?? "tools";
}

/** Stabiler Farbton (0-4) für Avatare aus einem Schlüssel (ID oder Name). */
export function avatarTone(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return Math.abs(hash) % 5;
}

export function AdminAvatar({ name, imageUrl, toneKey, size = "md" }: { name: string; imageUrl?: string | null; toneKey?: string; size?: "sm" | "md" | "lg" }) {
  const letters = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, size === "sm" ? 2 : 1)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <span className={`admin-avatar admin-avatar-${size} admin-avatar-tone-${avatarTone(toneKey ?? name)}`}>
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl} alt={name} />
      ) : (
        letters || "?"
      )}
    </span>
  );
}

/** Kosten eines Abos in Rappen pro gewählter Periode: Plan + Add-ons (Monatspreis, bei jährlicher
 * Abrechnung x 12), abzüglich Rabatt. Gleiche Regel wie TenantService.get_subscription. */
export function estimateSubscriptionCost({
  plan,
  cycle,
  addOns,
  discountPercent,
}: {
  plan: AdminPlan | undefined;
  cycle: "monthly" | "yearly";
  addOns: AdminFeature[];
  discountPercent: number;
}): { planRp: number | null; addOnRp: number; totalRp: number | null } {
  const planRp = plan ? (cycle === "monthly" ? plan.price_monthly_rp : plan.price_yearly_rp) : null;
  const perMonth = addOns.reduce((sum, f) => sum + (f.standalone_price_monthly_rp ?? 0), 0);
  const addOnRp = cycle === "monthly" ? perMonth : perMonth * 12;
  if (planRp === null && addOnRp === 0) return { planRp, addOnRp, totalRp: null };
  const subtotal = (planRp ?? 0) + addOnRp;
  return { planRp, addOnRp, totalRp: Math.round(subtotal * ((100 - discountPercent) / 100)) };
}

/** Auswahlkarte eines Plans (Name, Limits, Preis) - "Neuer Mandant" und Tab "Plan & Abo". */
export function PlanOption({
  plan,
  name,
  checked,
  cycle,
  onSelect,
}: {
  plan: AdminPlan;
  name: string;
  checked: boolean;
  cycle: "monthly" | "yearly";
  onSelect: () => void;
}) {
  const t = useTranslations("admin.plans");
  const price = cycle === "monthly" ? plan.price_monthly_rp : plan.price_yearly_rp;
  return (
    <label className={checked ? "admin-plan-option admin-plan-option-active" : "admin-plan-option"}>
      <input type="radio" name={name} checked={checked} onChange={onSelect} />
      <span className="admin-plan-option-copy">
        <span className="admin-plan-option-title">
          <strong>{plan.name}</strong>
          {!plan.is_bookable ? <Badge className="admin-badge-sm">{t("notBookable")}</Badge> : null}
        </span>
        <span className="muted">
          {plan.included_user_limit === null ? t("unlimitedUsers") : t("userCount", { count: plan.included_user_limit })}
          {" · "}
          {plan.included_storage_bytes === null ? t("noStorageLimit") : formatFileSize(plan.included_storage_bytes)}
        </span>
      </span>
      <span className="admin-plan-option-price">{price === null ? "–" : t("pricePerCycle", { price: formatChfShort(price), cycle: cycle === "monthly" ? t("month") : t("year") })}</span>
    </label>
  );
}

export function BillingCycleToggle({ value, onChange }: { value: "monthly" | "yearly"; onChange: (value: "monthly" | "yearly") => void }) {
  const t = useTranslations("admin.plans");
  return (
    <div>
      <FilterTabs
        value={value}
        onChange={onChange}
        options={[
          { value: "monthly", label: t("monthly") },
          { value: "yearly", label: t("yearly") },
        ]}
      />
    </div>
  );
}
