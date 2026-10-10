import type { PublicPlan } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number>) => string;

const GIB = 1024 ** 3;

/** Leistungszeilen einer Preiskarte, komplett aus den Katalogdaten abgeleitet: enthaelt ein Plan
 *  alle Module des vorherigen (guenstigeren) Plans, steht dort "Alles aus <Plan>" plus nur die
 *  zusaetzlichen Module - wie im Design. Danach Benutzer- und Speicherlimit. */
export function planFeatureLines(plan: PublicPlan, previous: PublicPlan | null, t: TFunc): string[] {
  const lines: string[] = [];
  const previousCodes = new Set(previous?.features.map((f) => f.code) ?? []);
  const includesPrevious =
    previous !== null && previousCodes.size > 0 && previous.features.every((f) => plan.features.some((own) => own.code === f.code));
  if (includesPrevious) {
    lines.push(t("everythingFrom", { plan: previous.name }));
    lines.push(...plan.features.filter((f) => !previousCodes.has(f.code)).map((f) => f.name));
  } else {
    lines.push(...plan.features.map((f) => f.name));
  }
  lines.push(plan.included_user_limit === null ? t("usersUnlimited") : t("usersUpTo", { count: plan.included_user_limit }));
  if (plan.included_storage_bytes === null) {
    lines.push(t("storageUnlimited"));
  } else {
    const gb = plan.included_storage_bytes / GIB;
    lines.push(t("storageGb", { gb: Number.isInteger(gb) ? gb : Math.round(gb * 10) / 10 }));
  }
  return lines;
}

/** Ersparnis des Jahresabos fuer den Umschalter: gleiche ganze Anzahl Gratismonate bei allen
 *  Plaenen -> "N Monate gratis", sonst die maximale Ersparnis in Prozent, ohne Ersparnis nichts. */
export function yearlySavings(plans: PublicPlan[]): { months: number } | { percent: number } | null {
  const ratios = plans
    .filter((p) => p.price_monthly_rp && p.price_yearly_rp)
    .map((p) => 12 - (p.price_yearly_rp as number) / (p.price_monthly_rp as number));
  if (ratios.length === 0) return null;
  const months = Math.round(ratios[0]);
  if (months >= 1 && ratios.every((r) => Math.abs(r - months) < 0.01)) return { months };
  const percent = Math.round(Math.max(...ratios.map((r) => (r / 12) * 100)));
  return percent > 0 ? { percent } : null;
}
