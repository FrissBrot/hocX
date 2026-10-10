"use client";

import { type ReactNode, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { toIntlLocale } from "@/lib/utils/format";
import type { PublicPlan } from "@/types/api";

import { planFeatureLines, yearlySavings } from "./website-plan-features";

type Interval = "month" | "year";

type Props = {
  /** Serverseitig gerenderte Abschnittsueberschrift, links neben dem Monat/Jahr-Umschalter. */
  heading: ReactNode;
  plans: PublicPlan[];
  /** Ziel der Karten-Buttons: mailto mit Plan im Betreff, sonst der Login der App. */
  contactEmail: string | null;
  appLoginUrl: string;
};

// Ganze Franken im Schweizer Stil ("CHF 19.–"), sonst mit Rappen.
function formatPlanPrice(rp: number, locale: string): string {
  const whole = rp % 100 === 0;
  const amount = new Intl.NumberFormat(toIntlLocale(locale), {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(rp / 100);
  return whole ? `CHF ${amount}.–` : `CHF ${amount}`; // i18n-ok: Waehrungsformat, kein UI-Text
}

export function WebsitePricing({ heading, plans, contactEmail, appLoginUrl }: Props) {
  const t = useTranslations("website.pricing");
  const locale = useLocale();
  const hasYearly = plans.some((p) => p.price_yearly_rp !== null);
  const [interval, setBillingInterval] = useState<Interval>("month");
  const savings = yearlySavings(plans);

  if (plans.length === 0) {
    return (
      <>
        <div className="ws-pricing-head">{heading}</div>
        <p className="ws-pricing-empty">{t("empty")}</p>
      </>
    );
  }

  return (
    <>
      <div className="ws-pricing-head">
      {heading}
      {hasYearly ? (
        <div className="ws-interval" role="group" aria-label={t("intervalLabel")}>
          <button
            type="button"
            className={interval === "month" ? "ws-interval-option ws-interval-option-active" : "ws-interval-option"}
            aria-pressed={interval === "month"}
            onClick={() => setBillingInterval("month")}
          >
            {t("monthly")}
          </button>
          <button
            type="button"
            className={interval === "year" ? "ws-interval-option ws-interval-option-active" : "ws-interval-option"}
            aria-pressed={interval === "year"}
            onClick={() => setBillingInterval("year")}
          >
            {t("yearly")}
            {savings ? (
              <span className="ws-interval-savings">
                {"months" in savings ? t("monthsFree", { count: savings.months }) : t("savePercent", { percent: savings.percent })}
              </span>
            ) : null}
          </button>
        </div>
      ) : null}
      </div>

      <div className="ws-plan-grid">
        {plans.map((plan, index) => {
          const yearlyPrice = interval === "year" && plan.price_yearly_rp !== null;
          const priceRp = yearlyPrice ? plan.price_yearly_rp : plan.price_monthly_rp ?? plan.price_yearly_rp;
          const unit = priceRp === null ? null : yearlyPrice || plan.price_monthly_rp === null ? t("perYear") : t("perMonth");
          const lines = planFeatureLines(plan, index > 0 ? plans[index - 1] : null, t);
          const ctaHref = contactEmail
            ? `mailto:${contactEmail}?subject=${encodeURIComponent(t("mailSubject", { plan: plan.name }))}`
            : appLoginUrl;
          return (
            <article key={plan.code} className={plan.is_featured ? "ws-plan ws-plan-featured" : "ws-plan"}>
              {plan.is_featured ? <span className="ws-plan-flag">{t("featured")}</span> : null}
              <div>
                <h3 className="ws-plan-name">{plan.name}</h3>
                {plan.description ? <p className="ws-plan-desc">{plan.description}</p> : null}
              </div>
              <div className="ws-plan-price">
                <span className="ws-plan-amount">{priceRp === null ? t("onRequest") : formatPlanPrice(priceRp, locale)}</span>
                {unit ? <span className="ws-plan-unit">{unit}</span> : null}
              </div>
              <ul className="ws-plan-features">
                {lines.map((line) => (
                  <li key={line}>
                    <span className="ws-plan-check" aria-hidden="true">
                      ✓
                    </span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
              <a className="ws-plan-cta" href={ctaHref}>
                {plan.is_featured ? t("ctaFeatured") : t("ctaDefault", { plan: plan.name })}
              </a>
            </article>
          );
        })}
      </div>
    </>
  );
}
