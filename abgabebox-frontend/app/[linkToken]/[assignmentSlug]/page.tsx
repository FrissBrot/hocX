import { notFound } from "next/navigation";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { getAssignmentDetail, listElements } from "@/lib/api";
import { formatDate } from "@/lib/format";

const COLORS = 4;

export default async function AssignmentElementsPage({
  params,
}: {
  params: Promise<{ linkToken: string; assignmentSlug: string }>;
}) {
  const { linkToken, assignmentSlug } = await params;
  const [assignment, elements] = await Promise.all([
    getAssignmentDetail(linkToken, assignmentSlug),
    listElements(linkToken, assignmentSlug),
  ]);
  if (assignment === null || elements === null) {
    notFound();
  }
  const t = await getTranslations("abgabebox.elements");

  return (
    <div className="box-step">
      <div className="box-step-head">
        <Link href={`/${linkToken}`} className="back-link">
          {t("backToAssignments")}
        </Link>
        <h1>{assignment.title}</h1>
        <p className="muted">{t("hint")}</p>
      </div>

      {elements.length === 0 ? (
        <div className="card">
          <p className="muted muted-flush">{t("empty")}</p>
        </div>
      ) : (
        <div className="element-list">
          {elements.map((element, i) => (
            <Link
              key={element.element_ref}
              className="element-row"
              href={`/${linkToken}/${assignmentSlug}/${element.element_ref}`}
            >
              <span className={`card-dot card-dot-${i % COLORS}`} aria-hidden="true" />
              <span className="element-body">
                <span className="element-label">{element.label}</span>
                {element.window_start || element.window_end ? (
                  <span className="element-meta">
                    {element.window_start && element.window_end
                      ? `${formatDate(element.window_start)} – ${formatDate(element.window_end)}`
                      : element.window_start
                        ? t("windowFrom", { date: formatDate(element.window_start) })
                        : t("windowUntil", { date: formatDate(element.window_end) })}
                  </span>
                ) : null}
                {element.uploaded_count > 0 ? (
                  <span className="element-meta">{t("uploadedCount", { count: element.uploaded_count })}</span>
                ) : null}
              </span>
              {/* Das Backend liefert nur offene Elemente (resolve_open_elements). */}
              <span className="status-pill status-pill-open">{t("statusOpen")}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
