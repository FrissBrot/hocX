import { notFound } from "next/navigation";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { listElements } from "@/lib/api";
import { formatDate } from "@/lib/format";

const COLORS = 4;

export default async function AssignmentElementsPage({
  params,
}: {
  params: Promise<{ linkToken: string; assignmentSlug: string }>;
}) {
  const { linkToken, assignmentSlug } = await params;
  const elements = await listElements(linkToken, assignmentSlug);
  if (elements === null) {
    notFound();
  }
  const t = await getTranslations("abgabebox.elements");

  return (
    <div>
      <h1>{t("title")}</h1>
      <p className="muted">{t("hint")}</p>

      {elements.length === 0 ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>{t("empty")}</p>
        </div>
      ) : (
        elements.map((element, i) => {
          const c = i % COLORS;
          return (
            <Link
              key={element.element_ref}
              className={`card card-link card-colored-${c}`}
              href={`/${linkToken}/${assignmentSlug}/${element.element_ref}`}
            >
              <div className="card-title">
                <span className={`card-dot card-dot-${c}`} />
                {element.label}
              </div>
              {element.window_start || element.window_end ? (
                <div className="window">
                  {element.window_start && element.window_end
                    ? `${formatDate(element.window_start)} – ${formatDate(element.window_end)}`
                    : element.window_start
                      ? t("windowFrom", { date: formatDate(element.window_start) })
                      : t("windowUntil", { date: formatDate(element.window_end) })}
                </div>
              ) : null}
              {element.uploaded_count > 0 ? (
                <div className="window">
                  {t("uploadedCount", { count: element.uploaded_count })}
                </div>
              ) : null}
            </Link>
          );
        })
      )}

      <Link href={`/${linkToken}`} className="back-btn">
        {t("backToOverview")}
      </Link>
    </div>
  );
}
