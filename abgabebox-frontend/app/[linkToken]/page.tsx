import { notFound } from "next/navigation";
import Link from "next/link";

import { listAssignments } from "@/lib/api";

const COLORS = 4;

export default async function LinkAssignmentsPage({ params }: { params: Promise<{ linkToken: string }> }) {
  const { linkToken } = await params;
  const resolution = await listAssignments(linkToken);
  if (resolution.status === "not_found") {
    notFound();
  }
  if (resolution.status === "feature_disabled") {
    return (
      <div className="card">
        <h1>Abgabebox nicht verfügbar</h1>
        <p className="muted" style={{ margin: 0 }}>
          Die Abgabebox ist für diesen Verein aktuell nicht verfügbar.
        </p>
      </div>
    );
  }
  const assignments = resolution.data;

  return (
    <div>
      <h1>Offene Abgaben</h1>
      <p className="muted">Wähle eine Abgabe aus, um deine Datei einzureichen.</p>

      {assignments.length === 0 ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>Aktuell sind keine Abgaben offen.</p>
        </div>
      ) : (
        assignments.map((assignment, i) => {
          const c = i % COLORS;
          return (
            <Link
              key={assignment.public_slug}
              className={`card card-link card-colored-${c}`}
              href={`/${linkToken}/${assignment.public_slug}`}
            >
              <div className="card-title">
                <span className={`card-dot card-dot-${c}`} />
                {assignment.title}
              </div>
              {assignment.description ? <div className="muted" style={{ margin: 0, paddingLeft: "var(--space-4)" }}>{assignment.description}</div> : null}
            </Link>
          );
        })
      )}
    </div>
  );
}
