"use client";

import { useTranslations } from "next-intl";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("common");
  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-brand">
          <div className="login-avatar login-avatar-fallback">
            <span>hX</span>
          </div>
          <div className="eyebrow">hocX</div>
        </div>
        <div className="login-heading">
          <h1>{t("connectionLost.title")}</h1>
          <p className="login-subtitle">{t("connectionLost.description")}</p>
        </div>
        <button type="button" className="button-secondary login-submit" onClick={() => reset()}>
          {t("retry")}
        </button>
      </section>
    </main>
  );
}
