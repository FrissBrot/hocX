import { useTranslations } from "next-intl";

import type { PublicCustomer } from "@/types/api";

/** Anzeigehöhe der Logos in px; das Backend liefert sie in doppelter Auflösung (max. 320×64). */
export const CUSTOMER_LOGO_HEIGHT = 32;

type Props = {
  customers: PublicCustomer[];
};

/** Kundenleiste «Im Einsatz bei»: Logo (falls vorhanden) und Name der freigegebenen Organisationen.
 *  width/height kommen aus den Pixelmassen des Backends, damit beim Laden nichts springt. */
export function WebsiteCustomers({ customers }: Props) {
  const t = useTranslations("website.customers");
  if (customers.length === 0) {
    return null;
  }
  return (
    <section className="ws-container ws-customers" aria-label={t("label")}>
      <span className="ws-customers-label">{t("label")}</span>
      <ul className="ws-customer-list">
        {customers.map((customer, index) => (
          <li key={`${customer.name}-${index}`} className={customer.logo ? "ws-customer ws-customer-with-logo" : "ws-customer"}>
            {customer.logo ? (
              // Name steht direkt daneben, das Logo ist dekorativ (alt="").
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="ws-customer-logo"
                src={customer.logo.url}
                alt=""
                width={Math.max(1, Math.round((customer.logo.width * CUSTOMER_LOGO_HEIGHT) / Math.max(1, customer.logo.height)))}
                height={CUSTOMER_LOGO_HEIGHT}
                loading="lazy"
                decoding="async"
              />
            ) : null}
            <span className="ws-customer-name">{customer.name}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
