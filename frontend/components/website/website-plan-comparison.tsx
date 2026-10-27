// Funktionsvergleich der Landing Page: alle buchbaren Abos als Spalten, Preise, Umfang und jedes
// verkäufliche Feature als Zeilen, nach Produktmodul gruppiert. Die Daten kommen bei jedem
// Seitenaufruf aus der Datenbank (GET /api/public/plan-comparison, page.tsx); Namen und
// Beschreibungen der Features wie im Adminportal gepflegt. Server-Komponente, kein JavaScript.

import { Fragment } from "react";
import { useLocale, useTranslations } from "next-intl";

import type { PublicFeature, PublicPlan } from "@/types/api";

import { formatPlanPrice } from "./website-plan-features";

const GIB = 1024 ** 3;

type Props = { plans: PublicPlan[]; features: PublicFeature[] };

export function WebsitePlanComparison({ plans, features }: Props) {
  const t = useTranslations("website.comparison");
  const locale = useLocale();
  if (plans.length === 0) return null;

  const groups: { module: string; items: PublicFeature[] }[] = [];
  for (const feature of features) {
    const last = groups.at(-1);
    if (last && last.module === feature.module) last.items.push(feature);
    else groups.push({ module: feature.module, items: [feature] });
  }
  const price = (rp: number | null) => (rp === null ? <span className="ws-compare-muted">{t("onRequest")}</span> : formatPlanPrice(rp, locale));
  const storage = (bytes: number | null) => {
    if (bytes === null) return t("unlimited");
    const gb = bytes / GIB;
    return t("storageGb", { gb: Number.isInteger(gb) ? gb : Math.round(gb * 10) / 10 });
  };
  const basics: { key: string; label: string; cell: (plan: PublicPlan) => React.ReactNode }[] = [
    { key: "monthly", label: t("rowPriceMonthly"), cell: (plan) => price(plan.price_monthly_rp) },
    { key: "yearly", label: t("rowPriceYearly"), cell: (plan) => price(plan.price_yearly_rp) },
    { key: "users", label: t("rowUsers"), cell: (plan) => (plan.included_user_limit === null ? t("unlimited") : t("usersUpTo", { count: plan.included_user_limit })) },
    { key: "storage", label: t("rowStorage"), cell: (plan) => storage(plan.included_storage_bytes) },
  ];

  function featureCell(plan: PublicPlan, feature: PublicFeature) {
    if (plan.features.some((item) => item.code === feature.code)) {
      return (
        <span className="ws-compare-yes">
          <span aria-hidden="true">✓</span>
          <span className="ws-sr-only">{t("included")}</span>
        </span>
      );
    }
    if (feature.standalone_price_monthly_rp !== null) {
      return (
        <span className="ws-compare-addon">
          {t("addon")}
          <span className="ws-compare-addon-price">{t("addonPrice", { price: formatPlanPrice(feature.standalone_price_monthly_rp, locale) })}</span>
        </span>
      );
    }
    return (
      <span className="ws-compare-no">
        <span aria-hidden="true">–</span>
        <span className="ws-sr-only">{t("notIncluded")}</span>
      </span>
    );
  }

  const columns = plans.length + 1;
  return (
    <div className="ws-compare-scroll" role="region" aria-label={t("caption")} tabIndex={0}>
      <table className="ws-compare">
        <caption className="ws-sr-only">{t("caption")}</caption>
        <thead>
          <tr>
            <th scope="col" className="ws-compare-corner">
              <span className="ws-sr-only">{t("featureColumn")}</span>
            </th>
            {plans.map((plan) => (
              <th key={plan.code} scope="col" className={plan.is_featured ? "ws-compare-plan ws-compare-plan-featured" : "ws-compare-plan"}>
                {plan.is_featured ? <span className="ws-compare-flag">{t("featured")}</span> : null}
                <span className="ws-compare-plan-name">{plan.name}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="ws-compare-group">
            <th scope="colgroup" colSpan={columns}>
              {t("groupBasics")}
            </th>
          </tr>
          {basics.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.label}</th>
              {plans.map((plan) => (
                <td key={plan.code} className={plan.is_featured ? "ws-compare-featured" : undefined}>
                  {row.cell(plan)}
                </td>
              ))}
            </tr>
          ))}
          {groups.map((group) => (
            <Fragment key={group.module}>
              <tr className="ws-compare-group">
                <th scope="colgroup" colSpan={columns}>
                  {t(`module.${group.module}`)}
                </th>
              </tr>
              {group.items.map((feature) => (
                <tr key={feature.code}>
                  <th scope="row">
                    <span className="ws-compare-feature">{feature.name}</span>
                    {feature.description ? <span className="ws-compare-feature-desc">{feature.description}</span> : null}
                  </th>
                  {plans.map((plan) => (
                    <td key={plan.code} className={plan.is_featured ? "ws-compare-featured" : undefined}>
                      {featureCell(plan, feature)}
                    </td>
                  ))}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
