import { notFound } from "next/navigation";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { listAssignments } from "@/lib/api";

const COLORS = 4;

export default async function LinkAssignmentsPage({ params }: { params: Promise<{ linkToken: string }> }) {
  const { linkToken } = await params;
  const resolution = await listAssignments(linkToken);
  if (resolution.status === "not_found") {
    notFound();
  }
  const t = await getTranslations("abgabebox.assignments");
  if (resolution.status === "feature_disabled") {
    return (
      <div className="card">
        <h1>{t("disabledTitle")}</h1>
        <p className="muted muted-flush">{t("disabledHint")}</p>
      </div>
    );
  }
  const assignments = resolution.data;

  return (
    <div className="box-step">
      <div className="box-step-head">
        <h1>{t("title")}</h1>
        <p className="muted">{t("hint")}</p>
      </div>

      {assignments.length === 0 ? (
        <div className="card">
          <p className="muted muted-flush">{t("empty")}</p>
        </div>
      ) : (
        <div className="choice-list">
          {assignments.map((assignment, i) => (
            <Link
              key={assignment.public_slug}
              className={`choice-card choice-tone-${i % COLORS}`}
              href={`/${linkToken}/${assignment.public_slug}`}
            >
              <span className="choice-icon" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M6 3.5h8l4 4v13H6z" />
                  <path d="M14 3.5V8h4" />
                </svg>
              </span>
              <span className="choice-body">
                <span className="choice-title">{assignment.title}</span>
                {assignment.description ? <span className="choice-desc">{assignment.description}</span> : null}
              </span>
              <svg className="choice-chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M9 6l6 6-6 6" />
              </svg>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
