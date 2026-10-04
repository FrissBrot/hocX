"use client";

import { useTranslations } from "next-intl";

// Audit A6, 2026-08-16: without this, an unhandled fetch/network error (e.g. the backend
// being restarted/unreachable) fell through to Next.js' generic English default error page -
// a jarring break from the otherwise fully localized Abgabebox, for a real failure
// mode (backend restart mid-deploy) that will actually happen from time to time.
export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("abgabebox.error");
  return (
    <div className="card">
      <h1>{t("title")}</h1>
      <p className="muted">
        {t("hint")}
      </p>
      <button type="button" onClick={reset}>
        {t("retry")}
      </button>
    </div>
  );
}
